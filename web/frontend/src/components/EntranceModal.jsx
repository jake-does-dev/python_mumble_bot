import { useEffect, useMemo, useState } from 'react'
import api from '../api'
import styles from './EntranceModal.module.css'

const MAX_CLIPS = 3

// Plays the chosen clip(s) when you join the bot's voice channel.
export default function EntranceModal({ clips = [], onClose }) {
  const [loading, setLoading] = useState(true)
  const [voiceLinked, setVoiceLinked] = useState(false)
  const [list, setList] = useState([]) // [{clip_ref, clip_name, speed, pitch}]
  const [search, setSearch] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.get('/api/entrance/me')
      .then(res => {
        setVoiceLinked(res.data.voice_linked)
        setList(res.data.clips || [])
      })
      .catch(() => setError('Could not load your entrance sound.'))
      .finally(() => setLoading(false))
  }, [])

  const results = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return []
    return clips
      .filter(c => c.name.toLowerCase().includes(q) || c.identifier.toLowerCase().includes(q))
      .slice(0, 8)
  }, [search, clips])

  function addClip(clip) {
    if (list.length >= MAX_CLIPS) return
    setSaved(false)
    setList([...list, { clip_ref: clip.identifier, clip_name: clip.name, speed: 1.0, pitch: 0 }])
    setSearch('')
  }

  function updateItem(i, patch) {
    setSaved(false)
    setList(list.map((it, idx) => (idx === i ? { ...it, ...patch } : it)))
  }

  function removeItem(i) {
    setSaved(false)
    setList(list.filter((_, idx) => idx !== i))
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const clipsBody = list.map(it => ({
        clip_ref: it.clip_ref,
        speed: Number(it.speed) || 1.0,
        pitch: Number(it.pitch) || 0,
      }))
      await api.put('/api/entrance/me', { clips: clipsBody })
      setSaved(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  async function clearAll() {
    setSaving(true)
    setError(null)
    try {
      await api.delete('/api/entrance/me')
      setList([])
      setSaved(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Clear failed.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.head}>
          <h2 className={styles.title}>🔔 Your entrance sound</h2>
          <button className={styles.close} onClick={onClose}>✕</button>
        </div>

        {loading ? (
          <p className={styles.muted}>Loading…</p>
        ) : !voiceLinked ? (
          <p className={styles.muted}>
            Your account isn't linked to a voice user yet — ask an admin to link you,
            then you can set an entrance sound that plays when you join the bot's channel.
          </p>
        ) : (
          <>
            <p className={styles.muted}>
              Plays when you join the bot's voice channel. Pick up to {MAX_CLIPS} clip{MAX_CLIPS > 1 ? 's' : ''} (played in order).
            </p>

            {list.length === 0 && <p className={styles.empty}>No entrance sound set.</p>}

            <ul className={styles.list}>
              {list.map((it, i) => (
                <li key={i} className={styles.item}>
                  <span className={styles.itemName}>{it.clip_name || it.clip_ref}</span>
                  <label className={styles.adj}>
                    speed
                    <input type="number" min="0.5" max="2" step="0.1" value={it.speed}
                      onChange={e => updateItem(i, { speed: e.target.value })} />
                  </label>
                  <label className={styles.adj}>
                    pitch
                    <input type="number" min="-12" max="12" step="1" value={it.pitch}
                      onChange={e => updateItem(i, { pitch: e.target.value })} />
                  </label>
                  <button className={styles.remove} onClick={() => removeItem(i)} title="Remove">✕</button>
                </li>
              ))}
            </ul>

            {list.length < MAX_CLIPS && (
              <div className={styles.picker}>
                <input
                  className={styles.search}
                  type="search"
                  placeholder="Search clips to add…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
                {results.length > 0 && (
                  <ul className={styles.results}>
                    {results.map(c => (
                      <li key={c.identifier}>
                        <button className={styles.result} onClick={() => addClip(c)}>
                          {c.name} <span className={styles.resultId}>{c.identifier}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {error && <p className={styles.error}>{error}</p>}
            {saved && !error && <p className={styles.ok}>✓ Saved</p>}

            <div className={styles.actions}>
              <button className={styles.clear} onClick={clearAll} disabled={saving || list.length === 0}>
                Clear
              </button>
              <button className={styles.save} onClick={save} disabled={saving}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
