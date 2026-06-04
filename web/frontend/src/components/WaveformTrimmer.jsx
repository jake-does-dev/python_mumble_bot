import { useRef, useEffect, useCallback, useState } from 'react'
import styles from './WaveformTrimmer.module.css'

function fmt(t) {
  if (!isFinite(t)) return '0.00s'
  return `${t.toFixed(2)}s`
}

/**
 * Controlled waveform + draggable trim region. Used at upload time
 * (decoded from a local File) and post-upload (fetched from the server).
 *
 * Props:
 *  - audioBuffer: decoded AudioBuffer (for drawing + preview) | null
 *  - duration:    total length in seconds
 *  - start, end:  current selection (seconds) — controlled
 *  - onChange(start, end): called as the handles are dragged
 *  - maxSelection: optional cap (seconds); selection beyond it is flagged
 */
export default function WaveformTrimmer({
  audioBuffer,
  duration,
  start,
  end,
  onChange,
  maxSelection,
}) {
  const canvasRef = useRef(null)
  const trackRef = useRef(null)
  const dragRef = useRef(null)
  const rafRef = useRef(null)
  const ctxRef = useRef(null)
  const srcRef = useRef(null)
  const playStartRef = useRef(0)   // AudioContext time when playback began
  const playOffsetRef = useRef(0)  // selection start the playback began from
  const stateRef = useRef({ start, end, duration })
  const [playing, setPlaying] = useState(false)
  const [playhead, setPlayhead] = useState(null)

  stateRef.current = { start, end, duration }

  const drawWaveform = useCallback((buf) => {
    const canvas = canvasRef.current
    if (!canvas || !buf) return
    const dpr = window.devicePixelRatio || 1
    const cssW = canvas.clientWidth || 520
    const cssH = canvas.clientHeight || 120
    canvas.width = cssW * dpr
    canvas.height = cssH * dpr
    const ctx = canvas.getContext('2d')
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, cssW, cssH)

    const data = buf.getChannelData(0)
    const buckets = Math.min(cssW, 600)
    const step = Math.floor(data.length / buckets) || 1
    const mid = cssH / 2
    const accent = getComputedStyle(canvas).getPropertyValue('--accent').trim() || '#aa3bff'
    ctx.fillStyle = accent
    const barW = cssW / buckets
    for (let i = 0; i < buckets; i++) {
      let peak = 0
      const base = i * step
      for (let j = 0; j < step; j++) {
        const v = Math.abs(data[base + j] || 0)
        if (v > peak) peak = v
      }
      const h = Math.max(1, peak * (cssH * 0.92))
      ctx.fillRect(i * barW, mid - h / 2, Math.max(1, barW - 0.5), h)
    }
  }, [])

  // Draw (and redraw on resize) whenever the buffer changes.
  useEffect(() => {
    if (!audioBuffer) return
    requestAnimationFrame(() => drawWaveform(audioBuffer))
    const ro = new ResizeObserver(() => drawWaveform(audioBuffer))
    if (canvasRef.current) ro.observe(canvasRef.current)
    return () => ro.disconnect()
  }, [audioBuffer, drawWaveform])

  function stopPlayback() {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = null
    const src = srcRef.current
    if (src) {
      src.onended = null
      try { src.stop() } catch { /* already stopped */ }
      try { src.disconnect() } catch { /* noop */ }
      srcRef.current = null
    }
    setPlaying(false)
    setPlayhead(null)
  }

  // Tear everything down on unmount.
  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      const src = srcRef.current
      if (src) { src.onended = null; try { src.stop() } catch { /* noop */ } }
      if (ctxRef.current) { ctxRef.current.close(); ctxRef.current = null }
    }
  }, [])

  // Drag handles.
  useEffect(() => {
    function onMove(e) {
      const which = dragRef.current
      if (!which) return
      const track = trackRef.current
      if (!track) return
      const rect = track.getBoundingClientRect()
      const x = Math.min(Math.max(e.clientX - rect.left, 0), rect.width)
      const t = (x / rect.width) * stateRef.current.duration
      const { start: s, end: en } = stateRef.current
      if (which === 'start') onChange(Math.min(t, en - 0.1), en)
      else onChange(s, Math.max(t, s + 0.1))
    }
    function onUp() { dragRef.current = null }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [onChange])

  function playSelection() {
    if (playing) { stopPlayback(); return }
    if (!audioBuffer) return
    const { start: s, end: e } = stateRef.current
    const length = Math.max(0, e - s)
    if (length <= 0) return

    // Play the exact selection straight from the decoded buffer. start()'s
    // (offset, duration) args are sample-accurate, so there's no seek race or
    // HTMLAudio `ended`-state quirk — what plays always matches the highlight.
    if (!ctxRef.current) {
      const AC = window.AudioContext || window.webkitAudioContext
      ctxRef.current = new AC()
    }
    const ctx = ctxRef.current
    if (ctx.state === 'suspended') ctx.resume()

    const src = ctx.createBufferSource()
    src.buffer = audioBuffer
    src.connect(ctx.destination)
    srcRef.current = src
    playStartRef.current = ctx.currentTime
    playOffsetRef.current = s
    src.onended = () => { if (srcRef.current === src) stopPlayback() }
    src.start(0, s, length)

    setPlaying(true)
    setPlayhead(s)
    const tick = () => {
      const pos = playOffsetRef.current + (ctx.currentTime - playStartRef.current)
      if (pos >= stateRef.current.end) { stopPlayback(); return }
      setPlayhead(pos)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
  }

  const startPct = duration ? (start / duration) * 100 : 0
  const endPct = duration ? (end / duration) * 100 : 100
  const selLen = end - start
  const tooLong = maxSelection != null && selLen > maxSelection + 0.05

  return (
    <>
      <div className={styles.track} ref={trackRef}>
        <canvas className={styles.canvas} ref={canvasRef} />
        <div className={styles.mask} style={{ left: 0, width: `${startPct}%` }} />
        <div className={styles.mask} style={{ left: `${endPct}%`, right: 0 }} />
        <div className={styles.region} style={{ left: `${startPct}%`, width: `${endPct - startPct}%` }} />
        <div
          className={styles.handle}
          style={{ left: `${startPct}%` }}
          onPointerDown={() => { dragRef.current = 'start' }}
        />
        <div
          className={styles.handle}
          style={{ left: `${endPct}%` }}
          onPointerDown={() => { dragRef.current = 'end' }}
        />
        {playhead != null && duration > 0 && (
          <div className={styles.playhead} style={{ left: `${(playhead / duration) * 100}%` }} />
        )}
      </div>

      <div className={styles.times}>
        <span>Start <strong>{fmt(start)}</strong></span>
        <span className={tooLong ? styles.tooLong : ''}>
          Selection <strong>{fmt(selLen)}</strong>
          {tooLong && ` — max ${maxSelection}s`}
        </span>
        <span>End <strong>{fmt(end)}</strong></span>
      </div>

      <button type="button" className={styles.preview} onClick={playSelection}>
        {playing ? '⏸ Stop' : '▶ Preview selection'}
      </button>
    </>
  )
}
