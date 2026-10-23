# Landing page and theme identities

Visitors arrive on the landing page at `/` or `#home`. `#login` and `#register`
use the existing authentication API. Protected links (`#materials`, `#chat`,
`#summary`, `#quiz`, `#interview`, `#history`) open sign-in and retain the intended
workspace destination, including when switching between account forms. A restored
session continues into the workspace. Signing out returns to the landing page.

The hero's Ask, Summarize, Quiz, and Rehearse tabs contain clearly labeled sample
content. The quiz is interactive and runs locally. It does not generate requests
to the learning API. Real study actions remain in the authenticated workspace.

## Nine identities, eighteen appearances

Each identity uses the existing light/dark surface and contrast tokens, plus the
shared identity system in `src/ThemeIdentity.css`. Preferences use the existing
browser storage keys and are applied before the initial paint. The landing page,
sign-in, and all workspace views share these settings.

| Theme | Visual vocabulary | Original illustration |
| --- | --- | --- |
| Olive Library | Bookish serif, paper grain, olive/gold, book corners | Olive branch |
| Midnight Terminal | Monospace, scan lines, command prefixes, crisp frames | Terminal window |
| Daylight Desk | Architectural light, restrained sans, open space, round controls | Sunlit desk geometry |
| Botanical Notes | Soft blooms, leaf shapes, friendly type, organic curves | Growing plant |
| Blueprint Studio | Drafting grid, mono headings, measurement details, offset shadows | Architectural plan |
| Legal Archive | Parchment, Baskerville, double rules, evidence-file edges | Balance scales |
| Classic Academy | Ruled notes, scholarly serif, arch shapes, book-like layers | Graduation cap |
| Creative Atelier | Watercolor washes, handwritten display, irregular corners | Paintbrush and color marks |
| Neon Quest | Luminous purple/cyan, geometric sans, glow, angular details | Lightning and sparks |

Twenty-four visible elements express the selected identity in both modes:

1. Page atmosphere and texture.
2. Heading typography.
3. Body typography.
4. Emphasized heading treatment.
5. Eyebrow typography, tracking, and decorative prefix.
6. Brand mark shape.
7. Primary button corners and shadows.
8. Panel surface, borders, and corners.
9. Hero backdrop pattern and geometry.
10. Hero orbit shape and stroke.
11. Original theme illustration.
12. Secondary illustration accent.
13. Theme edition caption.
14. Source note geometry, tilt, and paper treatment.
15. Product preview frame, tilt, and shadow.
16. Window controls and title bar.
17. Chat message geometry.
18. Citation and status badge shapes.
19. Icon containers and outlines.
20. Step numerals and ornaments.
21. Section and card dividing rules.
22. Feature card depth and edge treatment.
23. Theme gallery miniature patterns and illustrations.
24. Final invitation panel silhouette.

Where appropriate, the same details extend to workspace section icons, avatars,
chat/interview messages, citations, source pickers, upload controls, quizzes, and
the account form. Original theme illustrations are inline SVG, with no external
image dependency. Fonts use the app's existing Google Fonts import and fallbacks.

## Accessibility and verification

The preview tabs support Arrow Left/Right, Home, and End. The gallery exposes its
selected state, and the mode control states its next action. The page includes a
skip link, semantic headings, native FAQ disclosures, visible keyboard focus, and
reduced-motion support. Mobile theme names remain visible.

Run `npm test`, `npm run lint`, and `npm run build`. Browser checks cover every
palette in both modes at desktop and mobile sizes, theme persistence across
navigation/reload, sample interactions, and account links.

## Publish to the existing application

`wrangler.jsonc` targets the existing Cloudflare Worker and serves `dist/` with SPA
fallback. Build with the deployed backend's HTTPS base URL, including `/api` when
the backend is mounted under that prefix. The local `.env` points at localhost;
do not publish a build with that development address.

```powershell
$env:VITE_API_BASE_URL = 'https://your-current-api-host.example/api'
npm run build
npx wrangler deploy --keep-vars
```

Verify the backend health and frontend asset responses after deployment. A Quick
Tunnel hostname can change when the tunnel restarts; use the active address.
