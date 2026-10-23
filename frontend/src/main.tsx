import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

const API = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')
type Match = { id: string; team_id: string; opponent_id: string; scheduled_at: string; status: string; home_away: 'HOME' | 'AWAY'; home_score: number | null; away_score: number | null; season?: string | null }
type Memory = { id: string; title: string; summary: string; occurred_at: string; memory_type: string; confidence: number | null }
type Replay = { id: string; decision_type: string; decision_at: string; ai_recommendation_text: string | null; human_decision: string | null; match_id: string | null }
type ReplayDetail = { id: string; decision_type: string; decision_at: string; ai_recommendation_text: string | null; ai_recommendation_at: string | null; human_decision: string | null; human_decision_at: string | null; match_id: string | null }
type EventItem = { id: string; minute: number; side: string; event_type: string; description: string | null }
type Player = { id: string; first_name: string; last_name: string; preferred_position: string; secondary_position: string | null; status: string }
type Team = { id: string; name: string; short_name: string; season: string }
type SimMetric = { name: string; baseline_value: number | null; counterfactual_value: number | null; delta: number | null; units: string; available: boolean; reason: string | null }
type SimResult = { scenario_id: string; match_id: string; baseline_formation: string; counterfactual_formation: string; simulator_status: string; assumptions: string[]; warnings: string[]; metrics: SimMetric[]; unavailable_reasons: string[] }
type EvalMetric = { name: string; expected: number | null; actual: number | null; error: number | null; units: string; available: boolean; reason: string | null }
type EvalResult = { scenario_id: string; evaluation_status: string; evaluation_method: string; metrics: EvalMetric[]; sample_count: number; warnings: string[]; provenance: string[] }
const FORMATIONS = ['4-4-2','4-3-3','3-5-2','3-4-3','5-3-2','4-2-3-1','4-1-3-1','2-3-5','2-3-3-1','1-4-4-1']
function newUuid(): string { try { if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID() } catch { /* fall through */ } return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16) }) }

