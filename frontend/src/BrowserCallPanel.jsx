import React, { useEffect, useRef, useState } from 'react';
import { Headphones, LoaderCircle, Mic, MicOff, Square } from 'lucide-react';
import { BrowserVoiceSession } from './browserVoice.mjs';

const ENDED = new Set(['completed', 'cancelled', 'failed', 'interrupted']);
const PHASES = { idle: 'Ready when you are', preparing: 'Checking microphone', connecting: 'Connecting audio', active: 'Browser audio connected', ending: 'Disconnecting', ended: 'Browser disconnected', failed: 'Connection stopped' };

export function BrowserCallPanel({ task, health, request }) {
  const [phase, setPhase] = useState('idle');
  const [error, setError] = useState('');
  const [caption, setCaption] = useState('');
  const [speaking, setSpeaking] = useState(false);
  const [muted, setMuted] = useState(false);
  const controller = useRef(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const unload = () => controller.current?.unload();
    window.addEventListener('pagehide', unload);
    return () => {
      mounted.current = false;
      window.removeEventListener('pagehide', unload);
      void controller.current?.stop();
    };
  }, []);
  useEffect(() => {
    if (ENDED.has(task.status) && controller.current && !controller.current.closed) void controller.current.stop();
  }, [task.status]);
  async function start() {
    const safe = setter => value => { if (mounted.current) setter(value); };
    const session = new BrowserVoiceSession({ taskId: task.id, request,
      onState: safe(setPhase), onError: safe(setError), onCaption: safe(setCaption), onSpeech: safe(setSpeaking) });
    controller.current = session;
    setMuted(false);
    await session.start();
  }
  const busy = ['preparing', 'connecting', 'ending'].includes(phase);
  const owned = controller.current?.session && !controller.current.closed;
  const ready = task.status === 'ready' && health?.browser && !busy && !owned;
  const detached = !controller.current && !['ready', 'planning'].includes(task.status) && !ENDED.has(task.status);
  function toggleMute() {
    try { controller.current.sdk.setMuted(!muted); setMuted(!muted); }
    catch { setError('The microphone could not be updated. End the session if you need to disconnect.'); }
  }
  return <section className="panel browser-call" aria-labelledby="browser-call-title">
    <div className={`browser-call-icon ${speaking ? 'is-speaking' : ''}`}><Headphones size={29}/></div>
    <div className="browser-call-copy"><span className="eyebrow">REAL VOICE · BROWSER ROLE-PLAY</span><h2 id="browser-call-title">Talk to HoldOn</h2><p>You play the representative. HoldOn handles the conversation and checks proposed commitments with you. No phone number is dialed.</p><div className="browser-audio-state" role="status">{busy && <LoaderCircle size={13} className="spin"/>}{detached ? 'No audio connection in this view. End the call in its original tab or the Vapi dashboard.' : task.status === 'planning' ? 'Preparing your call plan…' : ENDED.has(task.status) && phase === 'idle' ? 'Session ended' : speaking ? 'HoldOn is speaking' : PHASES[phase]}</div>{caption && <p className="live-caption">{caption}</p>}{error && <p className="browser-call-error" role="alert">{error}</p>}{!ENDED.has(task.status) && <small>Allow microphone access when prompted. Leaving this call view disconnects browser audio.</small>}</div>
    <div className="browser-call-actions">{!ENDED.has(task.status) && !owned && !busy && <button className="button primary" disabled={!ready} onClick={start}><Mic size={16}/>Talk to HoldOn</button>}{phase === 'active' && owned && <button className="button secondary" onClick={toggleMute} aria-pressed={muted}>{muted ? <MicOff size={16}/> : <Mic size={16}/>} {muted ? 'Unmute' : 'Mute'}</button>}{(owned || ['preparing', 'connecting'].includes(phase)) && <button className="button secondary" onClick={() => void controller.current?.stop()}><Square size={13}/>End session</button>}</div>
  </section>;
}
