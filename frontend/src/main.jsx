import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowDownLeft, ArrowRight, ArrowUpRight, Check, CheckCheck, ChevronRight, CircleHelp, FileText, Headphones, LayoutDashboard, LoaderCircle, Menu, Mic, Phone, PhoneCall, Plus, Radio, ShieldCheck, Sparkles, Square, Workflow, X } from 'lucide-react';
import './styles.css';
import { AgentWorkflow, ConnectionStatus } from './ProgressPanels.jsx';
import { BrowserCallPanel } from './BrowserCallPanel.jsx';
import { WorkspaceAccess } from './WorkspaceAccess.jsx';
import { SmsSummary } from './SmsSummary.jsx';

const TERMINAL = new Set(['completed', 'cancelled', 'failed', 'interrupted']);
const LABELS = { ready: 'Ready to talk', planning: 'Planning', calling: 'Connecting', on_hold: 'On hold', in_progress: 'In conversation', awaiting_approval: 'Needs your approval', completed: 'Completed', cancelled: 'Cancelled', failed: 'Failed', interrupted: 'Interrupted' };
const EXAMPLES = [
  { title: 'A better internet bill', tag: 'Negotiate a bill', icon: '↘', goal: 'Call my internet provider and ask about a lower monthly rate.', context: 'I’m happy with the service, but the bill is too high. Ask about loyalty discounts. Do not change my plan without approval.' },
  { title: 'Plans change. So can you.', tag: 'Cancel a subscription', icon: '✳', goal: 'Cancel my gym membership and confirm there are no cancellation fees.', context: 'Ask when the cancellation takes effect and get a confirmation number. Do not accept a new contract.' },
  { title: 'One less thing to schedule', tag: 'Book an appointment', icon: '◷', goal: 'Ask about available appointments for a routine dental cleaning next week.', context: 'Prefer weekday mornings. Ask for pricing and available times before making a booking.' },
];

