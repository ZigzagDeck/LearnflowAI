import type { Palette } from './themes'

/** Original line illustrations; each theme has its own visual vocabulary. */
export function ThemeArtwork({ palette, className = '' }: { palette: Palette; className?: string }) {
  const artwork = {
    olive: <><path d="M74 153c35-27 55-68 61-117M112 91c-28 7-44-5-41-26 24-7 40 4 41 26ZM122 69c-4-24 9-39 31-38 3 22-8 37-31 38ZM94 122c-25 7-43-3-44-25 24-7 41 2 44 25ZM117 102c21 3 37-9 37-29-23-2-35 7-37 29ZM98 132c24 7 42-3 46-23-23-8-40 0-46 23Z" /><path d="M55 155h91M65 166h71" /></>,
    terminal: <><rect x="32" y="39" width="136" height="112" rx="4" /><path d="M32 61h136M45 50h1m9 0h1m9 0h1M50 84l17 13-17 13m29 0h31M48 134h49" /><path className="art-secondary" d="M120 130h32m-16-16v32" /></>,
    daylight: <><path d="M40 148h123M51 148V94h34v54m17 0V65h34v83M45 43h106M69 43v30m45-30v11" /><circle cx="150" cy="57" r="18" /><path className="art-secondary" d="m31 118 132-78M35 130l132-78" /></>,
    botanical: <><path d="M100 153V86m0 36c-35 3-52-17-46-44 30 0 47 17 46 44Zm0-15c-2-37 19-57 49-51 1 32-18 51-49 51Z" /><path d="M73 144h54l-8 29H81z" /><circle className="art-secondary" cx="83" cy="51" r="10" /><path className="art-secondary" d="M83 29v8m0 28v8M61 51h8m28 0h8M67 35l6 6m20 20 6 6M99 35l-6 6" /></>,
    blueprint: <><path d="M36 153h131M47 142V50h102v92H47Zm0-65h102M78 50v92m40-92v92M47 110h71M32 36h132M32 32v8m132-8v8M163 50v92m-4-92h8m-8 92h8" /><circle className="art-secondary" cx="136" cy="125" r="26" /><path className="art-secondary" d="m117 144 38-38m-19-7v52m-26-26h52" /></>,
    legal: <><path d="M100 37v115M53 66h94M100 37l-8 14h16zM59 66 37 110h44L59 66Zm82 0-22 44h44l-22-44ZM37 110c1 24 41 24 44 0m38 0c1 24 41 24 44 0M76 154h48m-59 11h70" /><circle className="art-secondary" cx="100" cy="63" r="6" /></>,
    academy: <><path d="m28 67 72-30 72 30-72 30-72-30Zm24 11v44c29 21 67 21 96 0V78M171 69v57m-5 0h10v20h-10z" /><path className="art-secondary" d="M60 158h81m-72 10h63M42 133l-5 21m117-20 6 20" /></>,
    atelier: <><path d="m74 141 54-95c6-10 22 0 16 10l-57 91-13-6ZM74 141c-32-2-10 30-35 25 32 16 47-1 48-19M120 60l15 9" /><path className="art-secondary" d="M47 62c-9-25 22-38 33-20s-12 35-29 31M124 127c31-16 53 11 33 26s-43 0-33-26ZM93 25l-5 10m77 56-13 3M28 102l9 5" /></>,
    neon: <><path d="m110 29-58 78h40l-3 62 61-88h-43l3-52Z" /><path className="art-secondary" d="M43 43h17m-8-8v17M153 145h17m-8-8v17M32 141l11-11m-11 0 11 11M151 39l11 11m-11 0 11-11" /><circle className="art-secondary" cx="43" cy="91" r="4" /><circle className="art-secondary" cx="161" cy="108" r="4" /></>,
  }
  return <svg className={`theme-artwork ${className}`} viewBox="0 0 200 200" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{artwork[palette]}</svg>
}
