import {
  PITCH_MIN,
  PITCH_MAX,
  SPEED_SLIDER_STEPS,
  speedToSlider,
  sliderToSpeed,
  pitchLabel,
} from '../lib/clipSettings'
import { gmInstrumentName } from '../lib/gmInstruments'
import styles from './SongInstrumentPanel.module.css'

// Sidebar "pick an instrument for this song" box. Lives in the Clips view so the
// user can use the full clip search/filter to find an instrument, click
// "🎵 Use as instrument" on any clip, then tweak the sliders here and play.
//
// Multi-line songs: each instrument "line" can get its own clip. Click a line to
// make it active, then "Use as instrument" assigns to that line. Lines left
// unassigned fall back to the default clip.
export default function SongInstrumentPanel({ pick, onUpdate, onPlay, onCancel, cooldownRemaining }) {
  const { song, clipRef, clipName, transpose, speed, gain, maxSeconds } = pick
  const lines = pick.lines || []
  const assignments = pick.assignments || {}
  const activeProgram = pick.activeProgram
  const limitMax = Math.min(300, Math.max(30, Math.ceil(song.duration_s || 0)))
  const onCooldown = cooldownRemaining > 0
  const ready = !!clipRef && !onCooldown
  // Only worth showing the per-line UI when the song actually has >1 line.
  const multiLine = lines.length > 1

  function setActive(program) {
    onUpdate({ activeProgram: activeProgram === program ? null : program })
  }
  function clearLine(program) {
    const next = { ...assignments }
    delete next[program]
    onUpdate({ assignments: next })
  }
  function setLineGain(program, g) {
    const cur = assignments[program]
    if (!cur) return
    onUpdate({ assignments: { ...assignments, [program]: { ...cur, gain: g } } })
  }

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <span className={styles.label}>🎵 Pick instrument</span>
        <button className={styles.cancel} onClick={onCancel} title="Cancel">✕</button>
      </div>

      <div className={styles.song} title={song.name}>{song.name}</div>

      {/* Default instrument (used by every line you don't override). */}
      <button
        type="button"
        className={`${styles.lineRow} ${activeProgram == null ? styles.lineActive : ''}`}
        onClick={() => onUpdate({ activeProgram: null })}
        title="Pick the default clip — used for any line you don't customise"
      >
        <span className={styles.lineName}>{multiLine ? 'All / default' : 'Instrument'}</span>
        <span className={clipRef ? styles.lineClip : styles.lineClipEmpty}>
          {clipRef ? (clipName || clipRef) : 'pick a clip →'}
        </span>
      </button>

      {multiLine && (
        <div className={styles.lines}>
          <div className={styles.linesHint}>
            {activeProgram == null
              ? 'Tap a line, then “Use as instrument” on a clip'
              : 'Now tap a clip’s “Use as instrument”'}
          </div>
          {lines.map(ln => {
            const a = assignments[ln.program]
            const active = activeProgram === ln.program
            return (
              <div key={ln.program} className={styles.line}>
                <button
                  type="button"
                  className={`${styles.lineRow} ${active ? styles.lineActive : ''}`}
                  onClick={() => setActive(ln.program)}
                  title={`${ln.note_count} notes`}
                >
                  <span className={styles.lineName}>{gmInstrumentName(ln.program)}</span>
                  <span className={a ? styles.lineClip : styles.lineClipEmpty}>
                    {a ? (a.clipName || a.clipRef) : 'default'}
                  </span>
                </button>
                {a && (
                  <div className={styles.lineCtl}>
                    <span className={styles.lineVol}>{a.gain > 0 ? '+' : ''}{a.gain} dB</span>
                    <input
                      type="range" min={-12} max={12} step={1} value={a.gain}
                      onChange={e => setLineGain(ln.program, Number(e.target.value))}
                    />
                    <button className={styles.lineClear} onClick={() => clearLine(ln.program)} title="Reset to default">✕</button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

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
          <input type="range" min={-12} max={0} step={1}
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
