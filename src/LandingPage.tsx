import { useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent, ReactNode } from 'react'
import { BookLogo, PalettePicker, ThemeToggle } from './ThemeControls'
import { ThemeArtwork } from './ThemeArtwork'
import { PALETTES } from './themes'
import type { Palette, Theme } from './themes'
import './LandingPage.css'

function Arrow({ diagonal = false }: { diagonal?: boolean }) {
  return <svg className="landing-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d={diagonal ? 'M6 18 18 6M6 6h12v12' : 'M4 12h15m-6-6 6 6-6 6'} /></svg>
}

function Icon({ kind }: { kind: 'source' | 'chat' | 'summary' | 'quiz' | 'interview' | 'check' }) {
  const paths: Record<typeof kind, ReactNode> = {
    source: <><path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6m-6 4h4" /></>,
    chat: <><path d="M4 4h16v12H9l-5 4zM8 8h8m-8 4h5" /></>,
    summary: <><path d="M5 4h14v16H5zM8 8h8m-8 4h8m-8 4h4" /></>,
    quiz: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="m8 12 3 3 5-6" /></>,
    interview: <><rect x="8" y="3" width="8" height="12" rx="4" /><path d="M5 11a7 7 0 0 0 14 0m-7 7v3m-4 0h8" /></>,
    check: <path d="m5 12 4 4L19 6" />,
  }
  return <svg className="landing-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[kind]}</svg>
}

const PREVIEW_TABS = ['chat', 'summary', 'quiz', 'interview'] as const
const TAB_LABELS = { chat: 'Ask', summary: 'Summarize', quiz: 'Quiz', interview: 'Rehearse' }
type PreviewTab = typeof PREVIEW_TABS[number]

function StudyPreview() {
  const [tab, setTab] = useState<PreviewTab>('chat')
  const [answer, setAnswer] = useState<number | null>(null)
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([])
  const moveTab = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next = index
    if (event.key === 'ArrowRight') next = (index + 1) % PREVIEW_TABS.length
    else if (event.key === 'ArrowLeft') next = (index + PREVIEW_TABS.length - 1) % PREVIEW_TABS.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = PREVIEW_TABS.length - 1
    else return
    event.preventDefault()
    setTab(PREVIEW_TABS[next])
    tabRefs.current[next]?.focus()
  }
  return <div className="study-preview">
    <div className="preview-titlebar"><span className="preview-window-dots" aria-hidden="true"><i /><i /><i /></span><span>Your next lightbulb moment</span><BookLogo small /></div>
    <div className="preview-body">
      <div className="preview-source"><span className="preview-file"><Icon kind="source" /></span><div><strong>The science of learning.pdf</strong><small>Sample source · Learning & memory</small></div><span className="preview-ready"><i />Ready</span></div>
      <div className="preview-tabs" role="tablist" aria-label="Explore a sample study workspace">
        {PREVIEW_TABS.map((item, index) => <button ref={(node) => { tabRefs.current[index] = node }} key={item} id={`preview-tab-${item}`} role="tab" aria-selected={tab === item} aria-controls={`preview-panel-${item}`} tabIndex={tab === item ? 0 : -1} type="button" onClick={() => setTab(item)} onKeyDown={(event) => moveTab(event, index)}><Icon kind={item} />{TAB_LABELS[item]}</button>)}
      </div>
      <div className="preview-content" role="tabpanel" id={`preview-panel-${tab}`} aria-labelledby={`preview-tab-${tab}`} tabIndex={0}>
        {tab === 'chat' && <><div className="preview-question">Why does testing myself help me remember?</div><div className="preview-answer"><span className="preview-spark" aria-hidden="true">✳</span><div><strong>Remembering is a form of learning.</strong><p>When you retrieve an idea from memory, you strengthen your ability to recall it again. That’s why a small quiz can do more than another reread.</p><span className="preview-citation"><Icon kind="source" />Sample reference · p. 12</span></div></div><div className="preview-input">Follow your curiosity…<span aria-hidden="true">↑</span></div></>}
        {tab === 'summary' && <div className="preview-summary"><span className="preview-overline">THE IDEA, DISTILLED</span><h3>Learn it. Recall it. Keep it.</h3><p>Three ideas from this sample reading:</p><ol><li><strong>Retrieve, don’t just reread.</strong> Bring an idea to mind before checking your notes.</li><li><strong>Space out your practice.</strong> Return to the topic across several sessions.</li><li><strong>Explain it simply.</strong> Notice the gaps in your own understanding.</li></ol><span className="preview-citation">Illustrative study guide</span></div>}
        {tab === 'quiz' && <div className="preview-quiz"><span className="preview-overline">A LITTLE CHECK-IN · 01 / 01</span><h3>Which is an example of active recall?</h3><div className="preview-options">{['Highlighting a paragraph', 'Explaining an idea with your notes closed', 'Rereading a chapter'].map((option, index) => <button type="button" key={option} aria-pressed={answer === index} className={answer === index ? 'is-picked' : ''} onClick={() => setAnswer(index)}><span>{String.fromCharCode(65 + index)}</span>{option}{answer === index && <Icon kind="check" />}</button>)}</div><p className="preview-feedback" aria-live="polite">{answer === null ? 'Try an answer. This is a sample quiz.' : answer === 1 ? 'Exactly. Bring the idea back from memory.' : 'Try B. Active recall means retrieving an idea from memory.'}</p></div>}
        {tab === 'interview' && <div className="preview-interview"><span className="preview-overline">PRACTICE FINDING YOUR WORDS</span><span className="preview-mic"><Icon kind="interview" /></span><h3>“How would you help someone remember a difficult concept?”</h3><p>A thoughtful question. Room to rehearse. Feedback to help you find your next improvement.</p><span className="preview-citation">Illustrative interview question</span></div>}
      </div>
    </div>
    <div className="preview-status"><span><i />A preview of what’s possible</span><span>Sample content</span></div>
  </div>
}

