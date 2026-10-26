"""ElevenLabs SIP outbound calls, authenticated approvals and final transcripts."""
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone

import httpx
from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, Field

from .errors import AgentError
from .store import now

TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}


def configured():
    return all(os.getenv(key) for key in ['ELEVENLABS_API_KEY', 'ELEVENLABS_AGENT_ID',
        'ELEVENLABS_PHONE_NUMBER_ID', 'ELEVENLABS_WEBHOOK_SECRET', 'ELEVENLABS_TOOL_SECRET',
        'ALLOWED_PHONE_NUMBERS'])


async def start(task, store, log):
    token = secrets.token_urlsafe(32)
    task['phone_session_hash'] = hashlib.sha256(token.encode()).hexdigest()
    task['phone_provider'] = 'elevenlabs'
    task['phone_agent_id'] = os.environ['ELEVENLABS_AGENT_ID']
    task['call_attempt_status'] = 'requesting'
    task['status'] = 'calling'
    log(task, 'Caller', 'Requesting an ElevenLabs SIP phone call. No automatic retries.')
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
            response = await client.post('https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call',
                headers={'xi-api-key': os.environ['ELEVENLABS_API_KEY']}, json={
                    'agent_id': os.environ['ELEVENLABS_AGENT_ID'],
                    'agent_phone_number_id': os.environ['ELEVENLABS_PHONE_NUMBER_ID'],
                    'to_number': task['phone'],
                    'conversation_initiation_client_data': {'dynamic_variables': {
                        'goal': task['goal'], 'context': task['context'], 'plan': '\n'.join(task['plan']),
                        'holdon_task_id': task['id'], 'secret__holdon_task_id': task['id'],
                        'secret__holdon_session': token}}})
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        fresh = store.get(task['id'])
        if fresh.get('eleven_report_received'):
            return  # A signed final report is stronger evidence than an HTTP timeout.
        fresh['call_attempt_status'] = 'unknown'
        store.save(fresh)
        raise AgentError('phone_unconfirmed') from error
    fresh = store.get(task['id'])
    if fresh.get('eleven_report_received'):
        return
    if result.get('success') is not True or not result.get('conversation_id'):
        fresh['call_attempt_status'] = 'unknown'
        store.save(fresh)
        raise AgentError('phone_unconfirmed')
    fresh = store.get(task['id'])  # Preserve early provider callbacks.
    if fresh.get('provider_call_id') not in {None, result['conversation_id']}:
        raise AgentError('phone_unconfirmed')
    fresh['provider_call_id'] = result['conversation_id']
    fresh['call_attempt_status'] = 'accepted'
    log(fresh, 'Caller', 'ElevenLabs accepted the phone call. Final transcript arrives through its authenticated post-call webhook.')


