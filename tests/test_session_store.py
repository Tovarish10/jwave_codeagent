from __future__ import annotations

from jwave_flow.session_store import SessionStore
from jwave_frontend.server import _session_id_from_run_path


def test_run_route_does_not_treat_legacy_api_run_as_session():
    assert _session_id_from_run_path("/api/run") == ""
    assert _session_id_from_run_path("/api/sessions/sess_123/run") == "sess_123"


def test_session_store_keeps_current_context(tmp_path):
    store = SessionStore(tmp_path)
    session = store.create("二维仿真")
    store.append_turn(
        session,
        "生成一个二维仿真",
        {
            "text": "print('ok')",
            "params_json": '{"nx": 128}',
            "requirement": "二维仿真",
            "stdout": "ok",
            "success": True,
            "verified": True,
            "trace": ["完成"],
        },
    )

    loaded = store.get(session["id"])
    assert loaded is not None
    assert loaded["current"]["code"] == "print('ok')"
    assert loaded["current"]["params_json"] == '{"nx": 128}'
    assert loaded["turns"][0]["index"] == 1
    assert store.list()[0]["turn_count"] == 1


def test_session_store_persists_memory_consent(tmp_path):
    session = SessionStore(tmp_path).create("授权会话", collect_memory=True)
    loaded = SessionStore(tmp_path).get(session["id"])
    assert loaded["consent"]["collect_memory"] is True
