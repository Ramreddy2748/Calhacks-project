import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import Agents
from .orchestration import FetchOrchestrator
from .store import Store, now
from .spacetime import SpacetimeMirror
from .sms import SmsDelivery
from . import access
from . import public_demo
from . import elevenlabs_phone
from .errors import error_code, error_message

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
store = Store(os.getenv('DATABASE_PATH', str(Path(__file__).resolve().parents[1] / 'holdon.sqlite3')))
agents = FetchOrchestrator(Agents())
sms = SmsDelivery()
logger = logging.getLogger('holdon')
jobs = {}
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}


@asynccontextmanager
async def lifespan(app):
    access.validate()
    public_demo.validate()
    # A restarted process cannot safely resume a simulation or assume a live call ended.
    for task in store.all():
        if (task.get('sms') or {}).get('status') == 'sending':
            task['sms']['status'] = 'unknown'
            store.save(task)
        if task['status'] not in TERMINAL:
            task['status'] = 'interrupted'
            task['error'] = 'Server restarted. Check your voice provider before starting another live call.'
            store.save(task)
    mirror = SpacetimeMirror(store)
    await agents.start()
    app.state.spacetime = mirror
    mirror.start()
    try:
        yield
    finally:
        pending = list(jobs.values())
        for job in pending:
            job.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await agents.close()
        await mirror.close()


app = FastAPI(title='HoldOn API', lifespan=lifespan,
              docs_url=None if access.required() else '/docs',
              redoc_url=None if access.required() else '/redoc',
              openapi_url=None if access.required() else '/openapi.json')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
                   allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'Last-Event-ID'])
app.add_middleware(access.AccessGate)
app.add_middleware(public_demo.PublicDemoGate, store=lambda: store)


class LoginInput(BaseModel):
    access_key: str = Field(max_length=300)


login_attempts = {}


@app.post('/api/login')
async def login(data: LoginInput, request: Request):
    if not access.required():
        return {'ok': True}
    client = request.client.host if request.client else 'unknown'
    now_seconds = time.monotonic()
    # Keep rate-limit bookkeeping bounded even across many distinct clients.
    for key in list(login_attempts):
        login_attempts[key] = [stamp for stamp in login_attempts[key] if stamp > now_seconds - 60]
        if not login_attempts[key]:
            del login_attempts[key]
    attempts = login_attempts.setdefault(client, [])
    if len(attempts) >= 5 or len(login_attempts) > 5000:
        raise HTTPException(429, 'Too many sign-in attempts. Wait a minute and retry.')
    attempts.append(now_seconds)
    if not hmac.compare_digest(data.access_key.encode(), os.getenv('HOLDON_ACCESS_KEY', '').encode()):
        raise HTTPException(401, 'Incorrect workspace access key')
    login_attempts.pop(client, None)
    response = JSONResponse({'ok': True})
    response.set_cookie(access.COOKIE, access.issue(), max_age=access.LIFETIME,
                        httponly=True, secure=True, samesite='strict', path='/')
    return response


@app.post('/api/logout')
async def logout():
    response = JSONResponse({'ok': True})
    response.delete_cookie(access.COOKIE, path='/', secure=True, httponly=True, samesite='strict')
    return response


class TaskInput(BaseModel):
    goal: str = Field(min_length=5, max_length=1200)
    context: str = Field(default='', max_length=3000)
    mode: Literal['demo', 'browser', 'live'] = 'demo'
    phone: str = ''
    teammate_confirmed: bool = False


class Decision(BaseModel):
    approved: bool


class SmsConfirmation(BaseModel):
    confirmed: Literal[True]


class BrowserEvent(BaseModel):
    session_token: str = Field(min_length=32, max_length=100)
    event_id: str = Field(min_length=1, max_length=100)
    kind: Literal['registered', 'connected', 'transcript', 'ended', 'error']
    provider_call_id: str = Field(default='', max_length=200)
    role: Literal['assistant', 'user'] = 'user'
    text: str = Field(default='', max_length=6000)


def require_task(task_id):
    task = store.get(task_id)
    if not task:
        raise HTTPException(404, 'Task not found')
    return task


def log(task, agent, message):
    task['activity'].append({'agent': agent, 'message': message, 'at': now()})
    store.save(task)


