import os
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

os.environ['DATABASE_PATH'] = tempfile.mktemp(suffix='.sqlite3')
os.environ['DEMO_STEP_SECONDS'] = '0.001'

import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('SPACETIMEDB_TOKEN', raising=False)
    monkeypatch.delenv('HOLDON_REQUIRE_AUTH', raising=False)
    monkeypatch.setattr(main, 'store', main.Store(str(tmp_path / 'test.sqlite3')))
    with TestClient(main.app) as client:
        yield client


def wait_for(client, task_id, status):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = client.get(f'/api/tasks/{task_id}').json()
        if task['status'] == status:
            return task
        if task['status'] == 'failed':
            pytest.fail(task['error'])
        time.sleep(0.02)
    pytest.fail(f'Task did not reach {status}: {task}')


@pytest.mark.parametrize('approved', [True, False])
def test_demo_waits_for_approval_then_reports(client, approved):
    response = client.post('/api/tasks', json={'goal': 'Ask for a lower internet bill'})
    assert response.status_code == 201
    task_id = response.json()['id']
    task = wait_for(client, task_id, 'awaiting_approval')
    assert task['approval']['status'] == 'pending'
    assert not task['summary']
    assert task['plan'] and 'AI assistant' in task['transcript'][0]['text']
    assert client.post(f'/api/tasks/{task_id}/approvals/wrong-id', json={'approved': True}).status_code == 409
    path = f"/api/tasks/{task_id}/approvals/{task['approval']['id']}"
    assert client.post(path, json={'approved': approved}).status_code == 200
    assert client.post(path, json={'approved': approved}).status_code == 409
    task = wait_for(client, task_id, 'completed')
    assert task['decision'] == ('approved' if approved else 'declined')
    assert ('HOLD-2048' in task['summary']) == approved
    assert task['provider_call_id'] is None


def test_cancel_before_approval(client):
    task_id = client.post('/api/tasks', json={'goal': 'Cancel a subscription'}).json()['id']
    response = client.post(f'/api/tasks/{task_id}/cancel')
    assert response.status_code == 200
    assert response.json()['status'] == 'cancelled'
    time.sleep(0.1)
    assert client.get(f'/api/tasks/{task_id}').json()['status'] == 'cancelled'


@pytest.mark.parametrize('decisions', [[True], [False, True], [False, False, False]])
def test_claude_simulation_uses_goal_and_waits_for_exact_decision(client, monkeypatch, decisions):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-only')
    monkeypatch.setenv('ANTHROPIC_MODEL', 'test-model')
    calls = []

    async def generated(system, payload):
        calls.append((system, payload))
        if 'Planner' in system:
            return json.dumps(['Disclose AI identity', 'Ask about refund eligibility', 'Get approval before proceeding'])
        if 'Negotiator' in system:
            return json.dumps({
                'opening': [
                    {'role': 'assistant', 'text': 'I’m asking about refund eligibility for my user.'},
                    {'role': 'representative', 'text': 'What happened with the purchase?'},
                    {'role': 'assistant', 'text': 'The user reports a duplicate charge; can you review eligibility?'},
                    {'role': 'representative', 'text': 'I can review the charge without making account changes.'}],
                'offer': 'May I open a refund eligibility review with no fee?',
                'reply': 'I will ask my user before proceeding.',
                'description': f"Authorize a no-fee refund eligibility review, option {payload['round']}?",
                'approved_reply': 'My user approves the no-fee eligibility review.',
                'approved_result': 'The simulated eligibility review is open; no refund is guaranteed.',
                'declined_reply': 'My user declines the review. Please make no changes.',
                'declined_result': 'No review was opened and nothing changed.'})
        assert payload['decision'] == ('approved' if decisions[-1] else 'declined')
        assert all('HOLD-2048' not in line['text'] for line in payload['transcript'])
        return 'Simulation summary: ' + ('Eligibility review requested; refund remains unconfirmed.'
                                         if decisions[-1] else 'Review declined; no changes made.')

    monkeypatch.setattr(main.agents.roles, 'ask', generated)
    task_id = client.post('/api/tasks', json={'goal': 'Ask for a refund of a duplicate charge',
        'context': 'Do not accept any fee.'}).json()['id']
    task = wait_for(client, task_id, 'awaiting_approval')
    assert task['engine'] == 'claude'
    assert 'eligibility review' in task['approval']['description']
    assert not any('review is open' in line['text'] for line in task['transcript'])
    assert len(calls) == 2  # No outcome or summary before the user decides.
    for index, approved in enumerate(decisions):
        old_id = task['approval']['id']
        old_path = f'/api/tasks/{task_id}/approvals/{old_id}'
        client.post(old_path, json={'approved': approved})
        if not approved and index < len(decisions) - 1:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                task = client.get(f'/api/tasks/{task_id}').json()
                if task['status'] == 'awaiting_approval' and task['approval']['id'] != old_id:
                    break
                time.sleep(0.02)
            assert task['status'] == 'awaiting_approval' and task['approval']['id'] != old_id
            assert not task['summary']
            assert 'decision' not in task  # A declined round cannot authorize its replacement.
            assert client.post(old_path, json={'approved': True}).status_code == 409
            assert len(calls[-1][1]['declined_proposals']) == index + 1
    completed = wait_for(client, task_id, 'completed')
    assert completed['summary'].startswith('Simulation summary:')
    assert len(calls) == len(decisions) + 2
    assert len(completed['approval_history']) == len(decisions)
    assert calls[0][1]['goal'] == 'Ask for a refund of a duplicate charge'
    assert calls[1][1]['context'] == 'Do not accept any fee.'
    assert ('review is open' in completed['transcript'][-1]['text']) == decisions[-1]
    assert sum('Hi, I’m HoldOn' in line['text'] for line in completed['transcript']) == 1


