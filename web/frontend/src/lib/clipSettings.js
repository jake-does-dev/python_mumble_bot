// Shared per-clip playback settings (pitch/speed) used by ClipCard and PadBoard.
// Settings persist in localStorage keyed by clip identifier, so a tweak made in
// one view carries to the others.

export const PITCH_MIN = -12
export const PITCH_MAX = 12
export const SPEED_MIN = 0.5
export const SPEED_MAX = 4
export const SPEED_SLIDER_STEPS = 1000
export const SPEED_SLIDER_MID = SPEED_SLIDER_STEPS / 2
const STORAGE_KEY = 'pmb_clip_settings'

// The speed slider is non-linear: more resolution below 1× than above.
export function speedToSlider(speed) {
  if (speed <= 1.0) {
    return Math.round((speed - SPEED_MIN) / (1.0 - SPEED_MIN) * SPEED_SLIDER_MID)
  }
  return Math.round(SPEED_SLIDER_MID + (speed - 1.0) / (SPEED_MAX - 1.0) * SPEED_SLIDER_MID)
}

export function sliderToSpeed(v) {
  if (v <= SPEED_SLIDER_MID) {
    return SPEED_MIN + (v / SPEED_SLIDER_MID) * (1.0 - SPEED_MIN)
  }
  return 1.0 + ((v - SPEED_SLIDER_MID) / SPEED_SLIDER_MID) * (SPEED_MAX - 1.0)
}

export function loadSetting(identifier, key, defaultValue) {
  try {
    const all = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    return all[identifier]?.[key] ?? defaultValue
  } catch {
    return defaultValue
  }
}

export function saveSetting(identifier, key, value) {
  try {
    const all = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    all[identifier] = { ...all[identifier], [key]: value }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all))
  } catch { /* ignore */ }
}

export function pitchLabel(v) {
  if (v === 0) return '0 st'
  return `${v > 0 ? '+' : ''}${v} st`
}
