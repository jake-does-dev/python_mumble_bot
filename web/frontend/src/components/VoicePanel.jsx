import { useState, useEffect, useCallback } from 'react'
import api from '../api'
import styles from './VoicePanel.module.css'

export default function VoicePanel() {
  const [channels, setChannels] = useState([])
  const [current, setCurrent] = useState(null)
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState(null)

  const refresh = useCallback(() => {
    api.get('/api/voice/channels')
      .then(res => {
        setChannels(res.data.channels || [])
        setCurrent(res.data.current_channel_id || null)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [refresh])

  function showToast(message) {
    setToast(message)
    setTimeout(() => setToast(null), 3500)
  }

  async function join() {
    if (!selected) return
    const channel = channels.find(c => c.id === selected)
    if (channel && (channel.users || 0) === 0) {
      showToast('Not joining a channel with no users in it!')
      return
    }
    setBusy(true)
    try {
      await api.post('/api/voice/join', { channel_id: selected })
      setTimeout(refresh, 1500)
    } catch (err) {
      if (err.response?.status === 403) showToast(err.response.data?.detail || 'Not allowed')
    } finally {
      setBusy(false)
    }
  }

  async function leave() {
    setBusy(true)
    try {
      await api.post('/api/voice/leave')
      setTimeout(refresh, 1500)
    } catch (err) {
      if (err.response?.status === 403) showToast(err.response.data?.detail || 'Not allowed')
    } finally {
      setBusy(false)
    }
  }

  const currentName = channels.find(c => c.id === current)?.name

  return (
    <>
      <div className={styles.panel}>
        <span className={styles.label}>🔊 Voice</span>
        <select
          className={styles.select}
          value={selected}
          onChange={e => setSelected(e.target.value)}
        >
          <option value="">Select channel…</option>
          {channels.map(c => (
            <option key={c.id} value={c.id}>{c.name} ({c.users ?? 0})</option>
          ))}
        </select>
        <button className={styles.btn} onClick={join} disabled={busy || !selected}>Join</button>
        <button className={styles.btn} onClick={leave} disabled={busy || !current}>Leave</button>
        <span className={current ? styles.statusOn : styles.status}>
          {current ? `In: ${currentName || current}` : 'Not connected'}
        </span>
      </div>
      {toast && <div className={styles.toast}>{toast}</div>}
    </>
  )
}