def test_cancel_expires_pending_approval(client):
    task_id = client.post('/api/tasks', json={'goal': 'Cancel a subscription'}).json()['id']
    task = wait_for(client, task_id, 'awaiting_approval')
    assert client.post(f'/api/tasks/{task_id}/cancel').json()['approval']['status'] == 'expired'
    assert client.post(f"/api/tasks/{task_id}/approvals/{task['approval']['id']}", json={'approved': True}).status_code == 409


def test_validation_and_missing_records(client):
    assert client.post('/api/tasks', json={'goal': '     '}).status_code == 422
    assert client.post('/api/tasks', json={'goal': 'short', 'mode': 'bogus'}).status_code == 422
    assert client.get('/api/tasks/missing').status_code == 404
    assert client.post('/api/tasks/missing/cancel').status_code == 404


def test_fetch_runtime_health_and_fail_closed_role_error(client, monkeypatch):
    status = client.get('/api/health').json()
    assert status['fetch']['ready']
    assert set(status['fetch']['agents']) == {'Orchestrator', 'Planner', 'Negotiator', 'Guardrail', 'Reporter'}
    assert not status['fetch']['public_registration']

    async def broken_planner(task):
        raise ValueError('Provider unavailable')

    monkeypatch.setattr(main.agents.roles, 'plan', broken_planner)
    task_id = client.post('/api/tasks', json={'goal': 'Ask about available appointments'}).json()['id']
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        task = client.get(f'/api/tasks/{task_id}').json()
        if task['status'] == 'failed':
            assert not task['provider_call_id']
            assert not task['approval']
            assert not main.agents.pending
            return
        time.sleep(0.02)
    pytest.fail('A failed uAgent request did not fail the task')


def test_live_mode_requires_configuration_and_allowlisted_teammate(client, monkeypatch):
    monkeypatch.delenv('VAPI_API_KEY', raising=False)
    assert client.post('/api/tasks', json={'goal': 'Call my teammate', 'mode': 'live'}).status_code == 503
    for key in ['VAPI_API_KEY', 'VAPI_PHONE_NUMBER_ID', 'VAPI_ASSISTANT_ID', 'VAPI_WEBHOOK_SECRET']:
        monkeypatch.setenv(key, 'test-only')
    monkeypatch.setenv('ALLOWED_PHONE_NUMBERS', '+14155551234')
    for data in [{'phone': '+14155551234'}, {'phone': '+14155559999', 'teammate_confirmed': True}]:
        assert client.post('/api/tasks', json={'goal': 'Call my teammate', 'mode': 'live', **data}).status_code == 422


