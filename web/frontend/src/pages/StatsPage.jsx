import { useState, useEffect, useMemo, useCallback } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import api from '../api'
import styles from './StatsPage.module.css'

const PERIODS = [
  { key: '24h', label: '24h' },
  { key: '7d', label: '7 days' },
  { key: '30d', label: '30 days' },
  { key: 'all', label: 'All time' },
]

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function BarList({ items, labelKey, valueKey, empty, onItemClick }) {
  const list = items || []
  const max = list.reduce((m, it) => Math.max(m, it[valueKey]), 0) || 1
  if (list.length === 0) return <p className={styles.empty}>{empty}</p>
  return (
    <ol className={styles.barList}>
      {list.map((it, i) => (
        <li key={i} className={styles.barRow}>
          <span
            className={`${styles.barLabel} ${onItemClick ? styles.clickable : ''}`}
            title={it[labelKey]}
            onClick={onItemClick ? () => onItemClick(it[labelKey]) : undefined}
          >
            {it[labelKey]}
          </span>
          <span className={styles.barTrack}>
            <span className={styles.barFill} style={{ width: `${(it[valueKey] / max) * 100}%` }} />
          </span>
          <span className={styles.barValue}>{it[valueKey]}</span>
        </li>
      ))}
    </ol>
  )
}

