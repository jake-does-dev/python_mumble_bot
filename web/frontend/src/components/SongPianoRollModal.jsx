import { useEffect, useMemo, useRef, useState } from 'react'
import api from '../api'
import { useTheme } from '../context/ThemeContext'
import { gmInstrumentName } from '../lib/gmInstruments'
import { lineColour } from '../lib/pianoRoll'
import PreviewPlayer from '../lib/previewPlayer'
import PianoRoll from './PianoRoll'
import styles from './SongPianoRollModal.module.css'

function fmt(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// Full-width piano-roll visualiser for a song, opened from a SongCard. Notes are
// coloured by instrument line so you can see which instrument plays which part;
// click a line to solo it, mute lines with the speaker toggle, and press Play to
// hear a synth preview while the playhead sweeps the roll.
export default function SongPianoRollModal({ song, onClose }) {
  const { theme } = useTheme()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [playing, setPlaying] = useState(false)
  const [solo, setSolo] = useState(null) // soloed program, or null
  const [muted, setMuted] = useState(() => new Set())

  const rollRef = useRef(null)
  const timeRef = useRef(null)
  const playerRef = useRef(null)
  const audibleRef = useRef(() => true)

  const lines = useMemo(() => data?.lines || [], [data])

  useEffect(() => {
    let cancelled = false
    api
      .get(`/api/songs/${song.id}/notes`)
      .then(res => {
        if (!cancelled) setData(res.data)
      })
      .catch(err => {
        if (!cancelled) setError(err.response?.data?.detail || 'Could not load the song')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [song.id])

  // Keep the audio thread's mute/solo check pointing at the latest state.
  useEffect(() => {
    audibleRef.current = program =>
      (solo == null || program === solo) && !muted.has(program)
  }, [solo, muted])

  // Which programs render at full strength (others dim) — mirrors what's audible.
  const litPrograms = useMemo(() => {
    if (!lines.length) return null
    const audible = lines.filter(ln => (solo == null || ln.program === solo) && !muted.has(ln.program))
    if (audible.length === lines.length) return null
    return new Set(audible.map(ln => ln.program))
  }, [lines, solo, muted])

  // Build the player once the notes arrive; tear it down on close.
  useEffect(() => {
    if (!data) return undefined
    const player = new PreviewPlayer(data.notes, {
      duration: data.duration_s,
      isAudible: p => audibleRef.current(p),
      onTick: t => {
        rollRef.current?.setPlayhead(t)
        if (timeRef.current) timeRef.current.textContent = `${fmt(t)} / ${fmt(data.duration_s)}`
      },
      onEnd: () => setPlaying(false),
    })
    playerRef.current = player
    return () => {
      player.dispose()
      playerRef.current = null
    }
  }, [data])

  // Close on Escape.
  useEffect(() => {
    const onKey = e => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function togglePlay() {
    const p = playerRef.current
    if (!p) return
    if (playing) {
      p.pause()
      setPlaying(false)
    } else {
      p.play()
      setPlaying(true)
    }
  }

  function stop() {
    playerRef.current?.stop()
    setPlaying(false)
  }

  function toggleSolo(program) {
    setSolo(s => (s === program ? null : program))
  }

  function toggleMute(program) {
    setMuted(m => {
      const next = new Set(m)
      if (next.has(program)) next.delete(program)
      else next.add(program)
      return next
    })
  }

  function resetLines() {
    setSolo(null)
    setMuted(new Set())
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.head}>
          <h2 className={styles.title}>🎹 {song.name}</h2>
          <button className={styles.close} onClick={onClose} title="Close">✕</button>
        </div>

        {loading ? (
          <p className={styles.muted}>Loading notes…</p>
        ) : error ? (
          <p className={styles.error}>{error}</p>
        ) : (
          <>
            <div className={styles.transport}>
              <button className={styles.playBtn} onClick={togglePlay}>
                {playing ? '⏸ Pause' : '▶ Play'}
              </button>
              <button className={styles.stopBtn} onClick={stop} title="Stop and rewind">
                ⏹
              </button>
              <span className={styles.time} ref={timeRef}>
                {`0:00 / ${fmt(data.duration_s)}`}
              </span>
              <span className={styles.previewNote}>
                synth preview — not the real clip sound
              </span>
            </div>

            <p className={styles.muted}>
              Each colour is one instrument line. Click a line to solo it, or mute
              it with the speaker. Click the roll to jump the playhead.
            </p>

            <div className={styles.legend}>
              <button
                type="button"
                className={`${styles.legendItem} ${solo == null && muted.size === 0 ? styles.legendActive : ''}`}
                onClick={resetLines}
              >
                All lines
              </button>
              {lines.map((ln, i) => {
                const isSolo = solo === ln.program
                const isMuted = muted.has(ln.program)
                return (
                  <span
                    key={ln.program}
                    className={`${styles.legendItem} ${isSolo ? styles.legendActive : ''} ${isMuted ? styles.legendMuted : ''}`}
                  >
                    <button
                      type="button"
                      className={styles.legendMain}
                      onClick={() => toggleSolo(ln.program)}
                      title={`${ln.note_count} notes — click to solo`}
                    >
                      <span className={styles.swatch} style={{ background: lineColour(i, theme) }} />
                      <span className={styles.legendName}>{gmInstrumentName(ln.program)}</span>
                      <span className={styles.legendCount}>{ln.note_count}</span>
                    </button>
                    <button
                      type="button"
                      className={styles.muteBtn}
                      onClick={() => toggleMute(ln.program)}
                      title={isMuted ? 'Unmute' : 'Mute'}
                    >
                      {isMuted ? '🔇' : '🔊'}
                    </button>
                  </span>
                )
              })}
            </div>

            <PianoRoll
              ref={rollRef}
              notes={data.notes}
              lines={lines}
              duration={data.duration_s}
              litPrograms={litPrograms}
              onSeek={t => playerRef.current?.seek(t)}
            />

            {data.truncated && (
              <p className={styles.muted}>
                This song is large — showing the busiest {data.notes.length} notes.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