def test_webhook_authentication(client, monkeypatch):
    monkeypatch.setenv('VAPI_WEBHOOK_SECRET', 'test-secret')
    assert client.post('/api/webhooks/vapi', json={}).status_code == 401
    assert client.post('/api/webhooks/vapi', json={}, headers={'x-vapi-secret': 'bad'}).status_code == 401
    assert client.post('/api/webhooks/vapi', json={}, headers={'x-vapi-secret': 'test-secret'}).status_code == 404


def test_live_phone_adapter_sends_only_the_confirmed_allowlisted_number(client, monkeypatch):
    import json
    import httpx
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    for key, value in {'VAPI_API_KEY': 'test-private-key', 'VAPI_PHONE_NUMBER_ID': 'test-number-id',
                       'VAPI_ASSISTANT_ID': 'test-assistant', 'VAPI_WEBHOOK_SECRET': 'test-secret',
                       'ALLOWED_PHONE_NUMBERS': '+14155551234'}.items():
        monkeypatch.setenv(key, value)
    original = httpx.AsyncClient
    requests = []
    def handle(request):
        assert str(request.url) == 'https://api.vapi.ai/call'
        assert request.headers['authorization'] == 'Bearer test-private-key'
        body = json.loads(request.content)
        assert body['customer']['number'] == '+14155551234'
        assert body['assistantId'] == 'test-assistant'
        assert body['phoneNumberId'] == 'test-number-id'
        requests.append(body)
        return httpx.Response(201, json={'id': 'mock-phone-call'})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    response = client.post('/api/tasks', json={'goal': 'Ask my teammate about a discount', 'mode': 'live',
        'phone': '+14155551234', 'teammate_confirmed': True})
    assert response.status_code == 201
    task = wait_for(client, response.json()['id'], 'calling')
    assert task['provider_call_id'] == 'mock-phone-call' and len(requests) == 1
    assert client.post(f"/api/tasks/{task['id']}/cancel").status_code == 409


def test_snapshot_persistence_and_replay(tmp_path):
    path = str(tmp_path / 'events.sqlite3')
    store = main.Store(path)
    task = {'id': 'task-1', 'created_at': main.now(), 'status': 'planning'}
    store.save(task)
    first = store.events('task-1', 0)
    task['status'] = 'completed'
    store.save(task)
    reopened = main.Store(path)
    assert reopened.get('task-1')['status'] == 'completed'
    assert len(reopened.events('task-1', first[0][0])) == 1
    assert len(reopened.all()) == 1


def test_restart_marks_unfinished_tasks_interrupted(tmp_path, monkeypatch):
    store = main.Store(str(tmp_path / 'restart.sqlite3'))
    store.save({'id': 'unfinished', 'created_at': main.now(), 'status': 'awaiting_approval'})
    monkeypatch.setattr(main, 'store', store)
    with TestClient(main.app) as client:
        task = client.get('/api/tasks/unfinished').json()
        assert task['status'] == 'interrupted'
        assert 'Server restarted' in task['error']


def live_task():
    task = {'id': 'live-task', 'goal': 'Ask my teammate about a meeting', 'context': '',
            'mode': 'live', 'status': 'in_progress', 'created_at': main.now(),
            'plan': [], 'activity': [], 'transcript': [], 'approval': None,
            'summary': None, 'provider_call_id': 'provider-call-1'}
    main.store.save(task)
    return task


def test_live_approval_tool_waits_for_specific_user_decision(client, monkeypatch):
    monkeypatch.setenv('VAPI_WEBHOOK_SECRET', 'test-secret')
    task = live_task()
    payload = {'message': {'type': 'tool-calls', 'call': {'id': 'provider-call-1'},
               'toolCallList': [{'id': 'tool-1', 'function': {'name': 'request_approval',
                  'arguments': {'description': 'Book the Tuesday meeting at no cost'}}}]}}
    with ThreadPoolExecutor() as executor:
        pending = executor.submit(client.post, '/api/webhooks/vapi', json=payload,
                                  headers={'x-vapi-secret': 'test-secret'})
        task = wait_for(client, task['id'], 'awaiting_approval')
        assert not pending.done()
        path = f"/api/tasks/{task['id']}/approvals/{task['approval']['id']}"
        client.post(path, json={'approved': False})
        response = pending.result(timeout=3)
        assert response.status_code == 200
        assert response.json()['results'][0]['toolCallId'] == 'tool-1'
        assert response.json()['results'][0]['result'].startswith('DENIED')
        assert main.store.get(task['id'])['status'] == 'in_progress'