function Timeline({ data }) {
  const max = data.reduce((m, d) => Math.max(m, d.count), 0) || 1
  if (data.length === 0) return <p className={styles.empty}>No plays in this period.</p>
  const step = data.length > 16 ? Math.ceil(data.length / 12) : 1
  return (
    <div className={styles.timeline}>
      <div className={styles.timelineBars}>
        {data.map((d, i) => (
          <div key={i} className={styles.timelineCol} title={`${d.label}: ${d.count}`}>
            <div className={styles.timelineBar} style={{ height: `${(d.count / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className={styles.timelineLabels}>
        {data.map((d, i) => (
          <span key={i} className={styles.timelineLabel}>{i % step === 0 ? d.label : ''}</span>
        ))}
      </div>
    </div>
  )
}

function Heatmap({ grid }) {
  const max = grid.reduce((m, row) => Math.max(m, ...row), 0) || 1
  const hours = Array.from({ length: 24 }, (_, h) => h)
  return (
    <div className={styles.heatmap}>
      <div className={styles.heatmapRow}>
        <span className={styles.heatmapCorner} />
        {hours.map(h => (
          <span key={h} className={styles.heatmapHour}>{h % 3 === 0 ? h : ''}</span>
        ))}
      </div>
      {grid.map((row, d) => (
        <div key={d} className={styles.heatmapRow}>
          <span className={styles.heatmapDay}>{WEEKDAYS[d]}</span>
          {row.map((v, h) => (
            <span
              key={h}
              className={styles.heatmapCell}
              style={{ opacity: v === 0 ? 0.06 : 0.15 + (v / max) * 0.85 }}
              title={`${WEEKDAYS[d]} ${h}:00 — ${v} play${v !== 1 ? 's' : ''}`}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

function WordCloud({ items, onItemClick }) {
  if (!items || items.length === 0) return <p className={styles.empty}>No clips played.</p>
  const max = items.reduce((m, it) => Math.max(m, it.count), 0) || 1
  const min = items.reduce((m, it) => Math.min(m, it.count), max)
  // Shuffle deterministically so it reads like a cloud, not a ranked list.
  const cloud = [...items].sort((a, b) => (a.name < b.name ? -1 : 1))
  return (
    <div className={styles.wordCloud}>
      {cloud.map((it, i) => {
        const t = max === min ? 1 : (it.count - min) / (max - min)
        const size = 0.85 + t * 1.9
        const weight = t > 0.5 ? 600 : 400
        const opacity = 0.55 + t * 0.45
        return (
          <span
            key={i}
            className={styles.word}
            style={{ fontSize: `${size}rem`, fontWeight: weight, opacity }}
            title={`${it.count} play${it.count !== 1 ? 's' : ''}`}
            onClick={() => onItemClick(it.name)}
          >
            {it.name}
          </span>
        )
      })}
    </div>
  )
}

const MODES = [
  { key: 'clips', label: '🔊 Clips' },
  { key: 'songs', label: '🎵 Songs' },
]

export default function StatsPage() {
  const { logout } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()
  const [mode, setMode] = useState('clips')   // 'clips' | 'songs'
  const [period, setPeriod] = useState('7d')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Drill-down: { kind: 'user' | 'clip' | 'song', key }. The endpoints used
  // depend on the active mode (clip stats vs song stats).
  const [drill, setDrill] = useState(null)
  const [drillData, setDrillData] = useState(null)
  const [drillLoading, setDrillLoading] = useState(false)

  const tzOffset = useMemo(() => new Date().getTimezoneOffset(), [])
  const songs = mode === 'songs'

  useEffect(() => {
    setLoading(true)
    setDrill(null)
    const path = songs ? '/api/stats/songs/' : '/api/stats/'
    api.get(path, { params: { period, tz_offset: tzOffset } })
      .then(res => { setData(res.data); setError(null) })
      .catch(err => {
        if (err.response?.status === 401) { logout(); navigate('/login') }
        else setError('Failed to load statistics')
      })
      .finally(() => setLoading(false))
  }, [period, tzOffset, mode])

  const loadDrill = useCallback((kind, key) => {
    setDrill({ kind, key })
    setDrillLoading(true)
    setDrillData(null)
    let path
    if (kind === 'song') path = `/api/stats/songs/song/${encodeURIComponent(key)}`
    else if (kind === 'user') path = songs ? `/api/stats/songs/user/${encodeURIComponent(key)}` : `/api/stats/user/${encodeURIComponent(key)}`
    else path = `/api/stats/clip/${encodeURIComponent(key)}`
    api.get(path, { params: { period, tz_offset: tzOffset } })
      .then(res => setDrillData(res.data))
      .catch(() => setDrillData(null))
      .finally(() => setDrillLoading(false))
  }, [period, tzOffset, songs])

  // Refresh an open drill-down when the period changes.
  useEffect(() => {
    if (drill) loadDrill(drill.kind, drill.key)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period])

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const busiest = data && data.busiest_day
    ? `${data.busiest_day} ${String(data.busiest_hour).padStart(2, '0')}:00`
    : '—'

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.nav}>
          <Link to="/" className={styles.navLink}>← Clips</Link>
          <span className={styles.title}>Statistics</span>
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

      <div className={styles.periodBar}>
        <div className={styles.modeTabs}>
          {MODES.map(m => (
            <button
              key={m.key}
              className={`${styles.modeBtn} ${mode === m.key ? styles.active : ''}`}
              onClick={() => { if (m.key !== mode) { setData(null); setLoading(true); setMode(m.key) } }}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div className={styles.periodGroup}>
          {PERIODS.map(p => (
            <button
              key={p.key}
              className={`${styles.periodBtn} ${period === p.key ? styles.active : ''}`}
              onClick={() => setPeriod(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.scroll}>
        {loading && <p className={styles.status}>Loading…</p>}
        {error && <p className={styles.errorMsg}>{error}</p>}

        {!loading && !error && data && (
          data.total_plays === 0 ? (
            <p className={styles.status}>No {songs ? 'songs' : 'plays'} recorded in this period.</p>
          ) : songs ? (
          <>
            {data.song_of_week && (
              <div
                className={styles.cotw}
                onClick={() => loadDrill('song', data.song_of_week.name)}
                title="View song stats"
              >
                <span className={styles.cotwIcon}>🏆</span>
                <div className={styles.cotwBody}>
                  <span className={styles.cotwLabel}>Song of the week</span>
                  <span className={styles.cotwName}>{data.song_of_week.name}</span>
                </div>
                <span className={styles.cotwCount}>{data.song_of_week.count}<small>plays</small></span>
              </div>
            )}

            <div className={styles.cards}>
              <div className={styles.card}>
                <span className={styles.cardValue}>{data.total_plays}</span>
                <span className={styles.cardLabel}>Total plays</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardValue}>{data.unique_songs}</span>
                <span className={styles.cardLabel}>Songs played</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardValue}>{data.unique_users}</span>
                <span className={styles.cardLabel}>Active users</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardValue}>{busiest}</span>
                <span className={styles.cardLabel}>Busiest time</span>
              </div>
            </div>

            <section className={styles.panel}>
              <h2 className={styles.panelTitle}>Plays over time</h2>
              <Timeline data={data.timeline} />
            </section>

            <section className={styles.panel}>
              <h2 className={styles.panelTitle}>Song cloud <span className={styles.hint}>— click any song</span></h2>
              <WordCloud items={data.song_cloud} onItemClick={name => loadDrill('song', name)} />
            </section>

            <div className={styles.twoCol}>
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>Most played songs</h2>
                <BarList items={data.top_songs} labelKey="name" valueKey="count" empty="No songs played." onItemClick={name => loadDrill('song', name)} />
              </section>
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>Top players</h2>
                <BarList items={data.top_users} labelKey="user" valueKey="count" empty="No plays yet." onItemClick={user => loadDrill('user', user)} />
              </section>
            </div>

            <section className={styles.panel}>
              <h2 className={styles.panelTitle}>Activity by day &amp; hour</h2>
              <Heatmap grid={data.heatmap} />
            </section>

            <div className={styles.twoCol}>
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>Favourite instruments <span className={styles.hint}>— clips used to play tunes</span></h2>
                <BarList items={data.top_instruments} labelKey="name" valueKey="count" empty="No songs played." />
              </section>
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>Who plays what</h2>
                {data.user_favourites.length === 0
                  ? <p className={styles.empty}>No plays yet.</p>
                  : (
                    <ul className={styles.favList}>
                      {data.user_favourites.map((f, i) => (
                        <li key={i} className={styles.favRow}>
                          <span className={`${styles.favUser} ${styles.clickable}`} onClick={() => loadDrill('user', f.user)}>{f.user}</span>
                          <span className={`${styles.favClip} ${styles.clickable}`} title={f.song_name} onClick={() => loadDrill('song', f.song_name)}>{f.song_name}</span>
                          <span className={styles.favCount}>{f.count}×</span>
                        </li>
                      ))}
                    </ul>
                  )}
              </section>
            </div>
          </>
          ) : (
          <>
            {data.clip_of_week && (
              <div
                className={styles.cotw}
                onClick={() => loadDrill('clip', data.clip_of_week.name)}
                title="View clip stats"
              >
                <span className={styles.cotwIcon}>🏆</span>
                <div className={styles.cotwBody}>
                  <span className={styles.cotwLabel}>Clip of the week</span>
                  <span className={styles.cotwName}>{data.clip_of_week.name}</span>
                </div>
                <span className={styles.cotwCount}>{data.clip_of_week.count}<small>plays</small></span>
              </div>
            )}

            <div className={styles.cards}>
              <div className={styles.card}>
                <span className={styles.cardValue}>{data.total_plays}</span>
                <span className={styles.cardLabel}>Total plays</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardValue}>{data.unique_clips}</span>
                <span className={styles.cardLabel}>Clips played</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardValue}>{data.unique_users}</span>
                <span className={styles.cardLabel}>Active users</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardValue}>{busiest}</span>
                <span className={styles.cardLabel}>Busiest time</span>
              </div>
            </div>

            <section className={styles.panel}>
              <h2 className={styles.panelTitle}>Plays over time</h2>
              <Timeline data={data.timeline} />
            </section>

            <section className={styles.panel}>
              <h2 className={styles.panelTitle}>Clip cloud <span className={styles.hint}>— click any clip</span></h2>
              <WordCloud items={data.clip_cloud} onItemClick={name => loadDrill('clip', name)} />
            </section>

            <div className={styles.twoCol}>
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>Most played clips</h2>
                <BarList items={data.top_clips} labelKey="name" valueKey="count" empty="No clips played." onItemClick={name => loadDrill('clip', name)} />
              </section>
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>Top players</h2>
                <BarList items={data.top_users} labelKey="user" valueKey="count" empty="No plays yet." onItemClick={user => loadDrill('user', user)} />
              </section>
            </div>

            <section className={styles.panel}>
              <h2 className={styles.panelTitle}>Activity by day &amp; hour</h2>
              <Heatmap grid={data.heatmap} />
            </section>

            <div className={styles.twoCol}>
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>Who plays what</h2>
                {data.user_favourites.length === 0
                  ? <p className={styles.empty}>No plays yet.</p>
                  : (
                    <ul className={styles.favList}>
                      {data.user_favourites.map((f, i) => (
                        <li key={i} className={styles.favRow}>
                          <span className={`${styles.favUser} ${styles.clickable}`} onClick={() => loadDrill('user', f.user)}>{f.user}</span>
                          <span className={`${styles.favClip} ${styles.clickable}`} title={f.clip_name} onClick={() => loadDrill('clip', f.clip_name)}>{f.clip_name}</span>
                          <span className={styles.favCount}>{f.count}×</span>
                        </li>
                      ))}
                    </ul>
                  )}
              </section>
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>Popular tags</h2>
                {data.top_tags.length === 0
                  ? <p className={styles.empty}>No tagged plays.</p>
                  : (
                    <div className={styles.tagCloud}>
                      {(() => {
                        const max = data.top_tags.reduce((m, t) => Math.max(m, t.count), 0) || 1
                        return data.top_tags.map((t, i) => (
                          <span
                            key={i}
                            className={styles.tagChip}
                            style={{ fontSize: `${0.8 + (t.count / max) * 0.9}rem` }}
                            title={`${t.count} plays`}
                          >
                            {t.tag} <em>{t.count}</em>
                          </span>
                        ))
                      })()}
                    </div>
                  )}
              </section>
            </div>
          </>
          )
        )}
      </div>

      {drill && (
        <div className={styles.modalOverlay} onClick={() => setDrill(null)}>
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHead}>
              <div>
                <span className={styles.modalKind}>
                  {drill.kind === 'user' ? 'Player' : drill.kind === 'song' ? 'Song' : 'Clip'}
                </span>
                <h3 className={styles.modalTitle}>{drill.key}</h3>
              </div>
              <button className={styles.modalClose} onClick={() => setDrill(null)}>✕</button>
            </div>

            {drillLoading && <p className={styles.status}>Loading…</p>}
            {!drillLoading && !drillData && <p className={styles.empty}>No data.</p>}
            {!drillLoading && drillData && (
              <div className={styles.modalBody}>
                <div className={styles.modalStats}>
                  <div><strong>{drillData.total_plays}</strong><span>plays</span></div>
                  {drill.kind === 'user'
                    ? <div><strong>{songs ? drillData.unique_songs : drillData.unique_clips}</strong><span>{songs ? 'songs' : 'clips'}</span></div>
                    : <div><strong>{drillData.unique_users}</strong><span>players</span></div>}
                  {drill.kind === 'user' && drillData.busiest_hour != null && (
                    <div><strong>{String(drillData.busiest_hour).padStart(2, '0')}:00</strong><span>busiest</span></div>
                  )}
                </div>

                <h4 className={styles.modalSub}>Plays over time</h4>
                <Timeline data={drillData.timeline} />

                {drill.kind === 'user' && songs ? (
                  <>
                    <h4 className={styles.modalSub}>Most played songs</h4>
                    <BarList items={drillData.top_songs} labelKey="name" valueKey="count" empty="No songs." onItemClick={name => loadDrill('song', name)} />
                    <h4 className={styles.modalSub}>Favourite instruments</h4>
                    <BarList items={drillData.top_instruments} labelKey="name" valueKey="count" empty="No instruments." />
                  </>
                ) : drill.kind === 'user' ? (
                  <>
                    <h4 className={styles.modalSub}>Most played clips</h4>
                    <BarList items={drillData.top_clips} labelKey="name" valueKey="count" empty="No clips." onItemClick={name => loadDrill('clip', name)} />
                  </>
                ) : drill.kind === 'song' ? (
                  <>
                    <h4 className={styles.modalSub}>Top players</h4>
                    <BarList items={drillData.top_users} labelKey="user" valueKey="count" empty="No players." onItemClick={user => loadDrill('user', user)} />
                    <h4 className={styles.modalSub}>Instruments used</h4>
                    <BarList items={drillData.top_instruments} labelKey="name" valueKey="count" empty="No instruments." />
                  </>
                ) : (
                  <>
                    <h4 className={styles.modalSub}>Top players</h4>
                    <BarList items={drillData.top_users} labelKey="user" valueKey="count" empty="No players." onItemClick={user => loadDrill('user', user)} />
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
