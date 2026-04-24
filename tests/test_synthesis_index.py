"""
Tests for the SQLite index over the Synthesis runs JSONL.

All tests run against a temp directory — no touch to production history.

Run:
    python -m tests.test_synthesis_index
    # or pytest -q tests/test_synthesis_index.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


from shared.tracking import synthesis_index


checks: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = ""):
    checks.append((name, bool(cond), detail))
    prefix = "PASS" if cond else "FAIL"
    suffix = f" — {detail}" if detail and not cond else ""
    print(f"  {prefix}: {name}{suffix}")


def _sample_entry(run_id: str, email: str = "x@example.com", prompt: str = "A test prompt",
                  sources: int = 0, structured: bool = False, category: str = "deep_research",
                  mode: str = "standard", ts: str = "2026-04-23T00:00:00+00:00") -> dict:
    return {
        "run_id": run_id,
        "timestamp": ts,
        "user_email": email,
        "prompt": prompt,
        "category": category,
        "mode": mode,
        "output": "final",
        "model_count": 5,
        "sources": [{"id": i + 1} for i in range(sources)],
        "structured_report": {"x": 1} if structured else None,
    }


def _append_to_jsonl(path: Path, entry: dict) -> tuple[int, int]:
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    with open(path, "ab") as f:
        off = f.tell()
        f.write(line)
    return off, len(line)


# ───── tests ─────

def test_empty_dir_ensure_index_is_safe():
    print("\n[index] ensure_index on missing JSONL is safe")
    with tempfile.TemporaryDirectory() as td:
        jsonl = Path(td) / "runs.jsonl"
        synthesis_index.ensure_index(jsonl)
        check("no exception", True)
        check("DB created alongside", jsonl.with_suffix(".db").exists())
        check("stats show 0 rows", synthesis_index.stats(jsonl)["rows"] == 0)


def test_append_and_lookup_roundtrip():
    print("\n[index] append → lookup returns full entry")
    with tempfile.TemporaryDirectory() as td:
        jsonl = Path(td) / "runs.jsonl"
        entry = _sample_entry("abc123", prompt="Q on X", sources=3, structured=True)
        off, length = _append_to_jsonl(jsonl, entry)
        synthesis_index.index_append(jsonl, entry, line_length=length, byte_offset=off)

        got = synthesis_index.lookup(jsonl, "abc123")
        check("lookup returns dict", isinstance(got, dict))
        check("run_id matches", got.get("run_id") == "abc123")
        check("prompt round-trips exactly", got.get("prompt") == "Q on X")
        check("sources list length preserved", len(got.get("sources") or []) == 3)
        check("structured_report preserved", got.get("structured_report") == {"x": 1})


def test_lookup_missing_returns_none():
    print("\n[index] lookup of unknown id returns None")
    with tempfile.TemporaryDirectory() as td:
        jsonl = Path(td) / "runs.jsonl"
        synthesis_index.ensure_index(jsonl)
        check("None for unknown id", synthesis_index.lookup(jsonl, "nope") is None)


def test_list_recent_newest_first_with_alias():
    print("\n[index] list_recent returns newest first + aliases prompt_preview as prompt")
    with tempfile.TemporaryDirectory() as td:
        jsonl = Path(td) / "runs.jsonl"
        for i, ts in enumerate([
            "2026-01-01T00:00:00+00:00",
            "2026-02-01T00:00:00+00:00",
            "2026-03-01T00:00:00+00:00",
        ]):
            e = _sample_entry(f"r{i}", ts=ts, prompt=f"p{i}-" + "x" * 500)
            off, length = _append_to_jsonl(jsonl, e)
            synthesis_index.index_append(jsonl, e, line_length=length, byte_offset=off)

        rows = synthesis_index.list_recent(jsonl, limit=10)
        check("three rows returned", len(rows) == 3)
        check("newest first", rows[0]["run_id"] == "r2")
        check("`prompt` alias present", "prompt" in rows[0])
        check("`prompt_preview` also present", "prompt_preview" in rows[0])
        check("alias matches preview", rows[0]["prompt"] == rows[0]["prompt_preview"])
        check("preview truncated to 300", len(rows[0]["prompt_preview"]) <= 300)


def test_list_recent_filter_by_user():
    print("\n[index] list_recent filter by user_email")
    with tempfile.TemporaryDirectory() as td:
        jsonl = Path(td) / "runs.jsonl"
        for i, em in enumerate(["a@x.com", "b@x.com", "a@x.com", "c@x.com"]):
            e = _sample_entry(f"r{i}", email=em,
                              ts=f"2026-0{i+1}-01T00:00:00+00:00")
            off, length = _append_to_jsonl(jsonl, e)
            synthesis_index.index_append(jsonl, e, line_length=length, byte_offset=off)

        a_rows = synthesis_index.list_recent(jsonl, limit=10, user_email="a@x.com")
        check("only a@x rows returned", all(r["user_email"] == "a@x.com" for r in a_rows))
        check("two a@x rows", len(a_rows) == 2)


def test_rebuild_from_existing_jsonl():
    print("\n[index] rebuild from JSONL when DB is missing")
    with tempfile.TemporaryDirectory() as td:
        jsonl = Path(td) / "runs.jsonl"
        # Write three entries directly — no index yet.
        for i in range(3):
            e = _sample_entry(f"x{i}", ts=f"2026-0{i+1}-01T00:00:00+00:00")
            line = (json.dumps(e) + "\n").encode("utf-8")
            with open(jsonl, "ab") as f:
                f.write(line)

        # DB does not exist yet.
        check("no DB file before", not jsonl.with_suffix(".db").exists())

        # First call must rebuild.
        got = synthesis_index.lookup(jsonl, "x1")
        check("rebuilt DB finds x1", got is not None and got["run_id"] == "x1")
        check("DB file now exists", jsonl.with_suffix(".db").exists())

        stats = synthesis_index.stats(jsonl)
        check("stats report 3 rows", stats["rows"] == 3)


def test_ensure_index_detects_stale():
    print("\n[index] ensure_index rebuilds when counts diverge")
    with tempfile.TemporaryDirectory() as td:
        jsonl = Path(td) / "runs.jsonl"
        # Two entries through the index.
        for i in range(2):
            e = _sample_entry(f"y{i}", ts=f"2026-0{i+1}-01T00:00:00+00:00")
            off, length = _append_to_jsonl(jsonl, e)
            synthesis_index.index_append(jsonl, e, line_length=length, byte_offset=off)

        # Now an out-of-band append — bypasses index.
        sneaky = _sample_entry("sneaky", ts="2026-05-01T00:00:00+00:00")
        _append_to_jsonl(jsonl, sneaky)

        # Pre ensure_index, 'sneaky' is unknown.
        rows_before = synthesis_index.list_recent(jsonl)
        check("sneaky not yet indexed", all(r["run_id"] != "sneaky" for r in rows_before))

        # ensure_index should notice the row count mismatch and rebuild.
        synthesis_index.ensure_index(jsonl)
        got = synthesis_index.lookup(jsonl, "sneaky")
        check("sneaky recovered after ensure_index", got is not None)


def test_corrupt_lines_skipped_in_rebuild():
    print("\n[index] rebuild skips corrupt JSONL lines")
    with tempfile.TemporaryDirectory() as td:
        jsonl = Path(td) / "runs.jsonl"
        good = _sample_entry("good1", ts="2026-01-01T00:00:00+00:00")
        with open(jsonl, "ab") as f:
            f.write((json.dumps(good) + "\n").encode("utf-8"))
            f.write(b"this-is-not-json\n")
            other = _sample_entry("good2", ts="2026-02-01T00:00:00+00:00")
            f.write((json.dumps(other) + "\n").encode("utf-8"))

        count = synthesis_index.rebuild(jsonl)
        check("rebuild returns 2 valid rows", count == 2)
        check("good1 looked up", synthesis_index.lookup(jsonl, "good1") is not None)
        check("good2 looked up", synthesis_index.lookup(jsonl, "good2") is not None)


def test_lookup_across_many_entries_is_stable():
    print("\n[index] offsets stay stable across many entries")
    with tempfile.TemporaryDirectory() as td:
        jsonl = Path(td) / "runs.jsonl"
        N = 50
        for i in range(N):
            e = _sample_entry(
                f"run-{i:03d}",
                prompt=("padding " * (i % 7 + 1)) + f"id{i}",
                ts=f"2026-04-{(i % 27) + 1:02d}T00:00:00+00:00",
            )
            off, length = _append_to_jsonl(jsonl, e)
            synthesis_index.index_append(jsonl, e, line_length=length, byte_offset=off)

        # Spot-check middle + last entries retrieve correct prompts.
        mid = synthesis_index.lookup(jsonl, "run-025")
        last = synthesis_index.lookup(jsonl, f"run-{N-1:03d}")
        check("mid entry found", mid is not None and "id25" in mid["prompt"])
        check("last entry found", last is not None and f"id{N-1}" in last["prompt"])


def test_stats_reports_range():
    print("\n[index] stats returns oldest + newest timestamp")
    with tempfile.TemporaryDirectory() as td:
        jsonl = Path(td) / "runs.jsonl"
        for ts, rid in [
            ("2026-01-15T00:00:00+00:00", "a"),
            ("2026-05-15T00:00:00+00:00", "b"),
            ("2026-03-15T00:00:00+00:00", "c"),
        ]:
            e = _sample_entry(rid, ts=ts)
            off, length = _append_to_jsonl(jsonl, e)
            synthesis_index.index_append(jsonl, e, line_length=length, byte_offset=off)
        s = synthesis_index.stats(jsonl)
        check("3 rows counted", s["rows"] == 3)
        check("oldest is Jan", s["oldest"].startswith("2026-01-15"))
        check("newest is May", s["newest"].startswith("2026-05-15"))


# ───── runner ─────

def main():
    tests = [
        test_empty_dir_ensure_index_is_safe,
        test_append_and_lookup_roundtrip,
        test_lookup_missing_returns_none,
        test_list_recent_newest_first_with_alias,
        test_list_recent_filter_by_user,
        test_rebuild_from_existing_jsonl,
        test_ensure_index_detects_stale,
        test_corrupt_lines_skipped_in_rebuild,
        test_lookup_across_many_entries_is_stable,
        test_stats_reports_range,
    ]
    for t in tests:
        t()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n{'-' * 60}")
    print(f"Synthesis index tests: {passed}/{total} passed")
    if passed != total:
        failures = [n for n, ok, _ in checks if not ok]
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
