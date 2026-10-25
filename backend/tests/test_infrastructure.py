import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import access, main
from app.spacetime import SpacetimeMirror
from app.store import Store, now


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'store', Store(str(tmp_path / 'infra.sqlite3')))
    monkeypatch.delenv('HOLDON_REQUIRE_AUTH', raising=False)
    monkeypatch.delenv('SPACETIMEDB_TOKEN', raising=False)
    main.login_attempts.clear()
    with TestClient(main.app, base_url='https://holdon.test') as client:
        yield client


def completed_task():
    task = {'id': 'summary-task', 'goal': 'Ask about a discount', 'mode': 'demo', 'status': 'completed',
            'summary': 'A scripted demo only. No account change occurred.', 'activity': [], 'created_at': now()}
    main.store.save(task)
    return task


def configure_sms(monkeypatch):
    for key, value in {'TWILIO_ACCOUNT_SID': 'AC' + 'a' * 32, 'TWILIO_AUTH_TOKEN': 'test-token',
                       'TWILIO_SMS_FROM': '+14155551234', 'TWILIO_SMS_TO': '+14155559999'}.items():
        monkeypatch.setenv(key, value)


def test_spacetime_outbox_replay_checkpoint_and_private_fields(tmp_path, monkeypatch):
    for key, value in {'SPACETIMEDB_URL': 'https://database.test', 'SPACETIMEDB_DATABASE': 'holdon',
                       'SPACETIMEDB_TOKEN': 'owner-token'}.items():
        monkeypatch.setenv(key, value)
    store = Store(str(tmp_path / 'outbox.sqlite3'))
    store.save({'id': 'task-a', 'status': 'planning', 'browser_session_hash': 'internal', 'browser_events': ['internal']})
    store.save({'id': 'task-a', 'status': 'completed'})
    received = []
    def handle(request):
        assert request.headers['authorization'] == 'Bearer owner-token'
        received.append(json.loads(request.content))
        return httpx.Response(200)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            mirror = SpacetimeMirror(store, client)
            assert await mirror.drain() == 2
            assert mirror.info()['pending_events'] == 0
            restarted = SpacetimeMirror(store, client)
            assert await restarted.drain() == 0
    asyncio.run(scenario())
    assert [payload[1] for payload in received] == [1, 2]
    assert 'internal' not in str(received)
    reopened = Store(str(tmp_path / 'outbox.sqlite3'))
    assert reopened.metadata('stream_id') == store.metadata('stream_id')


def test_spacetime_failure_keeps_durable_event_for_retry(tmp_path, monkeypatch):
    monkeypatch.setenv('SPACETIMEDB_URL', 'https://database.test')
    monkeypatch.setenv('SPACETIMEDB_DATABASE', 'holdon')
    monkeypatch.setenv('SPACETIMEDB_TOKEN', 'owner-token')
    store = Store(str(tmp_path / 'retry.sqlite3'))
    store.save({'id': 'retry-task'})
    attempts = []
    def handle(request):
        attempts.append(request.content)
        return httpx.Response(503 if len(attempts) == 1 else 200)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            mirror = SpacetimeMirror(store, client)
            with pytest.raises(httpx.HTTPStatusError):
                await mirror.drain()
            assert mirror.cursor == 0
            assert await mirror.drain() == 1
    asyncio.run(scenario())
    assert attempts[0] == attempts[1]


def test_hosted_gate_login_origin_and_logout(local, monkeypatch):
    monkeypatch.setenv('HOLDON_REQUIRE_AUTH', '1')
    monkeypatch.setenv('HOLDON_ACCESS_KEY', 'a' * 40)
    monkeypatch.setenv('PUBLIC_APP_URL', 'https://holdon.test')
    assert local.get('/api/tasks').status_code == 401
    assert local.get('/api/health').json() == {'ok': True, 'access_protected': True, 'login_required': True}
    assert local.post('/api/login', json={'access_key': 'wrong'}).status_code == 401
    response = local.post('/api/login', json={'access_key': 'a' * 40})
    cookie = response.headers['set-cookie'].lower()
    assert response.status_code == 200 and 'httponly' in cookie and 'secure' in cookie and 'samesite=strict' in cookie
    assert local.get('/api/tasks').status_code == 200
    assert local.post('/api/tasks', json={'goal': 'Test origin'}, headers={'origin': 'https://another.test'}).status_code == 403
    assert local.post('/api/logout').status_code == 200
    assert local.get('/api/tasks').status_code == 401


def test_access_tokens_expire_and_cannot_be_forged(monkeypatch):
    monkeypatch.setenv('HOLDON_ACCESS_KEY', 'a' * 40)
    token = access.issue()
    assert access.valid(token)
    assert not access.valid(token + 'x')
    assert not access.valid('garbage')
    assert not access.valid('non.ascii.☃')
    monkeypatch.setattr(access.time, 'time', lambda: time.time_ns() / 1e9 + access.LIFETIME + 1)
    assert not access.valid(token)


