import React, { useEffect, useRef, useState } from 'react';
import { ShieldCheck, LoaderCircle } from 'lucide-react';

export function WorkspaceAccess({ request, signedIn }) {
  const dialog = useRef(null);
  const [key, setKey] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { const node = dialog.current; node.showModal(); return () => node.close(); }, []);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    try { await request('/login', { method: 'POST', body: JSON.stringify({ access_key: key }) }); setKey(''); signedIn(); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  return <dialog className="modal" ref={dialog} aria-labelledby="workspace-access-title" onCancel={event => event.preventDefault()}><div className="modal-content"><span className="modal-symbol"><ShieldCheck size={23}/></span><h2 id="workspace-access-title">Your private workspace.</h2><p>Enter your workspace access key to view calls and control your assistant.</p><form onSubmit={submit}><label htmlFor="workspace-key">Workspace access key</label><input className="workspace-key" id="workspace-key" type="password" autoFocus autoComplete="current-password" required value={key} onChange={event => setKey(event.target.value)}/>{error && <p className="browser-call-error" role="alert">{error}</p>}<button className="button primary submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16}/> : 'Unlock workspace'}</button></form></div></dialog>;
}
