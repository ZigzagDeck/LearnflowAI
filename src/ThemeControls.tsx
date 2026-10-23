import { PALETTES } from './themes'
import type { Palette, Theme } from './themes'

export function BookLogo({ small = false }: { small?: boolean }) {
  return <span className={`brand-mark${small ? ' small' : ''}`} aria-hidden="true">
    <svg viewBox="0 0 32 32"><path d="M5 7.5c4.3-.9 8 .1 11 2.5v15c-3-2.4-6.7-3.3-11-2.5z" /><path d="M27 7.5c-4.3-.9-8 .1-11 2.5v15c3-2.4 6.7-3.3 11-2.5z" /><path d="M16 10v15" /></svg>
  </span>
}

export function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const nextTheme = theme === 'light' ? 'dark' : 'light'
  return <button className="theme-toggle" type="button" onClick={onToggle} aria-label={`Switch to ${nextTheme} mode`} title={`Switch to ${nextTheme} mode`}>
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {theme === 'light' ? <path d="M20.2 15.4A8.5 8.5 0 0 1 8.6 3.8 8.7 8.7 0 1 0 20.2 15.4Z" /> : <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>}
    </svg>
  </button>
}

export function PalettePicker({ palette, onChange }: { palette: Palette; onChange: (palette: Palette) => void }) {
  const selected = PALETTES.find((item) => item.id === palette) || PALETTES[0]
  return <label className="palette-picker" title={selected.note}>
    <span className="palette-swatch" style={{ background: selected.swatch }} aria-hidden="true" />
    <span className="sr-only">Visual theme</span>
    <select value={palette} onChange={(event) => onChange(event.target.value as Palette)} aria-label="Visual theme">
      {PALETTES.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
    </select>
  </label>
}