def say(task, role, text):
    task['transcript'].append({'role': role, 'text': text, 'at': now()})
    store.save(task)


def launch(task_id, coroutine):
    job = asyncio.create_task(coroutine)
    jobs[task_id] = job
    def forget(done):
        if jobs.get(task_id) is done:
            jobs.pop(task_id, None)
    job.add_done_callback(forget)


def live_configured():
    if os.getenv('PHONE_PROVIDER', 'elevenlabs') == 'elevenlabs':
        return elevenlabs_phone.configured()
    if os.getenv('PHONE_PROVIDER') != 'vapi':
        return False
    return all(os.getenv(k) for k in ['VAPI_API_KEY', 'VAPI_PHONE_NUMBER_ID',
                                     'VAPI_ASSISTANT_ID', 'VAPI_WEBHOOK_SECRET', 'ALLOWED_PHONE_NUMBERS'])


def browser_assistant():
    return os.getenv('VAPI_BROWSER_ASSISTANT_ID') or os.getenv('VAPI_ASSISTANT_ID', '')


def browser_configured():
    return bool(os.getenv('VAPI_PUBLIC_KEY') and browser_assistant() and os.getenv('VAPI_WEBHOOK_SECRET'))


@app.get('/api/health')
async def health(request: Request):
    if access.required() and not access.valid(request.cookies.get(access.COOKIE, '')):
        return {'ok': True, 'access_protected': True, 'login_required': True}
    return {'ok': True, 'demo': True, 'claude': agents.configured,
            'public_demo': public_demo.enabled(),
            'phone_provider': os.getenv('PHONE_PROVIDER', 'elevenlabs'),
            'live': live_configured() and not public_demo.enabled(),
            'browser': browser_configured() and not public_demo.enabled(),
            'spacetime': app.state.spacetime.info(),
            'sms': {'configured': False, 'recipient': None} if public_demo.enabled() else sms.info(),
            'access_protected': access.required(),
            'login_required': access.required() and not access.valid(request.cookies.get(access.COOKIE, '')),
            'storage': 'SQLite + SSE', 'orchestration': 'Fetch.ai uAgents (local)',
            'fetch': agents.info()}


@app.get('/api/tasks')
async def list_tasks(request: Request):
    tasks = store.all()
    if public_demo.enabled():
        tasks = [task for task in tasks if task.get('visitor_id') == request.state.visitor_id]
    return tasks


@app.get('/api/demo/session')
async def demo_session():
    return {'public_demo': False}


@app.get('/api/tasks/{task_id}')
async def get_task(task_id: str):
    return require_task(task_id)


@app.get('/api/tasks/{task_id}/sms')
async def preview_sms(task_id: str):
    task = require_task(task_id)
    if not task.get('summary'):
        raise HTTPException(409, 'Wait for the summary before sending an SMS')
    return {**sms.info(), 'body': sms.body(task), 'delivery': task.get('sms')}


@app.post('/api/tasks/{task_id}/sms')
async def send_sms(task_id: str, data: SmsConfirmation):
    task = require_task(task_id)
    if not sms.configured():
        raise HTTPException(503, 'Twilio SMS is not configured')
    if not task.get('summary'):
        raise HTTPException(409, 'Wait for the summary before sending an SMS')
    # Reserve before yielding to the network. Unknown outcomes cannot be retried:
    # the provider may already have accepted the message and charged for it.
    if task.get('sms') and task['sms']['status'] != 'failed':
        raise HTTPException(409, 'This summary already has an SMS attempt. Check Twilio before sending again.')
    task['sms'] = {'status': 'sending', 'attempted_at': now()}
    store.save(task)
    try:
        delivery = await sms.send(task)
    except httpx.HTTPStatusError as error:
        delivery = {'status': 'failed' if 400 <= error.response.status_code < 500 else 'unknown'}
    except (httpx.HTTPError, ValueError):
        delivery = {'status': 'unknown'}
    except asyncio.CancelledError:
        fresh = require_task(task_id)
        fresh['sms']['status'] = 'unknown'
        store.save(fresh)
        raise
    fresh = require_task(task_id)
    fresh['sms'].update(delivery)
    log(fresh, 'Reporter', f"SMS attempt status: {delivery['status']}. Provider acceptance does not imply delivery.")
    return fresh['sms']


