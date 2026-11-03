"""Offline tests for the Meta client (no network, no key).

Run: cd backend; ..\\.venv\\Scripts\\python.exe -m pytest -q
"""

import importlib.util
import json
from pathlib import Path

import pytest

from app.meta import pricing
from app.meta.client import (
    BudgetError,
    BudgetExceeded,
    BudgetLedgerError,
    ContributorModelError,
    FixtureNotFound,
    IncompleteResponse,
    MetaClient,
    MissingKeyError,
    _collect_file_ids,
    _to_jsonable,
    estimate_cost_from_body,
    estimate_input_tokens,
    ledger_summary,
    request_hash,
    resolve_ledger_path,
)
from app.meta.coords import Box, box_iou, box_iou_boxes, box_to_pixels, denormalize_box

ROOT = Path(__file__).resolve().parents[2]


def load_secret_rules():
    spec = importlib.util.spec_from_file_location(
        "secret_scan", str(ROOT / "tools" / "secret_scan.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.RULES


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Narrowed to retry waits only (M0-fix2 item 8): lock waits and
    # test-side sleeps stay real so the concurrency test is honest.
    monkeypatch.setattr("app.meta.client._sleep_retry", lambda s: None)


class FakeStatusError(Exception):
    def __init__(self, status_code: int, message: str = "fake error",
                 headers: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        if headers is not None:
            self.response = type("FakeResp", (), {
                "headers": dict(headers), "status_code": status_code})()


class FakeModels:
    def __init__(self, outer):
        self.outer = outer

    def list(self):
        self.outer.calls.append(("models.list", {}))
        return {"object": "list",
                "data": [{"id": "muse-spark-1.3", "object": "model"},
                         {"id": "sam-3.1", "object": "model"}]}


class FakeStreamer:
    def __init__(self, outer, kwargs):
        self.outer = outer
        self.kwargs = kwargs
        self.final = None

    def __enter__(self):
        if self.outer.stream_enter_failures:
            item = self.outer.stream_enter_failures.pop(0)
            status, message = item[0], item[1]
            headers = item[2] if len(item) > 2 else None
            if status is not None:
                raise FakeStatusError(status, message, headers=headers)
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        yield {"type": "response.output_text.delta", "delta": "stream-"}
        yield {"type": "response.output_text.done", "text": "ok"}
        self.final = {
            "id": "resp-stream", "object": "response", "status": "completed",
            "output_text": "stream-ok",
            "usage": {"input_tokens": 120, "output_tokens": 40,
                      "total_tokens": 160,
                      "input_tokens_details": {"cached_tokens": 20},
                      "output_tokens_details": {"reasoning_tokens": 5}},
        }
        return iter(())

    def get_final_response(self):
        return self.final or {"output_text": "stream-ok", "usage": {}}


class FakeResponses:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kwargs):
        self.outer.calls.append(("responses.create", kwargs))
        if self.outer.failures:
            item = self.outer.failures.pop(0)
            status, message = item[0], item[1]
            headers = item[2] if len(item) > 2 else None
            if status is not None:
                raise FakeStatusError(status, message, headers=headers)
        model = kwargs.get("model", "")
        if self.outer.next_response is not None:
            return dict(self.outer.next_response)
        text = self.outer.next_text or '{"amount": "5,000,000", "date": "2026-04-10"}'
        return {"id": "resp-fake", "object": "response", "model": model,
                "status": "completed",
                "output_text": text,
                "output": [{"type": "message",
                            "content": [{"type": "output_text", "text": text}]}],
                "usage": {"input_tokens": 120, "output_tokens": 40,
                          "total_tokens": 160,
                          "input_tokens_details": {"cached_tokens": 20},
                          "output_tokens_details": {"reasoning_tokens": 5}}}

    def stream(self, **kwargs):
        self.outer.calls.append(("responses.stream", kwargs))
        return FakeStreamer(self.outer, kwargs)


class FakeFiles:
    def __init__(self, outer):
        self.outer = outer

    def create(self, file=None, purpose="user_data"):
        self.outer.calls.append(("files.create", {"purpose": purpose}))
        return {"id": "file-fake123", "object": "file", "purpose": purpose}

    def delete(self, file_id):
        self.outer.calls.append(("files.delete", {"file_id": file_id}))
        if self.outer.delete_failures:
            status, message = self.outer.delete_failures.pop(0)
            if status is not None:
                raise FakeStatusError(status, message)
        return {"id": file_id, "object": "file", "deleted": True}


class FakeImages:
    def __init__(self, outer):
        self.outer = outer

    def generate(self, **kwargs):
        self.outer.calls.append(("images.generate", kwargs))
        usage = self.outer.next_image_usage or {"input_tokens": 0,
                                                "output_tokens": 0}
        return {"created": 1, "data": [{"b64_json": "ZmFrZQ=="}],
                "usage": dict(usage)}


class FakeTransport:
    def __init__(self, failures=None, next_text=None, next_response=None,
                 stream_enter_failures=None, delete_failures=None,
                 next_image_usage=None):
        self.calls: list = []
        self.failures = list(failures or [])
        self.next_text = next_text
        self.next_response = next_response
        self.stream_enter_failures = list(stream_enter_failures or [])
        self.delete_failures = list(delete_failures or [])
        self.next_image_usage = next_image_usage
        self.models = FakeModels(self)
        self.responses = FakeResponses(self)
        self.files = FakeFiles(self)
        self.images = FakeImages(self)


def make_client(tmp_path, mode, transport=None, run_id="test-run",
                monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.delenv("MODEL_API_KEY", raising=False)
        monkeypatch.setenv("META_MODE", mode)
        monkeypatch.delenv("META_RUN_CAP_USD", raising=False)
        monkeypatch.delenv("META_TOTAL_CAP_USD", raising=False)
        monkeypatch.delenv("META_LEDGER_PATH", raising=False)
    return MetaClient(mode=mode, run_id=run_id,
                      ledger_path=tmp_path / "ledger.jsonl",
                      fixture_dir=tmp_path / "fixtures",
                      transport=transport)


def read_ledger(tmp_path, name="ledger.jsonl"):
    path = tmp_path / name
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def finals(entries):
    return [e for e in entries if e.get("status") in ("completed", "failed")]


def test_budget_per_run_refuses_before_call(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"run_id": "r1", "cost_usd": 1.99}) + "\n",
                      encoding="utf-8")
    client = make_client(tmp_path, "live", FakeTransport(), run_id="r1",
                         monkeypatch=monkeypatch)
    with pytest.raises(BudgetExceeded):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=5000)
    assert len(client.transport.calls) == 0


def test_per_run_cap_ignores_other_runs(tmp_path, monkeypatch):
    # $1.99 on another run must not block this run (C10). Breaks if the
    # per-run check uses the grand total.
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"run_id": "other", "cost_usd": 1.99}) + "\n",
                      encoding="utf-8")
    client = make_client(tmp_path, "live", FakeTransport(), run_id="r-new",
                         monkeypatch=monkeypatch)
    body = client.responses_create("muse-spark-1.3", "hi",
                                   max_output_tokens=5000)
    assert body["id"] == "resp-fake"