def test_hosted_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv('HOLDON_REQUIRE_AUTH', '1')
    monkeypatch.setenv('HOLDON_ACCESS_KEY', 'short')
    monkeypatch.setenv('PUBLIC_APP_URL', 'http://holdon.test')
    with pytest.raises(ValueError, match='Hosted mode'):
        access.validate()


def test_login_rate_limit(local, monkeypatch):
    monkeypatch.setenv('HOLDON_REQUIRE_AUTH', '1')
    monkeypatch.setenv('HOLDON_ACCESS_KEY', 'a' * 40)
    monkeypatch.setenv('PUBLIC_APP_URL', 'https://holdon.test')
    for _ in range(5):
        assert local.post('/api/login', json={'access_key': '☃'}).status_code == 401
    assert local.post('/api/login', json={'access_key': 'wrong'}).status_code == 429


def test_sms_requires_confirmation_and_blocks_duplicate_sends(local, monkeypatch):
    configure_sms(monkeypatch)
    task = completed_task()
    calls = []
    async def send(record):
        calls.append(record['id'])
        return {'id': 'SM' + 'b' * 32, 'status': 'queued'}
    monkeypatch.setattr(main.sms, 'send', send)
    assert local.post(f"/api/tasks/{task['id']}/sms", json={'confirmed': False}).status_code == 422
    assert not calls
    preview = local.get(f"/api/tasks/{task['id']}/sms").json()
    assert preview['recipient'].endswith('9999') and '+14155559999' not in str(preview)
    result = local.post(f"/api/tasks/{task['id']}/sms", json={'confirmed': True}).json()
    assert result['status'] == 'queued'  # not delivered
    assert local.post(f"/api/tasks/{task['id']}/sms", json={'confirmed': True}).status_code == 409
    assert calls == [task['id']]


def test_sms_unknown_network_outcome_is_not_retried(local, monkeypatch):
    configure_sms(monkeypatch)
    task = completed_task()
    async def timeout(record):
        raise httpx.ReadTimeout('Unknown provider outcome')
    monkeypatch.setattr(main.sms, 'send', timeout)
    result = local.post(f"/api/tasks/{task['id']}/sms", json={'confirmed': True})
    assert result.json()['status'] == 'unknown'
    assert local.post(f"/api/tasks/{task['id']}/sms", json={'confirmed': True}).status_code == 409


def test_public_agent_returns_only_a_plan_without_private_actions(monkeypatch):
    from app.public_agent import public_reply
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'not-used')
    monkeypatch.setenv('ANTHROPIC_MODEL', 'not-used')
    async def forbidden(*args, **kwargs):
        raise AssertionError('Public planner must not spend provider credits')
    monkeypatch.setattr(main.agents.roles, 'ask', forbidden)
    reply = asyncio.run(public_reply('Ask my provider for a loyalty discount'))
    assert 'No call was placed' in reply and 'approval' in reply
    assert '5 to 1200' in asyncio.run(public_reply('x'))


def test_twilio_wire_adapter_uses_fixed_recipient_and_returns_queued(monkeypatch):
    from app.sms import SmsDelivery
    from urllib.parse import parse_qs
    configure_sms(monkeypatch)
    def handle(request):
        fields = parse_qs(request.content.decode())
        assert fields['To'] == ['+14155559999']
        assert fields['From'] == ['+14155551234']
        assert fields['Body'][0].startswith('HoldOn:')
        assert request.headers['authorization'].startswith('Basic ')
        return httpx.Response(201, json={'sid': 'SM' + 'b' * 32, 'status': 'queued'})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            result = await SmsDelivery(client).send({'goal': 'Demo goal', 'summary': 'No real account change.'})
            assert result['status'] == 'queued'
    asyncio.run(scenario())


def test_public_agent_constructor_and_registration_use_same_seed(monkeypatch):
    from app import public_agent, register_agent
    from uagents.dispatch import dispatcher
    monkeypatch.setenv('AGENTVERSE_SEED', 'test-only-agent-seed-123456789012345')
    monkeypatch.setenv('AGENTVERSE_ENDPOINT', 'https://agent.test/submit')
    monkeypatch.setenv('AGENTVERSE_API_KEY', 'test-only-key')
    loop = asyncio.new_event_loop()
    try:
        agent = public_agent.create_agent(loop)
        assert agent.protocols
        received = []
        def fake_register(**kwargs):
            received.append(kwargs)
            return True
        monkeypatch.setattr(register_agent, 'register_chat_agent', fake_register)
        assert register_agent.register()
        assert received[0]['endpoint'] == 'https://agent.test/submit'
        assert received[0]['active'] is True
        assert 'Does not place calls' in received[0]['readme']
        dispatcher.unregister(agent.address, agent)
    finally:
        loop.close()
