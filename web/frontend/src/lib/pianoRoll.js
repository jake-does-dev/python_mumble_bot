// Colour assignment for the piano-roll visualiser. Kept out of the component
// file so React fast-refresh stays happy (component files should only export
// components).

// How many instrument lines get their own colour. Beyond this they fold into a
// neutral "Other" grey — the categorical palette is only validated to 8 slots
// (dataviz skill). Lines arrive busiest-first, so the loud parts keep colour.
export const MAX_COLOURED_LINES = 8

// Same hues as the CSS palette in PianoRoll.module.css, mirrored here so the
// legend swatches (a different CSS module) match the SVG exactly per theme.
export const ROLL_COLOURS = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
  other: '#898781',
}

// program -> palette slot ("roll-1".."roll-8" or "roll-other"), by line order.
export function buildColourMap(lines) {
  const map = new Map()
  lines.forEach((ln, i) => {
    map.set(ln.program, i < MAX_COLOURED_LINES ? `roll-${i + 1}` : 'roll-other')
  })
  return map
}

// Swatch colour for the i-th line (busiest-first) in the given theme.
export function lineColour(index, theme) {
  if (index >= MAX_COLOURED_LINES) return ROLL_COLOURS.other
  return (ROLL_COLOURS[theme] || ROLL_COLOURS.light)[index]
}