def test_budget_total_refuses_before_call(tmp_path, monkeypatch):
    monkeypatch.setenv("META_TOTAL_CAP_USD", "20")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"run_id": "other", "cost_usd": 19.99}) + "\n",
                      encoding="utf-8")
    client = make_client(tmp_path, "live", FakeTransport(), run_id="r-new",
                         monkeypatch=monkeypatch)
    # make_client cleared caps; restore 20 for this test.
    monkeypatch.setenv("META_TOTAL_CAP_USD", "20")
    with pytest.raises(BudgetExceeded):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=5000)
    assert len(client.transport.calls) == 0


def test_total_cap_default_100_allows_20(tmp_path, monkeypatch):
    # Default total cap is $100 (AGENTS.md 11/3). Breaks if default is $20.
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"run_id": "other", "cost_usd": 19.99}) + "\n",
                      encoding="utf-8")
    client = make_client(tmp_path, "live", FakeTransport(), run_id="r-new",
                         monkeypatch=monkeypatch)
    assert pricing.total_cap_usd() == 100.0
    assert pricing.run_cap_usd() == 2.0
    body = client.responses_create("muse-spark-1.3", "hi",
                                   max_output_tokens=5000)
    assert body["id"] == "resp-fake"


def test_ledger_fields_and_no_key(tmp_path, monkeypatch):
    fake_key = "LLM_" + "X" * 25  # built at runtime to avoid static scan
    monkeypatch.setenv("MODEL_API_KEY", fake_key)
    monkeypatch.setenv("META_MODE", "live")
    monkeypatch.delenv("META_RUN_CAP_USD", raising=False)
    monkeypatch.delenv("META_TOTAL_CAP_USD", raising=False)
    client = MetaClient(mode="live", run_id="ledger-run",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures",
                        transport=FakeTransport())
    client.responses_create("muse-spark-1.3", "hello", max_output_tokens=100)
    entries = read_ledger(tmp_path)
    # Reservation + final (C8).
    assert len(entries) == 2
    assert entries[0]["status"] == "reserved"
    entry = [e for e in entries if e["status"] == "completed"][0]
    for field in ("ts", "run_id", "model", "endpoint", "input_tokens",
                  "cached_input_tokens", "output_tokens", "reasoning_tokens",
                  "image_count", "frame_count", "cost_usd", "latency_ms"):
        assert field in entry, field
    assert entry["run_id"] == "ledger-run"
    assert entry["model"] == "muse-spark-1.3"
    assert entry["cached_input_tokens"] == 20
    assert entry["reasoning_tokens"] == 5
    blob = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    assert fake_key not in blob
    assert "X" * 25 not in blob


def test_spark_cost_cached_and_reasoning_no_double_count(tmp_path, monkeypatch):
    # M0 fixtures bc43d6ae (max 300, out 300, reasoning 298) and 4051cfb1
    # (max 2000, out 2000, reasoning 1998) prove output_tokens includes
    # reasoning; pricing subtracts to avoid double-counting. Cached input
    # bills at $0.15/1M, not $1.25.
    client = make_client(tmp_path, "live", FakeTransport(), run_id="cost",
                         monkeypatch=monkeypatch)
    client.responses_create("muse-spark-1.3", "hello", max_output_tokens=100)
    entry = finals(read_ledger(tmp_path))[0]
    expected = pricing.spark_cost_usd(120, 40, 20, 5)
    assert entry["cost_usd"] == pytest.approx(expected)
    # Manual: fresh 100*$1.25 + cached 20*$0.15 + text 35*$4.25 + reas 5*$4.25.
    assert expected == pytest.approx(0.000298)
    double_counted = (100 * 1.25 + 20 * 0.15 + 40 * 4.25 + 5 * 4.25) / 1_000_000
    assert entry["cost_usd"] != pytest.approx(round(double_counted, 6))


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


def test_contributor_case_insensitive(tmp_path, monkeypatch):
    client = make_client(tmp_path, "live", FakeTransport(), run_id="c2",
                         monkeypatch=monkeypatch)
    with pytest.raises(ContributorModelError):
        client.responses_create("MUSE-SPARK-1.3-CONTRIBUTOR", "hi",
                                max_output_tokens=10)
    assert len(client.transport.calls) == 0
    assert not (tmp_path / "ledger.jsonl").exists()


