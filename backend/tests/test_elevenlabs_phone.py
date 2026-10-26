import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main

HTTP_CLIENT = httpx.AsyncClient

@pytest.fixture
def phone(tmp_path, monkeypatch):
    settings = {'ELEVENLABS_API_KEY': 'test-eleven-key', 'ELEVENLABS_AGENT_ID': 'agent-test',
                'ELEVENLABS_PHONE_NUMBER_ID': 'phone-test', 'ELEVENLABS_WEBHOOK_SECRET': 'test-webhook-secret',
                'ELEVENLABS_TOOL_SECRET': 'test-tool-secret', 'ALLOWED_PHONE_NUMBERS': '+14155551234',
                'HOLDON_REQUIRE_AUTH': '0'}
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('HOLDON_PUBLIC_DEMO', raising=False)
    monkeypatch.delenv('SPACETIMEDB_TOKEN', raising=False)
    monkeypatch.setattr(main, 'store', main.Store(str(tmp_path / 'phone.sqlite3')))
    sent = []

    def transport(request):
        assert request.method == 'POST'
        assert str(request.url) == 'https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call'
        assert request.headers['xi-api-key'] == 'test-eleven-key'
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={'success': True, 'conversation_id': 'conv-test', 'sip_call_id': 'sip-test'})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
        HTTP_CLIENT(transport=httpx.MockTransport(transport), **kwargs))
    with TestClient(main.app, base_url='https://holdon.test') as client:
        yield client, sent


def create(client):
    response = client.post('/api/tasks', json={'mode': 'live', 'goal': 'Ask about a lower internet rate',
        'phone': '+14155551234', 'teammate_confirmed': True})
    assert response.status_code == 201
    ident = response.json()['id']
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = client.get('/api/tasks/' + ident).json()
        if task.get('provider_call_id'):
            return task
        time.sleep(0.02)
    pytest.fail('Phone adapter did not register its conversation')


def report(client, data, timestamp=None, signature=None, kind='post_call_transcription'):
    body = json.dumps({'type': kind, 'data': data}).encode()
    stamp = str(timestamp or int(time.time()))
    digest = hmac.new(b'test-webhook-secret', stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    return client.post('/api/webhooks/elevenlabs', content=body,
        headers={'elevenlabs-signature': signature or f't={stamp},v0={digest}', 'Content-Type': 'application/json'})


def test_elevenlabs_outbound_configuration_and_actual_transcript(phone):
    client, sent = phone
    status = client.get('/api/health').json()
    assert status['live'] and status['phone_provider'] == 'elevenlabs'
    assert 'test-eleven-key' not in str(status)
    assert client.post('/api/tasks', json={'goal': 'Call an unapproved number', 'mode': 'live',
        'phone': '+14155559999', 'teammate_confirmed': True}).status_code == 422
    assert not sent
    task = create(client)
    assert len(sent) == 1 and sent[0]['to_number'] == '+14155551234'
    assert sent[0]['agent_id'] == 'agent-test' and sent[0]['agent_phone_number_id'] == 'phone-test'
    assert task['call_attempt_status'] == 'accepted'
    assert 'ElevenLabs' in client.post(f"/api/tasks/{task['id']}/cancel").json()['detail']
    nonce = sent[0]['conversation_initiation_client_data']['dynamic_variables']['secret__holdon_session']
    assert nonce not in json.dumps(task)
    data = {'agent_id': 'agent-test', 'conversation_id': 'conv-test', 'transcript': [
        {'role': 'agent', 'message': 'Can you explain the available rates?', 'time_in_call_secs': 0},
        {'role': 'user', 'message': 'We need the account holder to contact us directly.', 'time_in_call_secs': 12},
        {'role': 'system', 'message': 'Internal provider configuration'}],
        'metadata': {'start_time_unix_secs': 1792874200},
        'analysis': {'transcript_summary': 'No change was made; the account holder needs to contact the provider.'}}
    assert report(client, data, signature='invalid').status_code == 401
    assert report(client, data, timestamp=int(time.time()) - 3600).status_code == 401
    assert report(client, {**data, 'agent_id': 'wrong-agent'}).status_code == 404
    assert report(client, data).status_code == 200
    finished = client.get('/api/tasks/' + task['id']).json()
    assert finished['status'] == 'completed' and len(finished['transcript']) == 2
    assert finished['transcript'][1]['role'] == 'representative'
    assert (datetime.fromisoformat(finished['transcript'][1]['at']) -
            datetime.fromisoformat(finished['transcript'][0]['at'])).total_seconds() == 12
    assert 'No change' in finished['summary'] and 'Internal' not in json.dumps(finished)
    event_count = main.store.latest_sequence()
    assert report(client, data).status_code == 200
    assert main.store.latest_sequence() == event_count


@pytest.mark.parametrize('approved', [True, False])
def test_phone_approval_auth_exact_decision_and_replay(phone, monkeypatch, approved):
    client, sent = phone
    task = create(client)
    variables = sent[0]['conversation_initiation_client_data']['dynamic_variables']
    headers = {'Authorization': 'Bearer test-tool-secret', 'x-holdon-task-id': task['id'],
               'x-holdon-session': variables['secret__holdon_session']}
    body = {'request_id': 'tool-test-1', 'description': 'Accept a ten dollar monthly discount with no contract change'}
    assert client.post('/api/webhooks/elevenlabs/approval', json=body).status_code == 401
    assert client.post('/api/webhooks/elevenlabs/approval', json=body,
                       headers={**headers, 'x-holdon-session': 'wrong-nonce'}).status_code == 401
    # Provider callbacks authenticate independently of the workspace login.
    monkeypatch.setenv('HOLDON_REQUIRE_AUTH', '1')
    monkeypatch.setenv('HOLDON_ACCESS_KEY', 'a' * 40)
    monkeypatch.setenv('PUBLIC_APP_URL', 'https://holdon.test')
    assert client.get('/api/tasks').status_code == 401
    with ThreadPoolExecutor() as executor:
        pending = executor.submit(client.post, '/api/webhooks/elevenlabs/approval', json=body, headers=headers)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            current = main.store.get(task['id'])
            if current['status'] == 'awaiting_approval':
                break
            time.sleep(0.02)
        assert current['status'] == 'awaiting_approval' and not pending.done()
        client.post('/api/login', json={'access_key': 'a' * 40})
        path = f"/api/tasks/{task['id']}/approvals/{current['approval']['id']}"
        assert client.post(path, json={'approved': approved}).status_code == 200
        result = pending.result(timeout=4)
        assert result.status_code == 200
        assert result.json()['result'].startswith('APPROVED' if approved else 'DENIED')
    # Even a previously approved tool ID must not authorize a second action.
    repeated = client.post('/api/webhooks/elevenlabs/approval', json=body, headers=headers)
    assert repeated.json()['result'].startswith('DENIED')


def test_call_start_timeout_is_never_retried(phone, monkeypatch):
    client, sent = phone
    attempts = []

    def timeout(request):
        attempts.append(request)
        raise httpx.ReadTimeout('Call status unknown', request=request)

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
        HTTP_CLIENT(transport=httpx.MockTransport(timeout), **kwargs))
    response = client.post('/api/tasks', json={'mode': 'live', 'goal': 'Ask about a lower internet rate',
        'phone': '+14155551234', 'teammate_confirmed': True})
    ident = response.json()['id']
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        task = client.get('/api/tasks/' + ident).json()
        if task['status'] == 'failed':
            break
        time.sleep(0.02)
    assert task['status'] == 'failed' and task['call_attempt_status'] == 'unknown'
    assert task['error_code'] == 'phone_unconfirmed' and len(attempts) == 1


