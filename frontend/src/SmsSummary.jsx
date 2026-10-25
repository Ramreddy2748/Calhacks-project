import React, { useEffect, useRef, useState } from 'react';
import { MessageSquare, X, LoaderCircle } from 'lucide-react';

export function SmsSummary({ taskId, request }) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const dialog = useRef(null);
  useEffect(() => {
    if (!open) return;
    const node = dialog.current; node.showModal(); return () => node.close();
  }, [open]);
  async function show() {
    setOpen(true); setBusy(true); setError(''); setConfirmed(false); setPreview(null);
    try { setPreview(await request(`/tasks/${taskId}/sms`)); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  async function send() {
    setBusy(true); setError('');
    try {
      const delivery = await request(`/tasks/${taskId}/sms`, { method: 'POST', body: JSON.stringify({ confirmed: true }) });
      setPreview(previous => ({ ...previous, delivery }));
      setConfirmed(false);
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  async function check() {
    setBusy(true); setError('');
    try {
      const delivery = await request(`/tasks/${taskId}/sms/status`, { method: 'POST' });
      setPreview(previous => ({ ...previous, delivery }));
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  const canSend = preview?.configured && confirmed && (!preview.delivery || preview.delivery.status === 'failed');
  return <><button className="button secondary sms-launch" onClick={show}><MessageSquare size={15}/>Text summary</button>{open && <dialog className="modal" ref={dialog} aria-labelledby="sms-title" onCancel={event => { event.preventDefault(); if (!busy) setOpen(false); }}><div className="modal-content"><div className="modal-heading"><span className="modal-symbol"><MessageSquare size={23}/></span><button aria-label="Close SMS preview" disabled={busy} onClick={() => setOpen(false)}><X size={20}/></button></div><h2 id="sms-title">Send yourself the details.</h2><p>{preview?.configured ? `Recipient: ${preview.recipient}` : 'SMS needs a Twilio sender, recipient, and account credentials. Your summary is available here without SMS.'}</p>{busy && !preview && <LoaderCircle className="spin" size={20}/>}<pre className="sms-preview">{preview?.body}</pre>{preview?.delivery && <p className="sms-delivery" role="status">Twilio status: {preview.delivery.status}. {preview.delivery.status === 'unknown' ? 'Check Twilio before another send. No automatic retry will occur.' : 'Queued or accepted does not mean delivered.'}</p>}{preview?.configured && !preview.delivery && <label className="sms-consent"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>Send this summary to my configured number. This uses my Twilio balance and may be billed as multiple message segments.</label>}{preview?.configured && preview.delivery?.status === 'failed' && <label className="sms-consent"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>I checked the failed attempt in Twilio and want to try again.</label>}{error && <p className="browser-call-error" role="alert">{error}</p>}<div className="sms-actions">{preview?.delivery?.id && <button className="button secondary" disabled={busy} onClick={check}>Check delivery</button>}<button className="button primary" disabled={busy || !canSend} onClick={send}>{busy ? 'Working…' : 'Send SMS'}</button></div></div></dialog>}</>;
}
