import styles from './SongHistory.module.css'

function timeAgo(isoString) {
  const seconds = Math.floor((Date.now() - new Date(isoString)) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

// Right-hand sidebar list of song plays. Clicking an entry replays it with the
// same settings (if the song still exists).
export default function SongHistory({ history, songs, onReplay }) {
  return (
    <>
      <h2 className={styles.title}>Song History</h2>
      {!history || history.length === 0 ? (
        <p className={styles.empty}>No songs played yet</p>
      ) : (
        <ol className={styles.list}>
          {history.slice(0, 50).map((h, i) => {
            const found = songs.find(s => s.id === h.song_id)
            const replay = () => found && onReplay(found, {
              clip_ref: h.clip_ref,
              clip_name: h.clip_name,
              transpose: h.transpose,
              speed: h.speed,
              gain: h.gain,
              max_seconds: h.max_seconds,
              instruments: h.instruments || [],
            })
            const lineCount = (h.instruments || []).length
            return (
              <li
                key={i}
                className={`${styles.item} ${found ? styles.clickable : ''}`}
                onClick={found ? replay : undefined}
                title={found
                  ? `Replay ${h.song_name} on ${h.clip_name} with these settings`
                  : `${h.song_name} on ${h.clip_name} (song no longer available)`}
              >
                <span className={styles.name}>
                  🎵 {h.song_name} <span className={styles.on}>on {h.clip_name}</span>
                  {lineCount > 0 && (
                    <span className={styles.on}> +{lineCount} instrument{lineCount > 1 ? 's' : ''}</span>
                  )}
                </span>
                <span className={styles.meta}>
                  {h.requested_by} · {timeAgo(h.played_at)}
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </>
  )
}
