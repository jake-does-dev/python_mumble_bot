import { forwardRef, memo, useImperativeHandle, useMemo, useRef } from 'react'
import { gmInstrumentName } from '../lib/gmInstruments'
import { buildColourMap } from '../lib/pianoRoll'
import styles from './PianoRoll.module.css'

const PX_PER_SEC = 40 // horizontal zoom
const ROW_H = 6 // pixels per semitone
const PAD_SEMITONES = 2 // breathing room above/below the pitch range
const NOTE_NAMES = ['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B']

function noteLabel(pitch) {
  return `${NOTE_NAMES[pitch % 12]}${Math.floor(pitch / 12) - 1}`
}

// Time-axis tick spacing: keep ~8–16 labels regardless of song length.
function tickStep(duration) {
  for (const step of [1, 2, 5, 10, 15, 30, 60]) {
    if (duration / step <= 16) return step
  }
  return 120
}

// `litPrograms`: a Set of programs to show at full strength (others dim), or null
// for "all lit". `onSeek(seconds)` fires on click. The parent drives the playhead
// imperatively via the ref handle (`setPlayhead`) so per-frame updates don't
// re-render the note rects.
const PianoRoll = forwardRef(function PianoRoll(
  { notes, lines, duration, litPrograms = null, onSeek },
  ref
) {
  const colourMap = useMemo(() => buildColourMap(lines), [lines])
  const scrollRef = useRef(null)
  const playheadRef = useRef(null)

  useImperativeHandle(ref, () => ({
    // Position the playhead at `t` seconds (null hides it) and keep it in view.
    setPlayhead(t) {
      const ph = playheadRef.current
      const sc = scrollRef.current
      if (!ph || !sc) return
      if (t == null) {
        ph.style.opacity = '0'
        return
      }
      const x = t * PX_PER_SEC
      ph.style.opacity = '1'
      ph.style.transform = `translateX(${x}px)`
      const view = sc.clientWidth
      const maxScroll = Math.max(0, sc.scrollWidth - view)
      // Keep the playhead ~35% from the left so the roll slides under it.
      sc.scrollLeft = Math.max(0, Math.min(x - view * 0.35, maxScroll))
    },
  }), [])

  const geom = useMemo(() => {
    if (!notes.length) return null
    let lo = Infinity
    let hi = -Infinity
    let maxEnd = 0
    for (const n of notes) {
      if (n.p < lo) lo = n.p
      if (n.p > hi) hi = n.p
      const end = n.s + n.d
      if (end > maxEnd) maxEnd = end
    }
    const minPitch = lo - PAD_SEMITONES
    const maxPitch = hi + PAD_SEMITONES
    const span = maxPitch - minPitch
    const width = Math.max(1, (duration || maxEnd)) * PX_PER_SEC
    const height = span * ROW_H
    return { minPitch, maxPitch, span, width, height, maxEnd }
  }, [notes, duration])

  if (!geom) {
    return <p className={styles.empty}>No playable notes to show.</p>
  }

  const { minPitch, maxPitch, width, height } = geom
  const yOf = pitch => (maxPitch - pitch) * ROW_H

  // Octave gridlines + labels at each C.
  const cLines = []
  for (let p = Math.ceil(minPitch / 12) * 12; p <= maxPitch; p += 12) {
    cLines.push(p)
  }

  const totalSecs = duration || geom.maxEnd
  const step = tickStep(totalSecs || 1)
  const ticks = []
  for (let t = 0; t <= totalSecs + 0.001; t += step) ticks.push(t)

  function handleClick(e) {
    if (!onSeek) return
    const rect = e.currentTarget.getBoundingClientRect()
    onSeek((e.clientX - rect.left) / PX_PER_SEC)
  }

  return (
    <div className={styles.root}>
      <div className={styles.scroll} ref={scrollRef}>
        <div
          className={styles.canvas}
          style={{ width, height }}
          onClick={handleClick}
        >
          <svg
            className={styles.svg}
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="Piano roll of the song's notes, coloured by instrument"
          >
            {/* Octave gridlines (recessive) + pitch labels pinned left. */}
            {cLines.map(p => (
              <g key={`c${p}`}>
                <line
                  className={styles.grid}
                  x1={0}
                  x2={width}
                  y1={yOf(p) + ROW_H}
                  y2={yOf(p) + ROW_H}
                />
                <text className={styles.pitchLabel} x={3} y={yOf(p) + ROW_H - 1}>
                  {noteLabel(p)}
                </text>
              </g>
            ))}
            {/* Time gridlines + second labels along the top. */}
            {ticks.map(t => (
              <g key={`t${t}`}>
                <line
                  className={styles.gridV}
                  x1={t * PX_PER_SEC}
                  x2={t * PX_PER_SEC}
                  y1={0}
                  y2={height}
                />
                <text className={styles.timeLabel} x={t * PX_PER_SEC + 2} y={11}>
                  {t}s
                </text>
              </g>
            ))}
            {/* Notes, coloured by instrument line. Muted / un-soloed lines dim. */}
            {notes.map((n, i) => {
              const slot = colourMap.get(n.g) || 'roll-other'
              const dim = litPrograms != null && !litPrograms.has(n.g)
              return (
                <rect
                  key={i}
                  className={`${styles.note} ${styles[slot]} ${dim ? styles.dim : ''}`}
                  x={n.s * PX_PER_SEC}
                  y={yOf(n.p)}
                  width={Math.max(2, n.d * PX_PER_SEC)}
                  height={ROW_H - 1}
                  rx={1.5}
                >
                  <title>{`${noteLabel(n.p)} · ${gmInstrumentName(n.g)}`}</title>
                </rect>
              )
            })}
          </svg>
          {/* Playhead — moved imperatively; lives in content space so it scrolls
              with the roll. */}
          <div className={styles.playhead} ref={playheadRef} />
        </div>
      </div>
    </div>
  )
})

export default memo(PianoRoll)
