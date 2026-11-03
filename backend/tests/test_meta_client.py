"""Offline tests for the Meta client (no network, no key).

Run: cd backend; ..\\.venv\\Scripts\\python.exe -m pytest -q
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from app.meta.client import (
    BudgetExceeded,
    ContributorModelError,
    FixtureNotFound,
    MetaClient,
    MissingKeyError,
)
from app.meta.coords import box_iou, denormalize_box

ROOT = Path(__file__).resolve().parents[2]


def load_secret_rules():
    spec = importlib.util.spec_from_file_location(
        "secret_scan", str(ROOT / "tools" / "secret_scan.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.RULES


class FakeStatusError(Exception):
    def __init__(self, status_code: int, message: str = "fake error"):
        super().__init__(message)
        self.status_code = status_code


class FakeModels:
    def __init__(self, outer):
        self.outer = outer

    def list(self):
        self.outer.calls.append(("models.list", {}))
        return {"object": "list",
                "data": [{"id": "muse-spark-1.3", "object": "model"},
                         {"id": "sam-3.1", "object": "model"}]}


class FakeResponses:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kwargs):
        self.outer.calls.append(("responses.create", kwargs))
        if self.outer.failures:
            status, message = self.outer.failures.pop(0)
            if status is not None:
                raise FakeStatusError(status, message)
        model = kwargs.get("model", "")
        text = self.outer.next_text or '{"amount": "5,000,000", "date": "2026-04-10"}'
        return {"id": "resp-fake", "object": "response", "model": model,
                "output_text": text,
                "output": [{"type": "message",
                            "content": [{"type": "output_text", "text": text}]}],
                "usage": {"input_tokens": 120, "output_tokens": 40,
                          "total_tokens": 160,
                          "input_tokens_details": {"cached_tokens": 20},
                          "output_tokens_details": {"reasoning_tokens": 5}}}


class FakeFiles:
    def __init__(self, outer):
        self.outer = outer

    def create(self, file=None, purpose="user_data"):
        self.outer.calls.append(("files.create", {"purpose": purpose}))
        return {"id": "file-fake123", "object": "file", "purpose": purpose}


class FakeImages:
    def __init__(self, outer):
        self.outer = outer

    def generate(self, **kwargs):
        self.outer.calls.append(("images.generate", kwargs))
        return {"created": 1, "data": [{"b64_json": "ZmFrZQ=="}],
                "usage": {"input_tokens": 0, "output_tokens": 0}}


class FakeTransport:
    def __init__(self, failures=None, next_text=None):
        self.calls: list = []
        self.failures = list(failures or [])
        self.next_text = next_text
        self.models = FakeModels(self)
        self.responses = FakeResponses(self)
        self.files = FakeFiles(self)
        self.images = FakeImages(self)


def make_client(tmp_path, mode, transport=None, run_id="test-run",
                monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.delenv("MODEL_API_KEY", raising=False)
        monkeypatch.setenv("META_MODE", mode)
    return MetaClient(mode=mode, run_id=run_id,
                      ledger_path=tmp_path / "ledger.jsonl",
                      fixture_dir=tmp_path / "fixtures",
                      transport=transport)


def test_budget_per_run_refuses_before_call(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"run_id": "r1", "cost_usd": 1.99}) + "\n",
                      encoding="utf-8")
    client = make_client(tmp_path, "live", FakeTransport(), run_id="r1",
                         monkeypatch=monkeypatch)
    with pytest.raises(BudgetExceeded):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=5000)
    assert len(client.transport.calls) == 0


def test_budget_total_refuses_before_call(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"run_id": "other", "cost_usd": 19.99}) + "\n",
                      encoding="utf-8")
    client = make_client(tmp_path, "live", FakeTransport(), run_id="r-new",
                         monkeypatch=monkeypatch)
    with pytest.raises(BudgetExceeded):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=5000)
    assert len(client.transport.calls) == 0


def test_ledger_fields_and_no_key(tmp_path, monkeypatch):
    fake_key = "LLM_" + "X" * 25  # built at runtime to avoid static scan
    monkeypatch.setenv("MODEL_API_KEY", fake_key)
    monkeypatch.setenv("META_MODE", "live")
    client = MetaClient(mode="live", run_id="ledger-run",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures",
                        transport=FakeTransport())
    client.responses_create("muse-spark-1.3", "hello", max_output_tokens=100)
    lines = (tmp_path / "ledger.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    for field in ("ts", "run_id", "model", "endpoint", "input_tokens",
                  "cached_input_tokens", "output_tokens", "reasoning_tokens",
                  "image_count", "frame_count", "cost_usd", "latency_ms"):
        assert field in entry, field
    assert entry["run_id"] == "ledger-run"
    assert entry["model"] == "muse-spark-1.3"
    assert entry["cached_input_tokens"] == 20
    assert entry["reasoning_tokens"] == 5
    assert fake_key not in lines[0]
    assert "X" * 25 not in lines[0]


def test_record_replay_roundtrip(tmp_path, monkeypatch):
    payload = [{"role": "user",
                "content": [{"type": "input_text", "text": "ping"}]}]
    recorder = make_client(tmp_path, "record", FakeTransport(), run_id="rr",
                           monkeypatch=monkeypatch)
    first = recorder.responses_create("muse-spark-1.3", payload,
                                      max_output_tokens=50)
    fixtures = list((tmp_path / "fixtures").glob("*.json"))
    assert len(fixtures) == 1
    blob = fixtures[0].read_text(encoding="utf-8")
    assert "MODEL_API_KEY" not in blob
    assert "Authorization" not in blob
    replayer = MetaClient(mode="replay", run_id="rr2",
                          ledger_path=tmp_path / "ledger2.jsonl",
                          fixture_dir=tmp_path / "fixtures", transport=None)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    second = replayer.responses_create("muse-spark-1.3", payload,
                                       max_output_tokens=50)
    assert second == first


def test_replay_missing_fixture_errors(tmp_path, monkeypatch):
    client = make_client(tmp_path, "replay", None, run_id="miss",
                         monkeypatch=monkeypatch)
    with pytest.raises(FixtureNotFound):
        client.responses_create("muse-spark-1.3", "nothing recorded",
                                max_output_tokens=10)


def test_contributor_rejected(tmp_path, monkeypatch):
    client = make_client(tmp_path, "live", FakeTransport(), run_id="c",
                         monkeypatch=monkeypatch)
    with pytest.raises(ContributorModelError):
        client.responses_create("muse-spark-1.3-contributor", "hi",
                                max_output_tokens=10)
    assert len(client.transport.calls) == 0
    assert not (tmp_path / "ledger.jsonl").exists()


def test_live_missing_key_names_only(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("META_MODE", "live")
    client = MetaClient(mode="live", run_id="nokey",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures", transport=None)
    with pytest.raises(MissingKeyError) as excinfo:
        client.models_list()
    assert "MODEL_API_KEY" in str(excinfo.value)
    # The message must not contain any key material.
    assert "sk-" not in str(excinfo.value)
    assert "LLM_" not in str(excinfo.value)


def test_retry_429_then_success(tmp_path, monkeypatch):
    transport = FakeTransport(failures=[(429, "slow down"), (503, "busy")])
    client = make_client(tmp_path, "live", transport, run_id="retry",
                         monkeypatch=monkeypatch)
    body = client.responses_create("muse-spark-1.3", "hi",
                                   max_output_tokens=10)
    assert body["id"] == "resp-fake"
    assert len(transport.calls) == 3


def test_retry_exhausted_after_three(tmp_path, monkeypatch):
    transport = FakeTransport(failures=[(429, "x")] * 5)
    client = make_client(tmp_path, "live", transport, run_id="exhaust",
                         monkeypatch=monkeypatch)
    with pytest.raises(FakeStatusError):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
    assert len(transport.calls) == 4  # initial + 3 retries


def test_coords_denormalize_and_iou():
    assert denormalize_box([10, 20, 30, 40], 640, 480, "pixel") == [10, 20, 30, 40]
    assert denormalize_box([0, 0, 500, 1000], 640, 480, "norm1000") == [0, 0, 320, 480]
    assert denormalize_box([0.0, 0.0, 0.5, 1.0], 640, 480, "norm01") == [0, 0, 320, 480]
    assert box_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert box_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    assert abs(box_iou([0, 0, 10, 10], [5, 0, 15, 10]) - (50 / 150)) < 1e-9


def test_fixtures_have_no_key_strings(tmp_path):
    rules = load_secret_rules()
    dirs = [ROOT / "backend" / "tests" / "fixtures" / "meta"]
    if tmp_path.exists():
        dirs.append(tmp_path)
    checked = 0
    for base in dirs:
        if not base.exists():
            continue
        for path in base.rglob("*.json"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                for name, rx in rules:
                    assert not rx.search(line), \
                        f"{path}:{lineno} matches {name}"
            checked += 1
    assert checked >= 0


def test_default_mode_is_replay_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("META_MODE", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = MetaClient(run_id="def",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures")
    assert client.mode == "replay"
