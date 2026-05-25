import { useState, useEffect, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import api from '../api'
import ClipCard from '../components/ClipCard'
import styles from './ClipsPage.module.css'

function timeAgo(isoString) {
  const seconds = Math.floor((Date.now() - new Date(isoString)) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export default function ClipsPage() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  const [clips, setClips] = useState([])
  const [tags, setTags] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [search, setSearch] = useState('')
  const [activeTag, setActiveTag] = useState(null)
  const [favouritesOnly, setFavouritesOnly] = useState(false)
  const [playingId, setPlayingId] = useState(null)

  const [history, setHistory] = useState([])

  const fetchHistory = useCallback(() => {
    api.get('/api/commands/history').then(res => setHistory(res.data)).catch(() => {})
  }, [])

  useEffect(() => {
    Promise.all([api.get('/api/clips/'), api.get('/api/clips/tags')])
      .then(([clipsRes, tagsRes]) => {
        setClips(clipsRes.data)
        setTags(tagsRes.data)
      })
      .catch(err => {
        if (err.response?.status === 401) {
          logout()
          navigate('/login')
        } else {
          setError('Failed to load clips')
        }
      })
      .finally(() => setLoading(false))

    fetchHistory()
  }, [])

  useEffect(() => {
    const id = setInterval(fetchHistory, 10000)
    return () => clearInterval(id)
  }, [fetchHistory])

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return clips
      .filter(clip => {
        if (favouritesOnly && !clip.is_favourite) return false
        if (activeTag && !clip.tags.includes(activeTag)) return false
        if (q && !clip.name.toLowerCase().includes(q)) return false
        return true
      })
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [clips, search, activeTag, favouritesOnly])

  function handleToggleFavourite(identifier) {
    setClips(prev =>
      prev.map(c => c.identifier === identifier ? { ...c, is_favourite: !c.is_favourite } : c)
    )
    api.post(`/api/clips/${identifier}/favourite`).catch(() => {
      setClips(prev =>
        prev.map(c => c.identifier === identifier ? { ...c, is_favourite: !c.is_favourite } : c)
      )
    })
  }

  async function handlePlay(identifier) {
    setPlayingId(identifier)
    try {
      await api.post(`/api/commands/play/${identifier}`)
      setTimeout(fetchHistory, 1500)
    } finally {
      setPlayingId(null)
    }
  }

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.title}>Python Mumble Bot</span>
        <button className={styles.logout} onClick={handleLogout}>Sign out</button>
      </header>

      <div className={styles.layout}>
        <div className={styles.main}>
          <div className={styles.controls}>
            <input
              className={styles.search}
              type="search"
              placeholder="Search clips…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            <div className={styles.filters}>
              <button
                className={`${styles.filterBtn} ${!activeTag && !favouritesOnly ? styles.active : ''}`}
                onClick={() => { setActiveTag(null); setFavouritesOnly(false) }}
              >
                All
              </button>
              <button
                className={`${styles.filterBtn} ${favouritesOnly ? styles.active : ''}`}
                onClick={() => { setFavouritesOnly(f => !f); setActiveTag(null) }}
              >
                ★ Favourites
              </button>
              {tags.map(tag => (
                <button
                  key={tag}
                  className={`${styles.filterBtn} ${activeTag === tag ? styles.active : ''}`}
                  onClick={() => { setActiveTag(t => t === tag ? null : tag); setFavouritesOnly(false) }}
                >
                  {tag}
                </button>
              ))}
            </div>
          </div>

          {loading && <p className={styles.status}>Loading…</p>}
          {error && <p className={styles.error}>{error}</p>}

          {!loading && !error && (
            <>
              <p className={styles.count}>{filtered.length} clip{filtered.length !== 1 ? 's' : ''}</p>
              <div className={styles.grid}>
                {filtered.map(clip => (
                  <ClipCard
                    key={clip.identifier}
                    clip={clip}
                    onToggleFavourite={handleToggleFavourite}
                    onPlay={handlePlay}
                    playing={playingId === clip.identifier}
                  />
                ))}
              </div>
            </>
          )}
        </div>

        <aside className={styles.sidebar}>
          <h2 className={styles.sidebarTitle}>Recently Played</h2>
          {history.length === 0
            ? <p className={styles.sidebarEmpty}>Nothing played yet</p>
            : (
              <ol className={styles.historyList}>
                {history.map((entry, i) => (
                  <li key={i} className={styles.historyItem}>
                    <span className={styles.historyName}>{entry.clip_name}</span>
                    <span className={styles.historyMeta}>
                      {entry.requested_by} · {timeAgo(entry.played_at)}
                    </span>
                  </li>
                ))}
              </ol>
            )
          }
        </aside>
      </div>
    </div>
  )
}
