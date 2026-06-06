import {
  PITCH_MIN,
  PITCH_MAX,
  SPEED_SLIDER_STEPS,
  speedToSlider,
  sliderToSpeed,
  pitchLabel,
} from '../lib/clipSettings'
import styles from './SongInstrumentPanel.module.css'

// Sidebar "pick an instrument for this song" box. Lives in the Clips view so the
// user can use the full clip search/filter to find an instrument, click
// "🎵 Use as instrument" on any clip, then tweak the sliders here and play.
export default function SongInstrumentPanel({ pick, onUpdate, onPlay, onCancel, cooldownRemaining }) {
  const { song, clipRef, clipName, transpose, speed, gain, maxSeconds } = pick
  const limitMax = Math.min(300, Math.max(30, Math.ceil(song.duration_s || 0)))
  const onCooldown = cooldownRemaining > 0
  const ready = !!clipRef && !onCooldown

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <span className={styles.label}>🎵 Pick instrument</span>
        <button className={styles.cancel} onClick={onCancel} title="Cancel">✕</button>
      </div>

      <div className={styles.song} title={song.name}>{song.name}</div>

      <div className={clipRef ? styles.selected : styles.prompt}>
        {clipRef
          ? <><span className={styles.selDot}>▶</span> {clipName || clipRef}</>
          : '← Search clips, then “🎵 Use as instrument”'}
      </div>

      <div className={styles.group}>
        <label className={styles.row}>
          <span>Transpose <strong>{pitchLabel(transpose)}</strong></span>
          <input type="range" min={PITCH_MIN} max={PITCH_MAX} step={1}
            value={transpose} onChange={e => onUpdate({ transpose: Number(e.target.value) })} />
        </label>
        <label className={styles.row}>
          <span>Speed <strong>{speed.toFixed(2)}×</strong></span>
          <input type="range" min={0} max={SPEED_SLIDER_STEPS} step={1}
            value={speedToSlider(speed)}
            onChange={e => onUpdate({ speed: sliderToSpeed(Number(e.target.value)) })} />
        </label>
        <label className={styles.row}>
          <span>Volume <strong>{gain > 0 ? '+' : ''}{gain} dB</strong></span>
          <input type="range" min={-12} max={12} step={1}
            value={gain} onChange={e => onUpdate({ gain: Number(e.target.value) })} />
        </label>
        <label className={styles.row}>
          <span>Time limit <strong>{maxSeconds === 0 ? 'Full song' : `${maxSeconds}s`}</strong></span>
          <input type="range" min={0} max={limitMax} step={5}
            value={maxSeconds} onChange={e => onUpdate({ maxSeconds: Number(e.target.value) })} />
        </label>
      </div>

      <button className={styles.play} onClick={onPlay} disabled={!ready}>
        {onCooldown ? `Wait ${cooldownRemaining}s…` : (clipRef ? '🎵 Play' : 'Pick a clip first')}
      </button>
    </div>
  )
}
