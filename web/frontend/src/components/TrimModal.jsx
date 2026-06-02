import { useState, useEffect, useRef, useCallback } from 'react'
import api from '../api'
import styles from './TrimModal.module.css'

function fmt(t) {
  if (!isFinite(t)) return '0.00s'
  return `${t.toFixed(2)}s`
}

export default function TrimModal({ clip, onClose, onTrimmed }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [duration, setDuration] = useState(0)
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(0)
  const [busy, setBusy] = useState(false)
  const [playing, setPlaying] = useState(false)

  const canvasRef = useRef(null)
  const trackRef = useRef(null)
  const audioRef = useRef(null)
  const urlRef = useRef(null)
  const bufferRef = useRef(null)
  const dragRef = useRef(null)
  const stateRef = useRef({ start: 0, end: 0, duration: 0 })

  const canRevert = !!clip.original_file

  stateRef.current = { start, end, duration }

  const drawWaveform = useCallback((buf) => {
    const canvas = canvasRef.current
    if (!canvas) return
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

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.get(`/api/clips/${clip.identifier}/audio`, {
      responseType: 'arraybuffer',
      params: { t: Date.now() }, // bust any cached (pre-trim) audio
    })
      .then(async (res) => {
        const blob = new Blob([res.data])
        urlRef.current = URL.createObjectURL(blob)
        audioRef.current = new Audio(urlRef.current)
        const AC = window.AudioContext || window.webkitAudioContext
        const actx = new AC()
        const buf = await actx.decodeAudioData(res.data.slice(0))
        actx.close()
        if (cancelled) return
        bufferRef.current = buf
        setDuration(buf.duration)
        setStart(0)
        setEnd(buf.duration)
        requestAnimationFrame(() => drawWaveform(buf))
        setLoading(false)
      })
      .catch(() => {
        if (!cancelled) {
          setError('Could not load audio')
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
      if (audioRef.current) audioRef.current.pause()
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    }
  }, [clip.identifier, drawWaveform])

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
      if (which === 'start') {
        setStart(Math.min(t, stateRef.current.end - 0.1))
      } else {
        setEnd(Math.max(t, stateRef.current.start + 0.1))
      }
    }
    function onUp() { dragRef.current = null }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [])

  function playSelection() {
    const audio = audioRef.current
    if (!audio) return
    if (playing) {
      audio.pause()
      setPlaying(false)
      return
    }
    audio.currentTime = start
    const onTime = () => {
      if (audio.currentTime >= end) {
        audio.pause()
        audio.removeEventListener('timeupdate', onTime)
        setPlaying(false)
      }
    }
    audio.addEventListener('timeupdate', onTime)
    audio.play()
    setPlaying(true)
  }

  async function doTrim() {
    setBusy(true)
    try {
      const res = await api.post(`/api/clips/${clip.identifier}/trim`, { start, end })
      onTrimmed(res.data)
      onClose()
    } catch (err) {
      setError(err.response?.data?.detail || 'Trim failed')
      setBusy(false)
    }
  }

  async function doRevert() {
    setBusy(true)
    try {
      const res = await api.post(`/api/clips/${clip.identifier}/revert`)
      onTrimmed(res.data)
      onClose()
    } catch (err) {
      setError(err.response?.data?.detail || 'Revert failed')
      setBusy(false)
    }
  }

  const startPct = duration ? (start / duration) * 100 : 0
  const endPct = duration ? (end / duration) * 100 : 100
  const trimsWholeClip = start <= 0.001 && end >= duration - 0.001

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.head}>
          <div>
            <span className={styles.kind}>Trim audio</span>
            <h3 className={styles.title}>{clip.name}</h3>
          </div>
          <button className={styles.close} onClick={onClose}>✕</button>
        </div>

        {loading && <p className={styles.status}>Loading waveform…</p>}
        {error && <p className={styles.error}>{error}</p>}

        {!loading && !error && (
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
            </div>

            <div className={styles.times}>
              <span>Start <strong>{fmt(start)}</strong></span>
              <span>Selection <strong>{fmt(end - start)}</strong></span>
              <span>End <strong>{fmt(end)}</strong></span>
            </div>

            <div className={styles.actions}>
              <button className={styles.preview} onClick={playSelection}>
                {playing ? '⏸ Stop' : '▶ Preview selection'}
              </button>
              <div className={styles.actionsRight}>
                {canRevert && (
                  <button className={styles.revert} onClick={doRevert} disabled={busy} title="Restore the original (pre-trim) audio">
                    ↺ Revert to original
                  </button>
                )}
                <button
                  className={styles.trim}
                  onClick={doTrim}
                  disabled={busy || trimsWholeClip}
                  title={trimsWholeClip ? 'Adjust the handles to select a region' : 'Trim to selection'}
                >
                  ✂ Trim
                </button>
              </div>
            </div>
            <p className={styles.note}>Trimming replaces the audio (re-normalised) and keeps votes &amp; history. The original is backed up so you can revert.</p>
          </>
        )}
      </div>
    </div>
  )
}