@app.post('/api/tasks/{task_id}/sms/status')
async def refresh_sms_status(task_id: str):
    task = require_task(task_id)
    if not (task.get('sms') or {}).get('id'):
        raise HTTPException(409, 'No confirmed provider message ID is available; check Twilio')
    try:
        status = await sms.status(task['sms']['id'])
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Twilio message status could not be checked')
    task = require_task(task_id)
    task['sms']['status'] = status
    store.save(task)
    return task['sms']


@app.post('/api/tasks', status_code=201)
async def create_task(data: TaskInput, request: Request):
    if public_demo.enabled():
        if data.mode != 'demo':
            raise HTTPException(403, 'The public demo supports simulations only; no real calls or SMS.')
        error = public_demo.creation_error(store, request.state.visitor_id)
        if error:
            raise HTTPException(429, error)
    if not agents.ready:
        raise HTTPException(503, 'Fetch.ai orchestration is unavailable')
    if not data.goal.strip() or len(data.goal.strip()) < 5:
        raise HTTPException(422, 'Describe your goal in at least five characters')
    if data.mode == 'browser' and not browser_configured():
        raise HTTPException(503, 'Browser voice needs a Vapi public key, assistant ID, and authenticated approval webhook. Use demo mode until configured.')
    if data.mode == 'live':
        if not live_configured():
            raise HTTPException(503, 'Live calling is not configured. Use demo mode.')
        allowed = {p.strip() for p in os.getenv('ALLOWED_PHONE_NUMBERS', '').split(',')}
        if not data.teammate_confirmed or not re.fullmatch(r'\+[1-9]\d{7,14}', data.phone) or data.phone not in allowed:
            raise HTTPException(422, 'Phone calls require an explicitly confirmed, allowlisted number in E.164 format')
    task = {'id': str(uuid4()), **data.model_dump(), 'goal': data.goal.strip(),
            'status': 'planning', 'created_at': now(), 'updated_at': now(),
            'plan': [], 'transcript': [], 'activity': [], 'approval': None, 'summary': None,
            'error': None, 'provider_call_id': None,
            'engine': 'claude' if agents.configured else 'scripted'}
    if data.mode == 'live':
        task['phone_provider'] = os.getenv('PHONE_PROVIDER', 'elevenlabs')
    if public_demo.enabled():
        task['visitor_id'] = request.state.visitor_id
    store.save(task)
    launch(task['id'], run(task['id']))
    return task


@app.post('/api/tasks/{task_id}/approvals/{approval_id}')
async def decide(task_id: str, approval_id: str, data: Decision):
    task = require_task(task_id)
    approval = task.get('approval')
    if task['status'] != 'awaiting_approval' or not approval or approval['id'] != approval_id or approval['status'] != 'pending':
        raise HTTPException(409, 'This approval is no longer pending')
    approval['status'] = 'approved' if data.approved else 'declined'
    task['decision'] = approval['status']
    task.setdefault('approval_history', []).append({**approval, 'decided_at': now()})
    log(task, 'Guardrail', f"User {approval['status']} this specific request.")
    return task


@app.post('/api/tasks/{task_id}/cancel')
async def cancel(task_id: str):
    task = require_task(task_id)
    if task['status'] in TERMINAL:
        return task
    if task['mode'] == 'live' or (task['mode'] == 'browser' and task['status'] not in {'planning', 'ready'}):
        provider = 'ElevenLabs' if task.get('phone_provider') == 'elevenlabs' else 'Vapi'
        raise HTTPException(409, f'End live calls in the {provider} dashboard; local cancellation cannot confirm a hangup.')
    task['status'] = 'cancelled'
    task.pop('next_speaker', None)
    if task.get('approval') and task['approval']['status'] == 'pending':
        task['approval']['status'] = 'expired'
    store.save(task)
    if task_id in jobs:
        jobs[task_id].cancel()
    return task


