const microphoneError = error => ['NotAllowedError', 'PermissionDeniedError', 'NotFoundError', 'NotReadableError'].includes(error?.name);
const connectionError = 'Browser voice could not connect. Check microphone permissions and your Vapi dashboard before starting another session.';

// SDK events are serialized before the disconnect event so reporting sees the
// final transcript. Dependencies are injectable for lifecycle tests without calls.
export class BrowserVoiceSession {
  constructor({ taskId, request, loadSdk = () => import('@vapi-ai/web'), mediaDevices = globalThis.navigator?.mediaDevices,
    onState = () => {}, onError = () => {}, onCaption = () => {}, onSpeech = () => {} }) {
    Object.assign(this, { taskId, request, loadSdk, mediaDevices, onState, onError, onCaption, onSpeech });
    this.queue = Promise.resolve();
    this.closed = false;
    this.terminalSent = false;
  }

  event(kind, fields = {}) {
    return { session_token: this.session.session_token, event_id: crypto.randomUUID(), kind, ...fields };
  }

  enqueue(kind, fields = {}) {
    if (!this.session) return Promise.resolve();
    const event = this.event(kind, fields);
    this.queue = this.queue.then(() => this.request(`/tasks/${this.taskId}/browser/events`, {
      method: 'POST', body: JSON.stringify(event), signal: AbortSignal.timeout(8000),
    })).catch(() => {
      this.onError('Live updates could not be saved. Browser audio is disconnecting; check the backend and Vapi dashboard.');
      if (!['ended', 'error'].includes(kind)) void this.stop('error');
    });
    return this.queue;
  }

  releaseMicrophone() {
    this.stream?.getTracks().forEach(track => track.stop());
    this.stream = null;
  }

  async start() {
    this.onState('preparing');
    this.onError('');
    try {
      if (!this.mediaDevices?.getUserMedia) throw new Error('Microphone access requires localhost or HTTPS and a supported browser.');
      const module = await this.loadSdk();
      if (this.closed) return;
      // Ask before reserving a session or asking Vapi to create a call.
      this.stream = await this.mediaDevices.getUserMedia({ audio: true });
      if (this.closed) { this.releaseMicrophone(); return; }
      this.session = await this.request(`/tasks/${this.taskId}/browser/session`, { method: 'POST', signal: AbortSignal.timeout(8000) });
      if (this.closed) { await this.finish('ended'); this.releaseMicrophone(); return; }
      const Vapi = module.default;
      this.sdk = new Vapi(this.session.public_key, undefined, undefined, { audioSource: this.stream.getAudioTracks()[0] });
      this.sdk.on('call-start', () => {
        if (!this.closed) { this.onState('active'); void this.enqueue('connected'); }
      });
      this.sdk.on('call-end', () => { void this.stop(); });
      this.sdk.on('speech-start', () => { if (!this.closed) this.onSpeech(true); });
      this.sdk.on('speech-end', () => { this.onSpeech(false); });
      this.sdk.on('message', message => {
        if (this.closed || message.type !== 'transcript' || !['assistant', 'user'].includes(message.role) || typeof message.transcript !== 'string') return;
        this.onCaption(message.transcriptType === 'final' ? '' : message.transcript);
        if (message.transcriptType === 'final') void this.enqueue('transcript', { role: message.role, text: message.transcript.slice(0, 6000) });
      });
      this.sdk.on('error', error => {
        // SDK audio-processing warnings are nonfatal; start() and call-end own
        // transport errors. Never show raw provider payloads or credentials.
        if (String(error?.type || '').includes('audio-processing')) return;
        this.onError(connectionError);
        void this.stop('error');
      });
      this.onState('connecting');
      const call = await this.sdk.start(this.session.assistant_id, this.session.assistant_overrides,
        undefined, undefined, undefined, { roomDeleteOnUserLeaveEnabled: true });
      if (this.closed) { await this.sdk.stop(); this.releaseMicrophone(); return; }
      if (!call?.id) throw new Error('No call returned');
      await this.enqueue('registered', { provider_call_id: call.id });
    } catch (error) {
      this.releaseMicrophone();
      if (this.closed) return;
      this.onError(microphoneError(error) ? 'Microphone unavailable. Allow microphone access in your browser and check that a microphone is connected.' : connectionError);
      if (this.session) await this.stop('error');
      else this.onState('idle');  // permission failure has not created a call
    }
  }

  async finish(kind) {
    if (this.session && !this.terminalSent) {
      this.terminalSent = true;
      await this.enqueue(kind);
    }
  }

  stop(kind = 'ended') {
    if (this.stopping) return this.stopping;
    this.closed = true;
    this.onState('ending');
    // Defer SDK stop until stopping is assigned: stop() can emit call-end.
    this.stopping = Promise.resolve().then(async () => {
      try { await this.sdk?.stop(); }
      catch { this.onError('Browser audio could not confirm disconnect. Check the Vapi dashboard.'); }
      finally { this.releaseMicrophone(); }
      await this.finish(kind);
      this.onCaption(''); this.onSpeech(false);
      this.onState(kind === 'error' ? 'failed' : 'ended');
    });
    return this.stopping;
  }

  unload() {
    this.closed = true;
    this.releaseMicrophone();
    void this.sdk?.stop().catch(() => {});
    if (this.session && !this.terminalSent) {
      this.terminalSent = true;
      const body = new Blob([JSON.stringify(this.event('ended'))], { type: 'application/json' });
      globalThis.navigator?.sendBeacon?.(`/api/tasks/${this.taskId}/browser/events`, body);
    }
  }
}
