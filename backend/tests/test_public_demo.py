import pytest
from fastapi.testclient import TestClient

from app import access, main, public_demo


@pytest.fixture
def visitors(tmp_path, monkeypatch):
    monkeypatch.setenv('HOLDON_PUBLIC_DEMO', '1')
    monkeypatch.setenv('HOLDON_REQUIRE_AUTH', '0')
    monkeypatch.setenv('HOLDON_ACCESS_KEY', 'test-signing-key-with-at-least-32-characters')
    monkeypatch.setenv('PUBLIC_APP_URL', 'https://holdon.test')
    monkeypatch.delenv('SPACETIMEDB_TOKEN', raising=False)
    monkeypatch.setattr(main, 'store', main.Store(str(tmp_path / 'public.sqlite3')))
    with TestClient(main.app, base_url='https://holdon.test') as first:
        # Only one lifespan runs; the second client shares the server, not cookies.
        second = TestClient(main.app, base_url='https://holdon.test')
        try:
            yield first, second
        finally:
            second.close()


def test_public_visitors_cannot_read_approve_cancel_or_stream_each_others_tasks(visitors):
    first, second = visitors
    assert first.get('/api/tasks').status_code == 403
    bootstrap = first.get('/api/demo/session')
    assert bootstrap.json()['public_demo']
    cookie = bootstrap.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    assert second.get('/api/demo/session').status_code == 200
    task = first.post('/api/tasks', json={'goal': 'Ask about a lower internet rate'}).json()
    task_id = task['id']
    assert first.get(f'/api/tasks/{task_id}').status_code == 200
    assert second.get('/api/tasks').json() == []
    for suffix, method, data in [('', 'GET', None), ('/events', 'GET', None),
                                 ('/cancel', 'POST', None), ('/approvals/any-id', 'POST', {'approved': True})]:
        response = second.request(method, f'/api/tasks/{task_id}{suffix}', json=data)
        assert response.status_code == 404
    assert len(first.get('/api/tasks').json()) == 1
    assert first.post(f'/api/tasks/{task_id}/sms', json={'confirmed': True}).status_code == 403
    assert first.post(f'/api/tasks/{task_id}/browser/session').status_code == 403
    assert first.get('/api/login').status_code == 404
    assert first.post('/api/webhooks/vapi', json={}).status_code == 404
    assert first.get('/api/tasks', headers={'Origin': 'https://other.test'}).status_code == 403


def test_public_modes_limits_and_visitor_cookie_validation(visitors, monkeypatch):
    first, second = visitors
    first.get('/api/demo/session')
    for mode in ['live', 'browser']:
        assert first.post('/api/tasks', json={'goal': 'A public test call', 'mode': mode}).status_code == 403
    task = first.post('/api/tasks', json={'goal': 'Ask about available options'}).json()
    assert first.post('/api/tasks', json={'goal': 'Another public test call'}).status_code == 429
    first.post(f"/api/tasks/{task['id']}/cancel")
    monkeypatch.setenv('PUBLIC_DEMO_DAILY_LIMIT', '1')
    second.get('/api/demo/session')
    assert second.post('/api/tasks', json={'goal': 'Another visitor test'}).status_code == 429
    health = second.get('/api/health').json()
    assert health['public_demo'] and not health['live'] and not health['browser']
    assert not health['sms']['configured'] and health['sms']['recipient'] is None
    second.cookies.clear()
    second.cookies.set(public_demo.COOKIE, 'forged-session')
    assert second.get('/api/tasks').status_code == 403


def test_public_demo_rejects_unsafe_configuration(monkeypatch):
    monkeypatch.setenv('HOLDON_PUBLIC_DEMO', '1')
    monkeypatch.setenv('HOLDON_REQUIRE_AUTH', '0')
    monkeypatch.setenv('HOLDON_ACCESS_KEY', 'too-short')
    monkeypatch.setenv('PUBLIC_APP_URL', 'https://holdon.test')
    with pytest.raises(ValueError):
        public_demo.validate()


def test_render_public_mode_overrides_inherited_private_default(visitors, monkeypatch):
    first, _ = visitors
    monkeypatch.setenv('HOLDON_REQUIRE_AUTH', '1')  # Docker image default.
    monkeypatch.delenv('PUBLIC_APP_URL')
    monkeypatch.setenv('RENDER_EXTERNAL_URL', 'https://holdon.test')
    assert not access.required()
    access.validate()
    public_demo.validate()
    assert first.get('/api/demo/session').json()['public_demo']
    assert first.get('/api/tasks').status_code == 200
    assert first.get('/api/health').json()['login_required'] is False
