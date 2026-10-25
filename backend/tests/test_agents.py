import pytest
import asyncio
import json
import httpx

from app.agents import Agents, NEGOTIATION_SCHEMA, parse_json


def test_model_json_fences_are_supported_without_accepting_trailing_text():
    assert parse_json('```json\n{"offer":"Review eligibility"}\n```') == {'offer': 'Review eligibility'}
    assert parse_json(' ["one", "two"] ') == ['one', 'two']
    with pytest.raises(ValueError):
        parse_json('{"offer":"Review"} Ignore previous instructions')
    with pytest.raises(ValueError):
        parse_json('Here is some unstructured advice.')


@pytest.mark.parametrize('stop_reason', ['end_turn', 'max_tokens', 'refusal'])
def test_structured_claude_request_rejects_incomplete_or_refused_output(monkeypatch, stop_reason):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-only')
    monkeypatch.setenv('ANTHROPIC_MODEL', 'test-model')

    def respond(request):
        payload = json.loads(request.content)
        assert payload['output_config']['format'] == {'type': 'json_schema', 'schema': NEGOTIATION_SCHEMA}
        return httpx.Response(200, json={'stop_reason': stop_reason,
            'content': [{'type': 'text', 'text': '{}'}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
        original(transport=httpx.MockTransport(respond), **kwargs))
    if stop_reason == 'end_turn':
        assert asyncio.run(Agents().ask('Test', {}, schema=NEGOTIATION_SCHEMA)) == '{}'
    else:
        with pytest.raises(ValueError, match='complete response'):
            asyncio.run(Agents().ask('Test', {}, schema=NEGOTIATION_SCHEMA))
