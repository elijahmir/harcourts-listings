"""Unit tests for the stream-json parser.

These don't spawn claude — they feed canonical event JSON (captured from a
real probe) directly into _parse(). Run as:

    services/webapp/backend/.venv/bin/python -m pytest services/webapp/backend/tests/
"""
from __future__ import annotations

from services.webapp.backend.claude_runner import _parse


def test_system_init_extracts_session_id():
    ev = _parse({
        "type": "system",
        "subtype": "init",
        "session_id": "bdefcde3-f73e-46e3-abe1-d3e00b40a1cd",
        "cwd": "/anywhere",
        "model": "claude-opus-4-7",
    })
    assert ev.kind == "init"
    assert ev.session_id == "bdefcde3-f73e-46e3-abe1-d3e00b40a1cd"


def test_rate_limit_event():
    ev = _parse({
        "type": "rate_limit_event",
        "session_id": "sid",
        "rate_limit_info": {"status": "allowed"},
    })
    assert ev.kind == "rate_limit"
    assert ev.session_id == "sid"


def test_assistant_partial_is_text_delta():
    ev = _parse({
        "type": "assistant",
        "session_id": "sid",
        "message": {
            "stop_reason": None,
            "content": [{"type": "text", "text": "ping"}],
        },
    })
    assert ev.kind == "text_delta"
    assert ev.text == "ping"


def test_assistant_final_is_text_full():
    ev = _parse({
        "type": "assistant",
        "session_id": "sid",
        "message": {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ping"}],
        },
    })
    assert ev.kind == "text_full"
    assert ev.text == "ping"


def test_result_captures_tokens_and_cost():
    ev = _parse({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": "sid",
        "total_cost_usd": 0.24007,
        "usage": {
            "input_tokens": 5,
            "output_tokens": 6,
            "cache_creation_input_tokens": 38302,
            "cache_read_input_tokens": 0,
        },
    })
    assert ev.kind == "result"
    assert ev.input_tokens == 5
    assert ev.output_tokens == 6
    assert ev.cache_creation_tokens == 38302
    assert ev.cache_read_tokens == 0
    assert ev.total_cost_usd == 0.24007
    assert ev.is_error is False
    assert ev.error_message is None


def test_result_error_path():
    ev = _parse({
        "type": "result",
        "subtype": "error",
        "is_error": True,
        "api_error_status": "rate_limit_exceeded",
        "session_id": "sid",
        "result": "rate limit",
        "usage": {},
    })
    assert ev.kind == "result"
    assert ev.is_error is True
    assert ev.error_message == "rate_limit_exceeded"


def test_post_turn_summary_routes_to_turn_summary():
    ev = _parse({
        "type": "system",
        "subtype": "post_turn_summary",
        "session_id": "sid",
        "status_category": "review_ready",
    })
    assert ev.kind == "turn_summary"
    assert ev.session_id == "sid"


def test_unknown_event_falls_back_to_raw():
    # Unknown 'type' values intentionally route to kind='raw' so that
    # downstream code must handle them explicitly rather than silently
    # treating a future Claude event as if it were a known kind.
    ev = _parse({"type": "future_event_kind", "session_id": "sid", "anything": True})
    assert ev.kind == "raw"
    assert ev.session_id == "sid"
    assert ev.raw == {"type": "future_event_kind", "session_id": "sid", "anything": True}


def test_no_type_field_returns_raw():
    ev = _parse({"session_id": "sid"})
    assert ev.kind == "raw"
