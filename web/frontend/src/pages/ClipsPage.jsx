import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import api from '../api'
import ClipCard from '../components/ClipCard'
import UploadPanel from '../components/UploadPanel'
import QueuePanel from '../components/QueuePanel'
import VoicePanel from '../components/VoicePanel'
import PadBoard from '../components/PadBoard'
import HelpModal from '../components/HelpModal'
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
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()

  const [clips, setClips] = useState([])
  const [tags, setTags] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const [voiceControl, setVoiceControl] = useState(false)
  const [username, setUsername] = useState(null)
  const [presenceRequired, setPresenceRequired] = useState(false)
  const [voiceLinked, setVoiceLinked] = useState(false)
  const [actionToast, setActionToast] = useState(null)
  const [queueCooldownUntil, setQueueCooldownUntil] = useState(0)
  const [now, setNow] = useState(Date.now())

  const [search, setSearch] = useState('')
  const [activeTag, setActiveTag] = useState(null)
  const [favouritesOnly, setFavouritesOnly] = useState(false)
  const [playingId, setPlayingId] = useState(null)
  // Set when a history entry is clicked, to push that play's pitch/speed onto
  // the matching clip card. `nonce` lets the same values re-apply on re-click.
  const [historyPreset, setHistoryPreset] = useState(null)
  const [view, setView] = useState(() => localStorage.getItem('pmb_view') || 'grid')
  const [sort, setSort] = useState(() => localStorage.getItem('pmb_sort') || 'alpha')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [dragActive, setDragActive] = useState(false)  // file dragged over window
  const [droppedFile, setDroppedFile] = useState(null)
  const [helpOpen, setHelpOpen] = useState(false)
  const [tagsExpanded, setTagsExpanded] = useState(() => localStorage.getItem('pmb_tags_expanded') !== 'false')

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

  function handleToggleTags() {
    setTagsExpanded(v => {
      const next = !v
      localStorage.setItem('pmb_tags_expanded', String(next))
      if (!next) setActiveTag(null)
      return next
    })
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
        setPresenceRequired(meRes.data.presence_required)
        setVoiceLinked(meRes.data.voice_linked)
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

  // Collapse consecutive plays of the same clip by the same person into a single
  // entry with a count (e.g. "balls-q ×11") so spamming doesn't flood the list.
  const groupedHistory = useMemo(() => {
    const groups = []
    for (const entry of history) {
      const last = groups[groups.length - 1]
      if (last && last.clip_name === entry.clip_name && last.requested_by === entry.requested_by) {
        last.count += 1
      } else {
        groups.push({ ...entry, count: 1 })
      }
    }
    return groups
  }, [history])

  // Pad board = your favourites (stable alpha order so hotkeys don't shift).
  const pads = useMemo(
    () => clips.filter(c => c.is_favourite).sort((a, b) => a.name.localeCompare(b.name)),
    [clips]
  )

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return clips
      .filter(clip => {
        if (favouritesOnly && !clip.is_favourite) return false
        if (activeTag && !clip.tags.includes(activeTag)) return false
        if (q && !clip.name.toLowerCase().includes(q) && !clip.identifier.toLowerCase().includes(q) && !clip.tags.some(t => t.toLowerCase().includes(q))) return false
        return true
      })
      .sort((a, b) => {
        if (sort === 'top') return (b.score ?? 0) - (a.score ?? 0)
        if (sort === 'rot') return (a.score ?? 0) - (b.score ?? 0)
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

  function showActionToast(message) {
    setActionToast(message)
    setTimeout(() => setActionToast(null), 3500)
  }

  // Broadcast: every client polls for the latest stop/restart and toasts when a
  // new one appears, so all users see it — not just whoever clicked.
  const lastStopRef = useRef(undefined)
  const lastRestartRef = useRef(undefined)
  const checkBroadcastsRef = useRef(() => {})
  checkBroadcastsRef.current = async () => {
    try {
      const [stopRes, restartRes] = await Promise.all([
        api.get('/api/commands/last-stop'),
        api.get('/api/commands/last-restart'),
      ])
      const stopAt = stopRes.data.at
      if (stopAt) {
        if (lastStopRef.current === undefined) lastStopRef.current = stopAt
        else if (stopAt > lastStopRef.current) {
          lastStopRef.current = stopAt
          const by = stopRes.data.by
          showActionToast(by === username ? '⏹ You stopped playback' : `⏹ ${by} stopped playback`)
        }
      }
      const restartAt = restartRes.data.at
      if (restartAt) {
        if (lastRestartRef.current === undefined) lastRestartRef.current = restartAt
        else if (restartAt > lastRestartRef.current) {
          lastRestartRef.current = restartAt
          const by = restartRes.data.by
          showActionToast(by === username ? '♻ You restarted the bot — back in a few seconds' : `♻ ${by} restarted the bot — back in a few seconds`)
        }
      }
    } catch { /* ignore */ }
  }

  useEffect(() => {
    checkBroadcastsRef.current()
    const id = setInterval(() => checkBroadcastsRef.current(), 3000)
    return () => clearInterval(id)
  }, [])

  // Drag a file anywhere over the window → overlay; drop → open upload pre-loaded.
  // Only reacts to file drags (types includes "Files"), so dragging queue items
  // around doesn't trigger it.
  useEffect(() => {
    let depth = 0
    const hasFiles = (e) => {
      const t = e.dataTransfer && e.dataTransfer.types
      return !!t && Array.from(t).includes('Files')
    }
    const onEnter = (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth += 1; setDragActive(true) }
    const onOver = (e) => { if (hasFiles(e)) e.preventDefault() } // allow drop
    const onLeave = (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (depth === 0) setDragActive(false) }
    const onDrop = (e) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth = 0
      setDragActive(false)
      const f = e.dataTransfer.files && e.dataTransfer.files[0]
      if (!f) return
      setDroppedFile(f)
      setUploadOpen(true)
    }
    window.addEventListener('dragenter', onEnter)
    window.addEventListener('dragover', onOver)
    window.addEventListener('dragleave', onLeave)
    window.addEventListener('drop', onDrop)
    return () => {
      window.removeEventListener('dragenter', onEnter)
      window.removeEventListener('dragover', onOver)
      window.removeEventListener('dragleave', onLeave)
      window.removeEventListener('drop', onDrop)
    }
  }, [])

  async function handleStop() {
    try {
      await api.post('/api/commands/stop')
      await checkBroadcastsRef.current()
    } catch (err) {
      showActionToast(err.response?.data?.detail || 'Could not stop playback')
    }
  }

  const [confirmRestart, setConfirmRestart] = useState(false)
  async function handleRestart() {
    setConfirmRestart(false)
    try {
      await api.post('/api/commands/restart')
      await checkBroadcastsRef.current()
    } catch (err) {
      showActionToast(err.response?.data?.detail || 'Could not restart the bot')
    }
  }

  async function handlePlay(identifier, pitch, speed) {
    setPlayingId(identifier)
    try {
      await api.post(`/api/commands/play/${identifier}`, { pitch, speed })
      setTimeout(fetchHistory, 1500)
    } catch (err) {
      if (err.response?.status === 403 || err.response?.status === 429) {
        showActionToast(err.response.data?.detail || 'Not allowed to play right now')
      }
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

  function handleTrimmed(identifier, updatedClip) {
    setClips(prev => prev.map(c =>
      c.identifier === identifier ? { ...c, ...updatedClip } : c
    ))
  }

  async function handleGain(identifier, gainDb) {
    const res = await api.patch(`/api/clips/${identifier}/gain`, { gain_db: gainDb })
    setClips(prev => prev.map(c =>
      c.identifier === identifier ? { ...c, ...res.data } : c
    ))
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
    if (target && target.items.length >= 30) return
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

  function handleGenerateQueue(identifier, name, { minPitch, maxPitch, minSpeed, maxSpeed, count }) {
    const randInt = (a, b) => Math.floor(Math.random() * (b - a + 1)) + a
    const randSpeed = (a, b) => Math.round((a + Math.random() * (b - a)) * 100) / 100
    const items = Array.from({ length: count }, () => ({
      id: newId(),
      identifier,
      name,
      pitch: randInt(minPitch, maxPitch),
      speed: randSpeed(minSpeed, maxSpeed),
    }))
    const q = { id: newId(), name: `${name} ×${count}`, items }
    saveQueues([...queues, q])
    selectQueue(q.id)
    setSidebarTab('queue')
  }

  function handleReorderInQueue(queueId, fromIndex, toIndex) {
    saveQueues(queues.map(q => {
      if (q.id !== queueId) return q
      const items = [...q.items]
      if (
        fromIndex === toIndex ||
        fromIndex < 0 || toIndex < 0 ||
        fromIndex >= items.length || toIndex >= items.length
      ) return q
      const [moved] = items.splice(fromIndex, 1)
      items.splice(toIndex, 0, moved)
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
      setQueueCooldownUntil(Date.now() + 10000)
      setTimeout(fetchHistory, 1500)
    } catch (err) {
      if (err.response?.status === 429) {
        const m = /(\d+)/.exec(err.response.data?.detail || '')
        const secs = m ? Number(m[1]) : 10
        setQueueCooldownUntil(Date.now() + secs * 1000)
      } else if (err.response?.status === 403) {
        showActionToast(err.response.data?.detail || 'Not allowed to play right now')
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
      {dragActive && (
        <div className={styles.dropOverlay}>
          <div className={styles.dropInner}>
            <div className={styles.dropIcon}>⬆</div>
            <div className={styles.dropTitle}>Drop a clip to upload</div>
            <div className={styles.dropHint}>.wav or .mp3</div>
          </div>
        </div>
      )}
      <header className={styles.header}>
        <span className={styles.title}>Python Mumble Bot</span>
        <div className={styles.headerActions}>
          <button
            className={styles.themeToggle}
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          >
            {theme === 'dark' ? '☀' : '☾'}
          </button>
          <button className={styles.statsLink} onClick={() => setHelpOpen(true)} title="How to use the bot">❓ Help</button>
          <Link to="/stats" className={styles.statsLink}>📊 Stats</Link>
          {isAdmin && <Link to="/admin/users" className={styles.statsLink}>⚙ Users</Link>}

          <span className={styles.headerDivider} />

          <button
            className={`${styles.statsLink} ${uploadOpen ? styles.active : ''}`}
            onClick={() => setUploadOpen(o => !o)}
            title="Upload a clip"
          >
            ↑ Upload
          </button>
          {isAdmin && (
            <button
              className={styles.stopBtn}
              onClick={handleStop}
              title="Stop all playback now (admin)"
            >
              ⏹ Stop
            </button>
          )}
          {confirmRestart ? (
            <span className={styles.restartConfirm}>
              <button className={styles.restartBtn} onClick={handleRestart} title="Confirm restart">♻ Confirm?</button>
              <button className={styles.restartCancel} onClick={() => setConfirmRestart(false)} title="Cancel">✕</button>
            </span>
          ) : (
            <button
              className={styles.restartBtn}
              onClick={() => setConfirmRestart(true)}
              title="Restart the bot if it's laggy or stuck — it'll rejoin your channel"
            >
              ♻ Restart
            </button>
          )}

          <span className={styles.headerDivider} />

          <button className={styles.logout} onClick={handleLogout}>Sign out</button>
        </div>
      </header>

      {presenceRequired && !voiceLinked && !isAdmin && (
        <div className={styles.linkBanner}>
          ⚠ Your account isn't linked to a voice user yet — ask an admin to link you before you can play clips.
        </div>
      )}

      <div className={styles.layout}>
        <div className={styles.main}>
          <div className={styles.controls}>
            {uploadOpen && (
              <UploadPanel
                onClose={() => { setUploadOpen(false); setDroppedFile(null) }}
                onUploaded={handleUploaded}
                initialFile={droppedFile}
              />
            )}
            {voiceControl && <VoicePanel />}
            <div className={styles.controlsTop}>
              <div className={styles.searchWrap}>
                <input
                  className={styles.search}
                  type="search"
                  placeholder="Search clips…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  onFocus={() => { setActiveTag(null); setFavouritesOnly(false) }}
                />
                {search && (
                  <button className={styles.searchClear} onClick={() => setSearch('')} title="Clear search">✕</button>
                )}
              </div>
              <select
                className={styles.sortSelect}
                value={sort}
                onChange={e => handleSetSort(e.target.value)}
                title="Sort order"
                aria-label="Sort order"
              >
                <option value="alpha">A→Z</option>
                <option value="newest">Date ↓</option>
                <option value="oldest">Date ↑</option>
                <option value="top">★ Top</option>
                <option value="rot">🥀 Rot</option>
              </select>
              <div className={styles.viewToggle}>
                <button className={`${styles.viewBtn} ${view === 'grid' ? styles.active : ''}`} onClick={() => handleSetView('grid')} title="Grid view">⊞ Grid</button>
                <button className={`${styles.viewBtn} ${view === 'list' ? styles.active : ''}`} onClick={() => handleSetView('list')} title="List view">☰ List</button>
                <button className={`${styles.viewBtn} ${view === 'pads' ? styles.active : ''}`} onClick={() => handleSetView('pads')} title="Pad board (favourites + hotkeys)">▦ Pads</button>
              </div>
            </div>
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
              {tags.length > 0 && (
                <button
                  className={styles.filterBtn}
                  onClick={handleToggleTags}
                  title={tagsExpanded ? 'Hide tags' : 'Show tags'}
                >
                  {tagsExpanded ? '▾ Tags' : `▸ Tags (${tags.length})`}
                </button>
              )}
              {tagsExpanded && tags.map(tag => (
                <button
                  key={tag}
                  className={`${styles.filterBtn} ${activeTag === tag ? styles.active : ''}`}
                  onClick={() => { setActiveTag(t => t === tag ? null : tag); setFavouritesOnly(false); setSearch('') }}
                >
                  {tag}
                </button>
              ))}
            </div>
          </div>

          <div className={styles.clipsScroll}>
            {loading && <p className={styles.status}>Loading…</p>}
            {error && <p className={styles.error}>{error}</p>}

            {!loading && !error && view === 'pads' && (
              <PadBoard pads={pads} onPlay={handlePlay} playingId={playingId} />
            )}

            {!loading && !error && view !== 'pads' && (
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
                      onGenerateQueue={handleGenerateQueue}
                      onEdit={handleEdit}
                      onVote={handleVote}
                      onTrimmed={handleTrimmed}
                      onGain={handleGain}
                      username={username}
                      playing={playingId === clip.identifier}
                      isAdmin={isAdmin}
                      view={view}
                      preset={historyPreset && historyPreset.ref === clip.identifier ? historyPreset : null}
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
              onReorderItem={handleReorderInQueue}
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
                    {groupedHistory.reduce((acc, entry, i) => {
                      const label = dayLabel(entry.played_at)
                      const prevLabel = i > 0 ? dayLabel(groupedHistory[i - 1].played_at) : null
                      if (label !== prevLabel) {
                        acc.push(
                          <li key={`day-${label}`} className={styles.daySeparator}>{label}</li>
                        )
                      }
                      acc.push(
                        <li key={i} className={styles.historyItem}>
                          <span className={styles.historyNameRow}>
                            <span className={styles.historyName} onClick={() => { setSearch(entry.clip_name); setActiveTag(null); setFavouritesOnly(false); setHistoryPreset({ ref: entry.clip_ref, pitch: entry.pitch ?? 0, speed: entry.speed ?? 1, nonce: Date.now() }) }} title="Search for this clip (and match its pitch/speed)">{entry.clip_name}</span>
                            {entry.count > 1 && <span className={styles.historyCount}>×{entry.count}</span>}
                          </span>
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
      {actionToast && <div className={styles.actionToast}>{actionToast}</div>}
      {helpOpen && (
        <HelpModal
          onClose={() => setHelpOpen(false)}
          isAdmin={isAdmin}
          voiceControl={voiceControl}
          presenceRequired={presenceRequired}
          appTitle={document.title || 'the bot'}
        />
      )}
    </div>
  )
}