const FEATURES: Array<{ icon: 'chat' | 'summary' | 'quiz' | 'interview'; title: string; text: string; detail: string }> = [
  { icon: 'chat', title: 'A question worth asking.', text: 'Have a conversation with your materials. Follow the references back to the page, slide, or moment behind an answer.', detail: 'Source-grounded conversations' },
  { icon: 'summary', title: 'The bigger picture, clearer.', text: 'Find the throughline in a long reading. Make a concise summary, a detailed explanation, or a study guide.', detail: 'From complexity to clarity' },
  { icon: 'quiz', title: 'Make it stick.', text: 'Move from recognizing an idea to recalling it. Practice with different question types and review the explanations.', detail: 'Practice with purpose' },
  { icon: 'interview', title: 'Find your words.', text: 'Rehearse for the role you have in mind. Bring your résumé or job context, then reflect on your feedback.', detail: 'Thoughtful interview practice' },
]

const FAQS = [
  ['What can I bring to LearnFlow?', 'Upload PDFs, PowerPoint files (.pptx), or PNG and JPEG images. You can also add a public YouTube video when accessible captions are available. Once processing finishes, select your sources and start exploring.'],
  ['Do answers connect back to my sources?', 'Chat uses passages from your selected materials, with references that can point to a page, slide, image, or video timestamp. AI can still make mistakes, so use the references to check important details.'],
  ['Will my theme stay with me?', 'Yes. Your palette and light or dark preference are saved in this browser and continue through sign-in, your materials, conversations, summaries, quizzes, and interviews. Choose a different mood whenever you like.'],
  ['How do I get started?', 'Create an account, add your first material, and wait until it is marked Ready. Select it to ask a question, make a summary, build a quiz, or prepare for an interview. Your learning history is saved to your account.'],
]

