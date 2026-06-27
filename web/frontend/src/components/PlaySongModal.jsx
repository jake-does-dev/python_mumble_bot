import { useState, useMemo } from 'react'
import {
  PITCH_MIN,
  PITCH_MAX,
  SPEED_SLIDER_STEPS,
  speedToSlider,
  sliderToSpeed,
  pitchLabel,
} from '../lib/clipSettings'
import styles from './PlaySongModal.module.css'

export default function PlaySongModal({ song, clips, preset, onClose, onPlay }) {
  // `preset` (from a "Recently played" click) pre-fills the controls with that
  // previous play's selections, ready to fire again.
  const [search, setSearch] = useState(preset?.clip_name || '')
  const [clipRef, setClipRef] = useState(preset?.clip_ref || null)
  const [clipName, setClipName] = useState(preset?.clip_name || '')
  const [transpose, setTranspose] = useState(preset?.transpose ?? 0)
  const [speed, setSpeed] = useState(preset?.speed ?? 1.0)
  const [gain, setGain] = useState(preset?.gain ?? -6)  // music starts a touch quieter than clips
  const [maxSeconds, setMaxSeconds] = useState(preset?.max_seconds ?? 10)  // default cap; 0 = full song

  const limitMax = Math.min(300, Math.max(30, Math.ceil(song.duration_s || 0)))

  const matches = useMemo(() => {
    const q = search.trim().toLowerCase()
    const list = q
      ? clips.filter(c =>
          c.name.toLowerCase().includes(q) || c.identifier.toLowerCase().includes(q))
      : clips
    return list.slice(0, 50)
  }, [search, clips])

  function play() {
    if (!clipRef) return
    onPlay(song.id, {
      clip_ref: clipRef,
      clip_name: clipName,
      transpose,
      speed: Math.round(speed * 100) / 100,
      gain,
      max_seconds: maxSeconds,
    })
    onClose()
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.head}>
          <div>
            <span className={styles.kind}>Play song</span>
            <h3 className={styles.title}>{song.name}</h3>
          </div>
          <button className={styles.close} onClick={onClose}>✕</button>
        </div>

        <p className={styles.blurb}>
          Pick a clip to use as the instrument — it'll be pitch-shifted to play the
          tune ({song.note_count} notes).
        </p>

        <div className={styles.group}>
          <div className={styles.groupLabel}>Instrument clip</div>
          <input
            className={styles.searchInput}
            placeholder="Search clips…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            autoFocus
          />
          <ul className={styles.clipList}>
            {matches.map(c => (
              <li
                key={c.identifier}
                className={`${styles.clipItem} ${clipRef === c.identifier ? styles.clipItemActive : ''}`}
                onClick={() => { setClipRef(c.identifier); setClipName(c.name) }}
              >
                {c.name}
              </li>
            ))}
            {matches.length === 0 && <li className={styles.clipEmpty}>No clips match</li>}
          </ul>
        </div>

        <div className={styles.group}>
          <label className={styles.row}>
            <span>Transpose <strong>{pitchLabel(transpose)}</strong></span>
            <input type="range" min={PITCH_MIN} max={PITCH_MAX} step={1}
              value={transpose} onChange={e => setTranspose(Number(e.target.value))} />
          </label>
          <label className={styles.row}>
            <span>Speed <strong>{speed.toFixed(2)}×</strong></span>
            <input type="range" min={0} max={SPEED_SLIDER_STEPS} step={1}
              value={speedToSlider(speed)}
              onChange={e => setSpeed(sliderToSpeed(Number(e.target.value)))} />
          </label>
          <label className={styles.row}>
            <span>Volume <strong>{gain > 0 ? '+' : ''}{gain} dB</strong></span>
            <input type="range" min={-12} max={12} step={1}
              value={gain} onChange={e => setGain(Number(e.target.value))} />
          </label>
          <label className={styles.row}>
            <span>Time limit <strong>{maxSeconds === 0 ? 'Full song' : `${maxSeconds}s`}</strong></span>
            <input type="range" min={0} max={limitMax} step={5}
              value={maxSeconds} onChange={e => setMaxSeconds(Number(e.target.value))} />
          </label>
        </div>

        <div className={styles.actions}>
          <button className={styles.cancel} onClick={onClose}>Cancel</button>
          <button className={styles.play} onClick={play} disabled={!clipRef}>
            🎵 Play
          </button>
        </div>
      </div>
    </div>
  )
}