async function api(path, options) {
  const response = await fetch(`/api${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } });
  const body = await response.json();
  if (!response.ok) throw Object.assign(new Error(typeof body.detail === 'string' ? body.detail : 'Please check your input and try again.'), { status: response.status });
  return body;
}

function App() {
  const [tasks, setTasks] = useState([]);
  const [selected, setSelected] = useState(null);
  const [health, setHealth] = useState(null);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [connection, setConnection] = useState('checking');
  const [checkedAt, setCheckedAt] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const refreshInFlight = useRef(false);
  const [view, setView] = useState('overview');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(false);
  const [draft, setDraft] = useState({ goal: '', context: '', mode: 'demo', phone: '', teammate_confirmed: false });
  const [busy, setBusy] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const transcriptEnd = useRef(null);

  async function refresh() {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    setRefreshing(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const [list, status] = await Promise.allSettled([
        api('/tasks', { signal: controller.signal }),
        api('/health', { signal: controller.signal }),
      ]);
      if (list.status === 'fulfilled') setTasks(list.value);
      if (status.status === 'fulfilled') setNeedsLogin(Boolean(status.value.login_required));
      if (list.status === 'rejected' && list.reason.status === 401) setNeedsLogin(true);
      if (status.status === 'fulfilled' && status.value.ok) {
        setHealth(status.value); setConnection('online');
      } else {
        setHealth(null); setConnection('offline');
      }
      setCheckedAt(Date.now());
      if (status.status === 'fulfilled' && status.value.login_required) {
        setError(''); setTasks([]); setSelected(null);
      } else if (status.status === 'rejected' || (status.status === 'fulfilled' && !status.value.ok)) {
        setError('The API is unavailable. Start the backend, then retry.');
      } else if (list.status === 'rejected') {
        setError('Call history could not be loaded. Your connection status is available; retry to load calls.');
      } else {
        setError('');
      }
    } finally {
      clearTimeout(timeout);
      refreshInFlight.current = false;
      setRefreshing(false); setLoading(false);
    }
  }
  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    const id = setInterval(() => refresh(), 10000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (!selected) return;
    const stream = new EventSource(`/api/tasks/${selected}/events`);
    stream.onmessage = e => {
      const { task } = JSON.parse(e.data);
      setTasks(previous => [task, ...previous.filter(t => t.id !== task.id)].sort((a, b) => b.created_at.localeCompare(a.created_at)));
    };
    return () => stream.close();
  }, [selected]);
  const task = tasks.find(t => t.id === selected);
  useEffect(() => { transcriptEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [task?.transcript.length]);
  useEffect(() => {
    if (!modal) return;
    const handler = event => { if (event.key === 'Escape' && !busy) setModal(false); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [modal, busy]);

  function newCall(example, mode = 'demo') {
    setDraft({ goal: example?.goal || '', context: example?.context || '', mode, phone: '', teammate_confirmed: false });
    setError(''); setModal(true);
  }
  async function create(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const created = await api('/tasks', { method: 'POST', body: JSON.stringify(draft) });
      setTasks(prev => [created, ...prev]); setSelected(created.id); setView('overview'); setModal(false);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function decision(approved) {
    setBusy(true); setError('');
    try {
      const updated = await api(`/tasks/${task.id}/approvals/${task.approval.id}`, { method: 'POST', body: JSON.stringify({ approved }) });
      setTasks(prev => prev.map(t => t.id === updated.id ? updated : t));
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function cancel() {
    setBusy(true);
    try {
      const updated = await api(`/tasks/${task.id}/cancel`, { method: 'POST' });
      setTasks(prev => prev.map(t => t.id === updated.id ? updated : t));
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  function navigate(next) { setView(next); setSelected(null); setMobileNav(false); }
  const active = tasks.filter(t => !TERMINAL.has(t.status));
  const completed = tasks.filter(t => t.status === 'completed');

  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`}>
      <a className="brand" href="#" onClick={e => { e.preventDefault(); navigate('overview'); }}><span className="brand-mark"><Headphones size={22}/></span>holdon<span className="brand-dot">.</span></a>
      <div className="workspace"><span className="workspace-avatar">Y</span><div>Your workspace<small>Personal account</small></div><span className="workspace-tag">BETA</span></div>
      <div className="nav-caption">WORKSPACE</div>
      <nav aria-label="Main navigation">
        <button className={view === 'overview' ? 'active' : ''} onClick={() => navigate('overview')}><LayoutDashboard size={18}/>Overview</button>
        <button className={view === 'history' ? 'active' : ''} onClick={() => navigate('history')}><Phone size={18}/>Call history<span className="nav-count">{tasks.length}</span></button>
        <button className={view === 'agents' ? 'active' : ''} onClick={() => navigate('agents')}><Workflow size={18}/>Your agents</button>
      </nav>
      <div className="sidebar-note"><div className="note-art"><Sparkles size={24}/><span>✦</span></div><strong>Life’s too short<br/>for hold music.</strong><p>Hand off the call.<br/>Keep the rest of your day.</p><button onClick={() => newCall()}>Make your first move <ArrowUpRight size={15}/></button></div>
      <div className="sidebar-bottom"><span className={`status-dot ${connection === 'online' && health?.fetch?.ready ? '' : 'offline'}`}/>{connection === 'checking' ? 'Connecting to assistant' : connection !== 'online' ? 'Assistant is offline' : health?.fetch?.ready ? 'Your assistant is ready' : 'Agent runtime unavailable'}<button aria-label="How HoldOn works" onClick={() => navigate('agents')}><CircleHelp size={17}/></button></div>
      <div className="profile"><div className="avatar">YO</div><div>Your workspace<small>Cal Hacks 13.0</small></div><span className="profile-badge">H</span></div>
    </aside>
    <main>
      <header className="topbar"><div><button className="mobile-toggle" aria-label="Toggle navigation" onClick={() => setMobileNav(!mobileNav)}><Menu size={20}/></button><span>Workspace</span><ChevronRight size={14}/><strong>{view === 'overview' ? 'Overview' : view === 'history' ? 'Call history' : 'Your agents'}</strong></div><div className="private-label"><ShieldCheck size={15}/>You’re always in control</div></header>
      <div className="page">
        {error && !modal && <div className="error" role="alert">{error}<button onClick={refresh}>Retry</button><button aria-label="Dismiss error" onClick={() => setError('')}><X size={16}/></button></div>}
        <ConnectionStatus health={health} connection={connection} checkedAt={checkedAt} refreshing={refreshing} refresh={refresh}/>
        {view === 'agents' ? <><div className="page-heading"><div><div className="eyebrow">A LITTLE TEAM, ON YOUR SIDE</div><h1>Meet your agents.</h1><p>One goal. Four focused roles. You make the final call.</p></div></div><div className="agent-grid">{[
          ['Planner', 'Turns your goal and context into a clear call plan.', FileText],
          ['Negotiator', 'Carries the conversation forward and asks about available options.', Mic],
          ['Guardrail', 'Routes proposed commitments to you for approval. Declines when approval expires.', ShieldCheck],
          ['Reporter', 'Summarizes the conversation and records the outcome.', CheckCheck],
        ].map(([name, description, Icon]) => <article className="panel agent-card" key={name}><div className="agent-icon"><Icon size={24}/></div><h2>{name}</h2><p>{description}</p><span className="mini-label">{health?.claude ? 'Claude + Fetch.ai uAgents' : name === 'Negotiator' ? 'Scripted demo · Vapi for live calls' : 'Ready in demo mode'}</span></article>)}</div><div className="panel integration-panel"><h2>Connected foundations</h2><p>Fetch.ai uAgents coordinates the agent roles locally. SQLite stores call history and server-sent events deliver live updates.</p><div className="integration-row"><span>Claude · planning, simulation & reporting</span><span className="mini-label">{connection !== 'online' ? 'Unknown' : health?.claude ? 'Configured · not verified' : 'Credentials needed'}</span></div><div className="integration-row"><span>Vapi · voice & telephony</span><span className="mini-label">{connection !== 'online' ? 'Unknown' : health?.browser ? 'Browser configured · not verified' : health?.live ? 'Phone configured · not verified' : 'Credentials needed'}</span></div><div className="integration-row"><span>Fetch.ai uAgents · orchestration</span><span className="mini-label">{connection !== 'online' ? 'Unknown' : health?.fetch?.ready ? 'Running locally' : 'Unavailable'}</span></div><div className="integration-row"><span>SpacetimeDB · event mirror</span><span className="mini-label">{health?.spacetime?.error ? 'Sync error · queued locally' : health?.spacetime?.connected ? `Connected · ${health.spacetime.pending_events} queued` : health?.spacetime?.configured ? 'Configured · waiting to sync' : 'Not configured'}</span></div><div className="integration-row"><span>Twilio · summary SMS</span><span className="mini-label">{health?.sms?.configured ? 'Configured · send manually' : 'Not configured'}</span></div></div></> : <>
          <div className="page-heading"><div><div className="eyebrow">LESS HOLD. MORE LIFE.</div><h1>{view === 'history' ? 'Every call, in one place.' : 'Your time, back.'}<span className="heading-spark">✳</span></h1><p>{view === 'history' ? 'The conversations, decisions, and details. All here.' : 'The calls you’ve been putting off? Let’s take them off your list.'}</p></div><div className="page-actions"><button className="button secondary" onClick={() => newCall(null, 'browser')}><Mic size={17}/>Talk to HoldOn</button><button className="button primary" onClick={() => newCall()}><Plus size={18}/>New call</button></div></div>
          {view === 'overview' && !task && <>
            <section className="hero"><div><div className="hero-label"><span className="status-dot"/>YOUR PERSONAL CALL ASSISTANT</div><h2>You have better things<br/>to do than wait on hold.</h2><p>Tell HoldOn what you need. Your AI assistant takes<br className="desktop-break"/> care of the conversation, while you get on with life.</p><button className="button light" onClick={() => newCall()}>Let’s make a call <ArrowUpRight size={17}/></button><div className="hero-foot"><ShieldCheck size={14}/>AI does the talking. You call the shots.</div></div><div className="hero-visual" aria-hidden="true"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="orbit orbit-three"/><div className="float-chip chip-one"><span className="tiny-avatar"><PhoneCall size={15}/></span><div>On it, so you don’t have to be.<small>{connection === 'online' && health?.fetch?.ready ? 'Your assistant is ready' : connection === 'checking' ? 'Checking availability' : 'Check connection status'}</small></div><span className="chip-check"><Check size={14}/></span></div><div className="phone-orb"><Headphones size={65} strokeWidth={1.4}/></div><div className="sound-wave">{Array.from({ length: 23 }, (_, i) => <i key={i} style={{ height: `${10 + Math.abs(Math.sin(i * 1.7)) * 29}px`, animationDelay: `${i * .1}s` }}/>)}</div><div className="float-chip chip-two"><span className="chip-check"><Check size={14}/></span>One less thing on your list.<span>✦</span></div><span className="visual-star">✳</span></div></section>
            <div className="stats-grid"><Stat icon={PhoneCall} label="Calls handled" value={completed.length} note="A little less on your plate"/><Stat icon={Radio} label="In progress" value={active.length} note={active.length ? 'Your assistant is on it' : 'Ready when you are'} live={active.length > 0}/><Stat icon={ShieldCheck} label="Your control" value="Always" note="Every commitment needs a yes"/></div>
          </>}
          {task ? <>
            <button className="back-link" onClick={() => setSelected(null)}>← Back to {view === 'history' ? 'call history' : 'overview'}</button>
            <div className="call-heading"><div><span className="mini-label">{task.mode === 'demo' ? 'SIMULATED CALL' : task.mode === 'browser' ? 'BROWSER VOICE ROLE-PLAY' : 'LIVE TEAMMATE CALL'}</span><h2>{task.goal}</h2></div><Status status={task.status}/></div>
            {task.mode === 'demo' && <div className="demo-banner"><Sparkles size={16}/>{task.engine === 'claude' ? 'Claude simulation · A conversation tailored to your goal, with your approval before commitments.' : 'Scripted simulation · An offline walkthrough of the approval flow.'} No real phone call or account change occurs.</div>}
            <AgentWorkflow task={task}/>
            {task.mode === 'browser' && <BrowserCallPanel key={task.id} task={task} health={health} request={api}/>}
            {task.error && <div className="error" role="alert">{task.error}</div>}
            {task.status === 'awaiting_approval' && task.approval?.status === 'pending' && <section className="approval" aria-live="polite"><div className="approval-icon"><ShieldCheck size={23}/></div><div><strong>Your call. Your decision.</strong><p>{task.approval.description}</p><small>{task.mode !== 'demo' ? 'Expires after 20 seconds. No response means decline.' : task.engine === 'claude' ? 'Decline asks for another option, up to 3 proposals. End demo stops the session. Inactivity ends it after 5 minutes.' : 'The assistant is waiting. No response within 5 minutes means decline.'}</small></div><div className="approval-actions"><button className="button secondary" disabled={busy} onClick={() => decision(false)}>{task.mode === 'demo' && task.engine === 'claude' ? 'Find another option' : 'Decline'}</button><button className="button primary" disabled={busy} onClick={() => decision(true)}><Check size={16}/>Approve</button></div></section>}
            <div className="call-grid"><section className="panel transcript"><div className="panel-header"><h3><Radio size={17}/>Conversation</h3><span className="mini-label">{TERMINAL.has(task.status) ? 'CALL ENDED' : task.status === 'ready' ? 'READY TO TALK' : 'UPDATING LIVE'}</span></div><div className="messages" aria-live="polite">{!task.transcript.length && <div className="waiting">{task.status === 'ready' || TERMINAL.has(task.status) ? <Mic size={24}/> : <LoaderCircle className="spin" size={24}/>}<p>{task.status === 'ready' ? 'Connect your microphone to start the conversation.' : TERMINAL.has(task.status) ? 'No transcript was recorded.' : 'Preparing the conversation…'}</p></div>}{task.transcript.map((line, i) => <div className={`message ${line.role === 'assistant' ? 'assistant' : 'rep'}`} key={i}><div className="speaker-icon">{line.role === 'assistant' ? <Headphones size={15}/> : <Phone size={15}/>}</div><div><div className="speaker">{line.role === 'assistant' ? 'HoldOn' : task.mode === 'browser' ? 'You · representative' : 'Representative'}<time>{time(line.at)}</time></div><p>{line.text}</p></div></div>)}<div ref={transcriptEnd}/></div>{!TERMINAL.has(task.status) && task.mode === 'demo' && <div className="transcript-footer"><span><span className="status-dot"/>Demo session in progress</span><button disabled={busy} onClick={cancel}><Square size={12}/>End demo</button></div>}</section><div className="call-side"><section className="panel"><div className="panel-header"><h3><FileText size={17}/>The game plan</h3></div><ol className="plan-list">{task.plan.map((step, i) => <li key={i}><span>{i + 1}</span>{step}</li>)}</ol></section><section className="panel"><div className="panel-header"><h3><Workflow size={17}/>Agent activity</h3></div><div className="activity">{task.activity.map((item, i) => <div key={i}><span className="activity-dot"/><strong>{item.agent}<time>{time(item.at)}</time></strong><p>{item.message}</p></div>)}</div></section></div></div>
            {task.summary && <section className="panel summary"><div className="summary-icon"><CheckCheck size={24}/></div><div><span className="eyebrow">ONE LESS THING</span><h2>Your call, wrapped up.</h2><p>{task.summary}</p></div><SmsSummary taskId={task.id} request={api}/><button className="button secondary" onClick={() => { const blob = new Blob([JSON.stringify(task, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `holdon-${task.id}.json`; a.click(); URL.revokeObjectURL(url); }}><ArrowDownLeft size={16}/>Export</button></section>}
          </> : <>
            <section className="calls-section"><div className="section-heading"><h2>{view === 'history' ? 'All calls' : 'Your calls'}<span>{tasks.length}</span></h2>{view === 'overview' && <button onClick={() => navigate('history')}>View all calls <ArrowRight size={15}/></button>}</div><div className="panel calls-panel">{loading ? <div className="empty-state"><LoaderCircle className="spin"/><h3>Getting things ready…</h3></div> : tasks.length ? <div className="table-wrap"><table><thead><tr><th>CALL & GOAL</th><th>DATE</th><th>STATUS</th><th><span className="sr-only">Open call</span></th></tr></thead><tbody>{(view === 'history' ? tasks : tasks.slice(0, 5)).map(t => <tr key={t.id} onClick={() => setSelected(t.id)}><td><button className="call-row-button" onClick={() => setSelected(t.id)}><span className="table-phone"><Phone size={17}/></span><span>{t.goal}<small>{t.mode === 'demo' ? 'Demo call · no real number dialed' : t.mode === 'browser' ? 'Browser voice · role-play' : t.phone}</small></span></button></td><td className="date-cell">{new Date(t.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}<small>{time(t.created_at)}</small></td><td><Status status={t.status}/></td><td><ChevronRight size={17}/></td></tr>)}</tbody></table></div> : <div className="empty-state"><div className="empty-icon"><PhoneCall size={25}/><span>✦</span></div><h3>A quieter to-do list starts here.</h3><p>No calls yet. Give your assistant a task and let it take the first step.</p><button onClick={() => newCall()}>Create your first call <ArrowRight size={15}/></button></div>}</div></section>
            {view === 'overview' && <section className="ideas-section"><div className="section-heading"><h2>A little inspiration</h2><span>BIG OR SMALL, WE’VE GOT THE CALL.</span></div><div className="ideas-grid">{EXAMPLES.map((e, i) => <button className={`idea-card idea-${i}`} key={e.title} onClick={() => newCall(e)}><div className="idea-top"><span className="idea-icon">{e.icon}</span><ArrowUpRight size={18}/></div><h3>{e.title}</h3><span>{e.tag}</span></button>)}</div></section>}
          </>}
        </>}
        <footer><span>Made for getting on with your day.</span><span><Headphones size={13}/>HoldOn · Cal Hacks 13.0</span></footer>
      </div>
    </main>
    {needsLogin && <WorkspaceAccess request={api} signedIn={() => { setNeedsLogin(false); void refresh(); }}/>}
    {modal && <CallDialog draft={draft} setDraft={setDraft} create={create} busy={busy} error={error} health={health} close={() => { if (!busy) { setModal(false); setError(''); } }}/>}
  </div>;
}

function CallDialog({ draft, setDraft, create, busy, error, health, close }) {
  const dialog = useRef(null);
  useEffect(() => { const node = dialog.current; node.showModal(); return () => node.close(); }, []);
  const field = (name, value) => setDraft(previous => ({ ...previous, [name]: value }));
  return <dialog ref={dialog} aria-labelledby="new-call-title" className="modal" onCancel={e => { e.preventDefault(); close(); }} onClick={e => { if (e.target === dialog.current) close(); }}><div className="modal-content"><div className="modal-heading"><span className="modal-symbol"><PhoneCall size={23}/></span><button aria-label="Close new call" disabled={busy} onClick={close}><X size={20}/></button></div><div className="eyebrow">HAND IT OFF</div><h2 id="new-call-title">What can we take<br/>off your list?</h2><p>Give your assistant a goal. We’ll figure out the conversation.</p><form onSubmit={create}><label htmlFor="goal">What would you like done?</label><textarea id="goal" autoFocus required minLength={5} maxLength={1200} rows={3} placeholder="e.g. Ask my internet provider for a lower monthly rate…" value={draft.goal} onChange={e => field('goal', e.target.value)}/><label htmlFor="context">Anything your assistant should know? <span>Optional</span></label><textarea id="context" rows={2} maxLength={3000} placeholder="Preferences, constraints, or questions to ask. Leave out passwords and payment details." value={draft.context} onChange={e => field('context', e.target.value)}/><label htmlFor="mode">Call mode</label><select id="mode" value={draft.mode} onChange={e => field('mode', e.target.value)}><option value="demo">AI simulation · plan, conversation, approval & summary</option><option value="browser">Browser voice · talk to HoldOn through your microphone</option><option value="live" disabled={!health?.live}>Live teammate call {health?.live ? '' : '· setup required'}</option></select>{draft.mode === 'live' && <><label htmlFor="phone">Teammate’s phone number</label><input type="tel" id="phone" required pattern="\+[1-9][0-9]{7,14}" placeholder="+14155551234" value={draft.phone} onChange={e => field('phone', e.target.value)}/><label className="checkbox"><input type="checkbox" required checked={draft.teammate_confirmed} onChange={e => field('teammate_confirmed', e.target.checked)}/>This is an allowlisted teammate who expects this demo call.</label></>}<div className="form-safety"><ShieldCheck size={18}/><span>{draft.mode === 'demo' ? 'A clearly labeled simulation with a real approval step. Claude creates the plan and dialogue when configured. No number is dialed.' : draft.mode === 'browser' ? 'Your microphone connects to Vapi for a real voice role-play. No phone number is dialed.' : 'This places a real call. Your assistant must disclose that it is AI.'}</span></div>{draft.mode === 'browser' && !health?.browser && <p className="browser-setup-note">Browser voice needs a Vapi public key, assistant, and approval webhook configured. Choose Demo to try the scripted flow now.</p>}{error && <div className="error" role="alert">{error}</div>}<button className="button primary submit" disabled={busy || !health?.fetch?.ready || (draft.mode === 'browser' && !health?.browser)} type="submit">{busy ? <><LoaderCircle className="spin" size={17}/>Preparing…</> : <> {draft.mode === 'demo' ? 'Start demo call' : draft.mode === 'browser' ? 'Prepare browser call' : 'Place teammate call'}<ArrowUpRight size={17}/></>}</button></form></div></dialog>;
}
function time(value) { return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
function Status({ status }) { return <span className={`status status-${status}`}><span/>{LABELS[status] || status}</span>; }
function Stat({ icon: Icon, label, value, note, live }) { return <div className="stat"><div className="stat-top"><span>{label}</span><Icon size={17}/></div><div className="stat-value">{value}{live && <span className="status-dot"/>}</div><p>{note}</p></div>; }

createRoot(document.getElementById('root')).render(<App/>);