def test_live_final_transcripts_and_call_end(client, monkeypatch):
    monkeypatch.setenv('VAPI_WEBHOOK_SECRET', 'test-secret')
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    live_task()

    def webhook(message):
        return client.post('/api/webhooks/vapi', json={'message': {
            'call': {'id': 'provider-call-1'}, **message}}, headers={'x-vapi-secret': 'test-secret'})

    webhook({'type': 'transcript', 'transcriptType': 'partial', 'role': 'user', 'transcript': 'Hi'})
    assert not main.store.get('live-task')['transcript']
    webhook({'type': 'transcript', 'transcriptType': 'final', 'role': 'user', 'transcript': 'Tuesday is available.'})
    assert len(main.store.get('live-task')['transcript']) == 1
    assert webhook({'type': 'end-of-call-report'}).status_code == 200
    task = main.store.get('live-task')
    assert task['status'] == 'completed'
    assert 'Review the transcript' in task['summary']
    # Late events must not reopen a completed call.
    webhook({'type': 'status-update', 'status': 'in-progress'})
    assert main.store.get('live-task')['status'] == 'completed'


@pytest.fixture
def browser(client, monkeypatch):
    monkeypatch.setenv('VAPI_PUBLIC_KEY', 'public-test-key')
    monkeypatch.setenv('VAPI_BROWSER_ASSISTANT_ID', 'browser-assistant')
    monkeypatch.setenv('VAPI_WEBHOOK_SECRET', 'test-secret')
    monkeypatch.delenv('VAPI_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    response = client.post('/api/tasks', json={'goal': 'Ask for a lower internet bill', 'mode': 'browser'})
    assert response.status_code == 201
    task = wait_for(client, response.json()['id'], 'ready')
    assert task['plan'] and not task['provider_call_id'] and not task['transcript']
    return task


def browser_event(client, task_id, config, kind, event_id=None, **fields):
    return client.post(f'/api/tasks/{task_id}/browser/events', json={
        'session_token': config['session_token'], 'event_id': event_id or f'{kind}-1',
        'kind': kind, **fields})


def test_browser_config_does_not_require_phone_or_private_key(client, browser):
    health = client.get('/api/health').json()
    assert health['browser'] and not health['live']
    assert 'public-test-key' not in str(health)
    config = client.post(f"/api/tasks/{browser['id']}/browser/session").json()
    assert config['public_key'] == 'public-test-key'
    assert config['assistant_id'] == 'browser-assistant'
    assert 'test-secret' not in str(config)
    assert config['assistant_overrides']['variableValues']['goal'] == browser['goal']
    assert 'AI assistant' in config['assistant_overrides']['firstMessage']
    assert client.post(f"/api/tasks/{browser['id']}/browser/session").status_code == 409
    # Client events cannot forge a user approval decision.
    assert browser_event(client, browser['id'], config, 'authorize').status_code == 422


def test_unconfigured_browser_mode_is_rejected(client, monkeypatch):
    monkeypatch.delenv('VAPI_PUBLIC_KEY', raising=False)
    assert not client.get('/api/health').json()['browser']
    assert client.post('/api/tasks', json={'goal': 'Try a browser conversation', 'mode': 'browser'}).status_code == 503


def test_browser_event_auth_dedup_transcript_and_reporting(client, browser):
    task_id = browser['id']
    config = client.post(f'/api/tasks/{task_id}/browser/session').json()
    assert browser_event(client, task_id, {**config, 'session_token': 'wrong-token' * 4}, 'connected').status_code == 401
    assert browser_event(client, task_id, config, 'registered', provider_call_id='web-call-1').status_code == 200
    browser_event(client, task_id, config, 'connected')
    for _ in range(2):
        browser_event(client, task_id, config, 'transcript', role='user', text='I can offer a ten dollar discount.')
    task = client.get(f'/api/tasks/{task_id}').json()
    assert len(task['transcript']) == 1
    assert task['status'] == 'in_progress'
    browser_event(client, task_id, config, 'ended')
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        task = client.get(f'/api/tasks/{task_id}').json()
        if task['summary']:
            break
        time.sleep(0.02)
    assert task['status'] == 'completed'
    assert 'Browser role-play' in task['summary'] and 'HOLD-2048' not in task['summary']
    browser_event(client, task_id, config, 'connected', event_id='late-connected')
    assert client.get(f'/api/tasks/{task_id}').json()['status'] == 'completed'


def test_browser_webhook_can_bind_before_sdk_start_returns_and_waits_for_approval(client, browser):
    task_id = browser['id']
    config = client.post(f'/api/tasks/{task_id}/browser/session').json()
    payload = {'message': {'type': 'tool-calls', 'call': {'id': 'early-web-call',
        'assistantOverrides': config['assistant_overrides']},
        'toolCallList': [{'id': 'approval-tool', 'function': {'name': 'request_approval',
            'arguments': {'description': 'Accept a ten dollar monthly discount without changing the contract'}}}]}}
    with ThreadPoolExecutor() as executor:
        pending = executor.submit(client.post, '/api/webhooks/vapi', json=payload, headers={'x-vapi-secret': 'test-secret'})
        task = wait_for(client, task_id, 'awaiting_approval')
        assert task['provider_call_id'] == 'early-web-call'
        assert not pending.done()
        # Reconnecting the browser cannot bypass the pending approval.
        browser_event(client, task_id, config, 'connected')
        assert client.get(f'/api/tasks/{task_id}').json()['status'] == 'awaiting_approval'
        client.post(f"/api/tasks/{task_id}/approvals/{task['approval']['id']}", json={'approved': False})
        assert pending.result(timeout=3).json()['results'][0]['result'].startswith('DENIED')


def test_browser_provider_report_replaces_incomplete_client_transcript(client, browser):
    task_id = browser['id']
    config = client.post(f'/api/tasks/{task_id}/browser/session').json()
    browser_event(client, task_id, config, 'registered', provider_call_id='web-call-end')
    browser_event(client, task_id, config, 'ended')
    payload = {'message': {'type': 'end-of-call-report', 'call': {'id': 'web-call-end'}, 'artifact': {'messages': [
        {'role': 'system', 'message': 'Hidden configuration'},
        {'role': 'assistant', 'message': 'Hi, I am an AI assistant.'},
        {'role': 'user', 'message': 'We cannot offer that discount.'},
    ]}}}
    response = client.post('/api/webhooks/vapi', json=payload, headers={'x-vapi-secret': 'test-secret'})
    assert response.status_code == 200
    task = client.get(f'/api/tasks/{task_id}').json()
    assert task['provider_report_received']
    assert len(task['transcript']) == 2 and 'Hidden' not in str(task['transcript'])
    assert task['summary'].startswith('Browser role-play ended.')
    count = len(task['activity'])
    client.post('/api/webhooks/vapi', json=payload, headers={'x-vapi-secret': 'test-secret'})
    assert len(client.get(f'/api/tasks/{task_id}').json()['activity']) == count


def test_browser_disconnect_expires_approval_and_denies_pending_tool(client, browser):
    task_id = browser['id']
    config = client.post(f'/api/tasks/{task_id}/browser/session').json()
    task = main.store.get(task_id)
    task['approval'] = {'id': 'pending-request', 'description': 'Change the contract', 'status': 'pending'}
    task['status'] = 'awaiting_approval'
    main.store.save(task)
    browser_event(client, task_id, config, 'ended')
    task = client.get(f'/api/tasks/{task_id}').json()
    assert task['approval']['status'] == 'expired'
    assert client.post(f'/api/tasks/{task_id}/approvals/pending-request', json={'approved': True}).status_code == 409
