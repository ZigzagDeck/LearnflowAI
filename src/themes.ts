export type Theme = 'light' | 'dark'
export type Palette = 'olive' | 'terminal' | 'daylight' | 'botanical' | 'blueprint' | 'legal' | 'academy' | 'atelier' | 'neon'

export const PALETTES: Array<{ id: Palette; name: string; note: string; swatch: string; companion: string; edition: string }> = [
  { id: 'olive', name: 'Olive Library', note: 'A quiet corner for a curious mind.', swatch: '#747d43', companion: '#dfc7a2', edition: 'The considered collection' },
  { id: 'terminal', name: 'Midnight Terminal', note: 'Clear thinking. Beautiful execution.', swatch: '#348767', companion: '#9bbbd0', edition: 'Your next command: understand' },
  { id: 'daylight', name: 'Daylight Desk', note: 'Room to think. Space to begin.', swatch: '#6f7c72', companion: '#e5d5b9', edition: 'A fresh perspective' },
  { id: 'botanical', name: 'Botanical Notes', note: 'Small discoveries. Growing ideas.', swatch: '#7fa467', companion: '#d99dab', edition: 'Let your curiosity grow' },
  { id: 'blueprint', name: 'Blueprint Studio', note: 'Give your next big idea a structure.', swatch: '#477b9b', companion: '#d2a16b', edition: 'Designed for discovery' },
  { id: 'legal', name: 'Legal Archive', note: 'Follow the evidence. Find clarity.', swatch: '#8d6540', companion: '#b7a17d', edition: 'A case for deeper learning' },
  { id: 'academy', name: 'Classic Academy', note: 'Old-school curiosity. New possibilities.', swatch: '#a65345', companion: '#c6ad6b', edition: 'For the lifelong learner' },
  { id: 'atelier', name: 'Creative Atelier', note: 'Make a little room for possibility.', swatch: '#668a83', companion: '#dca976', edition: 'Ideas are a work in progress' },
  { id: 'neon', name: 'Neon Quest', note: 'A new level of understanding awaits.', swatch: '#9561d0', companion: '#52c4d5', edition: 'Your curiosity, upgraded' },
]