def test_live_missing_key_names_only(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("META_MODE", "live")
    monkeypatch.delenv("META_RUN_CAP_USD", raising=False)
    monkeypatch.delenv("META_TOTAL_CAP_USD", raising=False)
    client = MetaClient(mode="live", run_id="nokey",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures", transport=None)
    with pytest.raises(MissingKeyError) as excinfo:
        client.models_list()
    assert "MODEL_API_KEY" in str(excinfo.value)
    assert "sk-" not in str(excinfo.value)
    assert "LLM_" not in str(excinfo.value)


def test_run_id_required_in_live_and_record(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError):
        MetaClient(mode="live", run_id=None,
                   ledger_path=tmp_path / "ledger.jsonl",
                   fixture_dir=tmp_path / "fixtures",
                   transport=FakeTransport())
    with pytest.raises(ValueError):
        MetaClient(mode="record", run_id="",
                   ledger_path=tmp_path / "ledger.jsonl",
                   fixture_dir=tmp_path / "fixtures",
                   transport=FakeTransport())
    # Replay allows a missing run_id.
    client = MetaClient(mode="replay",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures")
    assert client.mode == "replay"


def test_m0_spike_run_id_fixed():
    spec = importlib.util.spec_from_file_location(
        "m0_spike", str(ROOT / "tools" / "m0_spike.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    # Fixed per probe (C6); breaks with timestamped ids.
    assert module.run_id_for("P2") == "M0-P2"
    assert module.run_id_for("P6") == "M0-P6"


def test_retry_429_then_success(tmp_path, monkeypatch):
    transport = FakeTransport(failures=[(429, "slow down"), (503, "busy")])
    client = make_client(tmp_path, "live", transport, run_id="retry",
                         monkeypatch=monkeypatch)
    body = client.responses_create("muse-spark-1.3", "hi",
                                   max_output_tokens=10)
    assert body["id"] == "resp-fake"
    assert len(transport.calls) == 3
    # One reservation + one final.
    assert len(read_ledger(tmp_path)) == 2


def test_retry_exhausted_after_three_records_failed(tmp_path, monkeypatch):
    transport = FakeTransport(failures=[(429, "x")] * 5)
    client = make_client(tmp_path, "live", transport, run_id="exhaust",
                         monkeypatch=monkeypatch)
    with pytest.raises(FakeStatusError):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
    assert len(transport.calls) == 4  # initial + 3 retries
    entries = read_ledger(tmp_path)
    assert len(entries) == 2
    failed = [e for e in entries if e["status"] == "failed"]
    assert len(failed) == 1
    # Failed-after-send records the pre-call expected cost (C1).
    expected = pricing.estimate_spark_cost_usd(
        estimate_input_tokens("hi"), 10)
    assert failed[0]["cost_usd"] == pytest.approx(expected)


def test_400_is_not_retried(tmp_path, monkeypatch):
    transport = FakeTransport(failures=[(400, "bad request")])
    client = make_client(tmp_path, "live", transport, run_id="bad",
                         monkeypatch=monkeypatch)
    with pytest.raises(FakeStatusError):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
    assert len(transport.calls) == 1
    assert finals(read_ledger(tmp_path))[0]["status"] == "failed"


def test_retry_after_capped_at_30s(tmp_path, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("app.meta.client._sleep_retry", sleeps.append)
    transport = FakeTransport(
        failures=[(429, "slow", {"retry-after": "120"})])
    client = make_client(tmp_path, "live", transport, run_id="ra",
                         monkeypatch=monkeypatch)
    body = client.responses_create("muse-spark-1.3", "hi",
                                   max_output_tokens=10)
    assert body["id"] == "resp-fake"
    assert len(sleeps) == 1
    assert sleeps[0] <= 30.0


def test_sdk_retries_off(tmp_path, monkeypatch):
    # OpenAI SDK must be constructed with max_retries=0 (C1).
    captured: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            raise AssertionError("stop after capture")

    import sys
    fake_mod = type("M", (), {"OpenAI": FakeOpenAI})()
    monkeypatch.setitem(sys.modules, "openai", fake_mod)
    monkeypatch.setenv("MODEL_API_KEY", "LLM_" + "Y" * 25)
    monkeypatch.delenv("META_RUN_CAP_USD", raising=False)
    monkeypatch.delenv("META_TOTAL_CAP_USD", raising=False)
    client = MetaClient(mode="live", run_id="sdk",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures", transport=None)
    with pytest.raises(AssertionError):
        client._live_transport()
    assert captured.get("max_retries") == 0


@pytest.mark.parametrize("key", ["model", "input", "max_output_tokens",
                                 "text", "reasoning", "stream", "store"])
def test_extra_forbidden_keys_rejected(tmp_path, monkeypatch, key):
    client = make_client(tmp_path, "live", FakeTransport(), run_id="ex",
                         monkeypatch=monkeypatch)
    with pytest.raises(ValueError):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10,
                                extra={key: "evil"})
    assert len(client.transport.calls) == 0
    assert not (tmp_path / "ledger.jsonl").exists()


def test_extra_allowed_metadata_passes(tmp_path, monkeypatch):
    # SAM video metadata (M0 P6) must still pass (C2 only blocks 7 keys).
    transport = FakeTransport()
    client = make_client(tmp_path, "live", transport, run_id="meta",
                         monkeypatch=monkeypatch)
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": "box"},
        {"type": "input_video", "file_id": "file-fake123"}]}]
    body = client.responses_create("sam-3.1", payload, frame_count=30,
                                   extra={"metadata": {"propagation_direction":
                                                       "forward"}})
    assert body["id"] == "resp-fake"


def test_ledger_corrupted_refuses_call(tmp_path, monkeypatch):
    (tmp_path / "ledger.jsonl").write_text('{"run_id": "x", "cost_usd": 1.0}\n'
                                           'NOT-JSON\n', encoding="utf-8")
    client = make_client(tmp_path, "live", FakeTransport(), run_id="corr",
                         monkeypatch=monkeypatch)
    with pytest.raises(BudgetLedgerError):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
    assert len(client.transport.calls) == 0


def test_ledger_missing_cost_refuses_call(tmp_path, monkeypatch):
    (tmp_path / "ledger.jsonl").write_text('{"run_id": "x"}\n',
                                           encoding="utf-8")
    client = make_client(tmp_path, "live", FakeTransport(), run_id="corr2",
                         monkeypatch=monkeypatch)
    with pytest.raises(BudgetLedgerError):
        client.models_list()
    assert len(client.transport.calls) == 0


def test_ledger_append_flushes(tmp_path, monkeypatch):
    # _append_ledger must flush each line (C3). Breaks if flush is removed.
    flushed: list[bool] = []
    import app.meta.client as client_mod
    real_open = Path.open

    def tracking_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        if "a" in (args[0] if args else kwargs.get("mode", "")):
            real_flush = handle.flush

            def flush_and_record(*a, **k):
                flushed.append(True)
                return real_flush(*a, **k)

            handle.flush = flush_and_record  # type: ignore[method-assign]
        return handle

    monkeypatch.setattr(Path, "open", tracking_open)
    client = make_client(tmp_path, "live", FakeTransport(), run_id="fl",
                         monkeypatch=monkeypatch)
    client.models_list()
    assert flushed, "ledger append did not flush"


def test_usage_missing_records_expected_cost(tmp_path, monkeypatch):
    transport = FakeTransport(next_response={
        "id": "resp-nousage", "object": "response", "status": "completed",
        "output_text": "hi", "usage": {}})
    client = make_client(tmp_path, "live", transport, run_id="nousage",
                         monkeypatch=monkeypatch)
    body = client.responses_create("muse-spark-1.3", "hello",
                                   max_output_tokens=100)
    assert body["id"] == "resp-nousage"
    entry = finals(read_ledger(tmp_path))[0]
    expected = pricing.estimate_spark_cost_usd(
        estimate_input_tokens("hello"), 100)
    # Breaks if usage-less responses record $0 (C4).
    assert entry["cost_usd"] == pytest.approx(expected)
    assert entry["cost_usd"] > 0


def test_request_hash_stable_key_order():
    a = request_hash("m", "e", {"b": 1, "a": 2}, {"y": 1, "x": 2})
    b = request_hash("m", "e", {"a": 2, "b": 1}, {"x": 2, "y": 1})
    assert a == b


def test_key_via_require_key_path_not_leaked(tmp_path, monkeypatch):
    # Key enters via _require_key -> OpenAI(...) (transport None, mocked
    # OpenAI returning a fake). Ledger, fixture, and errors must not
    # contain the key material.
    fake_key = "LLM_" + "Z" * 25
    monkeypatch.setenv("MODEL_API_KEY", fake_key)
    monkeypatch.delenv("META_RUN_CAP_USD", raising=False)
    monkeypatch.delenv("META_TOTAL_CAP_USD", raising=False)
    fake = FakeTransport()

    class FakeOpenAI:
        def __init__(self, api_key=None, **kwargs):
            assert api_key == fake_key
            self.models = fake.models
            self.responses = fake.responses
            self.files = fake.files
            self.images = fake.images

    import sys
    monkeypatch.setitem(sys.modules, "openai",
                        type("M", (), {"OpenAI": FakeOpenAI})())
    client = MetaClient(mode="record", run_id="keypath",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures", transport=None)
    try:
        client.responses_create("muse-spark-1.3", "hello",
                                max_output_tokens=10)
    except Exception as exc:  # noqa: BLE001 - must not leak either
        assert fake_key not in str(exc)
        assert "Z" * 25 not in str(exc)
        raise
    blob = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    assert fake_key not in blob
    assert "Z" * 25 not in blob
    for path in (tmp_path / "fixtures").glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert fake_key not in text
        assert "Z" * 25 not in text


def test_to_jsonable_skips_private_attrs():
    class Obj:
        def __init__(self):
            self.public = "ok"
            self._api_key = "LLM_SECRET"

    out = _to_jsonable(Obj())
    assert out == {"public": "ok"}
    assert "LLM_SECRET" not in json.dumps(out)


def test_sam_image_cost(tmp_path, monkeypatch):
    transport = FakeTransport(next_response={
        "id": "resp-sam", "object": "response", "status": "completed",
        "output_text": "<box>", "usage": {}})
    client = make_client(tmp_path, "live", transport, run_id="samimg",
                         monkeypatch=monkeypatch)
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": "bubble"},
        {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}]}]
    client.responses_create("sam-3.1", payload, image_count=1)
    entry = finals(read_ledger(tmp_path))[0]
    assert entry["cost_usd"] == pytest.approx(pricing.sam_image_cost_usd(1))
    assert entry["cost_usd"] == pytest.approx(0.0025)


def test_sam_video_cost_min_50_and_frame_required(tmp_path, monkeypatch):
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": "box"},
        {"type": "input_video", "file_id": "file-fake123"}]}]
    # Missing frame_count must fail (C7).
    client = make_client(tmp_path, "live", FakeTransport(), run_id="samv",
                         monkeypatch=monkeypatch)
    with pytest.raises(ValueError):
        client.responses_create("sam-3.1", payload)
    # 30 frames bills as 50 (minimum).
    transport = FakeTransport(next_response={
        "id": "r", "object": "response", "status": "completed",
        "output_text": "", "usage": {"video_frames_processed": 0}})
    client2 = make_client(tmp_path, "live", transport, run_id="samv2",
                          monkeypatch=monkeypatch)
    # Use a fresh ledger dir for the second client to avoid interference.
    client2.ledger_path = tmp_path / "ledger2.jsonl"
    client2.responses_create("sam-3.1", payload, frame_count=30)
    entry = finals(read_ledger(tmp_path, "ledger2.jsonl"))[0]
    assert entry["cost_usd"] == pytest.approx(0.01)
    assert entry["frame_count"] == 50


