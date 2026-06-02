import { useEffect, useState } from 'react'
import {
  PITCH_MIN,
  PITCH_MAX,
  SPEED_SLIDER_STEPS,
  speedToSlider,
  sliderToSpeed,
  loadSetting,
  saveSetting,
  pitchLabel,
} from '../lib/clipSettings'
import styles from './PadBoard.module.css'

const HOTKEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']

export default function PadBoard({ pads, onPlay, playingId }) {
  // Per-pad pitch/speed, shared with the grid/list cards via localStorage.
  const [settings, setSettings] = useState({})

  useEffect(() => {
    setSettings(prev => {
      const next = { ...prev }
      for (const c of pads) {
        if (!next[c.identifier]) {
          next[c.identifier] = {
            pitch: loadSetting(c.identifier, 'pitch', 0),
            speed: loadSetting(c.identifier, 'speed', 1),
          }
        }
      }
      return next
    })
  }, [pads])

  function getSetting(id) {
    return settings[id] || { pitch: 0, speed: 1 }
  }

  function setPitch(id, v) {
    saveSetting(id, 'pitch', v)
    setSettings(s => ({ ...s, [id]: { ...getSetting(id), pitch: v } }))
  }

  function setSpeed(id, v) {
    saveSetting(id, 'speed', v)
    setSettings(s => ({ ...s, [id]: { ...getSetting(id), speed: v } }))
  }

  function fire(id) {
    const s = getSetting(id)
    onPlay(id, s.pitch, s.speed)
  }

  useEffect(() => {
    function onKey(e) {
      if (e.repeat) return // ignore auto-repeat from a held-down key
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const el = e.target
      if (el && el.matches && el.matches('input, textarea, select')) return
      const idx = HOTKEYS.indexOf(e.key)
      if (idx >= 0 && idx < pads.length) {
        e.preventDefault()
        fire(pads[idx].identifier)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pads, onPlay, settings])

  if (pads.length === 0) {
    return (
      <p className={styles.empty}>
        Star clips (☆) to add them to your pad board — the first ten get hotkeys 1–9, 0.
      </p>
    )
  }

  return (
    <>
      <p className={styles.hint}>Tap a pad or press <kbd>1</kbd>–<kbd>9</kbd>, <kbd>0</kbd> to fire the first ten. Sliders set pitch &amp; speed (shared with the other views).</p>
      <div className={styles.board}>
        {pads.map((clip, i) => {
          const s = getSetting(clip.identifier)
          return (
            <div key={clip.identifier} className={`${styles.pad} ${playingId === clip.identifier ? styles.firing : ''}`}>
              <button className={styles.padFire} onClick={() => fire(clip.identifier)} title={`Play ${clip.name}`}>
                {i < HOTKEYS.length && <span className={styles.hotkey}>{HOTKEYS[i]}</span>}
                <span className={styles.padName}>{clip.name}</span>
              </button>
              <div className={styles.padControls}>
                <label className={styles.ctrl}>
                  <span>Pitch <strong>{pitchLabel(s.pitch)}</strong></span>
                  <input
                    type="range"
                    min={PITCH_MIN}
                    max={PITCH_MAX}
                    step={1}
                    value={s.pitch}
                    onChange={e => setPitch(clip.identifier, Number(e.target.value))}
                  />
                </label>
                <label className={styles.ctrl}>
                  <span>Speed <strong>{s.speed.toFixed(2)}×</strong></span>
                  <input
                    type="range"
                    min={0}
                    max={SPEED_SLIDER_STEPS}
                    step={1}
                    value={speedToSlider(s.speed)}
                    onChange={e => setSpeed(clip.identifier, sliderToSpeed(Number(e.target.value)))}
                  />
                </label>
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}