@app.get('/api/tasks/{task_id}/events')
async def events(task_id: str, request: Request, last_event_id: str = Header(default='0')):
    require_task(task_id)
    try:
        cursor = max(0, int(last_event_id))
    except ValueError:
        raise HTTPException(400, 'Invalid event cursor')

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            batch = store.events(task_id, cursor)
            for seq, data in batch:
                cursor = seq
                yield f'id: {seq}\ndata: {data}\n\n'
            if not batch:
                yield ': heartbeat\n\n'
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


async def run(task_id):
    try:
        task = require_task(task_id)
        log(task, 'Orchestrator', 'Routing this task to the Planner through Fetch.ai uAgents.')
        log(task, 'Planner', 'Claude is creating a plan from your goal and constraints.'
            if task.get('engine') == 'claude' else 'Turning your goal into a call plan.')
        task['plan'] = await agents.plan(task)
        log(task, 'Planner', 'Plan ready. Approval is required before commitments or sensitive disclosures.')
        if task['mode'] == 'live':
            await start_live(task)
        elif task['mode'] == 'browser':
            task['status'] = 'ready'
            log(task, 'Caller', 'Browser plan ready. Press Talk to HoldOn to enable your microphone and connect. No number is dialed.')
        else:
            await simulate(task)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception('Task execution failed: %s', task_id)
        task = require_task(task_id)
        task['status'] = 'failed'
        task.pop('next_speaker', None)
        task['error'] = error_message(error)
        task['error_code'] = error_code(error)
        store.save(task)


async def simulate(task):
    delay = float(os.getenv('DEMO_STEP_SECONDS', '1.5'))
    generated = task.get('engine') == 'claude'
    proposal = None

    async def deliver(role, text):
        task['next_speaker'] = role
        store.save(task)
        # Pace simulated turns by their length; tests can explicitly use zero delay.
        pause = max(delay, min(4, len(text.split()) / 10)) if delay >= 0.01 else delay
        await asyncio.sleep(pause)
        task.pop('next_speaker', None)
        say(task, role, text)
    if generated:
        log(task, 'Negotiator', 'Claude is preparing a goal-specific simulated conversation and proposed terms.')
        proposal = await agents.negotiate(task)
        # Keep the proposal local; the approval branch is never emitted in advance.
    await asyncio.sleep(delay)
    task['status'] = 'calling'
    log(task, 'Caller', 'Starting a simulated call. No phone number is dialed.')
    opening = [(line['role'], line['text']) for line in proposal['opening']] if generated else [
        ('assistant', 'Hi, I’m HoldOn, calling on behalf of my user. Is now a good time?'),
        ('representative', 'Of course. How can I help you today?'),
        ('assistant', f"My user’s goal is: {task['goal']}"),
        ('representative', 'Let me review the available options. Please hold for a moment.'),
    ]
    for role, text in opening:
        await asyncio.sleep(delay)
        await deliver(role, text)
    if not generated:
        task['status'] = 'on_hold'
        log(task, 'Caller', 'Simulated hold detected. Waiting for the representative.')
        await asyncio.sleep(delay * 2)
    # Each rejection is scoped to a proposal, not to the whole conversation.
    max_proposals = 3 if generated else 1
    for round_index in range(max_proposals):
        task['status'] = 'in_progress'
        await deliver('representative', proposal['offer'] if generated else 'I can make the requested change with no added fee. May I proceed?')
        if generated and proposal.get('action_type') == 'information':
            task['resolution'] = 'information_only'
            log(task, 'Negotiator', 'Explained the available information. No account action or disclosure was requested, so no approval is needed.')
            await deliver('assistant', 'Got it, thanks. I’ll pass that along.')
            break
        log(task, 'Negotiator', f'Proposal {round_index + 1}: requesting your approval of these specific terms.')
        if proposal is None:
            proposal = await agents.negotiate(task)
        await deliver('assistant', proposal['reply'])
        task.pop('decision', None)
        task['approval'] = await agents.review(task, proposal['description'])
        task['status'] = 'awaiting_approval'
        log(task, 'Guardrail', 'Paused for your decision. No action has been authorized.')
        for _ in range(120 if public_demo.enabled() else 600):
            await asyncio.sleep(0.5)
            task = require_task(task['id'])
            if task['status'] == 'cancelled':
                return
            if task['approval']['status'] != 'pending':
                break
        else:
            task['approval']['status'] = 'expired'
            task['decision'] = 'declined'
            task.setdefault('approval_history', []).append({**task['approval'], 'decided_at': now()})
            log(task, 'Guardrail', 'Approval timed out. Ending without authorizing any action.')
        approved = await agents.authorize(task, task['approval']['id'])
        expired = task['approval']['status'] == 'expired'
        task['status'] = 'in_progress'
        if approved:
            await deliver('assistant', proposal['approved_reply'] if generated else 'My user approves this change with no added fee.')
            await asyncio.sleep(delay)
            await deliver('representative', proposal['approved_result'] if generated else
                'All set. Your confirmation number is HOLD-2048. Have a great day!')
            if generated:
                await deliver('assistant', 'Thanks for your help. I’ll pass that along. Have a good day.')
            break
        if not generated or expired:
            await deliver('assistant', 'My user has not authorized this proposal. Please leave everything unchanged. Thank you.')
            break
        # Model-generated decline text may imply hangup; enforce continuation here.
        await deliver('assistant', 'They’d like to pass on that. Please don’t change anything. What else could we try?')
        await deliver('representative', 'Sure, I haven’t changed anything. Let’s look at another option.')
        if round_index + 1 == max_proposals:
            await deliver('assistant', 'We haven’t found a suitable option. Let’s leave things as they are. Thanks for checking.')
            log(task, 'Negotiator', 'Three proposals declined. Ending without agreement or account changes.')
            break
        task['simulation_round'] = round_index + 2
        log(task, 'Negotiator', 'Your proposal was declined. Claude is looking for a different option within your original limits.')
        proposal = await agents.negotiate(task)
        for line in proposal['opening']:
            await asyncio.sleep(delay)
            await deliver(line['role'], line['text'])
    log(task, 'Reporter', 'Claude is summarizing the recorded conversation and your decision.' if generated else 'Preparing the simulation summary.')
    task['summary'] = await agents.report(task)
    task['status'] = 'completed'
    log(task, 'Reporter', 'Call summary ready.')


