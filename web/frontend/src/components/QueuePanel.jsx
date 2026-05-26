import { useState } from 'react'
import styles from './QueuePanel.module.css'

function pitchLabel(v) {
  if (v === 0) return '0st'
  return `${v > 0 ? '+' : ''}${v}st`
}

export default function QueuePanel({
  queues, activeQueueId, onSelectQueue,
  onCreateQueue, onDeleteQueue, onRenameQueue,
  onRemoveItem, onMoveItem, onPlayQueue, onClearQueue,
  playingQueue,
}) {
  const [creating, setCreating] = useState(false)
  const [createName, setCreateName] = useState('')
  const [renamingId, setRenamingId] = useState(null)
  const [renameName, setRenameName] = useState('')

  const active = queues.find(q => q.id === activeQueueId)

  function submitCreate(e) {
    e?.preventDefault()
    const name = createName.trim() || `Queue ${queues.length + 1}`
    onCreateQueue(name)
    setCreateName('')
    setCreating(false)
  }

  function submitRename(e) {
    e?.preventDefault()
    const name = renameName.trim()
    if (name) onRenameQueue(renamingId, name)
    setRenamingId(null)
  }

  return (
    <div className={styles.panel}>
      <div className={styles.selectorRow}>
        {queues.length > 0 ? (
          <select
            className={styles.select}
            value={activeQueueId || ''}
            onChange={e => onSelectQueue(e.target.value)}
          >
            {queues.map(q => (
              <option key={q.id} value={q.id}>
                {q.name}{q.items.length > 0 ? ` (${q.items.length})` : ''}
              </option>
            ))}
          </select>
        ) : (
          <span className={styles.emptyLabel}>No queues yet</span>
        )}
        <div className={styles.selectorBtns}>
          {active && <>
            <button
              className={styles.iconBtn}
              onClick={() => { setRenamingId(active.id); setRenameName(active.name) }}
              title="Rename queue"
            >✎</button>
            <button
              className={styles.iconBtn}
              onClick={() => onDeleteQueue(active.id)}
              title="Delete queue"
            >×</button>
          </>}
          <button className={`${styles.iconBtn} ${styles.newBtn}`} onClick={() => setCreating(true)} title="New queue">+</button>
        </div>
      </div>

      {creating && (
        <form className={styles.nameForm} onSubmit={submitCreate}>
          <input
            className={styles.nameInput}
            autoFocus
            value={createName}
            onChange={e => setCreateName(e.target.value)}
            placeholder={`Queue ${queues.length + 1}`}
            onBlur={submitCreate}
            onKeyDown={e => { if (e.key === 'Escape') { setCreating(false); setCreateName('') } }}
          />
        </form>
      )}

      {renamingId && (
        <form className={styles.nameForm} onSubmit={submitRename}>
          <input
            className={styles.nameInput}
            autoFocus
            value={renameName}
            onChange={e => setRenameName(e.target.value)}
            onBlur={submitRename}
            onKeyDown={e => { if (e.key === 'Escape') setRenamingId(null) }}
          />
        </form>
      )}

      {active ? (
        active.items.length === 0
          ? <p className={styles.empty}>Add clips using + on any card</p>
          : (
            <ol className={styles.list}>
              {active.items.map((item, idx) => (
                <li key={item.id} className={styles.item}>
                  <div className={styles.itemMain}>
                    <span className={styles.itemName}>{item.name}</span>
                    <span className={styles.itemMeta}>{pitchLabel(item.pitch)} · {item.speed.toFixed(2)}×</span>
                  </div>
                  <div className={styles.itemBtns}>
                    <button className={styles.iconBtn} onClick={() => onMoveItem(activeQueueId, item.id, -1)} disabled={idx === 0}>↑</button>
                    <button className={styles.iconBtn} onClick={() => onMoveItem(activeQueueId, item.id, 1)} disabled={idx === active.items.length - 1}>↓</button>
                    <button className={styles.iconBtn} onClick={() => onRemoveItem(activeQueueId, item.id)}>×</button>
                  </div>
                </li>
              ))}
            </ol>
          )
      ) : (
        queues.length > 0 && <p className={styles.empty}>Select a queue above</p>
      )}

      {active && active.items.length > 0 && (
        <div className={styles.footer}>
          <button className={styles.clearBtn} onClick={() => onClearQueue(activeQueueId)}>Clear</button>
          <button className={styles.playBtn} onClick={() => onPlayQueue(activeQueueId)} disabled={playingQueue}>
            {playingQueue ? 'Playing…' : `▶ Play (${active.items.length})`}
          </button>
        </div>
      )}
    </div>
  )
}
