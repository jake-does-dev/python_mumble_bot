import { useState, useEffect, useCallback } from 'react'
import api from '../api'
import WaveformTrimmer from './WaveformTrimmer'
import styles from './TrimModal.module.css'

export default function TrimModal({ clip, onClose, onTrimmed }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [duration, setDuration] = useState(0)
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(0)
  const [busy, setBusy] = useState(false)
  const [buffer, setBuffer] = useState(null)

  const canRevert = !!clip.original_file
  const onChange = useCallback((s, e) => { setStart(s); setEnd(e) }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.get(`/api/clips/${clip.identifier}/audio`, {
      responseType: 'arraybuffer',
      params: { t: Date.now() }, // bust any cached (pre-trim) audio
    })
      .then(async (res) => {
        const AC = window.AudioContext || window.webkitAudioContext
        const actx = new AC()
        const buf = await actx.decodeAudioData(res.data.slice(0))
        actx.close()
        if (cancelled) return
        setBuffer(buf)
        setDuration(buf.duration)
        setStart(0)
        setEnd(buf.duration)
        setLoading(false)
      })
      .catch(() => {
        if (!cancelled) {
          setError('Could not load audio')
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [clip.identifier])

  async function doTrim() {
    setBusy(true)
    try {
      const res = await api.post(`/api/clips/${clip.identifier}/trim`, { start, end })
      onTrimmed(res.data)
      onClose()
    } catch (err) {
      setError(err.response?.data?.detail || 'Trim failed')
      setBusy(false)
    }
  }

  async function doRevert() {
    setBusy(true)
    try {
      const res = await api.post(`/api/clips/${clip.identifier}/revert`)
      onTrimmed(res.data)
      onClose()
    } catch (err) {
      setError(err.response?.data?.detail || 'Revert failed')
      setBusy(false)
    }
  }

  const trimsWholeClip = start <= 0.001 && end >= duration - 0.001

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.head}>
          <div>
            <span className={styles.kind}>Trim audio</span>
            <h3 className={styles.title}>{clip.name}</h3>
          </div>
          <button className={styles.close} onClick={onClose}>✕</button>
        </div>

        {loading && <p className={styles.status}>Loading waveform…</p>}
        {error && <p className={styles.error}>{error}</p>}

        {!loading && !error && (
          <>
            <WaveformTrimmer
              audioBuffer={buffer}
              duration={duration}
              start={start}
              end={end}
              onChange={onChange}
            />

            <div className={styles.actions}>
              {canRevert && (
                <button className={styles.revert} onClick={doRevert} disabled={busy} title="Restore the original (pre-trim) audio">
                  ↺ Revert to original
                </button>
              )}
              <button
                className={styles.trim}
                onClick={doTrim}
                disabled={busy || trimsWholeClip}
                title={trimsWholeClip ? 'Adjust the handles to select a region' : 'Trim to selection'}
              >
                ✂ Trim
              </button>
            </div>
            <p className={styles.note}>Trimming replaces the audio (re-normalised) and keeps votes &amp; history. The original is backed up so you can revert.</p>
          </>
        )}
      </div>
    </div>
  )
}