async def start_live(task):
    if task.get('phone_provider') == 'elevenlabs':
        await elevenlabs_phone.start(task, store, log)
        return
    # Use an existing, reviewed Vapi assistant; never improvise a voice configuration.
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post('https://api.vapi.ai/call',
            headers={'Authorization': f"Bearer {os.environ['VAPI_API_KEY']}"}, json={
                'assistantId': os.environ['VAPI_ASSISTANT_ID'],
                'phoneNumberId': os.environ['VAPI_PHONE_NUMBER_ID'],
                'customer': {'number': task['phone']},
                'assistantOverrides': {'variableValues': {
                    'goal': task['goal'], 'context': task['context'], 'plan': '\n'.join(task['plan'])}},
            })
        response.raise_for_status()
        task['provider_call_id'] = response.json()['id']
    task['status'] = 'calling'
    log(task, 'Caller', 'Vapi accepted the outbound call. Waiting for authenticated provider events.')


@app.post('/api/tasks/{task_id}/browser/session')
async def browser_session(task_id: str):
    task = require_task(task_id)
    if not browser_configured():
        raise HTTPException(503, 'Browser voice is not configured')
    if task['mode'] != 'browser' or task['status'] != 'ready':
        raise HTTPException(409, 'This task is not ready for a new browser session. Calls are never retried automatically.')
    token = secrets.token_urlsafe(32)
    task['browser_session_hash'] = hashlib.sha256(token.encode()).hexdigest()
    task['browser_events'] = []
    task['status'] = 'calling'
    log(task, 'Caller', 'Connecting browser audio to Vapi. You play the representative; no phone number is dialed.')
    return {'session_token': token, 'public_key': os.environ['VAPI_PUBLIC_KEY'],
            'assistant_id': browser_assistant(), 'assistant_overrides': {
                'firstMessage': 'Hi, I’m HoldOn, calling on behalf of my user. For this browser demo, you can play the representative. Is now a good time?',
                'clientMessages': ['transcript', 'speech-update', 'status-update'],
                'variableValues': {'goal': task['goal'], 'context': task['context'],
                    'plan': '\n'.join(task['plan']), 'holdon_task_id': task_id, 'holdon_session': token}}}


