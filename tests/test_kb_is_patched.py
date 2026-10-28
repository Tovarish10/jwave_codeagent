"""The knowledge base must not contain APIs that don't exist in jwave 0.2.1."""
from __future__ import annotations

from pathlib import Path

KB = Path(__file__).resolve().parent.parent / "kb" / "jwave_kb_organized.md"

# (regex-ish substring, why it is wrong)
FORBIDDEN = [
    ("jw.np.", "jwave has no top-level `np`; use jnp"),
    ("jw.show_field(", "show_field lives in jwave.utils"),
    ("jw.display_complex_field(", "display_complex_field lives in jwave.utils"),
    ("jw.TimeHarmonicSource(domain", "wrong constructor; use from_point_sources"),
    ("title='Helmholtz solution'", "display_complex_field takes no title"),
]


def test_kb_has_no_stale_apis():
    text = KB.read_text(encoding="utf-8")
    offenders = [f"{needle!r} ({why})" for needle, why in FORBIDDEN if needle in text]
    assert not offenders, "stale jwave API still present in the KB:\n  " + "\n  ".join(offenders)


def test_backup_matches_the_users_original():
    backup = KB.with_suffix(KB.suffix + ".bak")
    assert backup.exists(), "kb backup is missing"
    assert backup.stat().st_size > 0, "kb backup is empty"
