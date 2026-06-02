import { useState, useEffect, useCallback } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import api from '../api'
import styles from './AdminUsersPage.module.css'

export default function AdminUsersPage() {
  const { logout } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()

  const [users, setUsers] = useState([])
  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)
  const [savingFor, setSavingFor] = useState(null)
  const [draft, setDraft] = useState({}) // username -> selected voice_id

  const load = useCallback(() => {
    Promise.all([api.get('/api/users/'), api.get('/api/voice/channels')])
      .then(([usersRes, voiceRes]) => {
        setUsers(usersRes.data)
        const seen = new Map()
        for (const c of voiceRes.data.channels || []) {
          for (const m of c.members || []) {
            if (!seen.has(m.id)) seen.set(m.id, m.name)
          }
        }
        setMembers([...seen].map(([id, name]) => ({ id, name })))
        setError(null)
      })
      .catch(err => {
        if (err.response?.status === 401) { logout(); navigate('/login') }
        else if (err.response?.status === 403) setError('Admin access required')
        else setError('Failed to load users')
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  function showToast(message) {
    setToast(message)
    setTimeout(() => setToast(null), 3500)
  }

  // Candidate members for a user's dropdown: those currently in voice, plus the
  // user's existing link (so it still shows even if they're not present now).
  function candidatesFor(user) {
    const list = [...members]
    if (user.voice_id && !list.find(m => m.id === user.voice_id)) {
      list.push({ id: user.voice_id, name: `${user.voice_name || user.voice_id} (offline)` })
    }
    return list
  }

  async function save(user) {
    const voice_id = draft[user.username] ?? user.voice_id ?? ''
    const member = members.find(m => m.id === voice_id)
    setSavingFor(user.username)
    try {
      await api.patch(`/api/users/${user.username}/voice`, {
        voice_id: voice_id || null,
        voice_name: member?.name ?? (voice_id ? user.voice_name : null),
      })
      showToast(`Linked ${user.username}`)
      load()
    } catch {
      showToast('Failed to save link')
    } finally {
      setSavingFor(null)
    }
  }

  async function unlink(user) {
    setSavingFor(user.username)
    try {
      await api.patch(`/api/users/${user.username}/voice`, { voice_id: null, voice_name: null })
      showToast(`Unlinked ${user.username}`)
      setDraft(d => ({ ...d, [user.username]: '' }))
      load()
    } catch {
      showToast('Failed to unlink')
    } finally {
      setSavingFor(null)
    }
  }

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.nav}>
          <Link to="/" className={styles.navLink}>← Clips</Link>
          <span className={styles.title}>Voice links</span>
        </div>
        <div className={styles.headerActions}>
          <button
            className={styles.themeToggle}
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          >
            {theme === 'dark' ? '☀' : '☾'}
          </button>
          <button className={styles.logout} onClick={handleLogout}>Sign out</button>
        </div>
      </header>

      <div className={styles.scroll}>
        <p className={styles.hint}>
          Link each web user to their voice identity. A user must be in the channel (and
          linked here) to play clips. Members currently in voice appear in the dropdown —
          ask people to join, then map them.
        </p>

        {loading && <p className={styles.status}>Loading…</p>}
        {error && <p className={styles.errorMsg}>{error}</p>}

        {!loading && !error && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>User</th>
                <th>Linked to</th>
                <th>Voice member</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.map(user => {
                const selected = draft[user.username] ?? user.voice_id ?? ''
                return (
                  <tr key={user.username}>
                    <td className={styles.userCell}>
                      {user.username}
                      {user.is_admin && <span className={styles.adminBadge}>admin</span>}
                    </td>
                    <td className={styles.linkCell}>
                      {user.voice_id
                        ? <span className={styles.linked}>{user.voice_name || user.voice_id}</span>
                        : <span className={styles.unlinked}>not linked</span>}
                    </td>
                    <td>
                      <select
                        className={styles.select}
                        value={selected}
                        onChange={e => setDraft(d => ({ ...d, [user.username]: e.target.value }))}
                      >
                        <option value="">Select member…</option>
                        {candidatesFor(user).map(m => (
                          <option key={m.id} value={m.id}>{m.name}</option>
                        ))}
                      </select>
                    </td>
                    <td className={styles.actionsCell}>
                      <button
                        className={styles.save}
                        disabled={savingFor === user.username || !selected || selected === user.voice_id}
                        onClick={() => save(user)}
                      >
                        Save
                      </button>
                      <button
                        className={styles.unlink}
                        disabled={savingFor === user.username || !user.voice_id}
                        onClick={() => unlink(user)}
                      >
                        Unlink
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
      {toast && <div className={styles.toast}>{toast}</div>}
    </div>
  )
}