async def report_browser(task_id):
    task = require_task(task_id)
    try:
        summary = await agents.report(task)
    except Exception:
        logger.exception('Browser reporting failed: %s', task_id)
        summary = 'Review the saved transcript; automatic reporting was unavailable.'
    fresh = require_task(task_id)
    # Authenticated provider end reports take precedence over client-disconnect reports.
    if fresh.get('provider_report_received'):
        return
    fresh['summary'] = 'Browser role-play ended. No real account change was performed. ' + summary
    log(fresh, 'Reporter', 'Browser session summary ready from the saved transcript.')


@app.post('/api/tasks/{task_id}/browser/events')
async def browser_event(task_id: str, data: BrowserEvent):
    task = require_task(task_id)
    token_hash = hashlib.sha256(data.session_token.encode()).hexdigest()
    if task['mode'] != 'browser' or not hmac.compare_digest(task.get('browser_session_hash', ''), token_hash):
        raise HTTPException(401, 'Invalid browser session')
    if data.event_id in task.get('browser_events', []) or task['status'] in TERMINAL:
        return {'ok': True}
    if data.kind == 'registered':
        if not data.provider_call_id:
            raise HTTPException(422, 'A Vapi call ID is required')
        if task.get('provider_call_id') not in {None, data.provider_call_id} or any(
            t['id'] != task_id and t.get('provider_call_id') == data.provider_call_id for t in store.all()):
            raise HTTPException(409, 'Call ID is already associated with another session')
        task['provider_call_id'] = data.provider_call_id
    task.setdefault('browser_events', []).append(data.event_id)
    if data.kind == 'connected':
        # A repeated transport event must never dismiss an outstanding approval.
        if task['status'] != 'awaiting_approval':
            task['status'] = 'in_progress'
        log(task, 'Caller', 'Browser audio connected. Vapi is handling the voice conversation.')
    elif data.kind == 'transcript':
        if data.text.strip():
            say(task, data.role, data.text.strip())
    elif data.kind in {'ended', 'error'}:
        task['status'] = 'completed' if data.kind == 'ended' else 'failed'
        if task.get('approval') and task['approval']['status'] == 'pending':
            task['approval']['status'] = 'expired'
        if data.kind == 'error':
            task['error'] = 'Browser voice could not complete. Check microphone permissions, Vapi configuration, and the provider dashboard before starting a new session.'
        log(task, 'Caller', 'Browser audio disconnected. Check Vapi to confirm provider-side call termination if the connection was interrupted.')
        launch(task_id, report_browser(task_id))
    else:
        store.save(task)
    # Blank transcripts still need their event ID persisted for idempotency.
    if data.kind == 'transcript' and not data.text.strip():
        store.save(task)
    return {'ok': True}



