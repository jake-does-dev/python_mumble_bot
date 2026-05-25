import { useState } from 'react'
import styles from './ClipCard.module.css'

const PITCH_MIN = -12
const PITCH_MAX = 12
const SPEED_MIN = 0.05
const SPEED_MAX = 4
const SPEED_STEP = 0.05
const STORAGE_KEY = 'pmb_clip_settings'

function loadSetting(identifier, key, defaultValue) {
  try {
    const all = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    return all[identifier]?.[key] ?? defaultValue
  } catch {
    return defaultValue
  }
}

function saveSetting(identifier, key, value) {
  try {
    const all = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    all[identifier] = { ...all[identifier], [key]: value }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all))
  } catch {}
}

function pitchLabel(v) {
  if (v === 0) return '0 st'
  return `${v > 0 ? '+' : ''}${v} st`
}

export default function ClipCard({ clip, onToggleFavourite, onPlay, playing }) {
  const [pitch, setPitch] = useState(() => loadSetting(clip.identifier, 'pitch', 0))
  const [speed, setSpeed] = useState(() => loadSetting(clip.identifier, 'speed', 1))

  return (
    <div className={styles.card}>
      <div className={styles.name}>{clip.name}</div>
      <div className={styles.tags}>
        {clip.tags.map(tag => (
          <span key={tag} className={styles.tag}>{tag}</span>
        ))}
      </div>

      <div className={styles.sliders}>
        <div className={styles.sliderRow}>
          <span className={styles.sliderLabel}>Pitch <strong>{pitchLabel(pitch)}</strong></span>
          <input
            type="range"
            min={PITCH_MIN}
            max={PITCH_MAX}
            step={1}
            value={pitch}
            onChange={e => { const v = Number(e.target.value); setPitch(v); saveSetting(clip.identifier, 'pitch', v) }}
            className={styles.slider}
          />
        </div>
        <div className={styles.sliderRow}>
          <span className={styles.sliderLabel}>Speed <strong>{speed.toFixed(2)}×</strong></span>
          <input
            type="range"
            min={SPEED_MIN}
            max={SPEED_MAX}
            step={SPEED_STEP}
            value={speed}
            onChange={e => { const v = Number(e.target.value); setSpeed(v); saveSetting(clip.identifier, 'speed', v) }}
            className={styles.slider}
          />
        </div>
      </div>

      <div className={styles.actions}>
        <button
          className={`${styles.star} ${clip.is_favourite ? styles.starred : ''}`}
          onClick={() => onToggleFavourite(clip.identifier)}
          title={clip.is_favourite ? 'Remove favourite' : 'Add favourite'}
        >
          {clip.is_favourite ? '★' : '☆'}
        </button>
        <button
          className={`${styles.play} ${playing ? styles.playing : ''}`}
          onClick={() => onPlay(clip.identifier, pitch, speed)}
          disabled={playing}
          title="Play"
        >
          {playing ? '…' : '▶'}
        </button>
      </div>
    </div>
  )
}
