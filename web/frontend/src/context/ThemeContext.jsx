import { createContext, useContext, useState, useEffect } from 'react'

const ThemeContext = createContext(null)

function systemPrefersDark() {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function initialTheme() {
  const stored = localStorage.getItem('pmb_theme')
  if (stored === 'light' || stored === 'dark') return stored
  return systemPrefersDark() ? 'dark' : 'light'
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(initialTheme)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  function toggleTheme() {
    setTheme(prev => {
      const next = prev === 'dark' ? 'light' : 'dark'
      localStorage.setItem('pmb_theme', next)
      return next
    })
  }

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  return useContext(ThemeContext)
}
