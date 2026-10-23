// In-browser preview player for the piano roll. Plays each MIDI note as a short
// synth tone (Web Audio oscillator) in time, so you can *hear* the tune while the
// playhead sweeps the roll. This is a preview, not the bot's real clip-based
// render — it's oscillators, not the assigned instrument samples.
//
// Uses the standard "two clocks" pattern: a setInterval scheduler queues notes a
// short lookahead ahead of the audio clock (rock-solid timing), while a
// requestAnimationFrame loop drives the visual playhead (smooth, and it never
// touches React state — the modal updates the DOM imperatively from onTick).

const LOOKAHEAD_S = 0.1 // schedule notes this far ahead of the audio clock
const SCHED_INTERVAL_MS = 25 // how often the scheduler wakes
const MASTER_GAIN = 0.8
const NOTE_PEAK = 0.22 // per-note gain before the compressor
const MAX_NOTE_S = 4 // clamp very long notes so tails don't pile up

function midiToFreq(pitch) {
  return 440 * Math.pow(2, (pitch - 69) / 12)
}

export default class PreviewPlayer {
  // notes: sorted-by-start [{p, s, d, g}]. opts: { duration, isAudible(program),
  // onTick(seconds), onEnd() }.
  constructor(notes, opts) {
    this.notes = notes
    this.duration = opts.duration || 0
    this.isAudible = opts.isAudible || (() => true)
    this.onTick = opts.onTick || (() => {})
    this.onEnd = opts.onEnd || (() => {})

    this.ctx = null
    this.master = null
    this.playing = false
    this.offset = 0 // song seconds at the last play() / after a seek
    this.startCtxTime = 0 // ctx.currentTime when the current run began
    this.nextIdx = 0 // pointer into notes for the scheduler
    this.live = [] // oscillators currently scheduled, so we can cut them off
    this._interval = null
    this._raf = null
  }

  _ensureCtx() {
    if (this.ctx) return
    const AC = window.AudioContext || window.webkitAudioContext
    this.ctx = new AC()
    this.master = this.ctx.createGain()
    this.master.gain.value = MASTER_GAIN
    // A compressor keeps dense chords from clipping the sum of oscillators.
    const comp = this.ctx.createDynamicsCompressor()
    this.master.connect(comp)
    comp.connect(this.ctx.destination)
  }

  get currentTime() {
    if (!this.playing) return this.offset
    return this.ctx.currentTime - this.startCtxTime + this.offset
  }

  play() {
    this._ensureCtx()
    if (this.ctx.state === 'suspended') this.ctx.resume()
    if (this.playing) return
    // Restart from the top if we're parked at the end.
    if (this.offset >= this.duration) this.offset = 0
    this.playing = true
    this.startCtxTime = this.ctx.currentTime
    // Point the scheduler at the first note at/after the current offset.
    this.nextIdx = this._indexAt(this.offset)
    this._interval = setInterval(() => this._schedule(), SCHED_INTERVAL_MS)
    this._tick()
  }

  pause() {
    if (!this.playing) return
    this.offset = this.currentTime
    this._halt()
  }

  stop() {
    this._halt()
    this.offset = 0
    this.onTick(0)
  }

  seek(t) {
    const clamped = Math.max(0, Math.min(t, this.duration))
    if (this.playing) {
      this._cutLive()
      this.offset = clamped
      this.startCtxTime = this.ctx.currentTime
      this.nextIdx = this._indexAt(clamped)
    } else {
      this.offset = clamped
    }
    this.onTick(clamped)
  }

  dispose() {
    this._halt()
    if (this.ctx) this.ctx.close()
    this.ctx = null
  }

  // --- internals ---

  _halt() {
    this.playing = false
    if (this._interval) clearInterval(this._interval)
    if (this._raf) cancelAnimationFrame(this._raf)
    this._interval = null
    this._raf = null
    this._cutLive()
  }

  _cutLive() {
    const now = this.ctx ? this.ctx.currentTime : 0
    for (const osc of this.live) {
      try {
        osc.stop(now)
      } catch {
        /* already stopped */
      }
    }
    this.live = []
  }

  _indexAt(t) {
    // First note starting at or after t (notes are sorted by start).
    let i = 0
    while (i < this.notes.length && this.notes[i].s < t) i++
    return i
  }

  _schedule() {
    if (!this.playing) return
    const songTime = this.currentTime
    if (songTime >= this.duration) {
      this._halt()
      this.offset = this.duration
      this.onEnd()
      return
    }
    const horizon = songTime + LOOKAHEAD_S
    while (this.nextIdx < this.notes.length && this.notes[this.nextIdx].s < horizon) {
      const n = this.notes[this.nextIdx]
      if (this.isAudible(n.g)) {
        const when = this.startCtxTime + (n.s - this.offset)
        this._voice(n, Math.max(when, this.ctx.currentTime))
      }
      this.nextIdx++
    }
  }

  _voice(note, when) {
    const dur = Math.min(note.d, MAX_NOTE_S)
    const osc = this.ctx.createOscillator()
    osc.type = 'triangle'
    osc.frequency.value = midiToFreq(note.p)
    const g = this.ctx.createGain()
    // Pluck-ish envelope: fast attack, decay to a sustain, quick release.
    g.gain.setValueAtTime(0, when)
    g.gain.linearRampToValueAtTime(NOTE_PEAK, when + 0.005)
    g.gain.linearRampToValueAtTime(NOTE_PEAK * 0.6, when + 0.06)
    g.gain.setTargetAtTime(0.0001, when + dur, 0.06)
    osc.connect(g)
    g.connect(this.master)
    const end = when + dur + 0.25
    osc.start(when)
    osc.stop(end)
    this.live.push(osc)
    osc.onended = () => {
      const i = this.live.indexOf(osc)
      if (i >= 0) this.live.splice(i, 1)
    }
  }

  _tick() {
    this.onTick(this.currentTime)
    this._raf = requestAnimationFrame(() => this._tick())
  }
}
