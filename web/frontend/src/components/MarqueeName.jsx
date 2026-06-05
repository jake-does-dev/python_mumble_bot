import { useRef, useEffect } from 'react'
import styles from './MarqueeName.module.css'

// A text label that, when it's too long to fit, scrolls side-to-side on hover
// (same effect as the clip-card names). Measures overflow and drives it via a
// CSS variable; re-measures on container resize.
export default function MarqueeName({ text, className = '', title }) {
  const innerRef = useRef(null)

  useEffect(() => {
    const inner = innerRef.current
    if (!inner) return
    const update = () => {
      const overflow = inner.scrollWidth - inner.parentElement.clientWidth
      if (overflow > 0) {
        inner.style.setProperty('--name-overflow', `-${overflow}px`)
        inner.dataset.scrollable = 'true'
      } else {
        inner.style.removeProperty('--name-overflow')
        delete inner.dataset.scrollable
      }
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(inner.parentElement)
    return () => ro.disconnect()
  }, [text])

  return (
    <span className={`${styles.name} ${className}`} title={title ?? text}>
      <span className={styles.inner} ref={innerRef}>{text}</span>
    </span>
  )
}
