import pytest


@pytest.fixture(autouse=True)
def no_paid_providers(monkeypatch):
    """Local .env credentials must never cause real paid calls in tests."""
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_MODEL', raising=False)
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    monkeypatch.delenv('PHONE_PROVIDER', raising=False)
