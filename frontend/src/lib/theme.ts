import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

function current(): Theme {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
}

/** Light/dark, applied as a class on <html> and remembered per browser.
 *  index.html applies the saved value before first paint. */
export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(current)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      localStorage.setItem('theme', theme)
    } catch {
      // Private windows can refuse storage; the theme still applies.
    }
  }, [theme])

  return [theme, setTheme]
}
