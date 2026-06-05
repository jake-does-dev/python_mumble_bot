import { useRef, useState } from 'react'
import MarqueeName from './MarqueeName'
import styles from './SongsPanel.module.css'

function timeAgo(isoString) {
  const seconds = Math.floor((Date.now() - new Date(isoString)) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export default function SongsPanel({
  songs, clips, username, isAdmin, history,
  onUpload, onDelete, onRename, onPlay, cooldownRemaining, uploadError,
}) {
  const fileRef = useRef(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [renaming, setRenaming] = useState(null)   // song id being renamed
  const [renameValue, setRenameValue] = useState('')
  const [search, setSearch] = useState('')

  const q = search.trim().toLowerCase()
  const filtered = q ? songs.filter(s => s.name.toLowerCase().includes(q)) : songs

  function pick(e) {
    const file = e.target.files?.[0]
    if (file) onUpload(file)
    e.target.value = ''  // allow re-selecting the same file
  }

  function startRename(song) {
    setConfirmDelete(null)
    setRenaming(song.id)
    setRenameValue(song.name)
  }

  function commitRename(songId) {
    const name = renameValue.trim()
    if (name) onRename(songId, name)
    setRenaming(null)
  }

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <h2 className={styles.title}>Songs</h2>
        <button className={styles.upload} onClick={() => fileRef.current?.click()}>
          ↑ Upload .mid
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".mid,.midi,audio/midi"
          style={{ display: 'none' }}
          onChange={pick}
        />
      </div>

      <p className={styles.blurb}>
        Upload a MIDI, then play it with any clip as the instrument.
      </p>
      {uploadError && <p className={styles.error}>{uploadError}</p>}

      {songs.length > 0 && (
        <input
          className={styles.search}
          placeholder="Search songs…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      )}

      <div className={styles.scroll}>
      {songs.length === 0 ? (
        <p className={styles.empty}>No songs yet — upload a .mid to start.</p>
      ) : filtered.length === 0 ? (
        <p className={styles.empty}>No songs match “{search}”.</p>
      ) : (
        <ul className={styles.list}>
          {filtered.map(song => (
            <li key={song.id} className={styles.item}>
              {renaming === song.id ? (
                <div className={styles.renameRow}>
                  <input
                    className={styles.renameInput}
                    value={renameValue}
                    autoFocus
                    onChange={e => setRenameValue(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') commitRename(song.id)
                      if (e.key === 'Escape') setRenaming(null)
                    }}
                  />
                  <button className={styles.renameSave} onClick={() => commitRename(song.id)}>✓</button>
                  <button className={styles.renameCancel} onClick={() => setRenaming(null)}>✕</button>
                </div>
              ) : (
                <MarqueeName text={song.name} className={styles.name} />
              )}

              <span className={styles.meta}>
                {song.note_count} notes · {Math.round(song.duration_s)}s · ↑ {song.uploaded_by}
              </span>

              <div className={styles.actions}>
                <button
                  className={styles.play}
                  onClick={() => onPlay(song)}
                  disabled={cooldownRemaining > 0 || clips.length === 0}
                  title={cooldownRemaining > 0 ? `Wait ${cooldownRemaining}s` : 'Play this song'}
                >
                  {cooldownRemaining > 0 ? `▶ ${cooldownRemaining}s` : '▶ Play'}
                </button>
                {(isAdmin || song.uploaded_by === username) && (
                  <>
                    <button className={styles.iconBtn} onClick={() => startRename(song)} title="Rename">✎</button>
                    {confirmDelete === song.id ? (
                      <button
                        className={`${styles.iconBtn} ${styles.delConfirm}`}
                        onClick={() => { onDelete(song.id); setConfirmDelete(null) }}
                        title="Confirm delete"
                      >✓</button>
                    ) : (
                      <button className={styles.iconBtn} onClick={() => setConfirmDelete(song.id)} title="Delete">🗑</button>
                    )}
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {history && history.length > 0 && (
        <div className={styles.historyBlock}>
          <h3 className={styles.historyTitle}>Recently played</h3>
          <ol className={styles.historyList}>
            {history.slice(0, 30).map((h, i) => {
              const found = songs.find(s => s.id === h.song_id)
              const replay = () => found && onPlay(found, {
                clip_ref: h.clip_ref,
                clip_name: h.clip_name,
                transpose: h.transpose,
                speed: h.speed,
                gain: h.gain,
                max_seconds: h.max_seconds,
              })
              return (
                <li
                  key={i}
                  className={`${styles.historyItem} ${found ? styles.historyClickable : ''}`}
                  onClick={found ? replay : undefined}
                  title={found
                    ? `Replay ${h.song_name} on ${h.clip_name} with these settings`
                    : `${h.song_name} on ${h.clip_name} (song no longer available)`}
                >
                  <span className={styles.historyName}>
                    🎵 {h.song_name} <span className={styles.historyOn}>on {h.clip_name}</span>
                  </span>
                  <span className={styles.historyMeta}>
                    {h.requested_by} · {timeAgo(h.played_at)}
                  </span>
                </li>
              )
            })}
          </ol>
        </div>
      )}
      </div>
    </div>
  )
}