def test_sam_video_via_input_file_uses_frames(tmp_path, monkeypatch):
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": "track"},
        {"type": "input_file", "file_id": "file-fake123"}]}]
    # D6: an input_file alone is an image (no frame_count needed).
    client = make_client(tmp_path, "live", FakeTransport(), run_id="samf",
                         monkeypatch=monkeypatch)
    client.responses_create("sam-3.1", payload)
    entry = finals(read_ledger(tmp_path))[0]
    assert entry["cost_usd"] == pytest.approx(pricing.sam_image_cost_usd(1))
    assert entry["frame_count"] == 0
    # The same payload with frame_count is video.
    transport = FakeTransport(next_response={
        "id": "r", "object": "response", "status": "completed",
        "output_text": "", "usage": {"video_frames_processed": 60}})
    client2 = MetaClient(mode="live", run_id="samf2",
                         ledger_path=tmp_path / "ledger2.jsonl",
                         fixture_dir=tmp_path / "fixtures",
                         transport=transport)
    client2.responses_create("sam-3.1", payload, frame_count=60)
    entry = finals(read_ledger(tmp_path, "ledger2.jsonl"))[0]
    assert entry["cost_usd"] == pytest.approx(pricing.sam_video_cost_usd(60))


def test_muse_image_cost_flat_despite_tokens(tmp_path, monkeypatch):
    # M0 fixture 5b8897d6 has usage tokens (26,345/1,635) but the pricing
    # page bills flat $0.01/image; tokens are reference only.
    transport = FakeTransport(
        next_image_usage={"input_tokens": 26345, "output_tokens": 1635,
                          "total_tokens": 27980})
    client = make_client(tmp_path, "live", transport, run_id="img",
                         monkeypatch=monkeypatch)
    client.images_generate("muse-image-1.0", "a picture", size="1024x1024")
    entry = finals(read_ledger(tmp_path))[0]
    assert entry["cost_usd"] == pytest.approx(0.01)
    assert entry["input_tokens"] == 26345
    assert entry["output_tokens"] == 1635


def test_estimate_korean_chars_one_token_each():
    text = "2026-04-10에 5,000,000원을 갚겠다"
    est = estimate_input_tokens(text)
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    assert non_ascii > 0
    # Breaks with chars/4 underestimation (C7).
    assert est >= non_ascii


def test_estimate_pdf_inline_overestimates_m0(tmp_path):
    # M0 P3: 50,579-byte 2-page PDF used 5,403 tokens. The estimate must
    # exceed it (old 1,500/file fails).
    import base64
    raw = b"%PDF-1.4 fake " + b"x" * 50579
    data_url = ("data:application/pdf;base64,"
                + base64.b64encode(raw).decode("ascii"))
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": "read pdf"},
        {"type": "input_file", "filename": "iou_2page.pdf",
         "file_data": data_url}]}]
    assert estimate_input_tokens(payload) > 5403


def test_estimate_file_id_fallback_large():
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": "watch"},
        {"type": "input_file", "file_id": "file-abc"}]}]
    # Unknown size assumes a large PDF (old 1,500 fails).
    assert estimate_input_tokens(payload) >= 12000


def test_stream_retries_enter_then_succeeds(tmp_path, monkeypatch):
    transport = FakeTransport(
        stream_enter_failures=[(429, "slow"), (None, "")])
    client = make_client(tmp_path, "live", transport, run_id="stream",
                         monkeypatch=monkeypatch)
    body = client.responses_create("muse-spark-1.3", "hi",
                                   max_output_tokens=10, stream=True)
    assert "stream" in (body.get("output_text", "") + str(body))
    assert len([c for c in transport.calls
                if c[0] == "responses.stream"]) == 2
    entries = read_ledger(tmp_path)
    assert len(entries) == 2
    assert finals(entries)[0]["status"] == "completed"


def test_stream_failure_records_failed(tmp_path, monkeypatch):
    transport = FakeTransport(
        stream_enter_failures=[(429, "x")] * 5)
    client = make_client(tmp_path, "live", transport, run_id="streamfail",
                         monkeypatch=monkeypatch)
    with pytest.raises(FakeStatusError):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10,
                                stream=True)
    # Initial + 3 retries of __enter__ (C5).
    assert len([c for c in transport.calls
                if c[0] == "responses.stream"]) == 4
    entries = read_ledger(tmp_path)
    assert finals(entries)[0]["status"] == "failed"


