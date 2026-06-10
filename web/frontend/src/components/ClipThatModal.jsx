import { useEffect, useState, useCallback } from 'react'
import api from '../api'
import WaveformTrimmer from './WaveformTrimmer'
import TagSuggestions from './TagSuggestions'
import styles from './ClipThatModal.module.css'

const CAPTURE_SECONDS = 30 // how far back the bot grabs
const MAX_CLIP_SECONDS = 10 // a saved clip can't be longer than this

// "Clip that": instant-replay. Grab the last N seconds of someone in the bot's
// channel (the bot keeps a rolling per-person buffer), then trim + name + save it
// as a normal clip.
export default function ClipThatModal({ onClose, onSaved, allTags = [] }) {
  const [present, setPresent] = useState([])
  const [pending, setPending] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null) // voice id currently being captured
  const [toast, setToast] = useState(null)
  const [optin, setOptin] = useState(false)
  const [voiceLinked, setVoiceLinked] = useState(false)

  const refreshPresent = useCallback(
    () =>
      api
        .get('/api/voice/channels')
        .then(r => setPresent(r.data.present || []))
        .catch(() => {}),
    []
  )
  const refreshPending = useCallback(
    () =>
      api
        .get('/api/captures/pending')
        .then(r => setPending(r.data || []))
        .catch(() => {}),
    []
  )

  useEffect(() => {
    api
      .get('/api/users/me')
      .then(r => {
        setOptin(!!r.data.capture_optin)
        setVoiceLinked(!!r.data.voice_linked)
      })
      .catch(() => {})
    Promise.all([refreshPresent(), refreshPending()]).finally(() =>
      setLoading(false)
    )
    const id = setInterval(() => {
      refreshPresent()
      refreshPending()
    }, 4000)
    return () => clearInterval(id)
  }, [refreshPresent, refreshPending])

  function showToast(msg) {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

  async function toggleOptin() {
    const next = !optin
    setOptin(next)
    try {
      await api.put('/api/users/me/capture-optin', { opt_in: next })
    } catch {
      setOptin(!next)
      showToast('Could not update your setting.')
    }
  }

  async function clipThat(voiceId) {
    setBusy(voiceId)
    try {
      await api.post('/api/captures/', {
        target_voice: voiceId,
        duration: CAPTURE_SECONDS,
      })
      showToast('Clipped — it’ll appear below in a moment.')
      setTimeout(refreshPending, 1200)
    } catch (err) {
      showToast(err.response?.data?.detail || 'Could not clip that.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.head}>
          <h2 className={styles.title}>✂️ Clip that</h2>
          <button className={styles.close} onClick={onClose}>
            ✕
          </button>
        </div>

        {loading ? (
          <p className={styles.muted}>Loading…</p>
        ) : (
          <>
            <p className={styles.muted}>
              Grab the last {CAPTURE_SECONDS}s of someone in the bot’s channel,
              then trim, name and save it to the soundboard. Only people who’ve
              opted in can be clipped.
            </p>

            <div className={styles.consent}>
              <label className={styles.consentLabel}>
                <input
                  type="checkbox"
                  checked={optin}
                  disabled={!voiceLinked}
                  onChange={toggleOptin}
                />
                Allow others to clip my voice
              </label>
              {!voiceLinked ? (
                <span className={styles.consentNote}>
                  Link your account to a voice user first (ask an admin).
                </span>
              ) : !optin ? (
                <span className={styles.consentNote}>
                  Until you opt in, the bot doesn’t record you at all.
                </span>
              ) : null}
            </div>

            <h3 className={styles.section}>In the channel</h3>
            {present.filter(p => p.opted_in).length >= 2 && (
              <button
                className={styles.clipAllBtn}
                disabled={busy === '__all__'}
                onClick={() => clipThat('__all__')}
                title="Mix everyone opted-in into one clip — great for an exchange between people"
              >
                {busy === '__all__'
                  ? '…'
                  : `✂️ Clip everyone (last ${CAPTURE_SECONDS}s)`}
              </button>
            )}
            {present.length === 0 ? (
              <p className={styles.empty}>Nobody’s in the bot’s channel right now.</p>
            ) : (
              <ul className={styles.people}>
                {present.map(p => (
                  <li key={p.id} className={styles.person}>
                    <span className={styles.personName}>{p.name || p.id}</span>
                    {p.opted_in ? (
                      <button
                        className={styles.clipBtn}
                        disabled={busy === p.id}
                        onClick={() => clipThat(p.id)}
                      >
                        {busy === p.id ? '…' : `✂️ Clip last ${CAPTURE_SECONDS}s`}
                      </button>
                    ) : (
                      <span className={styles.optedOut}>hasn’t opted in</span>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <h3 className={styles.section}>To review</h3>
            {pending.length === 0 ? (
              <p className={styles.empty}>No captures waiting.</p>
            ) : (
              <ul className={styles.list}>
                {pending.map(cap => (
                  <CaptureReview
                    key={cap.id}
                    cap={cap}
                    onDone={refreshPending}
                    onToast={showToast}
                    onSaved={onSaved}
                    allTags={allTags}
                  />
                ))}
              </ul>
            )}
          </>
        )}

        {toast && <div className={styles.toast}>{toast}</div>}
      </div>
    </div>
  )
}

function CaptureReview({ cap, onDone, onToast, onSaved, allTags = [] }) {
  const [buffer, setBuffer] = useState(null)
  const [duration, setDuration] = useState(0)
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(0)
  const [name, setName] = useState('')
  const [tags, setTags] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const onChange = useCallback((s, e) => {
    setStart(s)
    setEnd(e)
  }, [])

  useEffect(() => {
    let cancelled = false
    api
      .get(`/api/captures/${cap.id}/audio`, { responseType: 'arraybuffer' })
      .then(async res => {
        const AC = window.AudioContext || window.webkitAudioContext
        const actx = new AC()
        const buf = await actx.decodeAudioData(res.data.slice(0))
        actx.close()
        if (cancelled) return
        setBuffer(buf)
        setDuration(buf.duration)
        setStart(0)
        setEnd(Math.min(buf.duration, MAX_CLIP_SECONDS))
        setLoading(false)
      })
      .catch(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [cap.id])

  const selLen = end - start
  const tooLong = selLen > MAX_CLIP_SECONDS + 0.05
  const validName = /^[a-zA-Z0-9_-]+$/.test(name.trim())

  async function save() {
    if (!validName) {
      onToast('Name: letters, numbers, _ and - only.')
      return
    }
    if (tooLong || selLen < 0.1) {
      onToast(`Trim the selection to ${MAX_CLIP_SECONDS}s or less.`)
      return
    }
    setSaving(true)
    try {
      const res = await api.post(`/api/captures/${cap.id}/save`, {
        name: name.trim(),
        tags: tags
          .split(',')
          .map(t => t.trim())
          .filter(Boolean),
        start,
        end,
      })
      onSaved?.(res.data) // show it in the clip list right away (no refresh)
      onToast(`Saved “${name.trim()}” to the soundboard.`)
      onDone()
    } catch (err) {
      onToast(err.response?.data?.detail || 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  async function discard() {
    setSaving(true)
    try {
      await api.delete(`/api/captures/${cap.id}`)
      onDone()
    } catch (err) {
      onToast(err.response?.data?.detail || 'Discard failed.')
      setSaving(false)
    }
  }

  return (
    <li className={styles.item}>
      <div className={styles.itemTop}>
        <span className={styles.itemName}>
          {cap.target_voice === '__all__' ? 'Everyone' : cap.target_voice}
        </span>
        <span className={styles.itemMeta}>
          {cap.duration_s ? `${cap.duration_s}s` : ''}
          {cap.requested_by ? ` · by ${cap.requested_by}` : ''}
        </span>
      </div>

      {loading ? (
        <p className={styles.muted}>Loading waveform…</p>
      ) : (
        <WaveformTrimmer
          audioBuffer={buffer}
          duration={duration}
          start={start}
          end={end}
          onChange={onChange}
          maxSelection={MAX_CLIP_SECONDS}
        />
      )}

      <div className={styles.itemForm}>
        <input
          className={styles.nameInput}
          placeholder="clip name (letters, numbers, _ -)"
          value={name}
          onChange={e => setName(e.target.value)}
        />
        <input
          className={styles.tagsInput}
          placeholder="tags (comma separated)"
          value={tags}
          onChange={e => setTags(e.target.value)}
        />
      </div>
      <TagSuggestions value={tags} onChange={setTags} allTags={allTags} />


      <div className={styles.itemActions}>
        <button className={styles.discard} onClick={discard} disabled={saving}>
          Discard
        </button>
        <button
          className={styles.save}
          onClick={save}
          disabled={saving || loading}
        >
          {saving ? '…' : 'Save clip'}
        </button>
      </div>
    </li>
  )
}
