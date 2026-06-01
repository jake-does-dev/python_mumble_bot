import { useState, useEffect } from 'react'
import api from '../api'
import styles from './UploadPanel.module.css'

const NAME_RE = /^[a-zA-Z0-9_\-]+$/
const MAX_SIZE_MB = 50
const MAX_DURATION_SECS = 10

export default function UploadPanel({ onClose, onUploaded }) {
  const [file, setFile] = useState(null)
  const [name, setName] = useState('')
  const [tags, setTags] = useState('')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)

  useEffect(() => {
    return () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }
  }, [previewUrl])

  function handleFileChange(e) {
    const f = e.target.files[0]
    if (!f) return
    setFile(f)
    setError(null)
    const stem = f.name.replace(/\.[^.]+$/, '')
    setName(stem)
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setPreviewUrl(URL.createObjectURL(f))
  }

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

    const formData = new FormData()
    formData.append('file', file)
    formData.append('name', trimmed)
    formData.append('tags', tags)

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
        </div>
        <div className={styles.field}>
          <label className={styles.label}>
            File <span className={styles.hint}>(.wav or .mp3, max {MAX_SIZE_MB} MB / {MAX_DURATION_SECS}s)</span>
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
      {error && <p className={styles.error}>{error}</p>}
      <div className={styles.actions}>
        <button type="button" className={styles.cancel} onClick={onClose} disabled={uploading}>
          Cancel
        </button>
        <button type="submit" className={styles.upload} disabled={uploading || !file}>
          {uploading ? 'Uploading…' : 'Upload'}
        </button>
      </div>
    </form>
  )
}
