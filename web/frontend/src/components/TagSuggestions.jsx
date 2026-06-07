import styles from './TagSuggestions.module.css'

// Clickable list of existing tags. Works on a comma-separated string value:
// clicking a tag adds it, clicking an already-selected one removes it. Lets you
// reuse existing tags instead of retyping (and keeps spelling consistent).
export default function TagSuggestions({ value, onChange, allTags = [] }) {
  if (!allTags.length) return null

  const current = value
    .split(',')
    .map(t => t.trim())
    .filter(Boolean)
  const selected = new Set(current.map(t => t.toLowerCase()))

  function toggle(tag) {
    if (selected.has(tag.toLowerCase())) {
      onChange(current.filter(t => t.toLowerCase() !== tag.toLowerCase()).join(', '))
    } else {
      onChange([...current, tag].join(', '))
    }
  }

  return (
    <div className={styles.wrap}>
      {allTags.map(tag => (
        <button
          type="button"
          key={tag}
          className={selected.has(tag.toLowerCase()) ? styles.active : styles.pill}
          onClick={() => toggle(tag)}
        >
          {tag}
        </button>
      ))}
    </div>
  )
}
