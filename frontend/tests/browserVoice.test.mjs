import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { webcrypto } from 'node:crypto';
import { BrowserVoiceSession } from '../src/browserVoice.mjs';

globalThis.crypto ??= webcrypto;
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

function setup(overrides = {}) {
  const events = [], states = [], errors = [], captions = [];
  const track = { stopped: false, stop() { this.stopped = true; } };
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  let instance;
  class FakeVapi extends EventEmitter {
    constructor() { super(); instance = this; this.stops = 0; }
    async start() { this.emit('call-start'); return { id: 'web-call-1' }; }
    async stop() { this.stops++; this.emit('call-end'); }
  }
  const request = async (path, options) => {
    if (path.endsWith('/session')) return { public_key: 'public-test-key', assistant_id: 'assistant', session_token: 'x'.repeat(40), assistant_overrides: {} };
    events.push(JSON.parse(options.body));
    return { ok: true };
  };
  const session = new BrowserVoiceSession({ taskId: 'task-1', request,
    loadSdk: async () => ({ default: FakeVapi }), mediaDevices: { getUserMedia: async () => stream },
    onState: state => states.push(state), onError: error => errors.push(error), onCaption: value => captions.push(value), ...overrides });
  return { session, events, states, errors, captions, track, FakeVapi, instance: () => instance };
}

test('permission denial does not create a Vapi call or backend session', async () => {
  let requests = 0;
  const setupResult = setup({ request: async () => { requests++; }, mediaDevices: { getUserMedia: async () => { throw Object.assign(new Error('Denied'), { name: 'NotAllowedError' }); } } });
  await setupResult.session.start();
  assert.equal(requests, 0);
  assert.equal(setupResult.instance(), undefined);
  assert.equal(setupResult.states.at(-1), 'idle');
  assert.match(setupResult.errors.at(-1), /Microphone unavailable/);
});

test('final transcripts are persisted in order before one disconnect event', async () => {
  const qa = setup();
  await qa.session.start();
  qa.instance().emit('message', { type: 'transcript', role: 'user', transcriptType: 'partial', transcript: 'Part' });
  qa.instance().emit('message', { type: 'transcript', role: 'user', transcriptType: 'final', transcript: 'Final offer' });
  await qa.session.stop();
  await qa.session.stop();
  assert.deepEqual(qa.events.map(event => event.kind), ['connected', 'registered', 'transcript', 'ended']);
  assert.equal(qa.events[2].text, 'Final offer');
  assert.ok(qa.track.stopped);
  assert.equal(qa.captions.at(-1), '');
  assert.equal(new Set(qa.events.map(event => event.event_id)).size, qa.events.length);
});

test('ending during microphone acquisition releases the eventual track without a call', async () => {
  const microphone = deferred();
  let requests = 0;
  const qa = setup({ mediaDevices: { getUserMedia: () => microphone.promise }, request: async () => { requests++; } });
  const starting = qa.session.start();
  await tick();
  await qa.session.stop();
  microphone.resolve({ getTracks: () => [qa.track] });
  await starting;
  assert.ok(qa.track.stopped);
  assert.equal(requests, 0);
});

test('late SDK start cannot reactivate an ended session', async () => {
  const joining = deferred();
  const qa = setup();
  qa.FakeVapi.prototype.start = () => joining.promise;
  const starting = qa.session.start();
  await tick();
  await qa.session.stop();
  joining.resolve({ id: 'late-call' });
  await starting;
  assert.equal(qa.events.filter(event => event.kind === 'ended').length, 1);
  assert.equal(qa.events.filter(event => event.kind === 'registered').length, 0);
  assert.ok(qa.instance().stops >= 2);
  assert.equal(qa.states.at(-1), 'ended');
});

test('an update failure disconnects audio and does not retry a paid call', async () => {
  let requests = 0;
  const qa = setup();
  const original = qa.session.request;
  qa.session.request = async (...args) => { requests++; if (args[0].endsWith('/events') && JSON.parse(args[1].body).kind === 'connected') throw new Error('Offline'); return original(...args); };
  await qa.session.start();
  await qa.session.stop('error');
  assert.ok(qa.track.stopped);
  assert.equal(qa.events.filter(event => event.kind === 'error').length, 1);
  assert.ok(requests <= 4);
  assert.ok(qa.errors.some(error => error.includes('could not be saved')));
});
