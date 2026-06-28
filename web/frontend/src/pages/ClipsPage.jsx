import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import api from '../api'
import ClipCard from '../components/ClipCard'
import UploadPanel from '../components/UploadPanel'
import QueuePanel from '../components/QueuePanel'
import SongCard from '../components/SongCard'
import SongHistory from '../components/SongHistory'
import NowPlaying from '../components/NowPlaying'
import SongInstrumentPanel from '../components/SongInstrumentPanel'
import VoicePanel from '../components/VoicePanel'
import PadBoard from '../components/PadBoard'
import HelpModal from '../components/HelpModal'
import EntranceModal from '../components/EntranceModal'
import ClipThatModal from '../components/ClipThatModal'
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
  const [clipCapture, setClipCapture] = useState(false)
  const [entranceEnabled, setEntranceEnabled] = useState(true)
  const [username, setUsername] = useState(null)
  const [presenceRequired, setPresenceRequired] = useState(false)
  const [voiceLinked, setVoiceLinked] = useState(false)
  const [actionToast, setActionToast] = useState(null)
  const [queueCooldownUntil, setQueueCooldownUntil] = useState(0)
  const [now, setNow] = useState(Date.now())

  const [search, setSearch] = useState('')
  const [activeTag, setActiveTag] = useState(null)
  const [favouritesOnly, setFavouritesOnly] = useState(false)
  // Duration bucket filter: null | 'short' (≤1s) | 'mid' (1–3s) | 'long' (3s+).
  const [durationBucket, setDurationBucket] = useState(null)
  const [playingId, setPlayingId] = useState(null)
  // Set when a history entry is clicked, to push that play's pitch/speed onto
  // the matching clip card. `nonce` lets the same values re-apply on re-click.
  const [historyPreset, setHistoryPreset] = useState(null)
  const [view, setView] = useState(() => localStorage.getItem('pmb_view') || 'grid')
  const [sort, setSort] = useState(() => localStorage.getItem('pmb_sort') || 'alpha')
  // Top-level main view: clips vs songs.
  const [mainView, setMainView] = useState(() => localStorage.getItem('pmb_main_view') || 'clips')
  const [songView, setSongView] = useState(() => localStorage.getItem('pmb_song_view') || 'grid')
  const [songSearch, setSongSearch] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [dragActive, setDragActive] = useState(false)  // file dragged over window
  const [droppedFile, setDroppedFile] = useState(null)
  const [helpOpen, setHelpOpen] = useState(false)
  const [entranceOpen, setEntranceOpen] = useState(false)
  const [clipThatOpen, setClipThatOpen] = useState(false)
  const [tagsExpanded, setTagsExpanded] = useState(() => localStorage.getItem('pmb_tags_expanded') !== 'false')

  const [sidebarTab, setSidebarTab] = useState('history')
  const [songs, setSongs] = useState([])
  const [songHistory, setSongHistory] = useState([])
  const [songState, setSongState] = useState({ current: null, queue: [] })
  const [skipping, setSkipping] = useState(false)
  const [songUploadError, setSongUploadError] = useState(null)
  // Active "pick an instrument for this song" flow. When set, the main view is
  // the Clips screen (full search) and a picker panel shows in the sidebar.
  const [songPick, setSongPick] = useState(null)
  const [queues, setQueues] = useState(loadQueues)
  const [activeQueueId, setActiveQueueId] = useState(() => localStorage.getItem('pmb_active_queue') || null)
  const [playingQueue, setPlayingQueue] = useState(false)

  const songFileRef = useRef(null)

  function handleSetView(v) {
    setView(v)
    localStorage.setItem('pmb_view', v)
  }

  function handleSetMainView(v) {
    setMainView(v)
    localStorage.setItem('pmb_main_view', v)
  }

  function handleSetSongView(v) {
    setSongView(v)
    localStorage.setItem('pmb_song_view', v)
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

  const fetchSongs = useCallback(() => {
    api.get('/api/songs/').then(res => setSongs(res.data)).catch(() => {})
  }, [])

  const fetchSongHistory = useCallback(() => {
    api.get('/api/songs/history').then(res => setSongHistory(res.data)).catch(() => {})
  }, [])

  const fetchSongState = useCallback(() => {
    api.get('/api/songs/now-playing').then(res => setSongState(res.data)).catch(() => {})
  }, [])

  async function handleSkipSong() {
    setSkipping(true)
    try {
      await api.post('/api/songs/skip')
      setTimeout(fetchSongState, 400)
    } catch (err) {
      if (err.response?.status === 403) showActionToast(err.response.data?.detail || 'Not allowed')
    } finally {
      setSkipping(false)
    }
  }

  useEffect(() => {
    Promise.all([api.get('/api/clips/'), api.get('/api/clips/tags'), api.get('/api/users/me')])
      .then(([clipsRes, tagsRes, meRes]) => {
        setClips(clipsRes.data)
        setTags(tagsRes.data)
        setIsAdmin(meRes.data.is_admin)
        setVoiceControl(meRes.data.voice_control)
        setClipCapture(meRes.data.clip_capture)
        setEntranceEnabled(meRes.data.entrance_enabled !== false)
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
    fetchSongs()
    fetchSongHistory()
    fetchSongState()
  }, [])

  useEffect(() => {
    const id = setInterval(() => {
      fetchHistory()
      fetchSongHistory()
      fetchSongState()
    }, 3000)
    return () => clearInterval(id)
  }, [fetchHistory, fetchSongHistory, fetchSongState])

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
        if (durationBucket) {
          const d = clip.duration_s
          if (d == null) return false  // unknown duration: hidden while bucketing
          if (durationBucket === 'short' && d > 1) return false
          if (durationBucket === 'mid' && (d <= 1 || d > 3)) return false
          if (durationBucket === 'long' && d <= 3) return false
        }
        if (q && !clip.name.toLowerCase().includes(q) && !clip.identifier.toLowerCase().includes(q) && !clip.tags.some(t => t.toLowerCase().includes(q))) return false
        return true
      })
      .sort((a, b) => {
        if (sort === 'top') return (b.score ?? 0) - (a.score ?? 0)
        if (sort === 'rot') return (a.score ?? 0) - (b.score ?? 0)
        if (sort === 'newest') return new Date(b.creation_time) - new Date(a.creation_time)
        if (sort === 'oldest') return new Date(a.creation_time) - new Date(b.creation_time)
        // Unknown durations sort to the end either way.
        if (sort === 'shortest') return (a.duration_s ?? Infinity) - (b.duration_s ?? Infinity)
        if (sort === 'longest') return (b.duration_s ?? -1) - (a.duration_s ?? -1)
        return a.name.localeCompare(b.name)
      })
  }, [clips, search, activeTag, favouritesOnly, sort, durationBucket])

  const filteredSongs = useMemo(() => {
    const q = songSearch.trim().toLowerCase()
    const list = q ? songs.filter(s => s.name.toLowerCase().includes(q)) : songs
    return [...list].sort((a, b) => a.name.localeCompare(b.name))
  }, [songs, songSearch])

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

  async function handlePlay(identifier, pitch, speed, reverse = false) {
    setPlayingId(identifier)
    try {
      await api.post(`/api/commands/play/${identifier}`, { pitch, speed, reverse })
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

  function handleAddToQueue(identifier, name, pitch, speed, reverse = false) {
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
        ? { ...q, items: [...q.items, { id: newId(), identifier, name, pitch, speed, reverse }] }
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
          reverse: item.reverse || false,
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

  async function handleUploadSong(file) {
    setSongUploadError(null)
    const formData = new FormData()
    formData.append('file', file)
    try {
      await api.post('/api/songs/upload', formData)
      fetchSongs()
    } catch (err) {
      setSongUploadError(err.response?.data?.detail || 'Upload failed')
    }
  }

  async function handleDeleteSong(songId) {
    try {
      await api.delete(`/api/songs/${songId}`)
      fetchSongs()
    } catch (err) {
      showActionToast(err.response?.data?.detail || 'Delete failed')
    }
  }

  async function handleRenameSong(songId, name) {
    try {
      await api.patch(`/api/songs/${songId}`, { name })
      fetchSongs()
    } catch (err) {
      showActionToast(err.response?.data?.detail || 'Rename failed')
    }
  }

  // Start the "pick an instrument" flow: jump to the Clips screen (full search)
  // and open the instrument picker in the sidebar, seeded from `preset` if the
  // play came from history.
  function startSongPick(song, preset = null) {
    // Replaying from history? Re-seed per-line clip assignments too.
    const assignments = {}
    for (const ins of preset?.instruments || []) {
      assignments[ins.program] = {
        clipRef: ins.clip_ref,
        clipName: ins.clip_name || ins.clip_ref,
        gain: ins.gain ?? 0,
      }
    }
    setSongPick({
      song,
      clipRef: preset?.clip_ref || null,
      clipName: preset?.clip_name || '',
      transpose: preset?.transpose ?? 0,
      speed: preset?.speed ?? 1.0,
      gain: preset?.gain ?? -6,  // music starts a touch quieter than clips
      maxSeconds: preset?.max_seconds ?? 10,
      lines: [],            // instrument lines (fetched below)
      activeProgram: null,  // which line a clip click assigns to (null = default)
      assignments,          // { program: {clipRef, clipName, gain} }
    })
    handleSetMainView('clips')
    if (view === 'pads') handleSetView('grid')  // pads have no per-clip select button
    // Fetch the song's instrument lines so the user can assign a clip per line.
    api.get(`/api/songs/${song.id}/lines`)
      .then(res => setSongPick(p => (p && p.song.id === song.id
        ? { ...p, lines: res.data || [] } : p)))
      .catch(() => {})
  }

  // A clip's "Use as instrument" button: assign to the active line, or set the
  // default instrument when no line is active.
  function assignInstrument(clip) {
    setSongPick(p => {
      if (!p) return p
      if (p.activeProgram == null) {
        return { ...p, clipRef: clip.identifier, clipName: clip.name }
      }
      const prev = p.assignments[p.activeProgram] || { gain: 0 }
      return {
        ...p,
        assignments: {
          ...p.assignments,
          [p.activeProgram]: { clipRef: clip.identifier, clipName: clip.name, gain: prev.gain },
        },
      }
    })
  }

  async function playFromPick() {
    if (!songPick?.clipRef || cooldownRemaining > 0) return
    const instruments = Object.entries(songPick.assignments || {})
      .filter(([, a]) => a && a.clipRef)
      .map(([program, a]) => ({
        program: Number(program),
        clip_ref: a.clipRef,
        gain: a.gain ?? 0,
      }))
    await doPlaySong(songPick.song.id, {
      clip_ref: songPick.clipRef,
      clip_name: songPick.clipName,
      transpose: songPick.transpose,
      speed: Math.round(songPick.speed * 100) / 100,
      gain: songPick.gain,
      max_seconds: songPick.maxSeconds,
      instruments,
    })
    setSongPick(null)
  }

  async function doPlaySong(songId, opts) {
    if (cooldownRemaining > 0) return
    try {
      await api.post(`/api/songs/${songId}/play`, opts)
      setQueueCooldownUntil(Date.now() + 10000)
      setTimeout(fetchHistory, 1500)
      setTimeout(fetchSongHistory, 1500)
      setTimeout(fetchSongState, 400)
      setTimeout(fetchSongState, 1200)
    } catch (err) {
      if (err.response?.status === 429) {
        const m = /(\d+)/.exec(err.response.data?.detail || '')
        const secs = m ? Number(m[1]) : 10
        setQueueCooldownUntil(Date.now() + secs * 1000)
      } else if (err.response?.status === 403) {
        showActionToast(err.response.data?.detail || 'Not allowed to play right now')
      } else {
        showActionToast(err.response?.data?.detail || 'Failed to play song')
      }
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
          {entranceEnabled && <button className={styles.statsLink} onClick={() => setEntranceOpen(true)} title="Set the sound that plays when you join the bot's channel">🔔 Entrance</button>}
          {clipCapture && <button className={styles.statsLink} onClick={() => setClipThatOpen(true)} title="Clip the last 30s of someone's voice into a soundboard clip">✂️ Clip that</button>}
          <button className={styles.statsLink} onClick={() => setHelpOpen(true)} title="How to use the bot">❓ Help</button>
          <Link to="/stats" className={styles.statsLink}>📊 Stats</Link>
          {isAdmin && <Link to="/admin/users" className={styles.statsLink}>⚙ Users</Link>}

          <span className={styles.headerDivider} />

          {mainView === 'clips' && (
            <button
              className={`${styles.statsLink} ${uploadOpen ? styles.active : ''}`}
              onClick={() => setUploadOpen(o => !o)}
              title="Upload a clip"
            >
              ↑ Upload
            </button>
          )}
          <button
            className={styles.stopBtn}
            onClick={handleStop}
            title="Stop all playback now"
          >
            ⏹ Stop
          </button>
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
          <div className={styles.mainTabs}>
            <button
              className={`${styles.mainTab} ${mainView === 'clips' ? styles.mainTabActive : ''}`}
              onClick={() => handleSetMainView('clips')}
            >
              🔊 Clips{clips.length > 0 ? ` (${clips.length})` : ''}
            </button>
            <button
              className={`${styles.mainTab} ${mainView === 'songs' ? styles.mainTabActive : ''}`}
              onClick={() => handleSetMainView('songs')}
            >
              🎵 Songs{songs.length > 0 ? ` (${songs.length})` : ''}
            </button>
          </div>

          {mainView === 'clips' ? (
          <>
          <div className={styles.controls}>
            {uploadOpen && (
              <UploadPanel
                onClose={() => { setUploadOpen(false); setDroppedFile(null) }}
                onUploaded={handleUploaded}
                initialFile={droppedFile}
                allTags={tags}
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
                <option value="shortest">⏱ Short</option>
                <option value="longest">⏱ Long</option>
              </select>
              <div className={styles.viewToggle}>
                <button className={`${styles.viewBtn} ${view === 'grid' ? styles.active : ''}`} onClick={() => handleSetView('grid')} title="Grid view">⊞ Grid</button>
                <button className={`${styles.viewBtn} ${view === 'list' ? styles.active : ''}`} onClick={() => handleSetView('list')} title="List view">☰ List</button>
                <button className={`${styles.viewBtn} ${view === 'pads' ? styles.active : ''}`} onClick={() => handleSetView('pads')} title="Pad board (favourites + hotkeys)">▦ Pads</button>
              </div>
            </div>
            <div className={styles.filters}>
              <button
                className={`${styles.filterBtn} ${!activeTag && !favouritesOnly && !durationBucket ? styles.active : ''}`}
                onClick={() => { setActiveTag(null); setFavouritesOnly(false); setDurationBucket(null) }}
              >
                All
              </button>
              <button
                className={`${styles.filterBtn} ${favouritesOnly ? styles.active : ''}`}
                onClick={() => { setFavouritesOnly(f => !f); setActiveTag(null) }}
              >
                ★ Favourites
              </button>
              <button
                className={`${styles.filterBtn} ${durationBucket === 'short' ? styles.active : ''}`}
                onClick={() => setDurationBucket(b => b === 'short' ? null : 'short')}
                title="Clips ≤1s — best for songs"
              >
                ⏱ ≤1s
              </button>
              <button
                className={`${styles.filterBtn} ${durationBucket === 'mid' ? styles.active : ''}`}
                onClick={() => setDurationBucket(b => b === 'mid' ? null : 'mid')}
                title="Clips 1–3s"
              >
                ⏱ 1–3s
              </button>
              <button
                className={`${styles.filterBtn} ${durationBucket === 'long' ? styles.active : ''}`}
                onClick={() => setDurationBucket(b => b === 'long' ? null : 'long')}
                title="Clips longer than 3s"
              >
                ⏱ 3s+
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
                      picking={!!songPick}
                      selectedInstrument={!!songPick && (
                        songPick.activeProgram == null
                          ? songPick.clipRef === clip.identifier
                          : songPick.assignments?.[songPick.activeProgram]?.clipRef === clip.identifier
                      )}
                      onSelectInstrument={assignInstrument}
                      allTags={tags}
                    />
                  ))}
                </div>
              </>
            )}
          </div>
          </>
          ) : (
          <>
          <div className={styles.controls}>
            <div className={styles.controlsTop}>
              <div className={styles.searchWrap}>
                <input
                  className={styles.search}
                  type="search"
                  placeholder="Search songs…"
                  value={songSearch}
                  onChange={e => setSongSearch(e.target.value)}
                />
                {songSearch && (
                  <button className={styles.searchClear} onClick={() => setSongSearch('')} title="Clear search">✕</button>
                )}
              </div>
              <button
                className={styles.sortSelect}
                onClick={() => songFileRef.current?.click()}
                title="Upload a MIDI song"
              >
                ↑ Upload .mid
              </button>
              <input
                ref={songFileRef}
                type="file"
                accept=".mid,.midi,audio/midi"
                style={{ display: 'none' }}
                onChange={e => { const f = e.target.files?.[0]; if (f) handleUploadSong(f); e.target.value = '' }}
              />
              <div className={styles.viewToggle}>
                <button className={`${styles.viewBtn} ${songView === 'grid' ? styles.active : ''}`} onClick={() => handleSetSongView('grid')} title="Grid view">⊞ Grid</button>
                <button className={`${styles.viewBtn} ${songView === 'list' ? styles.active : ''}`} onClick={() => handleSetSongView('list')} title="List view">☰ List</button>
              </div>
            </div>
            {songUploadError && <p className={styles.error}>{songUploadError}</p>}
          </div>

          <div className={styles.clipsScroll}>
            {songs.length === 0 ? (
              <p className={styles.status}>No songs yet — upload a .mid to start.</p>
            ) : filteredSongs.length === 0 ? (
              <p className={styles.status}>No songs match “{songSearch}”.</p>
            ) : (
              <>
                <p className={styles.count}>{filteredSongs.length} song{filteredSongs.length !== 1 ? 's' : ''}</p>
                <div className={songView === 'grid' ? styles.grid : styles.list}>
                  {filteredSongs.map(song => (
                    <SongCard
                      key={song.id}
                      song={song}
                      view={songView}
                      username={username}
                      isAdmin={isAdmin}
                      cooldownRemaining={cooldownRemaining}
                      onPlay={(s, preset = null) => startSongPick(s, preset)}
                      onRename={handleRenameSong}
                      onDelete={handleDeleteSong}
                    />
                  ))}
                </div>
              </>
            )}
          </div>
          </>
          )}
        </div>

        <aside className={styles.sidebar}>
          {mainView === 'songs' ? (
            <>
              <NowPlaying state={songState} onSkip={handleSkipSong} skipping={skipping} />
              <SongHistory
                history={songHistory}
                songs={songs}
                onReplay={(song, preset) => startSongPick(song, preset)}
              />
            </>
          ) : (
          <>
          {/* Also surface the song player here so a playing song / queue isn't
              lost when the user is browsing clips. Renders nothing when idle. */}
          <NowPlaying state={songState} onSkip={handleSkipSong} skipping={skipping} />
          {songPick && (
            <SongInstrumentPanel
              pick={songPick}
              onUpdate={(partial) => setSongPick(p => ({ ...p, ...partial }))}
              onPlay={playFromPick}
              onCancel={() => setSongPick(null)}
              cooldownRemaining={cooldownRemaining}
            />
          )}
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

      {entranceOpen && (
        <EntranceModal clips={clips} onClose={() => setEntranceOpen(false)} />
      )}
      {clipThatOpen && (
        <ClipThatModal
          onClose={() => setClipThatOpen(false)}
          onSaved={handleUploaded}
          allTags={tags}
        />
      )}
    </div>
  )
}
