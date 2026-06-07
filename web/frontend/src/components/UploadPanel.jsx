import { useState, useEffect, useRef, useCallback } from 'react'
import api from '../api'
import WaveformTrimmer from './WaveformTrimmer'
import TagSuggestions from './TagSuggestions'
import styles from './UploadPanel.module.css'

const NAME_RE = /^[a-zA-Z0-9_\-]+$/
const MAX_SIZE_MB = 100
const MAX_DURATION_SECS = 10        // the stored (trimmed) clip
const MAX_SOURCE_SECS = 300         // the source you can upload to trim down (5 min)

export default function UploadPanel({ onClose, onUploaded, initialFile = null, allTags = [] }) {
  const [file, setFile] = useState(null)
  const [name, setName] = useState('')
  const [tags, setTags] = useState('')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)

  const [buffer, setBuffer] = useState(null)
  const [duration, setDuration] = useState(0)
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(0)

  const urlRef = useRef(null)
  const onChange = useCallback((s, e) => { setStart(s); setEnd(e) }, [])

  useEffect(() => {
    return () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current) }
  }, [])

  // Load a chosen/dropped File: validate ext, set up preview + decode waveform.
  const loadFile = useCallback(async (f) => {
    if (!f) return
    const ext = f.name.split('.').pop().toLowerCase()
    if (!['wav', 'mp3'].includes(ext)) {
      setError('Only .wav and .mp3 files are accepted')
      return
    }
    setFile(f)
    setError(null)
    setBuffer(null); setDuration(0); setStart(0); setEnd(0)
    setName(f.name.replace(/\.[^.]+$/, ''))
    if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    urlRef.current = URL.createObjectURL(f)
    setPreviewUrl(urlRef.current)

    // Decode for the waveform. If it fails (some codecs), we silently fall back
    // to a plain upload — the server still enforces the 10s limit.
    try {
      const bytes = await f.arrayBuffer()
      const AC = window.AudioContext || window.webkitAudioContext
      const actx = new AC()
      const buf = await actx.decodeAudioData(bytes)
      actx.close()
      if (buf.duration > MAX_SOURCE_SECS) {
        setError(`Audio too long — max ${MAX_SOURCE_SECS}s. Pick a shorter file.`)
        return
      }
      setBuffer(buf)
      setDuration(buf.duration)
      setStart(0)
      setEnd(Math.min(buf.duration, MAX_DURATION_SECS))
    } catch {
      // No waveform; upload as-is (server validates duration).
    }
  }, [])

  // A file dropped onto the window opens this panel pre-loaded with it.
  useEffect(() => {
    if (initialFile) loadFile(initialFile)
  }, [initialFile, loadFile])

  function handleFileChange(e) {
    loadFile(e.target.files[0])
  }

  const selLen = end - start
  const selectionTooLong = !!buffer && selLen > MAX_DURATION_SECS + 0.05
  const trimming = !!buffer && (start > 0.05 || end < duration - 0.05)

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)

    if (!file) { setError('Please choose a file'); return }

    const trimmed = name.trim()
    if (!trimmed) { setError('Name is required'); return }
    if (!NAME_RE.test(trimmed)) {
      setError('Name may only contain letters, numbers, underscores, and hyphens')
      return
    }

    const ext = file.name.split('.').pop().toLowerCase()
    if (!['wav', 'mp3'].includes(ext)) {
      setError('Only .wav and .mp3 files are accepted')
      return
    }

    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      setError(`File too large — max ${MAX_SIZE_MB} MB`)
      return
    }

    if (selectionTooLong) {
      setError(`Trim your selection to ${MAX_DURATION_SECS}s or less`)
      return
    }

    const formData = new FormData()
    formData.append('file', file)
    formData.append('name', trimmed)
    formData.append('tags', tags)
    if (buffer) {
      formData.append('start', start.toFixed(3))
      formData.append('end', end.toFixed(3))
    }

    setUploading(true)
    try {
      const res = await api.post('/api/clips/upload', formData)
      onUploaded(res.data)
      onClose()
    } catch (err) {
      setError(err.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  return (
    <form className={styles.panel} onSubmit={handleSubmit} noValidate>
      <div className={styles.row}>
        <div className={styles.field}>
          <label className={styles.label}>Name</label>
          <input
            className={styles.input}
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="clip_name"
            spellCheck={false}
            disabled={uploading}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Tags <span className={styles.hint}>(optional, comma-separated)</span></label>
          <input
            className={styles.input}
            type="text"
            value={tags}
            onChange={e => setTags(e.target.value)}
            placeholder="funny, moments"
            disabled={uploading}
          />
          <TagSuggestions value={tags} onChange={setTags} allTags={allTags} />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>
            File <span className={styles.hint}>(.wav or .mp3, up to {MAX_SOURCE_SECS}s / {MAX_SIZE_MB} MB — trim to {MAX_DURATION_SECS}s)</span>
          </label>
          <label className={`${styles.fileBtn} ${uploading ? styles.disabled : ''}`}>
            {file ? file.name : 'Choose file…'}
            <input type="file" accept=".wav,.mp3" onChange={handleFileChange} hidden disabled={uploading} />
          </label>
        </div>
      </div>

      {previewUrl && (
        <audio className={styles.preview} controls src={previewUrl}>
          Your browser does not support audio preview.
        </audio>
      )}

      {buffer && (
        <div className={styles.trimmer}>
          <p className={styles.trimHint}>
            Drag the handles to pick the {MAX_DURATION_SECS}s you want to keep. Only the selection is uploaded.
          </p>
          <WaveformTrimmer
            audioBuffer={buffer}
            duration={duration}
            start={start}
            end={end}
            onChange={onChange}
            maxSelection={MAX_DURATION_SECS}
          />
        </div>
      )}

      {error && <p className={styles.error}>{error}</p>}
      <div className={styles.actions}>
        <button type="button" className={styles.cancel} onClick={onClose} disabled={uploading}>
          Cancel
        </button>
        <button type="submit" className={styles.upload} disabled={uploading || !file || selectionTooLong}>
          {uploading ? 'Uploading…' : (trimming ? 'Trim & upload' : 'Upload')}
        </button>
      </div>
    </form>
  )
}
