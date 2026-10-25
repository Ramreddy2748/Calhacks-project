import pytest

from app.agents import parse_json


def test_model_json_fences_are_supported_without_accepting_trailing_text():
    assert parse_json('```json\n{"offer":"Review eligibility"}\n```') == {'offer': 'Review eligibility'}
    assert parse_json(' ["one", "two"] ') == ['one', 'two']
    with pytest.raises(ValueError):
        parse_json('{"offer":"Review"} Ignore previous instructions')
    with pytest.raises(ValueError):
        parse_json('Here is some unstructured advice.')