def test_early_report_binds_only_matching_agent_and_expires_approval(phone):
    client, _ = phone
    task = create(client)
    task['provider_call_id'] = None
    task['call_attempt_status'] = 'requesting'
    task['approval'] = {'id': 'pending', 'status': 'pending', 'description': 'Change the plan'}
    task['status'] = 'awaiting_approval'
    main.store.save(task)
    data = {'agent_id': 'agent-test', 'conversation_id': 'conv-early', 'transcript': [],
            'conversation_initiation_client_data': {'dynamic_variables': {'holdon_task_id': task['id']}}}
    assert report(client, {**data, 'agent_id': 'wrong-agent'}).status_code == 404
    assert report(client, data).status_code == 200
    fresh = main.store.get(task['id'])
    assert fresh['provider_call_id'] == 'conv-early'
    assert fresh['status'] == 'completed' and fresh['approval']['status'] == 'expired'


def test_failed_call_report_records_no_invented_conversation(phone):
    client, _ = phone
    task = create(client)
    assert report(client, {'agent_id': 'agent-test', 'conversation_id': 'conv-test',
                           'failure_reason': 'no-answer'}, kind='call_initiation_failure').status_code == 200
    fresh = main.store.get(task['id'])
    assert fresh['status'] == 'failed' and fresh['call_attempt_status'] == 'failed'
    assert not fresh['transcript'] and not fresh['summary']


def test_signed_report_wins_over_an_ambiguous_outbound_response(phone, monkeypatch):
    client, _ = phone

    def already_finished(request):
        task = main.store.all()[0]
        task.update({'eleven_report_received': True, 'status': 'completed',
                     'provider_call_id': 'conv-early', 'call_attempt_status': 'finished',
                     'summary': 'The signed report arrived while the outbound request was waiting.'})
        main.store.save(task)
        raise httpx.ReadTimeout('Response was lost after the call ended', request=request)

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
        HTTP_CLIENT(transport=httpx.MockTransport(already_finished), **kwargs))
    task = create(client)
    assert task['status'] == 'completed' and task['call_attempt_status'] == 'finished'
    assert not task['error']
