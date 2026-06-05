import { useState, useRef, useEffect } from 'react'
import api from '../api'
import TrimModal from './TrimModal'
import GenerateQueueModal from './GenerateQueueModal'
import {
  PITCH_MIN,
  PITCH_MAX,
  SPEED_SLIDER_STEPS,
  speedToSlider,
  sliderToSpeed,
  loadSetting,
  saveSetting,
  pitchLabel,
} from '../lib/clipSettings'
import styles from './ClipCard.module.css'

function formatDate(iso) {
  if (!iso) return null
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function ClipCard({ clip, onToggleFavourite, onPlay, onDelete, onAddToQueue, onGenerateQueue, onEdit, onVote, onTrimmed, onGain, username = null, playing, isAdmin = false, view = 'grid', preset = null }) {
  const [pitch, setPitch] = useState(() => loadSetting(clip.identifier, 'pitch', 0))
  const [speed, setSpeed] = useState(() => loadSetting(clip.identifier, 'speed', 1))
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState(clip.name)
  const [editTags, setEditTags] = useState((clip.tags || []).join(', '))
  const [editError, setEditError] = useState(null)
  const [previewing, setPreviewing] = useState(false)
  const [trimming, setTrimming] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [gainDb, setGainDb] = useState(clip.gain_db ?? 0)
  const [gainSaving, setGainSaving] = useState(false)
  const nameInnerRef = useRef(null)
  const audioRef = useRef(null)
  const urlRef = useRef(null)
  const urlKeyRef = useRef(null)  // pitch|speed the cached preview was rendered at

  const canEdit = isAdmin || (clip.uploaded_by && clip.uploaded_by === username)

  // Clicking a history entry pushes that play's pitch/speed onto this card.
  useEffect(() => {
    if (!preset) return
    setPitch(preset.pitch)
    saveSetting(clip.identifier, 'pitch', preset.pitch)
    setSpeed(preset.speed)
    saveSetting(clip.identifier, 'speed', preset.speed)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset?.nonce])

  useEffect(() => {
    return () => {
      if (audioRef.current) audioRef.current.pause()
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    }
  }, [])

  async function handleDownload() {
    // Fetch via the API (so the auth header is sent — a plain <a href> can't),
    // then hand the blob to a temporary download link with the real filename.
    setDownloading(true)
    try {
      const res = await api.get(`/api/clips/${clip.identifier}/audio`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = clip.file || clip.name
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch {
      /* ignore — nothing downloaded */
    } finally {
      setDownloading(false)
    }
  }

  async function togglePreview() {
    if (previewing && audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
      setPreviewing(false)
      return
    }
    try {
      // The preview is rendered server-side at the current pitch/speed (exactly
      // how the bot plays it), so drop the cached audio if those have changed.
      const key = `${pitch}|${speed}`
      if (urlRef.current && urlKeyRef.current !== key) {
        if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
        URL.revokeObjectURL(urlRef.current)
        urlRef.current = null
      }
      if (!urlRef.current) {
        const res = await api.get(`/api/clips/${clip.identifier}/audio`, {
          params: { pitch, speed },
          responseType: 'blob',
        })
        urlRef.current = URL.createObjectURL(res.data)
        urlKeyRef.current = key
      }
      if (!audioRef.current) {
        audioRef.current = new Audio(urlRef.current)
        audioRef.current.addEventListener('ended', () => setPreviewing(false))
      }
      audioRef.current.currentTime = 0
      await audioRef.current.play()
      setPreviewing(true)
    } catch {
      setPreviewing(false)
    }
  }

  function startEdit() {
    setEditName(clip.name)
    setEditTags((clip.tags || []).join(', '))
    setGainDb(clip.gain_db ?? 0)
    setEditError(null)
    setEditing(true)
  }

  async function commitGain(value) {
    if (!onGain || value === (clip.gain_db ?? 0)) return
    setGainSaving(true)
    try {
      await onGain(clip.identifier, value)
    } catch (err) {
      setEditError(err.response?.data?.detail || 'Volume update failed')
      setGainDb(clip.gain_db ?? 0)
    } finally {
      setGainSaving(false)
    }
  }

  async function saveEdit() {
    setEditError(null)
    try {
      await onEdit(clip.identifier, {
        name: editName.trim(),
        tags: editTags.split(',').map(t => t.trim()).filter(Boolean),
      })
      setEditing(false)
    } catch (err) {
      setEditError(err.response?.data?.detail || 'Update failed')
    }
  }

  useEffect(() => {
    const inner = nameInnerRef.current
    if (!inner) return
    const update = () => {
      const overflow = inner.scrollWidth - inner.parentElement.clientWidth
      if (overflow > 0) {
        inner.style.setProperty('--name-overflow', `-${overflow}px`)
        inner.dataset.scrollable = 'true'
      } else {
        inner.style.removeProperty('--name-overflow')
        delete inner.dataset.scrollable
      }
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(inner.parentElement)
    return () => ro.disconnect()
  }, [clip.name, editing])

  return (
    <div className={`${styles.card} ${view === 'list' ? styles.cardList : ''}`}>
      {editing ? (
        <div className={styles.editForm}>
          <input
            className={styles.editInput}
            value={editName}
            onChange={e => setEditName(e.target.value)}
            placeholder="name"
            spellCheck={false}
          />
          <input
            className={styles.editInput}
            value={editTags}
            onChange={e => setEditTags(e.target.value)}
            placeholder="tags, comma, separated"
          />
          {editError && <span className={styles.editError}>{editError}</span>}
          {isAdmin && (
            <div className={styles.gainRow}>
              <span className={styles.gainLabel}>
                Volume <strong>{gainDb > 0 ? `+${gainDb}` : gainDb} dB</strong>
                {gainSaving && <em className={styles.gainSaving}> saving…</em>}
              </span>
              <input
                type="range"
                min={-12}
                max={12}
                step={1}
                value={gainDb}
                onChange={e => setGainDb(Number(e.target.value))}
                onMouseUp={e => commitGain(Number(e.target.value))}
                onTouchEnd={e => commitGain(Number(e.target.value))}
                onKeyUp={e => commitGain(Number(e.target.value))}
                className={styles.slider}
                title="Per-clip volume trim, applied on top of loudness normalisation"
              />
            </div>
          )}
          <button type="button" className={styles.trimBtn} onClick={() => setTrimming(true)}>✂ Trim audio…</button>
          <div className={styles.editActions}>
            <button type="button" className={styles.editCancel} onClick={() => setEditing(false)}>Cancel</button>
            <button type="button" className={styles.editSave} onClick={saveEdit}>Save</button>
          </div>
        </div>
      ) : (
        <div className={styles.info}>
          <div className={styles.nameRow}>
            <span
              className={`${styles.name} ${styles.nameClickable} ${previewing ? styles.namePreviewing : ''}`}
              onClick={togglePreview}
              title="Click to preview in your browser"
              role="button"
            >
              <span className={styles.nameInner} ref={nameInnerRef}>
                {previewing ? '⏸ ' : ''}{clip.name}
              </span>
            </span>
            <span
              className={styles.identifier}
              title={clip.uploaded_by ? `id: ${clip.identifier}` : undefined}
            >
              {clip.uploaded_by ? `↑ ${clip.uploaded_by}` : clip.identifier}
            </span>
          </div>
          <div className={styles.tags}>
            {clip.tags.map(tag => (
              <span key={tag} className={styles.tag}>{tag}</span>
            ))}
          </div>
          <div className={styles.metaRow}>
            <div className={styles.votes}>
              <button
                className={`${styles.voteBtn} ${clip.my_vote === 1 ? styles.voteUp : ''}`}
                onClick={() => onVote(clip.identifier, clip.my_vote === 1 ? 0 : 1)}
                title="Upvote"
              >▲</button>
              <span className={styles.voteScore}>{clip.score ?? 0}</span>
              <button
                className={`${styles.voteBtn} ${clip.my_vote === -1 ? styles.voteDown : ''}`}
                onClick={() => onVote(clip.identifier, clip.my_vote === -1 ? 0 : -1)}
                title="Downvote"
              >▼</button>
            </div>
            {clip.creation_time && (
              <span className={styles.date}>{formatDate(clip.creation_time)}</span>
            )}
          </div>
        </div>
      )}

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
            min={0}
            max={SPEED_SLIDER_STEPS}
            step={1}
            value={speedToSlider(speed)}
            onChange={e => { const v = sliderToSpeed(Number(e.target.value)); setSpeed(v); saveSetting(clip.identifier, 'speed', v) }}
            className={styles.slider}
          />
        </div>
      </div>

      <div className={styles.actions}>
        {canEdit && !editing && (
          <button className={styles.edit} onClick={startEdit} title="Edit name & tags">✎</button>
        )}
        {isAdmin && (
          confirmDelete
            ? <>
                <button
                  className={`${styles.del} ${styles.delConfirm}`}
                  onClick={() => onDelete(clip.identifier)}
                  title="Confirm delete"
                >✓</button>
                <button
                  className={styles.del}
                  onClick={() => setConfirmDelete(false)}
                  title="Cancel delete"
                >✕</button>
              </>
            : <button
                className={styles.del}
                onClick={() => setConfirmDelete(true)}
                title="Delete clip"
              >🗑</button>
        )}
        <button
          className={styles.queue}
          onClick={() => onAddToQueue(clip.identifier, clip.name, pitch, speed)}
          title="Add to queue"
        >+</button>
        <button
          className={styles.download}
          onClick={handleDownload}
          disabled={downloading}
          title="Download this clip"
        >{downloading ? '…' : '⬇'}</button>
        <button
          className={styles.generate}
          onClick={() => setGenerating(true)}
          title="Generate a randomised pitch/speed queue from this clip"
        >🎲</button>
        <button
          className={`${styles.star} ${clip.is_favourite ? styles.starred : ''}`}
          onClick={() => onToggleFavourite(clip.identifier)}
          title={clip.is_favourite ? 'Remove favourite' : 'Add favourite'}
        >
          {clip.is_favourite ? '★' : '☆'}
        </button>
        <button
          className={styles.reset}
          onClick={() => {
            setPitch(0); saveSetting(clip.identifier, 'pitch', 0)
            setSpeed(1); saveSetting(clip.identifier, 'speed', 1)
          }}
          title="Reset pitch and speed"
        >↺</button>
        <button
          className={`${styles.play} ${playing ? styles.playing : ''}`}
          onClick={() => onPlay(clip.identifier, pitch, speed)}
          disabled={playing}
          title="Play"
        >
          {playing ? '…' : '▶'}
        </button>
      </div>

      {trimming && (
        <TrimModal
          clip={clip}
          onClose={() => setTrimming(false)}
          onTrimmed={(updated) => {
            // Bust the cached preview so it refetches the trimmed audio.
            if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
            if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null }
            setPreviewing(false)
            if (onTrimmed) onTrimmed(clip.identifier, updated)
          }}
        />
      )}

      {generating && (
        <GenerateQueueModal
          clip={clip}
          onClose={() => setGenerating(false)}
          onGenerate={(opts) => onGenerateQueue(clip.identifier, clip.name, opts)}
        />
      )}
    </div>
  )
}
