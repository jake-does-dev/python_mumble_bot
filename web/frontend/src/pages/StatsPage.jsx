import { useState, useEffect, useMemo } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import api from '../api'
import styles from './StatsPage.module.css'

const PERIODS = [
  { key: '24h', label: '24h' },
  { key: '7d', label: '7 days' },
  { key: '30d', label: '30 days' },
  { key: 'all', label: 'All time' },
]

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function BarList({ items, labelKey, valueKey, empty }) {
  const max = items.reduce((m, it) => Math.max(m, it[valueKey]), 0) || 1
  if (items.length === 0) return <p className={styles.empty}>{empty}</p>
  return (
    <ol className={styles.barList}>
      {items.map((it, i) => (
        <li key={i} className={styles.barRow}>
          <span className={styles.barLabel} title={it[labelKey]}>{it[labelKey]}</span>
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
  // Thin out x-axis labels when there are many buckets.
  const step = data.length > 16 ? Math.ceil(data.length / 12) : 1
  return (
    <div className={styles.timeline}>
      <div className={styles.timelineBars}>
        {data.map((d, i) => (
          <div key={i} className={styles.timelineCol} title={`${d.label}: ${d.count}`}>
            <div
              className={styles.timelineBar}
              style={{ height: `${(d.count / max) * 100}%` }}
            />
          </div>
        ))}
      </div>
      <div className={styles.timelineLabels}>
        {data.map((d, i) => (
          <span key={i} className={styles.timelineLabel}>
            {i % step === 0 ? d.label : ''}
          </span>
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

export default function StatsPage() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const [period, setPeriod] = useState('7d')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const tzOffset = useMemo(() => new Date().getTimezoneOffset(), [])

  useEffect(() => {
    setLoading(true)
    api.get('/api/stats/', { params: { period, tz_offset: tzOffset } })
      .then(res => { setData(res.data); setError(null) })
      .catch(err => {
        if (err.response?.status === 401) { logout(); navigate('/login') }
        else setError('Failed to load statistics')
      })
      .finally(() => setLoading(false))
  }, [period, tzOffset])

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
        <button className={styles.logout} onClick={handleLogout}>Sign out</button>
      </header>

      <div className={styles.periodBar}>
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

      <div className={styles.scroll}>
        {loading && <p className={styles.status}>Loading…</p>}
        {error && <p className={styles.errorMsg}>{error}</p>}

        {!loading && !error && data && (
          data.total_plays === 0 ? (
            <p className={styles.status}>No plays recorded in this period.</p>
          ) : (
          <>
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

            <div className={styles.twoCol}>
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>Most played clips</h2>
                <BarList items={data.top_clips} labelKey="name" valueKey="count" empty="No clips played." />
              </section>
              <section className={styles.panel}>
                <h2 className={styles.panelTitle}>Top players</h2>
                <BarList items={data.top_users} labelKey="user" valueKey="count" empty="No plays yet." />
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
                          <span className={styles.favUser}>{f.user}</span>
                          <span className={styles.favClip} title={f.clip_name}>{f.clip_name}</span>
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
    </div>
  )
}