@app.post('/api/webhooks/vapi')
async def vapi_webhook(request: Request, x_vapi_secret: str = Header(default='')):
    secret = os.getenv('VAPI_WEBHOOK_SECRET', '')
    if not secret or not hmac.compare_digest(secret, x_vapi_secret):
        raise HTTPException(401, 'Invalid webhook secret')
    payload = await request.json()
    message = payload.get('message', {})
    call = message.get('call', {})
    call_id = call.get('id')
    task = next((t for t in store.all() if t.get('provider_call_id') == call_id and call_id
                 and t.get('phone_provider', 'vapi') == 'vapi'), None)
    if not task and call_id:
        # Vapi can send its first webhook before start() resolves in the browser.
        variables = (call.get('assistantOverrides') or {}).get('variableValues') or {}
        candidate = store.get(str(variables.get('holdon_task_id', '')))
        token_hash = hashlib.sha256(str(variables.get('holdon_session', '')).encode()).hexdigest()
        if (candidate and candidate['mode'] == 'browser' and candidate.get('browser_session_hash')
                and hmac.compare_digest(candidate['browser_session_hash'], token_hash)
                and candidate.get('provider_call_id') in {None, call_id}):
            task = candidate
            task['provider_call_id'] = call_id
            store.save(task)
    if not task:
        raise HTTPException(404, 'Call not found; retry after call registration')
    kind = message.get('type')
    browser_end_report = (task['mode'] == 'browser' and kind == 'end-of-call-report'
                          and not task.get('provider_report_received'))
    if task['status'] in TERMINAL and not browser_end_report:
        return {'results': [{'toolCallId': c['id'], 'result': 'DENIED: call is no longer active.'}
                            for c in message.get('toolCallList', [])]}
    if kind == 'tool-calls':
        results = []
        for call in message.get('toolCallList', []):
            name = call.get('function', {}).get('name')
            if name != 'request_approval':
                results.append({'toolCallId': call['id'], 'result': 'DENIED: unknown tool.'})
                continue
            args = call['function'].get('arguments', {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            task = require_task(task['id'])
            if task.get('approval') and task['approval']['status'] == 'pending':
                results.append({'toolCallId': call['id'], 'result': 'DENIED: another approval is pending.'})
                continue
            # Recheck after the asynchronous role handoff: another webhook may
            # have requested approval or ended the call while the agent replied.
            approval = await agents.review(task, str(args.get('description', 'Unspecified action')))
            task = require_task(task['id'])
            if task['status'] in TERMINAL or (task.get('approval') and task['approval']['status'] == 'pending'):
                results.append({'toolCallId': call['id'], 'result': 'DENIED: call ended or another approval is pending.'})
                continue
            task['approval'] = approval
            task['status'] = 'awaiting_approval'
            log(task, 'Guardrail', 'Live caller requested authorization. Waiting up to 20 seconds.')
            for _ in range(40):
                await asyncio.sleep(0.5)
                task = require_task(task['id'])
                if task['status'] in TERMINAL or task['approval']['status'] != 'pending':
                    break
            approval_id = task['approval']['id']
            permitted = await agents.authorize(task, approval_id)
            task = require_task(task['id'])
            if task['approval']['id'] != approval_id:
                results.append({'toolCallId': call['id'], 'result': 'DENIED: approval was superseded.'})
                continue
            permitted = permitted and task['status'] not in TERMINAL
            if task['approval']['status'] == 'pending':
                task['approval']['status'] = 'expired'
            if task['status'] not in TERMINAL:
                task['status'] = 'in_progress'
            store.save(task)
            results.append({'toolCallId': call['id'], 'result':
                            'APPROVED for this exact action only.' if permitted else 'DENIED. Do not perform this action.'})
        return {'results': results}
    if kind == 'transcript' and message.get('transcriptType') == 'final' and task['mode'] != 'browser':
        say(task, message.get('role', 'representative'), str(message.get('transcript', '')))
    elif kind == 'status-update' and message.get('status') == 'in-progress' and task['status'] != 'awaiting_approval':
        task['status'] = 'in_progress'
        store.save(task)
    elif kind == 'end-of-call-report':
        task['status'] = 'completed'
        task['provider_report_received'] = True
        if task['mode'] == 'browser':
            # Prefer the authenticated end artifact when supplied, without
            # duplicating SDK transcripts or exposing hidden system messages.
            lines = [{'role': line['role'], 'text': line['message'], 'at': now()}
                     for line in (message.get('artifact') or {}).get('messages', [])
                     if line.get('role') in {'user', 'assistant'} and isinstance(line.get('message'), str)]
            if lines:
                task['transcript'] = lines
        if task.get('approval') and task['approval']['status'] == 'pending':
            task['approval']['status'] = 'expired'
        store.save(task)
        try:
            task['summary'] = await agents.report(task)
            if task['mode'] == 'browser':
                task['summary'] = 'Browser role-play ended. No real account change was performed. ' + task['summary']
        except Exception:
            task['summary'] = 'Call ended. Automatic reporting failed; review the transcript for the outcome.'
        # Preserve concurrent changes when reporting yields to another request.
        fresh = require_task(task['id'])
        fresh['summary'] = task['summary']
        log(fresh, 'Reporter', 'Provider reported the call ended. Summary ready.')
    return {'ok': True}

elevenlabs_phone.attach_routes(app, lambda: store, agents, log)

# Docker serves the built dashboard and API from one HTTPS origin. Development
# still uses Vite's /api proxy. Mount last so API routes retain precedence.
frontend_dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if frontend_dist.is_dir():
    app.mount('/', StaticFiles(directory=frontend_dist, html=True), name='dashboard')
