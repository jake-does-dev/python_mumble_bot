import { useEffect, useState } from 'react'
import api from '../api'
import { useTheme } from '../context/ThemeContext'
import { gmInstrumentName } from '../lib/gmInstruments'
import { lineColour } from '../lib/pianoRoll'
import PianoRoll from './PianoRoll'
import styles from './SongPianoRollModal.module.css'

// Full-width piano-roll visualiser for a song, opened from a SongCard. Notes are
// coloured by instrument line so you can see which instrument plays which part;
// click a line in the legend to isolate (highlight) just its notes.
export default function SongPianoRollModal({ song, onClose }) {
  const { theme } = useTheme()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeProgram, setActiveProgram] = useState(null)

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

  // Close on Escape.
  useEffect(() => {
    const onKey = e => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const lines = data?.lines || []

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
            <p className={styles.muted}>
              Each colour is one instrument line. Click one to highlight just its
              notes — that’s the part you assign a clip to when you play the song.
            </p>

            <div className={styles.legend}>
              <button
                type="button"
                className={`${styles.legendItem} ${activeProgram == null ? styles.legendActive : ''}`}
                onClick={() => setActiveProgram(null)}
              >
                All lines
              </button>
              {lines.map((ln, i) => {
                const active = activeProgram === ln.program
                return (
                  <button
                    key={ln.program}
                    type="button"
                    className={`${styles.legendItem} ${active ? styles.legendActive : ''}`}
                    onClick={() => setActiveProgram(active ? null : ln.program)}
                    title={`${ln.note_count} notes`}
                  >
                    <span
                      className={styles.swatch}
                      style={{ background: lineColour(i, theme) }}
                    />
                    <span className={styles.legendName}>{gmInstrumentName(ln.program)}</span>
                    <span className={styles.legendCount}>{ln.note_count}</span>
                  </button>
                )
              })}
            </div>

            <PianoRoll
              notes={data.notes}
              lines={lines}
              duration={data.duration_s}
              activeProgram={activeProgram}
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