def test_incomplete_raises_and_records_cost(tmp_path, monkeypatch):
    transport = FakeTransport(next_response={
        "id": "r-inc", "object": "response", "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output_text": "",
        "usage": {"input_tokens": 851, "output_tokens": 2000,
                  "total_tokens": 2851,
                  "input_tokens_details": {"cached_tokens": 739},
                  "output_tokens_details": {"reasoning_tokens": 1998}}})
    client = make_client(tmp_path, "record", transport, run_id="inc",
                         monkeypatch=monkeypatch)
    with pytest.raises(IncompleteResponse) as excinfo:
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=2000)
    assert "max_output_tokens" in str(excinfo.value)
    assert excinfo.value.reason == "max_output_tokens"
    entry = finals(read_ledger(tmp_path))[0]
    # Billed cost recorded even though the caller must retry (C13).
    assert entry["cost_usd"] > 0
    assert len(list((tmp_path / "fixtures").glob("*.json"))) == 1
    # Replay of the incomplete fixture also raises.
    replayer = MetaClient(mode="replay", run_id="inc2",
                          ledger_path=tmp_path / "ledger2.jsonl",
                          fixture_dir=tmp_path / "fixtures", transport=None)
    with pytest.raises(IncompleteResponse):
        replayer.responses_create("muse-spark-1.3", "hi",
                                  max_output_tokens=2000)


def test_files_delete_roundtrip_and_auto_cleanup(tmp_path, monkeypatch):
    transport = FakeTransport()
    client = make_client(tmp_path, "record", transport, run_id="del",
                         monkeypatch=monkeypatch)
    created = client.files_create(b"bytes", "v.mp4")
    assert created["id"] == "file-fake123"
    deleted = client.files_delete("file-fake123")
    assert deleted["deleted"] is True
    assert ("files.delete", {"file_id": "file-fake123"}) in transport.calls
    # Record saved a delete fixture; replay reproduces it.
    assert len(list((tmp_path / "fixtures").glob("*.json"))) == 2
    replayer = MetaClient(mode="replay", run_id="del2",
                          ledger_path=tmp_path / "ledger2.jsonl",
                          fixture_dir=tmp_path / "fixtures", transport=None)
    assert replayer.files_delete("file-fake123")["deleted"] is True


def test_cleanup_files_warns_only_on_delete_failure(tmp_path, monkeypatch):
    # D1: no automatic deletion; explicit cleanup_files warns (never
    # raises) when a delete fails.
    transport = FakeTransport(delete_failures=[(500, "gone")] * 5)
    client = make_client(tmp_path, "live", transport, run_id="clean",
                         monkeypatch=monkeypatch)
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": "watch"},
        {"type": "input_file", "file_id": "file-fake123"}]}]
    body = client.responses_create("muse-spark-1.3", payload,
                                   max_output_tokens=10)
    assert body["id"] == "resp-fake"
    assert not [c for c in transport.calls if c[0] == "files.delete"]
    with pytest.warns(RuntimeWarning, match="file delete failed"):
        client.cleanup_files(_collect_file_ids(payload))
    assert ("files.delete", {"file_id": "file-fake123"}) in transport.calls


def test_coords_denormalize_and_iou():
    assert denormalize_box([10, 20, 30, 40], 640, 480, "pixel") == [10, 20, 30, 40]
    assert denormalize_box([0, 0, 500, 1000], 640, 480, "norm1000") == [0, 0, 320, 480]
    assert denormalize_box([0.0, 0.0, 0.5, 1.0], 640, 480, "norm01") == [0, 0, 320, 480]
    assert box_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert box_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    assert abs(box_iou([0, 0, 10, 10], [5, 0, 15, 10]) - (50 / 150)) < 1e-9


def test_box_to_pixels_spark_and_sam():
    # Spark norm1000.
    spark = Box(x1=0, y1=0, x2=500, y2=1000, system="norm1000",
                ref_w=640, ref_h=960)
    assert box_to_pixels(spark, 640, 960) == [0, 0, 320, 960]
    # SAM pixel in its input size (M0: 640x960, 360x400).
    sam = Box(x1=16, y1=218, x2=375, y2=262, system="pixel",
              ref_w=640, ref_h=960)
    assert box_to_pixels(sam, 640, 960) == [16, 218, 375, 262]
    # Pixel scales when the original differs from the SAM input size.
    small = Box(x1=0, y1=0, x2=180, y2=200, system="pixel",
                ref_w=360, ref_h=400)
    assert box_to_pixels(small, 720, 800) == [0, 0, 360, 400]


def test_box_mixing_systems_errors():
    a = Box(x1=0, y1=0, x2=500, y2=500, system="norm1000",
            ref_w=640, ref_h=960)
    b = Box(x1=0, y1=0, x2=320, y2=480, system="pixel",
            ref_w=640, ref_h=960)
    with pytest.raises(ValueError):
        box_iou_boxes(a, b)
    c = Box(x1=0, y1=0, x2=10, y2=10, system="pixel",
            ref_w=640, ref_h=960)
    d = Box(x1=0, y1=0, x2=10, y2=10, system="pixel",
            ref_w=360, ref_h=400)
    with pytest.raises(ValueError):
        box_iou_boxes(c, d)
    # Same system and ref works.
    e = Box(x1=0, y1=0, x2=10, y2=10, system="pixel",
            ref_w=100, ref_h=100)
    assert box_iou_boxes(e, e) == 1.0


def test_concurrent_reservation_blocks_overspend(tmp_path, monkeypatch):
    # Two concurrent $1.70-expected calls on a $2 run cap: the second must
    # see the first reservation and refuse (C8). The ledger read holds the
    # lock for an extra 0.3s so both threads overlap inside check+reserve;
    # without the lock both read an empty ledger and pass, so the test
    # fails (M0-fix2 item 8). The winner is gated in the transport layer
    # so its reservation stays open while the loser checks. Sleeps here
    # are real: only retry waits are patched.
    import concurrent.futures
    import threading
    import time as real_time
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("META_RUN_CAP_USD", raising=False)
    monkeypatch.delenv("META_TOTAL_CAP_USD", raising=False)
    monkeypatch.delenv("META_LEDGER_PATH", raising=False)
    real_read = MetaClient._read_ledger_unlocked

    def slow_read(self):
        entries = real_read(self)
        real_time.sleep(0.3)  # Widen the check+reserve race window (locked).
        return entries

    monkeypatch.setattr(MetaClient, "_read_ledger_unlocked", slow_read)
    ledger_path = tmp_path / "ledger.jsonl"
    fixture_dir = tmp_path / "fixtures"
    go = threading.Event()
    entered = threading.Event()
    release = threading.Event()
    transport = FakeTransport()
    gate_lock = threading.Lock()
    blocked_once = {"done": False}
    base_create = transport.responses.create

    def single_create(**kwargs):
        with gate_lock:
            do_gate = not blocked_once["done"]
            blocked_once["done"] = True
        if do_gate:
            entered.set()
            assert release.wait(timeout=10)
        return base_create(**kwargs)

    transport.responses.create = single_create  # type: ignore[method-assign]

    def big_call():
        assert go.wait(timeout=10)
        client = MetaClient(mode="live", run_id="conc",
                            ledger_path=ledger_path,
                            fixture_dir=fixture_dir, transport=transport)
        return client.responses_create("muse-spark-1.3", "hi",
                                       max_output_tokens=400000)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(big_call)
        second = pool.submit(big_call)
        go.set()
        try:
            assert entered.wait(timeout=10)
            # The loser needs ~0.6s (winner's locked read + its own).
            real_time.sleep(0.9)
        finally:
            release.set()
        outcomes = []
        for future in (first, second):
            try:
                body = future.result(timeout=30)
                outcomes.append(("ok", body["id"]))
            except BudgetExceeded:
                outcomes.append(("refused", ""))
    assert sorted(o[0] for o in outcomes) == ["ok", "refused"]
    run_total, _ = MetaClient(
        mode="replay", run_id="conc", ledger_path=ledger_path,
        fixture_dir=fixture_dir).ledger_totals()
    assert run_total < 2.0


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
    assert checked > 0


