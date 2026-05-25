import styles from './ClipCard.module.css'

export default function ClipCard({ clip, onToggleFavourite, onPlay, playing }) {
  return (
    <div className={styles.card}>
      <div className={styles.name}>{clip.name}</div>
      <div className={styles.tags}>
        {clip.tags.map(tag => (
          <span key={tag} className={styles.tag}>{tag}</span>
        ))}
      </div>
      <div className={styles.actions}>
        <button
          className={`${styles.star} ${clip.is_favourite ? styles.starred : ''}`}
          onClick={() => onToggleFavourite(clip.identifier)}
          title={clip.is_favourite ? 'Remove favourite' : 'Add favourite'}
        >
          {clip.is_favourite ? '★' : '☆'}
        </button>
        <button
          className={`${styles.play} ${playing ? styles.playing : ''}`}
          onClick={() => onPlay(clip.identifier)}
          disabled={playing}
          title="Play"
        >
          {playing ? '…' : '▶'}
        </button>
      </div>
    </div>
  )
}
