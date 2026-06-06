import { useState, useEffect } from 'react'
import MarqueeName from './MarqueeName'
import styles from './NowPlaying.module.css'

// A little player above the song history: shows the currently-playing song with
// a progress bar + Skip, and the upcoming song queue. Songs play one at a time —
// the bot mirrors its state to `song_state`, polled by the parent.
export default function NowPlaying({ state, onSkip, skipping }) {
  const current = state?.current
  const queue = state?.queue || []
  const [now, setNow] = useState(Date.now())

  // Tick while a song plays so the progress bar advances smoothly between polls.
  useEffect(() => {
    if (!current) return
    const id = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [current])

  if (!current && queue.length === 0) return null

  let pct = 0
  let remaining = 0
  if (current) {
    const start = new Date(current.started_at).getTime()
    const dur = (current.duration_s || 0) * 1000
    const elapsed = Math.max(0, now - start)
    pct = dur > 0 ? Math.min(100, (elapsed / dur) * 100) : 0
    remaining = Math.max(0, Math.ceil((dur - elapsed) / 1000))
  }

  return (
    <div className={styles.player}>
      <div className={styles.head}>
        <span className={styles.label}>{current ? '▶ Now playing' : 'Up next'}</span>
        {current && (
          <button className={styles.skip} onClick={onSkip} disabled={skipping} title="Skip this song — anyone can">
            ⏭ Skip
          </button>
        )}
      </div>

      {current && (
        <div className={styles.current}>
          <MarqueeName text={current.song_name} className={styles.songName} />
          <div className={styles.meta}>on {current.clip_name} · {current.requested_by}</div>
          <div className={styles.bar}><div className={styles.fill} style={{ width: `${pct}%` }} /></div>
          <div className={styles.time}>{remaining}s left</div>
        </div>
      )}

      {queue.length > 0 && (
        <>
          <div className={styles.queueLabel}>Up next ({queue.length})</div>
          <ol className={styles.queue}>
            {queue.map((q, i) => (
              <li key={i} className={styles.queueItem}>
                <span className={styles.qIndex}>{i + 1}</span>
                <span className={styles.qName} title={q.song_name}>{q.song_name}</span>
                <span className={styles.qMeta}>{q.clip_name} · {q.requested_by}</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  )
}
