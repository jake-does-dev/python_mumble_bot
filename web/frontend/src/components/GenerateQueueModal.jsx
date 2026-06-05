import { useState } from 'react'
import {
  PITCH_MIN,
  PITCH_MAX,
  SPEED_SLIDER_STEPS,
  speedToSlider,
  sliderToSpeed,
  pitchLabel,
} from '../lib/clipSettings'
import styles from './GenerateQueueModal.module.css'

const COUNT = 15

export default function GenerateQueueModal({ clip, onClose, onGenerate }) {
  const [minPitch, setMinPitch] = useState(-4)
  const [maxPitch, setMaxPitch] = useState(4)
  const [minSpeed, setMinSpeed] = useState(0.8)
  const [maxSpeed, setMaxSpeed] = useState(1.4)

  // Keep each pair ordered (min never crosses max).
  const onMinPitch = (v) => setMinPitch(Math.min(v, maxPitch))
  const onMaxPitch = (v) => setMaxPitch(Math.max(v, minPitch))
  const onMinSpeed = (v) => setMinSpeed(Math.min(v, maxSpeed))
  const onMaxSpeed = (v) => setMaxSpeed(Math.max(v, minSpeed))

  function generate() {
    onGenerate({ minPitch, maxPitch, minSpeed, maxSpeed, count: COUNT })
    onClose()
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.head}>
          <div>
            <span className={styles.kind}>Generate queue</span>
            <h3 className={styles.title}>{clip.name}</h3>
          </div>
          <button className={styles.close} onClick={onClose}>✕</button>
        </div>

        <p className={styles.blurb}>
          Builds a queue of <b>{COUNT}</b> copies of this clip, each at a random pitch &amp; speed
          within the ranges below.
        </p>

        <div className={styles.group}>
          <div className={styles.groupLabel}>Pitch range</div>
          <label className={styles.row}>
            <span>Min <strong>{pitchLabel(minPitch)}</strong></span>
            <input type="range" min={PITCH_MIN} max={PITCH_MAX} step={1}
              value={minPitch} onChange={e => onMinPitch(Number(e.target.value))} />
          </label>
          <label className={styles.row}>
            <span>Max <strong>{pitchLabel(maxPitch)}</strong></span>
            <input type="range" min={PITCH_MIN} max={PITCH_MAX} step={1}
              value={maxPitch} onChange={e => onMaxPitch(Number(e.target.value))} />
          </label>
        </div>

        <div className={styles.group}>
          <div className={styles.groupLabel}>Speed range</div>
          <label className={styles.row}>
            <span>Min <strong>{minSpeed.toFixed(2)}×</strong></span>
            <input type="range" min={0} max={SPEED_SLIDER_STEPS} step={1}
              value={speedToSlider(minSpeed)} onChange={e => onMinSpeed(sliderToSpeed(Number(e.target.value)))} />
          </label>
          <label className={styles.row}>
            <span>Max <strong>{maxSpeed.toFixed(2)}×</strong></span>
            <input type="range" min={0} max={SPEED_SLIDER_STEPS} step={1}
              value={speedToSlider(maxSpeed)} onChange={e => onMaxSpeed(sliderToSpeed(Number(e.target.value)))} />
          </label>
        </div>

        <div className={styles.actions}>
          <button className={styles.cancel} onClick={onClose}>Cancel</button>
          <button className={styles.generate} onClick={generate}>🎲 Generate {COUNT}</button>
        </div>
      </div>
    </div>
  )
}