export default function LandingPage({ palette, theme, onPaletteChange, onToggleTheme }: { palette: Palette; theme: Theme; onPaletteChange: (palette: Palette) => void; onToggleTheme: () => void }) {
  const selected = PALETTES.find((item) => item.id === palette) || PALETTES[0]
  return <div className="landing-page">
    <a className="landing-skip" href="#landing-main">Skip to content</a>
    <header className="landing-header landing-wrap">
      <a className="brand landing-brand" href="#home" aria-label="LearnFlow AI home"><BookLogo /><span>LearnFlow<span className="brand-accent"> AI</span><small>A little more understanding.</small></span></a>
      <nav className="landing-nav" aria-label="Landing page"><a href="#how-it-works">How it works</a><a href="#possibilities">The possibilities</a><a href="#make-it-yours">Make it yours</a></nav>
      <div className="landing-header-actions"><PalettePicker palette={palette} onChange={onPaletteChange} /><ThemeToggle theme={theme} onToggle={onToggleTheme} /><a className="landing-signin" href="#login">Sign in <Arrow diagonal /></a></div>
    </header>
    <main id="landing-main" className="landing-main">
      <section className="landing-hero landing-wrap" aria-labelledby="landing-title">
        <div className="hero-copy"><p className="landing-eyebrow"><span className="edition-mark" />YOUR CURIOSITY. A LITTLE MORE POSSIBILITY.</p><h1 id="landing-title">Go from<br />taking notes<br />to <span>connecting dots.</span></h1><p className="hero-description">Your sources, questions, and lightbulb moments.<br className="desktop-break" /> One thoughtful space to turn what you read<br className="desktop-break" /> into what you understand.</p><div className="hero-actions"><a className="landing-button" href="#register">Find your flow <Arrow /></a><a className="landing-text-link" href="#how-it-works">Take a look around <span aria-hidden="true">↓</span></a></div><p className="hero-footnote"><Icon kind="check" />Your materials. Your pace. Your kind of focus.</p></div>
        <div className="hero-stage"><div className="hero-halo" aria-hidden="true" /><div className="hero-orbit" aria-hidden="true" /><div className="hero-edition"><ThemeArtwork palette={palette} /><span>{selected.edition}</span></div><div className="hero-source-note"><span className="note-pin" /><Icon kind="source" /><span>A chapter.<br />A question.<br /><strong>A new connection.</strong></span><svg viewBox="0 0 95 40" fill="none" aria-hidden="true"><path d="M3 6c19 32 54 30 80 14m-12-3 16 1-4 13" /></svg></div><StudyPreview /><div className="hero-annotation"><span aria-hidden="true">✳</span>Less scattered. More connected.</div><span className="hero-coordinate" aria-hidden="true">READ → ASK → PRACTICE</span></div>
      </section>
      <div className="source-strip landing-wrap"><span className="source-strip-label">GOOD IDEAS COME FROM EVERYWHERE</span><div><span><Icon kind="source" />PDFs & papers</span><span><svg className="landing-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M4 5h16v12H4zM12 17v4m-4 0h8M8 9h8m-8 4h5" /></svg>Slides</span><span><svg className="landing-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m5 18 5-5 3 3 3-5 4 5" /></svg>Images & notes</span><span><svg className="landing-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="4" /><path d="m10 9 5 3-5 3z" /></svg>Captioned YouTube videos</span></div></div>
      <section className="landing-how landing-wrap landing-section" id="how-it-works" aria-labelledby="how-title"><div className="landing-section-heading"><p className="landing-eyebrow">01 / A SMALL SHIFT IN HOW YOU STUDY</p><h2 id="how-title">Less collecting.<br /><em>More connecting.</em></h2><p>You already have the material.<br />Give it a place to become understanding.</p></div><div className="journey-grid">{[
        { number: '01', icon: 'source' as const, title: 'Bring your world.', text: 'A dense paper. A lecture deck. That video you saved. Bring your sources together and let them finish processing.', note: 'Start with what you have' },
        { number: '02', icon: 'chat' as const, title: 'Follow a question.', text: 'Select your sources and ask what’s on your mind. Explore an explanation, connect ideas, and check the references.', note: 'Make room for the “why”' },
        { number: '03', icon: 'quiz' as const, title: 'Make it your own.', text: 'Turn your reading into a study guide, test your recall, or rehearse an interview. Take the next step that fits you.', note: 'Understanding takes practice' },
      ].map((step) => <article className="journey-step" key={step.number}><div className="journey-top"><span className="journey-number">{step.number}</span><span className="journey-icon"><Icon kind={step.icon} /></span></div><h3>{step.title}</h3><p>{step.text}</p><span className="journey-note">{step.note}<Arrow diagonal /></span></article>)}</div></section>
      <section className="landing-possibilities landing-section" id="possibilities" aria-labelledby="possibilities-title"><div className="landing-wrap"><div className="landing-section-heading possibilities-heading"><div><p className="landing-eyebrow">02 / ONE SPACE, MORE WAYS TO LEARN</p><h2 id="possibilities-title">For the moment<br />it <em>starts to click.</em></h2></div><p>Read with context. Ask with evidence.<br />Practice with purpose.</p></div><div className="feature-grid">{FEATURES.map((feature, index) => <article className={`landing-feature feature-${feature.icon}`} key={feature.icon}><div className="feature-top"><span className="feature-icon"><Icon kind={feature.icon} /></span><span className="feature-index">0{index + 1}</span></div><h3>{feature.title}</h3><p>{feature.text}</p><span className="feature-detail">{feature.detail}</span></article>)}</div><div className="evidence-note"><span className="evidence-symbol" aria-hidden="true">↳</span><p><strong>A little healthy curiosity goes a long way.</strong> AI can make mistakes. References help you go back to the source and think for yourself.</p></div></div></section>
      <section className="landing-themes landing-wrap landing-section" id="make-it-yours" aria-labelledby="themes-title"><div className="theme-introduction"><div><p className="landing-eyebrow">03 / SETTLE INTO YOUR OWN CORNER</p><h2 id="themes-title">Your mind.<br />Your mood.<br /><em>Your space.</em></h2><p>A quiet library. A drafting table. A late-night terminal. Nine distinct worlds, each with a light and a dark side.</p><p className="theme-persistence"><Icon kind="check" />The atmosphere stays with you, from here to your workspace.</p></div><div className="theme-live-caption" aria-live="polite"><ThemeArtwork palette={palette} /><div><span>YOU’RE EXPLORING</span><strong>{selected.name}</strong><small>{selected.note}</small></div></div><button className="landing-mode-button" type="button" onClick={onToggleTheme}><span aria-hidden="true">{theme === 'light' ? '◐' : '◑'}</span>Currently in {theme === 'light' ? 'light' : 'dark'} mode <span>Try {theme === 'light' ? 'dark' : 'light'} ↗</span></button></div><div className="theme-gallery" aria-label="Choose your visual theme">{PALETTES.map((item, index) => <button type="button" className="theme-tile" data-sample={item.id} aria-pressed={palette === item.id} onClick={() => onPaletteChange(item.id)} key={item.id} style={{ '--sample-accent': item.swatch, '--sample-companion': item.companion } as CSSProperties}><span className="theme-tile-scene"><span className="tile-corner">0{index + 1}</span><ThemeArtwork palette={item.id} /><span className="tile-mini-lines" aria-hidden="true"><i /><i /><i /></span><span className="tile-selection" aria-hidden="true">{palette === item.id ? '✓' : '↗'}</span></span><span className="theme-tile-label"><strong>{item.name}</strong><span className="theme-color-dots" aria-hidden="true"><i /><i /><i /></span></span></button>)}</div></section>
      <section className="landing-faq landing-wrap landing-section" aria-labelledby="faq-title"><div><p className="landing-eyebrow">A FEW THINGS YOU MIGHT BE WONDERING</p><h2 id="faq-title">Before you<br /><em>settle in.</em></h2></div><div className="faq-list">{FAQS.map(([question, answer]) => <details key={question}><summary>{question}<span aria-hidden="true">+</span></summary><p>{answer}</p></details>)}</div></section>
      <section className="landing-final landing-wrap"><div className="final-inner"><ThemeArtwork palette={palette} className="final-art" /><p className="landing-eyebrow">YOUR NEXT LIGHTBULB MOMENT STARTS HERE</p><h2>A little curiosity.<br /><em>A whole lot of possibility.</em></h2><p>Bring something you want to understand.<br />We’ll give you a thoughtful place to begin.</p><a className="landing-button" href="#register">Find your flow <Arrow /></a><span className="final-edition">{selected.name} / {theme === 'light' ? 'The light edition' : 'The after-hours edition'}</span></div></section>
    </main>
    <footer className="landing-footer landing-wrap"><a className="brand" href="#home"><BookLogo /><span>LearnFlow AI</span></a><p>For the joy of figuring things out.</p><div><a href="#login">Sign in</a><a href="#register">Create account <Arrow diagonal /></a><a href="#home" aria-label="Back to top">↑</a></div></footer>
  </div>
}
