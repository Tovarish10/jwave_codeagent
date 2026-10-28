from jwave_flow.memory import MemoryStore, redact


def test_redact_removes_secrets_and_local_paths():
    value = "token=sk-abcdefghijklmnop /home/alice/private.py alice@example.com"
    redacted = redact(value)
    assert "sk-abcdefghijklmnop" not in redacted
    assert "/home/alice" not in redacted
    assert "alice@example.com" not in redacted


def test_opt_in_memory_distills_and_feedback_updates_confidence(tmp_path):
    store = MemoryStore(tmp_path / "memories.jsonl")
    card = store.record(
        "二维仿真",
        {
            "success": True,
            "verified": True,
            "requirement": "声速 1500，5 MHz 点源",
            "params_json": '{"frequency": 5000000}',
            "code_final": "print('ok')",
            "trace": ["参数提取完成", "语义校验通过"],
            "param_check_ok": True,
            "selfcheck": {"abs_max": 1.2},
        },
        "sess_123",
    )
    assert store.search("二维仿真")[0]["id"] == card["id"]
    assert card["schema_version"] == 2
    assert card["problem"]["requirement"] == "声速 1500，5 MHz 点源"
    assert card["solution"]["parameters"] == '{"frequency": 5000000}'
    assert "语义校验通过" in card["solution"]["steps"]
    assert "验证：" in store.context("二维仿真")
    assert store.feedback(card["id"], False)
    assert store.search("二维仿真")[0]["confidence"] < 0.9