def test_default_mode_is_replay_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("META_MODE", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = MetaClient(run_id="def",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures")
    assert client.mode == "replay"


# -- M0-fix2: D1 no automatic file deletion -------------------------------


def test_no_auto_delete_after_success(tmp_path, monkeypatch):
    # D1: a successful call never deletes payload files by itself.
    transport = FakeTransport()
    client = make_client(tmp_path, "live", transport, run_id="nodelete",
                         monkeypatch=monkeypatch)
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": "watch"},
        {"type": "input_file", "file_id": "file-fake123"}]}]
    body = client.responses_create("muse-spark-1.3", payload,
                                   max_output_tokens=10)
    assert body["id"] == "resp-fake"
    assert not [c for c in transport.calls if c[0] == "files.delete"]
    client.cleanup_files(["file-fake123"])
    assert ("files.delete", {"file_id": "file-fake123"}) in transport.calls


def test_incomplete_retry_same_file_id(tmp_path, monkeypatch):
    # D1: an incomplete response must not delete files: the retry reuses
    # the same file_id. The fake transport 404s any id seen deleted.
    transport = FakeTransport()
    deleted: set[str] = set()
    base_delete = transport.files.delete

    def tracking_delete(file_id):
        out = base_delete(file_id)
        deleted.add(file_id)
        return out

    transport.files.delete = tracking_delete  # type: ignore[method-assign]
    base_create = transport.responses.create
    calls = {"n": 0}
    incomplete = {
        "id": "r-inc", "object": "response", "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output_text": "",
        "usage": {"input_tokens": 851, "output_tokens": 2000,
                  "total_tokens": 2851,
                  "input_tokens_details": {"cached_tokens": 739},
                  "output_tokens_details": {"reasoning_tokens": 1998}}}

    def gated_create(**kwargs):
        blob = json.dumps(kwargs.get("input", ""), default=str)
        for fid in deleted:
            if fid in blob:
                raise FakeStatusError(404, "file gone")
        calls["n"] += 1
        if calls["n"] == 1:
            return dict(incomplete)
        return base_create(**kwargs)

    transport.responses.create = gated_create  # type: ignore[method-assign]
    client = make_client(tmp_path, "live", transport, run_id="retry-fid",
                         monkeypatch=monkeypatch)
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": "watch"},
        {"type": "input_file", "file_id": "file-keep123"}]}]
    with pytest.raises(IncompleteResponse):
        client.responses_create("muse-spark-1.3", payload,
                                max_output_tokens=10)
    body = client.responses_create("muse-spark-1.3", payload,
                                   max_output_tokens=4000)
    assert body["id"] == "resp-fake"
    assert not [c for c in transport.calls if c[0] == "files.delete"]
    client.cleanup_files(["file-keep123"])
    assert ("files.delete", {"file_id": "file-keep123"}) in transport.calls
    # After explicit cleanup the id is really gone.
    with pytest.raises(FakeStatusError):
        client.responses_create("muse-spark-1.3", payload,
                                max_output_tokens=4000)


def test_failed_call_does_not_auto_delete(tmp_path, monkeypatch):
    # D1 + M0-fix1 gap: a failed call leaves files alone (a retry may
    # reuse the id); explicit cleanup still works afterwards.
    transport = FakeTransport(failures=[(500, "boom")] * 5)
    client = make_client(tmp_path, "live", transport, run_id="failkeep",
                         monkeypatch=monkeypatch)
    payload = [{"role": "user", "content": [
        {"type": "input_text", "text": "watch"},
        {"type": "input_file", "file_id": "file-keep456"}]}]
    with pytest.raises(FakeStatusError):
        client.responses_create("muse-spark-1.3", payload,
                                max_output_tokens=10)
    assert not [c for c in transport.calls if c[0] == "files.delete"]
    failed = finals(read_ledger(tmp_path))
    assert len(failed) == 1 and failed[0]["status"] == "failed"
    client.cleanup_files(["file-keep456"])
    assert ("files.delete", {"file_id": "file-keep456"}) in transport.calls


def test_cleanup_files_replay_noop(tmp_path, monkeypatch):
    client = make_client(tmp_path, "replay", None, run_id="rp",
                         monkeypatch=monkeypatch)
    client.cleanup_files(["file-abc"])  # no transport, no error
    client.cleanup_files(None)
    client.cleanup_files([])


# -- M0-fix2: D2 reservation always finalized ----------------------------