def valid_signature(raw, header):
    secret = os.getenv('ELEVENLABS_WEBHOOK_SECRET', '')
    if not secret:
        return False
    try:
        parts = [part.strip().split('=', 1) for part in header.split(',')]
        timestamp = next(value for key, value in parts if key == 't')
        if abs(time.time() - int(timestamp)) > 1800:
            return False
        expected = hmac.new(secret.encode(), timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        return any(key == 'v0' and hmac.compare_digest(expected, value) for key, value in parts)
    except (ValueError, StopIteration, TypeError):
        return False


def transcript_time(data, turn):
    start_time = (data.get('metadata') or {}).get('start_time_unix_secs')
    offset = turn.get('time_in_call_secs', 0)
    if isinstance(start_time, (int, float)) and isinstance(offset, (int, float)) and offset >= 0:
        try:
            return datetime.fromtimestamp(start_time + offset, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return now()


class ApprovalInput(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=5, max_length=1500)


def attach_routes(app, get_store, agents, log):
    @app.post('/api/webhooks/elevenlabs/approval')
    async def approval(data: ApprovalInput, authorization: str = Header(default=''),
                       x_holdon_task_id: str = Header(default=''), x_holdon_session: str = Header(default='')):
        secret = os.getenv('ELEVENLABS_TOOL_SECRET', '')
        if not secret or not hmac.compare_digest(authorization.encode(), ('Bearer ' + secret).encode()):
            raise HTTPException(401, 'Invalid tool authorization')
        store = get_store()
        task = store.get(x_holdon_task_id)
        session_hash = hashlib.sha256(x_holdon_session.encode()).hexdigest()
        if (not task or task.get('phone_provider') != 'elevenlabs' or task['mode'] != 'live'
                or not task.get('phone_session_hash')
                or not hmac.compare_digest(task['phone_session_hash'], session_hash)):
            raise HTTPException(401, 'Invalid call session')
        denied = {'result': 'DENIED. Do not perform this action.'}
        if (task['status'] in TERMINAL or data.request_id in task.get('phone_tool_requests', [])
                or (task.get('approval') and task['approval']['status'] == 'pending')):
            return denied
        # Reserve the ID before yielding. A replay must never execute an approved action twice.
        task.setdefault('phone_tool_requests', []).append(data.request_id)
        store.save(task)
        try:
            record = await agents.review(task, data.description)
        except Exception:
            return denied
        task = store.get(task['id'])
        if task['status'] in TERMINAL or (task.get('approval') and task['approval']['status'] == 'pending'):
            return denied
        task['approval'] = record
        task.pop('decision', None)
        task['status'] = 'awaiting_approval'
        log(task, 'Guardrail', 'Phone caller requested approval. Waiting up to 20 seconds for your exact decision.')
        for _ in range(40):
            await asyncio.sleep(0.5)
            task = store.get(task['id'])
            if task['status'] in TERMINAL or task['approval']['id'] != record['id'] or task['approval']['status'] != 'pending':
                break
        if task['approval']['id'] != record['id']:
            return denied
        try:
            permitted = await agents.authorize(task, record['id'])
        except Exception:
            permitted = False
        task = store.get(task['id'])
        permitted = (permitted and task['status'] not in TERMINAL and task['approval']['id'] == record['id']
                     and task['approval']['status'] == 'approved')
        if task['approval']['status'] == 'pending':
            task['approval']['status'] = 'expired'
        if task['status'] not in TERMINAL:
            task['status'] = 'in_progress'
        store.save(task)
        return {'result': 'APPROVED for this exact action only.'} if permitted else denied

    @app.post('/api/webhooks/elevenlabs')
    async def webhook(request: Request, elevenlabs_signature: str = Header(default='')):
        raw = await request.body()
        if not valid_signature(raw, elevenlabs_signature):
            raise HTTPException(401, 'Invalid ElevenLabs signature')
        try:
            payload = json.loads(raw)
        except ValueError:
            raise HTTPException(400, 'Invalid JSON')
        if not isinstance(payload, dict) or not isinstance(payload.get('data', {}), dict):
            raise HTTPException(400, 'Invalid event shape')
        kind, data = payload.get('type'), payload.get('data', {})
        if kind not in {'post_call_transcription', 'call_initiation_failure'}:
            return {'ok': True}
        if not data.get('agent_id') or not data.get('conversation_id'):
            raise HTTPException(404, 'Call not found')
        store = get_store()
        conversation_id = data['conversation_id']
        task = next((task for task in store.all() if task.get('phone_provider') == 'elevenlabs'
                     and task.get('provider_call_id') == conversation_id), None)
        if not task:
            variables = (data.get('conversation_initiation_client_data') or {}).get('dynamic_variables', {})
            candidate = store.get(str(variables.get('holdon_task_id', '')))
            if (candidate and candidate.get('phone_provider') == 'elevenlabs' and candidate['mode'] == 'live'
                    and candidate.get('phone_agent_id') == data['agent_id']
                    and candidate.get('call_attempt_status') in {'requesting', 'unknown'}
                    and candidate.get('provider_call_id') in {None, conversation_id}):
                task = candidate
                task['provider_call_id'] = conversation_id
        if not task or task.get('phone_agent_id') != data['agent_id']:
            raise HTTPException(404, 'Call not found')
        if task.get('eleven_report_received'):
            return {'ok': True}
        task['eleven_report_received'] = True
        if task.get('approval') and task['approval']['status'] == 'pending':
            task['approval']['status'] = 'expired'
        if kind == 'call_initiation_failure':
            task['status'] = 'failed'
            task['call_attempt_status'] = 'failed'
            task['error'] = 'The phone call did not connect. Check ElevenLabs and the carrier before starting another call.'
            log(task, 'Caller', 'ElevenLabs reported that the call did not connect.')
            return {'ok': True}
        task['transcript'] = [{'role': 'assistant' if turn['role'] == 'agent' else 'representative',
                               'text': turn['message'], 'at': transcript_time(data, turn)}
                              for turn in data.get('transcript', [])
                              if turn.get('role') in {'agent', 'user'} and isinstance(turn.get('message'), str)
                              and turn['message'].strip()]
        task['status'] = 'failed' if data.get('status') == 'failed' else 'completed'
        task['error'] = 'ElevenLabs reported that this conversation failed. Review its transcript and provider logs.' if task['status'] == 'failed' else None
        task['call_attempt_status'] = 'finished'
        task['summary'] = (data.get('analysis') or {}).get('transcript_summary') or 'Phone call ended. Review the saved transcript for the outcome.'
        log(task, 'Reporter', 'ElevenLabs delivered the actual phone transcript and post-call report.')
        return {'ok': True}