async function request<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API}${path}`, { ...init, headers: { ...(init.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers } })
  } catch (error) {
    if (error instanceof TypeError) throw new Error('Can’t reach the TACTUSBALL server. Start the backend at localhost:8000, then try again.')
    throw error
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `${response.status} ${response.statusText}`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function App() {
  const [token, setToken] = useState(localStorage.getItem('tactus_token') || '')
  const [page, setPage] = useState(location.hash === '#app' ? 'Command center' : 'Home')
  const [navOpen, setNavOpen] = useState(false)
  const [motionOff, setMotionOff] = useState(localStorage.getItem('tactus_motion') === 'off')
  const [matches, setMatches] = useState<Match[]>([])
  const [selectedFeature, setSelectedFeature] = useState(0)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadMatch, setUploadMatch] = useState('')
  const [uploadResult, setUploadResult] = useState('')
  const [introActive, setIntroActive] = useState(() => !sessionStorage.getItem('tactus_intro_seen') && localStorage.getItem('tactus_motion') !== 'off' && !window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const orbitBallRef = useRef<HTMLSpanElement>(null)
  const [memories, setMemories] = useState<Memory[]>([])
  const [replays, setReplays] = useState<Replay[]>([])
  const [health, setHealth] = useState<'checking' | 'online' | 'offline'>('checking')
  const [error, setError] = useState('')
  const [copilotQuestion, setCopilotQuestion] = useState('')
  const [copilotOpen, setCopilotOpen] = useState(false)
  const [copilotAnswer, setCopilotAnswer] = useState<{answer:string; grounded:boolean; citations:{source_type:string; source_id:string}[]; model:string; warnings:string[]}|null>(null)
  const [copilotStatus, setCopilotStatus] = useState<null | { kind: 'unconfigured' | 'failed' | 'session'; message: string }>(null)
  const [showSetup, setShowSetup] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const [registerMode, setRegisterMode] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [events, setEvents] = useState<EventItem[]>([])
  const [eventsMatch, setEventsMatch] = useState('')
  const [eventsState, setEventsState] = useState<'idle'|'loading'|'ready'|'empty'>('idle')
  const [players, setPlayers] = useState<Player[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [rosterState, setRosterState] = useState<'idle'|'loading'|'ready'>('idle')
  const [selectedPlayer, setSelectedPlayer] = useState('')
  const [memoryFilter, setMemoryFilter] = useState('')
  const [selectedReplay, setSelectedReplay] = useState<ReplayDetail|null>(null)
  const [cfMatch, setCfMatch] = useState('')
  const [cfBase, setCfBase] = useState('4-3-3')
  const [cfAlt, setCfAlt] = useState('3-4-3')
  const [cfOut, setCfOut] = useState('')
  const [cfIn, setCfIn] = useState('')
  const [cfResult, setCfResult] = useState<SimResult|null>(null)
  const [evalSpec, setEvalSpec] = useState('')
  const [evalResult, setEvalResult] = useState<EvalResult|null>(null)

  useEffect(() => {
    const update = () => setPage(location.hash === '#app' ? 'Command center' : 'Home')
    window.addEventListener('hashchange', update)
    const observer = new IntersectionObserver(entries => entries.forEach(entry => entry.target.classList.toggle('revealed', entry.isIntersecting)), { threshold: .14 })
    document.querySelectorAll('.reveal').forEach(el => observer.observe(el))
    return () => { window.removeEventListener('hashchange', update); observer.disconnect() }
  }, [page])

  useEffect(() => { document.title = page === 'Home' ? 'TACTUSBALL — Read the game' : `TACTUSBALL — ${page}` }, [page])

  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { setLoginOpen(false); setCopilotOpen(false) } }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [])

  useEffect(() => {
    if (page !== 'Home' || motionOff || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let frame = 0
    const points = [[0,.38],[.17,.67],[.36,.28],[.56,.63],[.76,.34],[1,.58]]
    const update = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight)
        const progress = Math.min(1, Math.max(0, window.scrollY / maxScroll))
        let segment = points.findIndex((_, index) => index < points.length - 1 && progress <= points[index + 1][0])
        if (segment < 0) segment = points.length - 2
        const start = points[segment]
        const end = points[segment + 1]
        const amount = Math.min(1, Math.max(0, (progress - start[0]) / Math.max(.001, end[0] - start[0])))
        const y = (start[1] + (end[1] - start[1]) * amount) * window.innerHeight
        if (orbitBallRef.current) orbitBallRef.current.style.top = `${Math.round(y)}px`
      })
    }
    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => { cancelAnimationFrame(frame); window.removeEventListener('scroll', update); window.removeEventListener('resize', update) }
  }, [page, motionOff])

  useEffect(() => {
    if (!introActive) return
    const timer = window.setTimeout(() => {
      sessionStorage.setItem('tactus_intro_seen', '1')
      setIntroActive(false)
    }, 3100)
    return () => window.clearTimeout(timer)
  }, [introActive])

  useEffect(() => {
    if (motionOff && introActive) {
      sessionStorage.setItem('tactus_intro_seen', '1')
      setIntroActive(false)
    }
  }, [motionOff, introActive])

  useEffect(() => {
    request<{status?: string}>('/health').then(() => setHealth('online')).catch(() => setHealth('offline'))
  }, [])

  useEffect(() => {
    if (!token) return
    setBusy(true); setError('')
    Promise.allSettled([
      request<Match[]>('/matches?limit=20', token),
      request<Memory[]>('/memory?limit=12', token),
      request<Replay[]>('/memory/decisions/replay?limit=12', token),
      request('/auth/me', token),
    ]).then(results => {
      if (results[0].status === 'fulfilled') setMatches(results[0].value)
      else setError(`Match library: ${results[0].reason instanceof Error ? results[0].reason.message : 'unavailable'}`)
      if (results[1].status === 'fulfilled') setMemories(results[1].value)
      if (results[2].status === 'fulfilled') setReplays(results[2].value)
      if (results[3].status === 'rejected') signOut()
    }).finally(() => setBusy(false))
  }, [token])

  useEffect(() => {
    if (!token || (page !== 'Tactical intelligence' && page !== 'Video analysis')) return
    const id = eventsMatch || matches[0]?.id || ''
    if (!id) { setEvents([]); setEventsState('idle'); return }
    setEventsState('loading')
    request<EventItem[]>(`/matches/${encodeURIComponent(id)}/events?limit=50`, token)
      .then(value => { setEvents(value); setEventsState(value.length ? 'ready' : 'empty') })
      .catch(e => { setEvents([]); setEventsState('idle'); setError(`Match events: ${e instanceof Error ? e.message : 'unavailable'}`) })
  }, [eventsMatch, page, token, matches])

  useEffect(() => {
    if (!token || (page !== 'Club & squad' && page !== 'Player intelligence' && page !== 'Counterfactual lab')) return
    if (players.length || teams.length || rosterState === 'loading') return
    setRosterState('loading')
    Promise.allSettled([request<Player[]>('/players', token), request<Team[]>('/teams', token)]).then(results => {
      if (results[0].status === 'fulfilled') setPlayers(results[0].value)
      else setError(`Squad: ${results[0].reason instanceof Error ? results[0].reason.message : 'unavailable'}`)
      if (results[1].status === 'fulfilled') setTeams(results[1].value)
      setRosterState('ready')
    })
  }, [page, token, players.length, teams.length, rosterState])

  function signOut() { setToken(''); localStorage.removeItem('tactus_token'); setPage('Home'); location.hash = '' }
  function toggleMotion() { const next = !motionOff; setMotionOff(next); localStorage.setItem('tactus_motion', next ? 'off' : 'on') }
  async function login(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const result = await request<{access_token:string}>(registerMode?'/auth/register':'/auth/login', undefined, { method: 'POST', body: JSON.stringify(registerMode ? { email, password, full_name: fullName } : { email, password }) })
      localStorage.setItem('tactus_token', result.access_token); setToken(result.access_token); setLoginOpen(false); setPage('Command center'); location.hash = 'app'
    } catch (e) { setError(e instanceof Error ? e.message : 'Sign in failed') }
    finally { setBusy(false) }
  }
  async function askCopilot(event: React.FormEvent) {
    event.preventDefault(); if (!token || !copilotQuestion.trim()) return
    setBusy(true); setError(''); setCopilotAnswer(null); setCopilotStatus(null); setShowSetup(false)
    try { setCopilotAnswer(await request('/ai/copilot/query', token, { method: 'POST', body: JSON.stringify({ question: copilotQuestion }) })) }
    catch (e) {
      const message = e instanceof Error ? e.message : 'Copilot request failed'
      if (/not configured/i.test(message)) setCopilotStatus({ kind: 'unconfigured', message })
      else if (/access token|unauthorized|^401\b|session expired/i.test(message)) setCopilotStatus({ kind: 'session', message })
      else setCopilotStatus({ kind: 'failed', message })
    }
    finally { setBusy(false) }
  }
  async function uploadMatchVideo(event: React.FormEvent) {
    event.preventDefault(); if (!token || !uploadFile || !uploadMatch) return
    setBusy(true); setError(''); setUploadResult('')
    try {
      const response = await fetch(`${API}/matches/${encodeURIComponent(uploadMatch)}/videos`, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': uploadFile.type, 'X-Filename': uploadFile.name }, body: uploadFile })
      const data = await response.json().catch(() => null)
      if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `${response.status} ${response.statusText}`)
      if (!data || typeof data.original_filename !== 'string') throw new Error('Unexpected upload response from the server.')
      setUploadResult(`Video received: ${data.original_filename} · ${data.processing_status}. Configure pitch calibration before requesting vision processing.`); setUploadFile(null)
    } catch (e) { setError(e instanceof Error ? e.message : 'Video upload failed') }
    finally { setBusy(false) }
  }
  async function openReplay(id: string) {
    if (!token) { setLoginOpen(true); return }
    setBusy(true); setError('')
    try { setSelectedReplay(await request<ReplayDetail>(`/memory/decisions/replay/${encodeURIComponent(id)}`, token)) }
    catch (e) { setError(e instanceof Error ? e.message : 'Replay unavailable') }
    finally { setBusy(false) }
  }
  async function runSimulation(event: React.FormEvent) {
    event.preventDefault(); if (!token) { setLoginOpen(true); return }
    const matchId = cfMatch || matches[0]?.id || ''
    if (!matchId || !cfOut.trim() || !cfIn.trim()) { setError('Choose a match and enter both player IDs for the hypothetical change.'); return }
    setBusy(true); setError(''); setCfResult(null); setEvalResult(null)
    try {
      setCfResult(await request<SimResult>('/counterfactual/simulate', token, { method: 'POST', body: JSON.stringify({ scenario_id: newUuid(), match_id: matchId, baseline_formation: cfBase, counterfactual_formation: cfAlt, changes: [{ out_player_id: cfOut.trim(), in_player_id: cfIn.trim() }] }) }))
    } catch (e) { setError(e instanceof Error ? e.message : 'Simulation failed') }
    finally { setBusy(false) }
  }
  async function runEvaluation(event: React.FormEvent) {
    event.preventDefault(); if (!token) { setLoginOpen(true); return }
    const actual: Record<string, number> = {}
    for (const line of evalSpec.split('\n')) {
      const trimmed = line.trim()
      if (!trimmed) continue
      const eq = trimmed.indexOf('=')
      if (eq < 0) { setError(`Ground truth line "${trimmed}" needs name=value format.`); return }
      const value = Number(trimmed.slice(eq + 1).trim())
      if (!Number.isFinite(value)) { setError(`Ground truth value for "${trimmed.slice(0, eq).trim()}" must be numeric.`); return }
      actual[trimmed.slice(0, eq).trim()] = value
    }
    const names = Object.keys(actual)
    if (!cfResult || !names.length) { setError('Run a simulation first, then supply at least one ground-truth metric as name=value.'); return }
    setBusy(true); setError(''); setEvalResult(null)
    try {
      setEvalResult(await request<EvalResult>('/counterfactual/evaluate', token, { method: 'POST', body: JSON.stringify({ scenario_id: cfResult.scenario_id, match_id: cfResult.match_id, expected_metrics: names, actual_metrics: actual }) }))
    } catch (e) { setError(e instanceof Error ? e.message : 'Evaluation failed') }
    finally { setBusy(false) }
  }

  const features = [
    { number: '01', title: 'MATCH VIDEO ANALYSIS', summary: 'Bring footage into the match workspace.', detail: 'Upload video against an authorized match record. Vision processing requires pitch calibration and an available detector; upload completion is shown separately from analysis.', image: '/images/feature-match-video.jpg', page: 'Video analysis' },
    { number: '02', title: 'TACTICAL INTELLIGENCE', summary: 'Trace the patterns behind a phase of play.', detail: 'Review available match events and evidence. Tactical model foundations are untrained, so the interface never presents them as validated football intelligence.', image: '/images/feature-tactics.jpg', page: 'Tactical intelligence' },
    { number: '03', title: 'COUNTERFACTUAL LAB', summary: 'Compare a proposed change with its baseline.', detail: 'Submit a supported hypothetical scenario and inspect structural differences, unavailable metrics and warnings. Results are advisory, not predictions.', image: '/images/feature-counterfactual.jpg', page: 'Counterfactual lab' },
    { number: '04', title: 'CLUB MEMORY', summary: 'Keep context with its provenance.', detail: 'Browse memories through governed endpoints. Source, sensitivity and retention rules stay attached, and restricted records remain hidden.', image: '/images/feature-memory.jpg', page: 'Club memory' },
    { number: '05', title: 'DECISION REPLAY', summary: 'Reconstruct what was known at decision time.', detail: 'Review the recorded human decision, any AI recommendation, decision-time evidence and later outcomes as separate timeline events.', image: '/images/feature-decision-replay.jpg', page: 'Decision replay' },
    { number: '06', title: 'AI COPILOT', summary: 'Follow answers back to their evidence.', detail: 'Ask Muse a question and inspect actual tool use, grounding, warnings and citations. If the club has no provider configured, the backend reports that directly.', image: '/images/feature-muse.jpg', page: 'AI Copilot' },
  ]

  function openFeatureWorkspace() {
    const feature = features[selectedFeature]
    setPage(feature.page)
    location.hash = 'app'
    if (!token) setLoginOpen(true)
  }

  function selectFeaturePreview(index: number) {
    setSelectedFeature(index)
    if (window.matchMedia('(max-width: 700px)').matches) {
      window.setTimeout(() => document.querySelector('.feature-preview')?.scrollIntoView({ behavior: motionOff ? 'auto' : 'smooth', block: 'nearest' }), 0)
    }
  }

  function copilotForm(autoFocus: boolean, label: string) {
    return (<form className="copilot-form" onSubmit={askCopilot}><textarea autoFocus={autoFocus} value={copilotQuestion} onChange={e=>setCopilotQuestion(e.target.value)} placeholder="Ask about club memory or match evidence…" maxLength={2000}/><button disabled={busy||!copilotQuestion.trim()} aria-label={label}>{busy?'…':'↑'}</button></form>)
  }
  function copilotStatusBlock() {
    return (<>
      {busy&&!copilotAnswer&&!copilotStatus&&<p className="empty-state">Checking the available evidence…</p>}
      {copilotStatus?.kind==='unconfigured'&&<div className="copilot-status" role="status"><span className="status-dot"/><span>Copilot provider not configured</span><button type="button" className="small-link" onClick={()=>setShowSetup(!showSetup)} aria-expanded={showSetup}>{showSetup?'Hide setup':'View setup'}</button></div>}
      {showSetup&&copilotStatus?.kind==='unconfigured'&&<div className="setup-panel" role="note"><b>Enable Muse in three steps</b><span>1 · A club administrator sets <code>COPILOT_API_KEY</code> in the backend <code>.env</code> — a key for any OpenAI-compatible chat endpoint.</span><span>2 · Optionally set <code>COPILOT_MODEL</code> and <code>COPILOT_BASE_URL</code>; the defaults target the public OpenAI endpoint.</span><span>3 · Restart the backend and ask again. Keys stay server-side — never in the browser.</span></div>}
      {copilotStatus?.kind==='session'&&<p className="copilot-request-error" role="alert">Your session expired. <button type="button" className="small-link" onClick={()=>{setCopilotStatus(null);setLoginOpen(true)}}>Sign in again</button></p>}
      {copilotStatus?.kind==='failed'&&<p className="copilot-request-error" role="alert">Copilot request failed: {copilotStatus.message}. Check the backend connection and try again.</p>}
      {copilotAnswer&&<div className="answer"><span className={copilotAnswer.grounded?'grounded':'ungrounded'}>{copilotAnswer.grounded?'GROUNDED ANSWER':'NOT GROUNDED'}</span><p>{copilotAnswer.answer}</p><small>{copilotAnswer.model} · {copilotAnswer.citations.length} citations</small>{copilotAnswer.citations.map((c,i)=><small key={i}>Source: {c.source_type} · {c.source_id}</small>)}{copilotAnswer.warnings.map((w,i)=><small key={i}>{w}</small>)}</div>}
    </>)
  }
  return <div className={motionOff ? 'app motion-off' : 'app'}>
    {page === 'Home' ? <>
      {introActive && <div className="kick-intro" role="status" aria-label="TACTUSBALL cinematic introduction"><div className="kick-stadium"/><div className="kick-copy"><span className="kick-wordmark">TACTUS<span>BALL</span></span><span className="kick-tagline">SEE THE GAME. CHANGE IT.</span></div><div className="kick-scene" aria-hidden="true"><div className="kick-goal"><i/><i/><i/><i/><i/><i/><i/><i/></div><svg className="kick-player" viewBox="0 0 410 520"><defs><linearGradient id="kit" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#d9dfc4"/><stop offset="1" stopColor="#626b51"/></linearGradient></defs><circle cx="175" cy="83" r="38" fill="#171a15"/><path fill="url(#kit)" d="M145 120 Q181 105 211 126 L249 219 224 306 182 292 156 232 128 301 83 281 112 199Z"/><path fill="#171a15" d="M152 285 218 295 206 382 143 397 122 362Z"/><path className="kick-leg plant-leg" fill="#d6d7ce" d="m137 371 56 8-34 100-19 12-11-12 10-72-31-19Z"/><path className="kick-leg strike-leg" fill="#d9dfc4" d="m197 293 33 17 37 79 74 29 12 16-13 13-102-25-26-14-47-81Z"/><path fill="#d9dfc4" d="m329 408 46 4 12 14-8 12-44-4-18-11Z"/></svg><div className="kick-ball"><span/></div><div className="kick-impact"/></div><button className="skip-intro" onClick={()=>{sessionStorage.setItem('tactus_intro_seen','1');setIntroActive(false)}}>Skip intro <span>↗</span></button><span className="intro-sound-note">A MOMENT BEFORE THE GAME OPENS</span></div>}
      <header className="public-nav"><a className="brand" href="#top"><img className="brand-mark" src="/tactusball-mark.svg" alt=""/>TACTUS<span className="brand-light">BALL</span></a><nav><a href="#system">The system</a><a href="#patterns">Read the game</a><button className="nav-cta" onClick={() => token ? (setPage('Command center'), location.hash = 'app') : setLoginOpen(true)}>Enter platform <span>↗</span></button></nav></header>
      <main id="top">
        <section className="hero" aria-label="TACTUSBALL introduction">
          <div className="hero-backdrop" /><div className="hero-grid" />
          <div className="hero-copy"><p className="eyebrow"><span className="live-dot" /> THE FOOTBALL INTELLIGENCE PLATFORM</p><h1>SEE THE<br/><em>GAME.</em><br/>CHANGE IT.</h1><div className="hero-bottom"><p>Turn match evidence into<br/>better football decisions.</p><div className="hero-actions"><a className="explore-link" href="#story">Explore TACTUSBALL <span>↘</span></a><button className="round-link" onClick={()=>token?(setPage('Command center'),location.hash='app'):setLoginOpen(true)} aria-label={token?'Enter workspace':'Sign in'}>↗</button></div></div></div>
          <div className="hero-rail"><span>AN EVIDENCE-LED CLUB OPERATING SYSTEM</span><span>SCROLL TO EXPLORE&nbsp; ↓</span></div>
        </section>
        <section className="intro editorial" id="story"><div className="section-kicker reveal">A DIFFERENT VIEW OF THE GAME <span>— 01</span></div><div className="intro-layout"><h2 className="reveal">THE GAME<br/>HAS ANOTHER<br/><i>LAYER.</i></h2><div className="intro-aside reveal"><p>Football is played in moments. Better decisions come from seeing how those moments connect.</p><p className="muted">TACTUSBALL brings match evidence, tactical context and club knowledge into one considered workspace.</p><a className="text-link" href="#system">Explore the system <span>↘</span></a></div></div><div className="stadium-strip reveal"><div className="strip-overlay"/><div className="strip-topline"><span>THE FULL MATCH, IN CONTEXT</span><span className="strip-live"><i/> ILLUSTRATIVE VIEW</span></div><div className="strip-play" aria-hidden="true"><svg viewBox="0 0 1000 320" preserveAspectRatio="none"><path d="M70 240 C230 240 230 105 390 130 S600 245 760 125 900 105 950 76"/><circle r="8"><animateMotion dur="7s" repeatCount="indefinite" path="M70 240 C230 240 230 105 390 130 S600 245 760 125 900 105 950 76"/></circle></svg><span className="strip-moment moment-one">01 <b>OBSERVE</b></span><span className="strip-moment moment-two">02 <b>CONNECT</b></span><span className="strip-moment moment-three">03 <b>DECIDE</b></span></div><div className="strip-bottom"><span>FROM FIRST TOUCH</span><div className="strip-timeline"><i/></div><span>TO THE BIG PICTURE</span></div><div className="strip-number">90<span>′</span></div></div></section>
        <section className="patterns" id="patterns"><div className="section-kicker reveal">SEE THE PATTERNS <span>— 02</span></div><div className="patterns-heading"><h2 className="reveal">SPACE TELLS<br/><i>A STORY.</i></h2><div className="sample-tag">ILLUSTRATIVE EXAMPLE<br/>NOT MATCH TRACKING DATA</div></div><div className="pitch-wrap reveal"><div className="pitch"><div className="pitch-topline"><span>SEQUENCE 01 <b>·</b> PRESS BREAK</span><span className="sequence-status"><i/> PLAYING</span></div><div className="pitch-line halfway"/><div className="pitch-circle"/><div className="pitch-box left-box"/><div className="pitch-box right-box"/><svg viewBox="0 0 1000 420" preserveAspectRatio="none" aria-hidden="true"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="none" stroke="#e9fb70" strokeWidth="1.5"/></marker></defs><path className="pass-line" d="M180 276 Q330 95 470 203 T774 142" markerEnd="url(#arrow)"/><path className="run-line" d="M225 120 Q450 370 740 270"/><g id="moving-ball" className="moving-ball"><circle r="10"/><circle className="ball-glow" r="18"/><animateMotion dur="5.8s" repeatCount="indefinite" path="M180 276 Q330 95 470 203 T774 142"/></g></svg>{[[18,66,'a'],[28,29,'a'],[37,62,'a'],[48,49,'a'],[58,28,'a'],[63,70,'a'],[78,35,'a'],[85,62,'a'],[25,46,'b'],[40,24,'b'],[52,76,'b'],[69,54,'b'],[83,25,'b']].map(([x,y,c],i)=><span key={i} className={`player-dot team-${c}`} style={{left:`${x}%`,top:`${y}%`}}/>)}<div className="pitch-legend"><span><i className="legend-a"/> HOME</span><span><i className="legend-b"/> OPPONENT</span><span><i className="legend-line"/> PASSING LANE</span></div><div className="pitch-progress"><span>BUILD</span><i><b/></i><span>BREAK LINE</span><i><b/></i><span>ADVANCE</span></div></div></div><div className="pattern-note"><span>01 / PRESS BREAK</span><span>Illustrative sequence. No live or verified tracking is displayed.</span></div></section>
        <section className="system" id="system"><div className="section-kicker reveal">THE INTELLIGENCE SYSTEM <span>— 03</span></div><div className="system-head"><h2 className="reveal">EVERY DETAIL.<br/><i>IN ITS PLACE.</i></h2><p className="reveal">A connected view from the touchline to the boardroom. Built around evidence, provenance and human judgment.</p></div><div className="feature-explorer"><div className="feature-list" aria-label="TACTUSBALL capabilities">{features.map((feature,index)=><button type="button" key={feature.number} className={`feature-row reveal ${selectedFeature===index?'selected':''}`} aria-pressed={selectedFeature===index} onClick={()=>selectFeaturePreview(index)}><span className="feature-num">{feature.number}</span><span className="feature-title">{feature.title}</span><span className="feature-copy">{feature.summary}</span><span className="feature-arrow">↗</span></button>)}</div><article className="feature-preview" aria-live="polite" key={features[selectedFeature].number}><img src={features[selectedFeature].image} alt="" loading="lazy" decoding="async"/><div className="feature-preview-shade"/><span className="feature-preview-index">{features[selectedFeature].number} / CAPABILITY</span><div className="feature-preview-copy"><span className="feature-preview-label">{features[selectedFeature].title}</span><p>{features[selectedFeature].detail}</p><button type="button" className="preview-action" onClick={openFeatureWorkspace}>EXPLORE THIS WORKSPACE <span>↗</span></button></div></article></div></section>
        <section className="orbit"><div className="orbit-copy reveal"><div className="section-kicker">THE INTELLIGENCE ORBIT <span>— 04</span></div><h2>ASK A BETTER<br/><i>QUESTION.</i></h2><p>Meet Muse. One question opens a path through governed club memory and match evidence. Follow the sources. Keep the decision human.</p><button className="light-button" onClick={()=>token?setCopilotOpen(true):setLoginOpen(true)}>Ask Muse <span>↗</span></button></div><div className="orbit-graphic" aria-hidden="true"><div className="orbit-ring ring-one"/><div className="orbit-ring ring-two"/><div className="orbit-ring ring-three"/><svg className="orbit-route" viewBox="0 0 500 400" preserveAspectRatio="none"><path d="M70 108 C134 6 270 22 341 107 S382 300 265 325 88 275 115 199 301 145 402 218"/><path d="M90 130 C170 65 229 79 281 133"/></svg><div className="orbit-ball">M</div><span className="orbit-flight-ball"><i/></span><span className="orbit-node n1">QUESTION</span><span className="orbit-node n2">EVIDENCE</span><span className="orbit-node n3">CONTEXT</span><span className="orbit-node n4">HUMAN DECISION</span></div></section>
        <section className="closing"><div className="section-kicker reveal">YOUR CLUB. THE WHOLE PICTURE. <span>— 05</span></div><h2 className="reveal">ENTER<br/><i>TACTUSBALL.</i></h2><button className="closing-link" onClick={()=>token?(setPage('Command center'),location.hash='app'):setLoginOpen(true)}>Enter the platform <span>↗</span></button><div className="closing-mark">T</div></section>
      </main>
      <footer className="footer"><a className="brand" href="#top"><img className="brand-mark" src="/tactusball-mark.svg" alt=""/>TACTUS<span className="brand-light">BALL</span></a><span>FOOTBALL INTELLIGENCE, IN CONTEXT.</span><button type="button" role="switch" aria-checked={!motionOff} className="tact-switch" onClick={toggleMotion}><span className="tact-track"><span className="tact-thumb"/></span><span>Motion {motionOff?'off':'on'}</span></button><span>© TACTUSBALL</span></footer>
      <span ref={orbitBallRef} className="orbit-track-ball" aria-hidden="true"><i/></span><button className="orbit-launcher" aria-label="Ask Muse" title="Ask Muse" onClick={()=>token?setCopilotOpen(true):setLoginOpen(true)}><span className="launcher-ball"><i/></span><span className="launcher-label">ASK MUSE</span></button>
      {copilotOpen&&<div className="copilot-modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setCopilotOpen(false)}}><section className="copilot-modal" aria-label="Muse AI Copilot"><div className="copilot-modal-head"><span className="launcher-ball"><i/></span><div><span className="card-kicker">TACTUSBALL · MUSE</span><h2>Ask Muse.</h2></div><button onClick={()=>setCopilotOpen(false)} aria-label="Close Muse">×</button></div><p className="copilot-modal-note">Answers use available, governed club evidence. The ball is an interface element, not match tracking data.</p>{copilotForm(true, 'Submit question')}{copilotStatusBlock()}<div className="copilot-modal-foot">Recommendations support people. Decisions remain human.</div></section></div>}
    </> : <div className="workspace"><aside className={`side-nav ${navOpen?'open':''}`}><a className="brand" href="#" onClick={e=>{e.preventDefault();setPage('Home');location.hash=''}}><img className="brand-mark" src="/tactusball-mark.svg" alt=""/>TACTUS<span className="brand-light">BALL</span></a><div className="club-switch"><span className="club-emblem">N</span><span>TACTUSBALL<small>FIRST TEAM</small></span><span className="chevron">⌄</span></div><p className="nav-label">WORKSPACE</p>{['Command center','Club & squad','Player intelligence','Match library','Video analysis','Tactical intelligence','Counterfactual lab','Club memory','Decision replay','AI Copilot'].map((item,i)=><button key={item} className={`side-link ${page===item?'active':''}`} onClick={()=>{setPage(item);setNavOpen(false)}}><span className="side-icon">{['◫','♧','◉','▤','▷','⌘','⇄','◈','↺','✳'][i]}</span>{item}<span className="side-chevron">›</span></button>)}<div className="side-bottom"><span className="api-status"><i className={`status-dot ${health}`}/>{health==='online'?'API connected':health==='offline'?'API unavailable':'Checking API'}</span><button className="side-link" onClick={toggleMotion}>◌&nbsp;&nbsp; Motion {motionOff?'off':'on'}</button><button className="user-row" onClick={()=>{token?signOut():setLoginOpen(true)}}><span className="avatar">{token?'A':'?'}</span><span>{token?'Analyst':'Sign in'}<small>{token?'Sign out':'Access workspace'}</small></span><span className="side-chevron">↗</span></button></div></aside>
      <div className="workspace-main"><header className="workspace-top"><button className="mobile-menu" onClick={()=>setNavOpen(!navOpen)}>☰</button><div className="crumb">TACTUSBALL <span>/</span> {page.toUpperCase()}</div><div className="top-actions"><span className="today">{new Intl.DateTimeFormat('en-GB',{weekday:'short',day:'2-digit',month:'short'}).format(new Date()).toUpperCase()}</span><button className="icon-button" aria-label="Notifications">♧</button><span className="avatar">A</span></div></header>
      <main className="dashboard" key={page}><div className="dashboard-title"><div><p className="eyebrow dark-eyebrow"><span className="live-dot"/> THE TOUCHLINE, IN VIEW</p><h1>{page}</h1><p className="dashboard-subtitle">Your club, connected to the moments that matter.</p></div><button className="dark-button" onClick={()=>{setPage('Match library');setError('')}}>Open match library <span>↗</span></button></div>
      {error&&<div className="notice"><span>{error}</span><button onClick={()=>setError('')}>×</button></div>}
      {page==='Command center'&&<div className="dash-grid"><section className="dash-card matches-card"><div className="card-heading"><div><span className="card-kicker">MATCH LIBRARY</span><h2>Recent matches</h2></div><button className="small-link" onClick={()=>setPage('Match library')}>View all ↗</button></div>{busy&&!matches.length?<p className="empty-state">Loading match records…</p>:matches.length?<div className="match-list">{matches.slice(0,5).map(match=><div className="match-item" key={match.id}><span className="match-date">{new Date(match.scheduled_at).toLocaleDateString('en-GB',{day:'2-digit',month:'short'})}<small>{match.status}</small></span><span className="match-teams"><b>{match.home_away==='HOME'?'TACTUSBALL':'OPPONENT'}</b><small>vs</small><b>{match.home_away==='HOME'?'OPPONENT':'TACTUSBALL'}</b></span><span className="score">{match.home_score??'–'} <i>:</i> {match.away_score??'–'}</span><span className="match-arrow">↗</span></div>)}</div>:<div className="empty-state"><span className="empty-symbol">▤</span><b>No match records yet</b><span>Matches from your authenticated club account will appear here.</span></div>}</section>
      <section className="dash-card copilot-card"><div className="card-heading"><div><span className="card-kicker">GOVERNED AI</span><h2>Ask the Copilot</h2></div><span className="copilot-mark">✳</span></div><p>Questions are answered using available tools and governed evidence. The model provider must be configured by your club.</p>{copilotForm(false, 'Ask Copilot')}{copilotStatusBlock()}<div className="suggestion">Try: <button onClick={()=>setCopilotQuestion('What evidence is available in Club Memory?')}>What evidence is available in Club Memory?</button></div></section>
      <section className="dash-card memory-card"><div className="card-heading"><div><span className="card-kicker">GOVERNED KNOWLEDGE</span><h2>Club memory</h2></div><button className="small-link" onClick={()=>setPage('Club memory')}>Browse ↗</button></div>{memories.length?memories.slice(0,3).map(m=><article className="memory-item" key={m.id}><span className="memory-type">{m.memory_type.replaceAll('_',' ')}</span><h3>{m.title}</h3><p>{m.summary}</p><small>{new Date(m.occurred_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})} · {m.confidence===null?'Confidence unknown':`${Math.round(m.confidence*100)}% recorded confidence`}</small></article>):<div className="empty-state slim"><b>No visible memory records</b><span>Governance filters what this account can access.</span></div>}</section>
      <section className="dash-card replay-card"><div className="card-heading"><div><span className="card-kicker">DECISION HISTORY</span><h2>Decision replay</h2></div><button className="small-link" onClick={()=>setPage('Decision replay')}>Review ↗</button></div>{replays.length?replays.slice(0,3).map(r=><article className="replay-item" key={r.id}><div className="replay-timeline"><i/></div><div><span className="memory-type">{r.decision_type.replaceAll('_',' ')} · {new Date(r.decision_at).toLocaleDateString('en-GB',{day:'numeric',month:'short'})}</span><p>{r.ai_recommendation_text||'No AI recommendation recorded'}</p><small>Human decision: {r.human_decision?.replaceAll('_',' ')||'not recorded'}</small></div></article>):<div className="empty-state slim"><b>No replay records yet</b><span>Decision-time evidence remains distinct from later outcomes.</span></div>}</section></div>}
      {page==='Command center'&&<section className="dash-card upload-card"><div className="card-heading"><div><span className="card-kicker">VIDEO INGESTION</span><h2>Add match footage</h2></div><span className="copilot-mark">▷</span></div><p>Upload is available to authorized match managers. Processing requires a configured detector and pitch calibration.</p><form className="upload-form" onSubmit={uploadMatchVideo}><label>Match<select required value={uploadMatch} onChange={e=>setUploadMatch(e.target.value)}><option value="">Choose a match</option>{matches.map(m=><option key={m.id} value={m.id}>{new Date(m.scheduled_at).toLocaleDateString('en-GB')} · {m.status} · {m.id.slice(0,8)}</option>)}</select></label><label className="file-pick">{uploadFile?uploadFile.name:'Choose video file'}<input type="file" accept="video/*" required onChange={e=>setUploadFile(e.target.files?.[0]||null)}/></label><button className="dark-button" disabled={busy||!uploadFile||!uploadMatch}>{busy?'Uploading…':'Upload video'} <span>↑</span></button></form>{uploadResult&&<p className="upload-result">{uploadResult}</p>}</section>}
      {page==='Match library'&&<section className="dash-card"><div className="card-heading"><div><span className="card-kicker">MATCH LIBRARY</span><h2>All matches</h2></div><span className="count-pill">{matches.length} records</span></div>{busy&&!matches.length?<p className="empty-state">Loading match records…</p>:matches.length?<div className="match-list">{matches.map(match=><div className="match-item" key={match.id}><span className="match-date">{new Date(match.scheduled_at).toLocaleDateString('en-GB',{day:'2-digit',month:'short'})}<small>{match.status}</small></span><span className="match-teams"><b>{match.home_away==='HOME'?'TACTUSBALL':'OPPONENT'}</b><small>vs</small><b>{match.home_away==='HOME'?'OPPONENT':'TACTUSBALL'}</b></span><span className="score">{match.home_score??'–'} <i>:</i> {match.away_score??'–'}</span><span className="match-arrow">↗</span></div>)}</div>:<div className="empty-state"><span className="empty-symbol">▤</span><b>No match records yet</b><span>Matches from your authenticated club account will appear here.</span></div>}</section>}
      {page==='Video analysis'&&<section className="dash-card"><div className="card-heading"><div><span className="card-kicker">VIDEO INGESTION</span><h2>Add match footage</h2></div><span className="copilot-mark">▷</span></div><p>Upload is available to authorized match managers. Processing requires a configured detector and pitch calibration. Upload completion is reported separately from analysis.</p><form className="upload-form" onSubmit={uploadMatchVideo}><label>Match<select required value={uploadMatch} onChange={e=>setUploadMatch(e.target.value)}><option value="">Choose a match</option>{matches.map(m=><option key={m.id} value={m.id}>{new Date(m.scheduled_at).toLocaleDateString('en-GB')} · {m.status} · {m.id.slice(0,8)}</option>)}</select></label><label className="file-pick">{uploadFile?uploadFile.name:'Choose video file'}<input type="file" accept="video/*" required onChange={e=>setUploadFile(e.target.files?.[0]||null)}/></label><button className="dark-button" disabled={busy||!uploadFile||!uploadMatch}>{busy?'Uploading…':'Upload video'} <span>↑</span></button></form>{uploadResult&&<p className="upload-result">{uploadResult}</p>}</section>}
      {page==='Tactical intelligence'&&<section className="dash-card"><div className="card-heading"><div><span className="card-kicker">TACTICAL INTELLIGENCE</span><h2>Recorded match events</h2></div></div><p>Events come from the match record, not from model inference. Tactical model foundations are untrained, so nothing here is presented as validated football intelligence.</p><label className="field-label">Match<select value={eventsMatch||matches[0]?.id||''} onChange={e=>setEventsMatch(e.target.value)}>{matches.map(m=><option key={m.id} value={m.id}>{new Date(m.scheduled_at).toLocaleDateString('en-GB')} · {m.status} · {m.id.slice(0,8)}</option>)}</select></label>{eventsState==='loading'&&<p className="empty-state">Loading events…</p>}{eventsState==='empty'&&<div className="empty-state"><b>No recorded events</b><span>This match has no recorded events yet.</span></div>}{eventsState==='ready'&&<div className="match-list">{events.map(ev=><div className="match-item" key={ev.id}><span className="match-date">{ev.minute}′<small>{ev.side}</small></span><span className="match-teams"><b>{ev.event_type.replaceAll('_',' ')}</b>{ev.description&&<small>{ev.description}</small>}</span><span className="score">·</span><span className="match-arrow">·</span></div>)}</div>}{eventsState==='idle'&&<div className="empty-state"><b>Select a match</b><span>Choose a match to load its recorded events.</span></div>}</section>}
      {page==='Counterfactual lab'&&<><section className="dash-card"><div className="card-heading"><div><span className="card-kicker">COUNTERFACTUAL LAB</span><h2>Propose a change</h2></div></div><p>Compare a supported hypothetical scenario against its baseline. Results are structural observations with explicit unavailable metrics — never predictions.</p><form className="lab-form" onSubmit={runSimulation}><label>Match<select value={cfMatch||matches[0]?.id||''} onChange={e=>setCfMatch(e.target.value)}><option value="">Choose a match</option>{matches.map(m=><option key={m.id} value={m.id}>{new Date(m.scheduled_at).toLocaleDateString('en-GB')} · {m.status} · {m.id.slice(0,8)}</option>)}</select></label><label>Baseline formation<select value={cfBase} onChange={e=>setCfBase(e.target.value)}>{FORMATIONS.map(f=><option key={f} value={f}>{f}</option>)}</select></label><label>Counterfactual formation<select value={cfAlt} onChange={e=>setCfAlt(e.target.value)}>{FORMATIONS.map(f=><option key={f} value={f}>{f}</option>)}</select></label><label>Player out (ID)<input value={cfOut} onChange={e=>setCfOut(e.target.value)} placeholder="UUID of outgoing player" list="squad-ids" required/></label><label>Player in (ID)<input value={cfIn} onChange={e=>setCfIn(e.target.value)} placeholder="UUID of incoming player" list="squad-ids" required/></label><datalist id="squad-ids">{players.map(p=><option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</datalist><button className="dark-button" disabled={busy}>{busy?'Running…':'Run simulation'} <span>↗</span></button></form>{cfResult&&<div className="lab-result"><p className="result-status">Simulator: <b>{cfResult.simulator_status}</b> · {cfResult.baseline_formation} → {cfResult.counterfactual_formation}</p>{cfResult.metrics.length?<table className="metric-table"><thead><tr><th>Metric</th><th>Baseline</th><th>Counterfactual</th><th>Δ</th></tr></thead><tbody>{cfResult.metrics.map(m=><tr key={m.name}><td>{m.name.replaceAll('_',' ')}</td><td>{m.baseline_value===null?'unknown':m.baseline_value}</td><td>{m.counterfactual_value===null?'unknown':m.counterfactual_value}</td><td>{m.delta===null?'unknown':(m.delta>0?'+':'')+m.delta}</td></tr>)}</tbody></table>:<p className="empty-state">No computable metrics for this scenario.</p>}{cfResult.unavailable_reasons.map((r,i)=><p className="field-note" key={i}>Unavailable: {r}</p>)}{cfResult.assumptions.map((a,i)=><p className="field-note" key={'a'+i}>Assumption: {a}</p>)}{cfResult.warnings.map((w,i)=><p className="field-note warn" key={'w'+i}>Warning: {w}</p>)}</div>}</section><section className="dash-card"><div className="card-heading"><div><span className="card-kicker">GROUND-TRUTH EVALUATION</span><h2>Evaluate the result</h2></div></div><p>Supply observed ground-truth metrics as one <code>name=value</code> pair per line. Without ground truth the lab reports insufficient evidence — never a score.</p><form className="lab-form" onSubmit={runEvaluation}><label>Ground truth<textarea value={evalSpec} onChange={e=>setEvalSpec(e.target.value)} rows={4} placeholder={'total_player_count = 7'}/></label><button className="dark-button" disabled={busy||!cfResult}>{busy?'Evaluating…':'Evaluate result'} <span>↗</span></button></form>{evalResult&&<div className="lab-result"><p className="result-status">Evaluation: <b>{evalResult.evaluation_status.replaceAll('_',' ')}</b> · method {evalResult.evaluation_method} · {evalResult.sample_count} samples</p>{evalResult.metrics.length?<table className="metric-table"><thead><tr><th>Metric</th><th>Expected</th><th>Actual</th><th>Error</th></tr></thead><tbody>{evalResult.metrics.map(m=><tr key={m.name}><td>{m.name.replaceAll('_',' ')}</td><td>{m.expected===null?'unknown':m.expected}</td><td>{m.actual===null?'unknown':m.actual}</td><td>{m.error===null?'unknown':m.error}</td></tr>)}</tbody></table>:<p className="empty-state">No metrics could be computed from the supplied evidence.</p>}{evalResult.warnings.map((w,i)=><p className="field-note warn" key={i}>{w}</p>)}{evalResult.provenance.length?<p className="field-note">Provenance: {evalResult.provenance.join(' · ')}</p>:null}</div>}</section></>}
      {page==='Club memory'&&<section className="dash-card"><div className="card-heading"><div><span className="card-kicker">GOVERNED KNOWLEDGE</span><h2>Club memory</h2></div><span className="count-pill">{memories.length} visible</span></div><label className="field-label">Filter<input value={memoryFilter} onChange={e=>setMemoryFilter(e.target.value)} placeholder="Filter by title, summary or type…"/></label>{memories.filter(m=>{const q=memoryFilter.trim().toLowerCase();return !q||m.title.toLowerCase().includes(q)||m.summary.toLowerCase().includes(q)||m.memory_type.toLowerCase().includes(q)}).map(m=><article className="memory-item" key={m.id}><span className="memory-type">{m.memory_type.replaceAll('_',' ')}</span><h3>{m.title}</h3><p>{m.summary}</p><small>{new Date(m.occurred_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})} · {m.confidence===null?'Confidence unknown':`${Math.round(m.confidence*100)}% recorded confidence`}</small></article>)}{!memories.length&&<div className="empty-state slim"><b>No visible memory records</b><span>Governance filters what this account can access.</span></div>}</section>}
      {page==='Decision replay'&&<section className="dash-card"><div className="card-heading"><div><span className="card-kicker">DECISION HISTORY</span><h2>Decision replay</h2></div><span className="count-pill">{replays.length} records</span></div>{replays.length?<div className="replay-list">{replays.map(r=><button type="button" key={r.id} className={`replay-row${selectedReplay?.id===r.id?' selected':''}`} onClick={()=>openReplay(r.id)}><span className="memory-type">{r.decision_type.replaceAll('_',' ')} · {new Date(r.decision_at).toLocaleDateString('en-GB',{day:'numeric',month:'short'})}</span><span>{r.human_decision?.replaceAll('_',' ')||'decision not recorded'}</span></button>)}</div>:<div className="empty-state slim"><b>No replay records yet</b><span>Decision-time evidence remains distinct from later outcomes.</span></div>}{selectedReplay&&<div className="detail-panel"><div className="card-heading"><h3>Replay detail</h3><button className="small-link" onClick={()=>setSelectedReplay(null)}>Close ×</button></div><dl><div><dt>Decision</dt><dd>{selectedReplay.decision_type.replaceAll('_',' ')} · {new Date(selectedReplay.decision_at).toLocaleString('en-GB')}</dd></div><div><dt>AI recommendation</dt><dd>{selectedReplay.ai_recommendation_text||'No AI recommendation recorded'}{selectedReplay.ai_recommendation_at&&` · ${new Date(selectedReplay.ai_recommendation_at).toLocaleString('en-GB')}`}</dd></div><div><dt>Human decision</dt><dd>{selectedReplay.human_decision?.replaceAll('_',' ')||'not recorded'}{selectedReplay.human_decision_at&&` · ${new Date(selectedReplay.human_decision_at).toLocaleString('en-GB')}`}</dd></div><div><dt>Match</dt><dd>{selectedReplay.match_id||'no linked match'}</dd></div></dl></div>}</section>}
      {page==='AI Copilot'&&<section className="dash-card"><div className="card-heading"><div><span className="card-kicker">GOVERNED AI</span><h2>Ask the Copilot</h2></div><span className="copilot-mark">✳</span></div><p>Questions are answered using available tools and governed evidence. The model provider must be configured by your club. Recommendations support people — decisions remain human.</p>{copilotForm(false, 'Ask Copilot')}{copilotStatusBlock()}<div className="suggestion">Try: <button onClick={()=>setCopilotQuestion('What evidence is available in Club Memory?')}>What evidence is available in Club Memory?</button></div></section>}
      {page==='Club & squad'&&<section className="dash-card"><div className="card-heading"><div><span className="card-kicker">CLUB & SQUAD</span><h2>Teams and players</h2></div></div>{rosterState==='loading'&&<p className="empty-state">Loading squad records…</p>}{rosterState==='ready'&&<>{teams.length?<div className="match-list">{teams.map(t=><div className="match-item" key={t.id}><span className="match-date">{t.short_name}<small>{t.season}</small></span><span className="match-teams"><b>{t.name}</b></span><span className="score">·</span><span className="match-arrow">·</span></div>)}</div>:<div className="empty-state"><b>No teams yet</b><span>Teams from your authenticated club account will appear here.</span></div>}{players.length?<div className="match-list">{players.map(p=><div className="match-item" key={p.id}><span className="match-date">{p.preferred_position}<small>{p.status}</small></span><span className="match-teams"><b>{p.first_name} {p.last_name}</b>{p.secondary_position&&<small>also {p.secondary_position}</small>}</span><span className="score">·</span><span className="match-arrow">·</span></div>)}</div>:<div className="empty-state"><b>No players yet</b><span>Players from your authenticated club account will appear here.</span></div>}</>}</section>}
      {page==='Player intelligence'&&<section className="dash-card"><div className="card-heading"><div><span className="card-kicker">PLAYER INTELLIGENCE</span><h2>Player record</h2></div></div>{rosterState==='loading'&&<p className="empty-state">Loading squad records…</p>}{rosterState!=='loading'&&<><label className="field-label">Player<select value={selectedPlayer} onChange={e=>setSelectedPlayer(e.target.value)}><option value="">Choose a player</option>{players.map(p=><option key={p.id} value={p.id}>{p.first_name} {p.last_name} · {p.preferred_position}</option>)}</select></label>{(()=>{const p=players.find(x=>x.id===selectedPlayer);return p?<div className="detail-panel"><dl><div><dt>Name</dt><dd>{p.first_name} {p.last_name}</dd></div><div><dt>Preferred position</dt><dd>{p.preferred_position.replaceAll('_',' ')}</dd></div>{p.secondary_position&&<div><dt>Secondary position</dt><dd>{p.secondary_position.replaceAll('_',' ')}</dd></div>}<div><dt>Status</dt><dd>{p.status.replaceAll('_',' ')}</dd></div><div><dt>Record</dt><dd>{p.id}</dd></div></dl><p className="field-note">Performance, availability and wellness detail stays governed; this view shows the roster record only.</p></div>:<div className="empty-state"><b>No player selected</b><span>Choose a player to inspect the roster record.</span></div>})()}</>}</section>}
      <section className="dashboard-footer"><span>RECOMMENDATIONS SUPPORT PEOPLE. DECISIONS REMAIN HUMAN.</span><span>Evidence before certainty.</span></section>
      </main></div></div>}
    {loginOpen&&<div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setLoginOpen(false)}}><form className="login-modal" onSubmit={login} aria-label={registerMode?'Create a club account':'Sign in to TACTUSBALL'}><aside className="login-visual"><a className="login-brand" href="#top"><img src="/tactusball-mark.svg" alt=""/> TACTUS<span>BALL</span></a><div className="login-visual-copy"><span>FOOTBALL, IN CONTEXT</span><h2>See more.<br/><i>Decide well.</i></h2><p>Bring match evidence, tactical context and club knowledge into one considered workspace.</p></div><span className="login-visual-foot">EVIDENCE FIRST · PEOPLE DECIDE</span></aside><div className="login-fields"><button type="button" className="modal-close" onClick={()=>setLoginOpen(false)} aria-label="Close sign in">×</button><span className="card-kicker">{registerMode?'NEW CLUB ACCOUNT':'SECURE CLUB ACCESS'}</span><h3>{registerMode?'Join the club.':'Welcome back.'}</h3><p className="login-intro">{registerMode?'Create your account to access TACTUSBALL.':'Sign in with your club account to continue.'}</p>{registerMode&&<label>Full name<input type="text" autoComplete="name" required maxLength={120} value={fullName} onChange={e=>setFullName(e.target.value)}/></label>}<label>Email address<input type="email" autoComplete="username" required autoFocus value={email} onChange={e=>setEmail(e.target.value)}/></label><label>Password<span className="password-control"><input type={showPassword?'text':'password'} autoComplete={registerMode?'new-password':'current-password'} required minLength={registerMode?12:undefined} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} aria-describedby={registerMode?'password-guidance':undefined}/><button type="button" onClick={()=>setShowPassword(!showPassword)} aria-label={showPassword?'Hide password':'Show password'}>{showPassword?'HIDE':'SHOW'}</button></span></label>{registerMode&&<small className="password-guidance" id="password-guidance">Use 12–128 characters. Save your password securely; it can’t be recovered from the server.</small>}{error&&<p className="login-error" role="alert">{error}</p>}<button className="dark-button login-submit" disabled={busy}>{busy?(registerMode?'Creating account…':'Signing in…'):(registerMode?'Create account':'Sign in')} <span>↗</span></button><div className="login-switch">{registerMode?'Already have an account?':'New to TACTUSBALL?'} <button type="button" onClick={()=>{setRegisterMode(!registerMode);setError('')}}>{registerMode?'Sign in':'Create an account'}</button></div><small className="login-security-note">New accounts start with the PLAYER role. Club access is controlled by your server-side role.</small></div></form></div>}
  </div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