def test_no_reservation_when_key_missing(tmp_path, monkeypatch):
    # D2: key check and transport creation run before the reservation,
    # so their failures leave no dangling reserved line.
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("META_RUN_CAP_USD", raising=False)
    monkeypatch.delenv("META_TOTAL_CAP_USD", raising=False)
    monkeypatch.delenv("META_LEDGER_PATH", raising=False)
    client = MetaClient(mode="live", run_id="nokey2",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures", transport=None)
    with pytest.raises(MissingKeyError):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
    assert not (tmp_path / "ledger.jsonl").exists()


def test_parse_failure_records_failed(tmp_path, monkeypatch):
    # D2: a response-parse failure after the send finalizes the
    # reservation with a failed line, then re-raises.
    transport = FakeTransport(next_response={
        "id": "r-garbage", "object": "response", "status": "completed",
        "output_text": "hi", "usage": {"input_tokens": "garbage"}})
    client = make_client(tmp_path, "live", transport, run_id="parsefail",
                         monkeypatch=monkeypatch)
    with pytest.raises(ValueError):
        client.responses_create("muse-spark-1.3", "hello",
                                max_output_tokens=100)
    entries = read_ledger(tmp_path)
    assert len(entries) == 2
    failed = [e for e in entries if e["status"] == "failed"]
    assert len(failed) == 1
    expected = pricing.estimate_spark_cost_usd(
        estimate_input_tokens("hello"), 100)
    assert failed[0]["cost_usd"] == pytest.approx(expected)
    assert failed[0]["reservation_id"] == entries[0]["reservation_id"]


# -- M0-fix2: D3 public ledger summary -----------------------------------


def test_ledger_summary_offsets_and_prefix(tmp_path, monkeypatch):
    monkeypatch.delenv("META_LEDGER_PATH", raising=False)
    lines = [
        {"run_id": "M0-P1", "status": "reserved",
         "reservation_id": "rid-1", "cost_usd": 0.01},
        {"run_id": "M0-P1", "status": "completed",
         "reservation_id": "rid-1", "cost_usd": 0.004},
        {"run_id": "M0-P1", "status": "reserved",
         "reservation_id": "rid-open", "cost_usd": 0.02},
        {"run_id": "M0-P2", "cost_usd": 0.05},  # old line, no status
        {"run_id": "other", "status": "failed",
         "reservation_id": "rid-2", "cost_usd": 0.003},
        {"run_id": "other", "status": "reserved",
         "reservation_id": "rid-2", "cost_usd": 0.009},
    ]
    path = tmp_path / "ledger.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in lines) + "\n",
                    encoding="utf-8")
    summary = ledger_summary(ledger_path=path)
    # 0.004 + open 0.02 + old 0.05 + failed 0.003; offset lines excluded.
    assert summary["total_usd"] == pytest.approx(0.077)
    assert summary["by_run_id"]["M0-P1"] == pytest.approx(0.024)
    assert summary["by_run_id"]["M0-P2"] == pytest.approx(0.05)
    assert summary["by_run_id"]["other"] == pytest.approx(0.003)
    assert summary["by_status"]["reserved"] == {
        "count": 3, "cost_usd": pytest.approx(0.02)}
    assert summary["by_status"]["completed"] == {
        "count": 2, "cost_usd": pytest.approx(0.054)}
    assert summary["by_status"]["failed"] == {
        "count": 1, "cost_usd": pytest.approx(0.003)}
    prefixed = ledger_summary("M0-P", ledger_path=path)
    assert prefixed["total_usd"] == pytest.approx(0.074)
    assert sorted(prefixed["by_run_id"]) == ["M0-P1", "M0-P2"]
    assert ledger_summary("other", ledger_path=path)["total_usd"] == \
        pytest.approx(0.003)


def test_estimate_cost_from_body():
    spark_body = {"usage": {"input_tokens": 120, "output_tokens": 40,
                           "input_tokens_details": {"cached_tokens": 20},
                           "output_tokens_details": {"reasoning_tokens": 5}}}
    assert estimate_cost_from_body(
        "muse-spark-1.3", "responses", spark_body) == pytest.approx(
            pricing.spark_cost_usd(120, 40, 20, 5))
    assert estimate_cost_from_body(
        "sam-3.1", "responses",
        {"usage": {"video_frames_processed": 60}}) == pytest.approx(
            pricing.sam_video_cost_usd(60))
    assert estimate_cost_from_body(
        "sam-3.1", "responses",
        {"usage": {}, "output_text": "box"}) == pytest.approx(
            pricing.sam_image_cost_usd(1))
    assert estimate_cost_from_body(
        "muse-image-1.0", "images.generate",
        {"data": [{"b64_json": "a"}, {"b64_json": "b"}]}) == pytest.approx(
            0.02)
    assert estimate_cost_from_body("", "models.list", {"data": []}) == 0.0
    assert estimate_cost_from_body("", "files.delete", {}) == 0.0
    assert estimate_cost_from_body(
        "muse-spark-1.3", "responses", {"usage": {}}) == 0.0
    assert estimate_cost_from_body("muse-spark-1.3", "responses", None) == 0.0
    assert estimate_cost_from_body("muse-spark-1.3", "responses", 42) == 0.0


# -- M0-fix2: D4 single ledger path --------------------------------------


def test_meta_ledger_path_env(tmp_path, monkeypatch):
    from app.meta.client import _ledger_lock_path
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("META_RUN_CAP_USD", raising=False)
    monkeypatch.delenv("META_TOTAL_CAP_USD", raising=False)
    shared = tmp_path / "shared" / "ledger.jsonl"
    monkeypatch.setenv("META_LEDGER_PATH", str(shared))
    assert resolve_ledger_path() == shared
    client = MetaClient(mode="live", run_id="env-ledger",
                        fixture_dir=tmp_path / "fixtures",
                        transport=FakeTransport())
    assert client.ledger_path == shared
    assert _ledger_lock_path(shared) == shared.parent / "ledger.jsonl.lock"
    client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
    assert shared.exists()
    assert ledger_summary()["total_usd"] > 0
    # An explicit path wins over the environment.
    other = tmp_path / "other.jsonl"
    client2 = MetaClient(mode="live", run_id="env-ledger2",
                         ledger_path=other,
                         fixture_dir=tmp_path / "fixtures",
                         transport=FakeTransport())
    assert client2.ledger_path == other


# -- M0-fix2: D5 Windows lock --------------------------------------------


def test_stale_lock_cleaned(tmp_path, monkeypatch):
    import os
    import time as real_time
    client = make_client(tmp_path, "live", FakeTransport(), run_id="stale",
                         monkeypatch=monkeypatch)
    lock_path = tmp_path / "ledger.jsonl.lock"
    lock_path.write_text("99999999", encoding="utf-8")
    old = real_time.time() - 6.0
    os.utime(lock_path, (old, old))
    body = client.responses_create("muse-spark-1.3", "hi",
                                   max_output_tokens=10)
    assert body["id"] == "resp-fake"
    assert list(tmp_path.glob("*.lock*")) == []


def test_lock_timeouts_stale_shorter_than_wait():
    import app.meta.client as client_mod
    assert client_mod._LOCK_STALE_S == 5.0
    assert client_mod._LOCK_TIMEOUT_S == 15.0
    assert client_mod._LOCK_STALE_S < client_mod._LOCK_TIMEOUT_S


def test_budget_error_catches_both():
    assert issubclass(BudgetExceeded, BudgetError)
    assert issubclass(BudgetLedgerError, BudgetError)
    for exc in (BudgetExceeded("x"), BudgetLedgerError("y")):
        with pytest.raises(BudgetError):
            raise exc


# -- M0-fix2: D7 connection reuse ----------------------------------------


def test_sdk_client_reused_and_closed(tmp_path, monkeypatch):
    import sys
    created: list = []
    closed: list = []
    fake = FakeTransport()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.models = fake.models
            self.responses = fake.responses
            self.files = fake.files
            self.images = fake.images

        def close(self):
            closed.append(True)

    monkeypatch.setitem(sys.modules, "openai",
                        type("M", (), {"OpenAI": FakeOpenAI})())
    monkeypatch.setenv("MODEL_API_KEY", "LLM_" + "Q" * 25)
    monkeypatch.delenv("META_RUN_CAP_USD", raising=False)
    monkeypatch.delenv("META_TOTAL_CAP_USD", raising=False)
    monkeypatch.delenv("META_LEDGER_PATH", raising=False)
    client = MetaClient(mode="live", run_id="reuse",
                        ledger_path=tmp_path / "ledger.jsonl",
                        fixture_dir=tmp_path / "fixtures", transport=None)
    try:
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
        client.models_list()
        assert len(created) == 1
        assert created[0].get("max_retries") == 0
        assert client._live_transport() is client._live_transport()
        client.close()
        assert closed == [True]
        client.close()  # second close is a no-op
        assert closed == [True]
        client.models_list()  # works again (re-created on demand)
        assert len(created) == 2
    finally:
        client.close()


