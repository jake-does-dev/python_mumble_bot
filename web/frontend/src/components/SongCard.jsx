import { useState } from 'react'
import MarqueeName from './MarqueeName'
import styles from './SongCard.module.css'

export default function SongCard({
  song, view, username, isAdmin, cooldownRemaining, onPlay, onRename, onDelete,
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(song.name)
  const canEdit = isAdmin || song.uploaded_by === username

  function commitRename() {
    const name = renameValue.trim()
    if (name && name !== song.name) onRename(song.id, name)
    setRenaming(false)
  }

  return (
    <div className={`${styles.card} ${view === 'list' ? styles.cardList : ''}`}>
      <div className={styles.info}>
        {renaming ? (
          <div className={styles.renameRow}>
            <input
              className={styles.renameInput}
              value={renameValue}
              autoFocus
              onChange={e => setRenameValue(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') commitRename()
                if (e.key === 'Escape') setRenaming(false)
              }}
            />
            <button className={styles.iconBtn} onClick={commitRename} title="Save">✓</button>
            <button className={styles.iconBtn} onClick={() => setRenaming(false)} title="Cancel">✕</button>
          </div>
        ) : (
          <MarqueeName text={song.name} className={styles.name} />
        )}
        <span className={styles.meta}>
          {song.note_count} notes · {Math.round(song.duration_s)}s · ↑ {song.uploaded_by}
        </span>
      </div>

      <div className={styles.actions}>
        <button
          className={styles.play}
          onClick={() => onPlay(song)}
          disabled={cooldownRemaining > 0}
          title={cooldownRemaining > 0 ? `Wait ${cooldownRemaining}s` : 'Play this song'}
        >
          {cooldownRemaining > 0 ? `▶ ${cooldownRemaining}s` : '▶ Play'}
        </button>
        {canEdit && (
          <>
            <button
              className={styles.iconBtn}
              onClick={() => { setRenaming(true); setRenameValue(song.name); setConfirmDelete(false) }}
              title="Rename"
            >✎</button>
            {confirmDelete ? (
              <button
                className={`${styles.iconBtn} ${styles.delConfirm}`}
                onClick={() => { onDelete(song.id); setConfirmDelete(false) }}
                title="Confirm delete"
              >✓</button>
            ) : (
              <button className={styles.iconBtn} onClick={() => setConfirmDelete(true)} title="Delete">🗑</button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
