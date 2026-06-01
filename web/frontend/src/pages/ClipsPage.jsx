import { useState, useEffect, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import api from '../api'
import ClipCard from '../components/ClipCard'
import UploadPanel from '../components/UploadPanel'
import QueuePanel from '../components/QueuePanel'
import VoicePanel from '../components/VoicePanel'
import styles from './ClipsPage.module.css'

const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2)

function loadQueues() {
  try { return JSON.parse(localStorage.getItem('pmb_queues') || '[]') } catch { return [] }
}

function timeAgo(isoString) {
  const seconds = Math.floor((Date.now() - new Date(isoString)) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function dayLabel(isoString) {
  const d = new Date(isoString)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

export default function ClipsPage() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  const [clips, setClips] = useState([])
  const [tags, setTags] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const [voiceControl, setVoiceControl] = useState(false)
  const [username, setUsername] = useState(null)
  const [queueCooldownUntil, setQueueCooldownUntil] = useState(0)
  const [now, setNow] = useState(Date.now())

  const [search, setSearch] = useState('')
  const [activeTag, setActiveTag] = useState(null)
  const [favouritesOnly, setFavouritesOnly] = useState(false)
  const [playingId, setPlayingId] = useState(null)
  const [view, setView] = useState(() => localStorage.getItem('pmb_view') || 'grid')
  const [sort, setSort] = useState(() => localStorage.getItem('pmb_sort') || 'alpha')
  const [uploadOpen, setUploadOpen] = useState(false)

  const [sidebarTab, setSidebarTab] = useState('history')
  const [queues, setQueues] = useState(loadQueues)
  const [activeQueueId, setActiveQueueId] = useState(() => localStorage.getItem('pmb_active_queue') || null)
  const [playingQueue, setPlayingQueue] = useState(false)

  function handleSetView(v) {
    setView(v)
    localStorage.setItem('pmb_view', v)
  }

  function handleSetSort(v) {
    setSort(v)
    localStorage.setItem('pmb_sort', v)
  }

  const [history, setHistory] = useState([])

  const fetchHistory = useCallback(() => {
    api.get('/api/commands/history').then(res => setHistory(res.data)).catch(() => {})
  }, [])

  useEffect(() => {
    Promise.all([api.get('/api/clips/'), api.get('/api/clips/tags'), api.get('/api/users/me')])
      .then(([clipsRes, tagsRes, meRes]) => {
        setClips(clipsRes.data)
        setTags(tagsRes.data)
        setIsAdmin(meRes.data.is_admin)
        setVoiceControl(meRes.data.voice_control)
        setUsername(meRes.data.username)
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
    const id = setInterval(fetchHistory, 3000)
    return () => clearInterval(id)
  }, [fetchHistory])

  useEffect(() => {
    if (queueCooldownUntil <= Date.now()) return
    const id = setInterval(() => {
      setNow(Date.now())
      if (Date.now() >= queueCooldownUntil) clearInterval(id)
    }, 1000)
    return () => clearInterval(id)
  }, [queueCooldownUntil])

  const cooldownRemaining = Math.max(0, Math.ceil((queueCooldownUntil - now) / 1000))

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return clips
      .filter(clip => {
        if (favouritesOnly && !clip.is_favourite) return false
        if (activeTag && !clip.tags.includes(activeTag)) return false
        if (q && !clip.name.toLowerCase().includes(q) && !clip.identifier.toLowerCase().includes(q)) return false
        return true
      })
      .sort((a, b) => {
        if (sort === 'top') return (b.score ?? 0) - (a.score ?? 0)
        if (sort === 'newest') return new Date(b.creation_time) - new Date(a.creation_time)
        if (sort === 'oldest') return new Date(a.creation_time) - new Date(b.creation_time)
        return a.name.localeCompare(b.name)
      })
  }, [clips, search, activeTag, favouritesOnly, sort])

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

  async function handlePlay(identifier, pitch, speed) {
    setPlayingId(identifier)
    try {
      await api.post(`/api/commands/play/${identifier}`, { pitch, speed })
      setTimeout(fetchHistory, 1500)
    } finally {
      setPlayingId(null)
    }
  }

  function handleUploaded(newClip) {
    setClips(prev => [...prev, { ...newClip, is_favourite: false }])
    api.get('/api/clips/tags').then(res => setTags(res.data)).catch(() => {})
  }

  function handleDelete(identifier) {
    setClips(prev => prev.filter(c => c.identifier !== identifier))
    api.delete(`/api/clips/${identifier}`).catch(() => {
      api.get('/api/clips/').then(res => setClips(res.data)).catch(() => {})
    })
  }

  async function handleEdit(identifier, { name, tags: newTags }) {
    const res = await api.patch(`/api/clips/${identifier}`, { name, tags: newTags })
    setClips(prev => prev.map(c =>
      c.identifier === identifier ? { ...c, ...res.data } : c
    ))
    api.get('/api/clips/tags').then(r => setTags(r.data)).catch(() => {})
  }

  function handleVote(identifier, value) {
    api.post(`/api/clips/${identifier}/vote`, { value })
      .then(res => {
        setClips(prev => prev.map(c =>
          c.identifier === identifier
            ? { ...c, score: res.data.score, my_vote: res.data.my_vote }
            : c
        ))
      })
      .catch(() => {})
  }

  function saveQueues(next) {
    setQueues(next)
    localStorage.setItem('pmb_queues', JSON.stringify(next))
  }

  function selectQueue(id) {
    setActiveQueueId(id)
    localStorage.setItem('pmb_active_queue', id)
  }

  function handleCreateQueue(name) {
    const q = { id: newId(), name, items: [] }
    const next = [...queues, q]
    saveQueues(next)
    selectQueue(q.id)
    setSidebarTab('queue')
  }

  function handleDeleteQueue(id) {
    const next = queues.filter(q => q.id !== id)
    saveQueues(next)
    const newActive = next.length > 0 ? next[next.length - 1].id : null
    selectQueue(newActive || '')
  }

  function handleRenameQueue(id, name) {
    saveQueues(queues.map(q => q.id === id ? { ...q, name } : q))
  }

  function handleAddToQueue(identifier, name, pitch, speed) {
    let targetId = activeQueueId
    let current = queues
    if (!current.find(q => q.id === targetId)) {
      const q = { id: newId(), name: 'Queue 1', items: [] }
      current = [...queues, q]
      saveQueues(current)
      selectQueue(q.id)
      targetId = q.id
    }
    const target = current.find(q => q.id === targetId)
    if (target && target.items.length >= 15) return
    saveQueues(current.map(q =>
      q.id === targetId
        ? { ...q, items: [...q.items, { id: newId(), identifier, name, pitch, speed }] }
        : q
    ))
    setSidebarTab('queue')
  }

  function handleRemoveFromQueue(queueId, itemId) {
    saveQueues(queues.map(q =>
      q.id === queueId ? { ...q, items: q.items.filter(i => i.id !== itemId) } : q
    ))
  }

  function handleMoveInQueue(queueId, itemId, direction) {
    saveQueues(queues.map(q => {
      if (q.id !== queueId) return q
      const items = [...q.items]
      const idx = items.findIndex(i => i.id === itemId)
      const to = idx + direction
      if (to < 0 || to >= items.length) return q;
      [items[idx], items[to]] = [items[to], items[idx]]
      return { ...q, items }
    }))
  }

  function handleClearQueue(queueId) {
    saveQueues(queues.map(q => q.id === queueId ? { ...q, items: [] } : q))
  }

  async function handlePlayQueue(queueId) {
    const q = queues.find(q => q.id === queueId)
    if (!q || q.items.length === 0) return
    if (cooldownRemaining > 0) return
    setPlayingQueue(true)
    try {
      await api.post('/api/commands/play-queue', {
        queue_name: q.name,
        items: q.items.map(item => ({
          clip_ref: item.identifier,
          clip_name: item.name,
          pitch: item.pitch,
          speed: item.speed,
        })),
      })
      setQueueCooldownUntil(Date.now() + 30000)
      setTimeout(fetchHistory, 1500)
    } catch (err) {
      if (err.response?.status === 429) {
        const m = /(\d+)/.exec(err.response.data?.detail || '')
        const secs = m ? Number(m[1]) : 30
        setQueueCooldownUntil(Date.now() + secs * 1000)
      }
    } finally {
      setPlayingQueue(false)
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
            <div className={styles.controlsTop}>
              <div className={styles.searchWrap}>
                <input
                  className={styles.search}
                  type="search"
                  placeholder="Search clips…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
                {search && (
                  <button className={styles.searchClear} onClick={() => setSearch('')} title="Clear search">✕</button>
                )}
              </div>
              <div className={styles.viewToggle}>
                <button className={`${styles.viewBtn} ${sort === 'alpha'   ? styles.active : ''}`} onClick={() => handleSetSort('alpha')}  title="Sort A→Z">A→Z</button>
                <button className={`${styles.viewBtn} ${sort === 'newest'  ? styles.active : ''}`} onClick={() => handleSetSort('newest')} title="Sort newest first">Date ↓</button>
                <button className={`${styles.viewBtn} ${sort === 'oldest'  ? styles.active : ''}`} onClick={() => handleSetSort('oldest')} title="Sort oldest first">Date ↑</button>
                <button className={`${styles.viewBtn} ${sort === 'top'     ? styles.active : ''}`} onClick={() => handleSetSort('top')}    title="Sort by votes">★ Top</button>
              </div>
              <div className={styles.viewToggle}>
                <button className={`${styles.viewBtn} ${view === 'grid' ? styles.active : ''}`} onClick={() => handleSetView('grid')} title="Grid view">⊞</button>
                <button className={`${styles.viewBtn} ${view === 'list' ? styles.active : ''}`} onClick={() => handleSetView('list')} title="List view">☰</button>
              </div>
              <button
                className={`${styles.viewBtn} ${uploadOpen ? styles.active : ''}`}
                onClick={() => setUploadOpen(o => !o)}
                title="Upload a clip"
              >
                ↑ Upload
              </button>
            </div>
            {uploadOpen && (
              <UploadPanel
                onClose={() => setUploadOpen(false)}
                onUploaded={handleUploaded}
              />
            )}
            {voiceControl && <VoicePanel />}
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

          <div className={styles.clipsScroll}>
            {loading && <p className={styles.status}>Loading…</p>}
            {error && <p className={styles.error}>{error}</p>}

            {!loading && !error && (
              <>
                <p className={styles.count}>{filtered.length} clip{filtered.length !== 1 ? 's' : ''}</p>
                <div className={view === 'grid' ? styles.grid : styles.list}>
                  {filtered.map(clip => (
                    <ClipCard
                      key={clip.identifier}
                      clip={clip}
                      onToggleFavourite={handleToggleFavourite}
                      onPlay={handlePlay}
                      onDelete={handleDelete}
                      onAddToQueue={handleAddToQueue}
                      onEdit={handleEdit}
                      onVote={handleVote}
                      username={username}
                      playing={playingId === clip.identifier}
                      isAdmin={isAdmin}
                      view={view}
                    />
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        <aside className={styles.sidebar}>
          <div className={styles.sidebarTabs}>
            <button
              className={`${styles.sidebarTab} ${sidebarTab === 'queue' ? styles.sidebarTabActive : ''}`}
              onClick={() => setSidebarTab('queue')}
            >
              Queue{queues.find(q => q.id === activeQueueId)?.items.length > 0
                ? ` (${queues.find(q => q.id === activeQueueId).items.length})`
                : ''}
            </button>
            <button
              className={`${styles.sidebarTab} ${sidebarTab === 'history' ? styles.sidebarTabActive : ''}`}
              onClick={() => setSidebarTab('history')}
            >
              History
            </button>
          </div>

          {sidebarTab === 'queue' ? (
            <QueuePanel
              queues={queues}
              activeQueueId={activeQueueId}
              onSelectQueue={selectQueue}
              onCreateQueue={handleCreateQueue}
              onDeleteQueue={handleDeleteQueue}
              onRenameQueue={handleRenameQueue}
              onRemoveItem={handleRemoveFromQueue}
              onMoveItem={handleMoveInQueue}
              onPlayQueue={handlePlayQueue}
              onClearQueue={handleClearQueue}
              playingQueue={playingQueue}
              cooldownRemaining={cooldownRemaining}
            />
          ) : (
            <>
              <h2 className={styles.sidebarTitle}>Recently Played</h2>
              {history.length === 0
                ? <p className={styles.sidebarEmpty}>Nothing played yet</p>
                : (
                  <ol className={styles.historyList}>
                    {history.reduce((acc, entry, i) => {
                      const label = dayLabel(entry.played_at)
                      const prevLabel = i > 0 ? dayLabel(history[i - 1].played_at) : null
                      if (label !== prevLabel) {
                        acc.push(
                          <li key={`day-${label}`} className={styles.daySeparator}>{label}</li>
                        )
                      }
                      acc.push(
                        <li key={i} className={styles.historyItem}>
                          <span className={styles.historyName} onClick={() => setSearch(entry.clip_name)} title="Search for this clip">{entry.clip_name}</span>
                          <span className={styles.historyMeta}>
                            {entry.requested_by} · {timeAgo(entry.played_at)}
                          </span>
                        </li>
                      )
                      return acc
                    }, [])}
                  </ol>
                )
              }
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