# -- M0-fix2: D9 extra allowlist -----------------------------------------


@pytest.mark.parametrize("key", ["extra_body", "instructions", "temperature",
                                 "top_p", "model", "stream"])
def test_extra_allowlist_rejects_non_metadata(tmp_path, monkeypatch, key):
    client = make_client(tmp_path, "live", FakeTransport(), run_id="ex9",
                         monkeypatch=monkeypatch)
    with pytest.raises(ValueError):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10,
                                extra={key: "evil"})
    assert len(client.transport.calls) == 0
    assert not (tmp_path / "ledger.jsonl").exists()


def test_fixtures_extra_only_metadata():
    # D9: every recorded responses call used only "metadata" in extra, so
    # the allowlist keeps all existing fixtures replayable (hashes equal).
    allowed = {"store", "max_output_tokens", "text_format", "reasoning",
               "stream", "metadata"}
    base = ROOT / "backend" / "tests" / "fixtures" / "meta"
    responses_fixtures = 0
    with_metadata = 0
    for path in sorted(base.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("request", {}).get("endpoint") != "responses":
            continue
        responses_fixtures += 1
        params = data["request"].get("params", {})
        assert set(params) <= allowed, f"{path.name}: {sorted(params)}"
        if "metadata" in params:
            with_metadata += 1
    assert responses_fixtures > 0
    assert with_metadata > 0


# -- M0-fix2: D10 cap parsing --------------------------------------------


@pytest.mark.parametrize("bad", ["20usd", "abc", "-1", "-0.5", "inf", "+inf",
                                 "-inf", "Infinity", "nan", "1e999"])
def test_cap_invalid_values_raise(monkeypatch, bad):
    monkeypatch.setenv("META_RUN_CAP_USD", bad)
    with pytest.raises(ValueError):
        pricing.run_cap_usd()
    monkeypatch.delenv("META_RUN_CAP_USD", raising=False)
    monkeypatch.setenv("META_TOTAL_CAP_USD", bad)
    with pytest.raises(ValueError):
        pricing.total_cap_usd()


def test_cap_zero_refuses_live_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("META_RUN_CAP_USD", "0")
    assert pricing.run_cap_usd() == 0.0
    client = make_client(tmp_path, "live", FakeTransport(), run_id="zero",
                         monkeypatch=monkeypatch)
    monkeypatch.setenv("META_RUN_CAP_USD", "0")  # make_client cleared it
    with pytest.raises(BudgetExceeded):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
    assert len(client.transport.calls) == 0


# -- M0-fix2: D11 ledger and lock details --------------------------------


def test_files_delete_works_over_cap(tmp_path, monkeypatch):
    # D11: cleanup must work after the caps are exceeded (no budget check).
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"run_id": "over", "cost_usd": 150.0})
                      + "\n", encoding="utf-8")
    client = make_client(tmp_path, "live", FakeTransport(), run_id="over",
                         monkeypatch=monkeypatch)
    # Sanity: a billable call is refused (both caps exceeded).
    with pytest.raises(BudgetExceeded):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
    deleted = client.files_delete("file-fake123")
    assert deleted["deleted"] is True


def test_future_mtime_lock_is_stale(tmp_path, monkeypatch):
    import os
    import time as real_time
    client = make_client(tmp_path, "live", FakeTransport(), run_id="future",
                         monkeypatch=monkeypatch)
    lock_path = tmp_path / "ledger.jsonl.lock"
    lock_path.write_text("99999999", encoding="utf-8")
    future = real_time.time() + 3600.0
    os.utime(lock_path, (future, future))
    body = client.responses_create("muse-spark-1.3", "hi",
                                   max_output_tokens=10)
    assert body["id"] == "resp-fake"
    assert list(tmp_path.glob("*.lock*")) == []


def test_release_lock_retries_permission_error(tmp_path, monkeypatch):
    import app.meta.client as client_mod
    attempts: list = []

    def always_busy(self):
        attempts.append(1)
        raise PermissionError("delete pending")

    monkeypatch.setattr(Path, "unlink", always_busy)
    client_mod._release_file_lock(tmp_path / "x.lock")  # must not raise
    assert len(attempts) == client_mod._LOCK_RELEASE_ATTEMPTS
    # And a missing lock is a silent no-op.

    def missing(self):
        raise FileNotFoundError(str(self))

    monkeypatch.setattr(Path, "unlink", missing)
    client_mod._release_file_lock(tmp_path / "x.lock")


# -- M0-fix2: gaps the M0-fix1 breaking test missed ----------------------


def test_ledger_read_oserror_refuses(tmp_path, monkeypatch):
    # A ledger that cannot be read (here: a directory) refuses the call
    # instead of treating spend as zero.
    client = make_client(tmp_path, "live", FakeTransport(), run_id="d",
                         monkeypatch=monkeypatch)
    client.ledger_path = tmp_path  # reading a directory raises OSError
    with pytest.raises(BudgetLedgerError):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
    assert len(client.transport.calls) == 0


def test_estimate_korean_only_string_counts_each_char():
    # chars/4 underestimation passed with only 6 Korean chars in the old
    # probe string; a pure-Korean string needs >= 1 token per char.
    text = "안녕하세요반갑습니다"
    assert estimate_input_tokens(text) >= len(text)
    assert estimate_input_tokens("가") >= 1


def test_run_cap_env_reflected(tmp_path, monkeypatch):
    # A tiny run cap refuses; a raised run cap allows spend the $2
    # default would refuse (old gap: the env var was ignored).
    client = make_client(tmp_path, "live", FakeTransport(), run_id="rc",
                         monkeypatch=monkeypatch)
    monkeypatch.setenv("META_RUN_CAP_USD", "0.000001")
    with pytest.raises(BudgetExceeded):
        client.responses_create("muse-spark-1.3", "hi", max_output_tokens=10)
    assert len(client.transport.calls) == 0
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"run_id": "rc2", "cost_usd": 3.0}) + "\n",
                      encoding="utf-8")
    client2 = make_client(tmp_path, "live", FakeTransport(), run_id="rc2",
                          monkeypatch=monkeypatch)
    monkeypatch.setenv("META_RUN_CAP_USD", "5")  # make_client cleared it
    body = client2.responses_create("muse-spark-1.3", "hi",
                                    max_output_tokens=10)
    assert body["id"] == "resp-fake"
