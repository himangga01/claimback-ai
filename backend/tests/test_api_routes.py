import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_and_health():
    res = client.get("/")
    assert res.status_code == 200
    assert "ClaimBack" in res.text

    res_h = client.get("/health")
    assert res_h.status_code == 200
    assert res_h.json()["status"] == "healthy"


def test_get_demo_samples():
    res = client.get("/api/demo/samples")
    assert res.status_code == 200
    data = res.json()
    assert "korean_sample" in data
    assert "us_sample" in data


def test_api_verify_endpoint():
    samples = client.get("/api/demo/samples").json()
    kr = samples["korean_sample"]

    res = client.post("/api/verify", json={
        "loan_fact": kr["loan_fact"],
        "claim_draft": kr["claim_draft"],
        "target_date": "2026-10-31"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PASS"
    assert data["is_valid"] is True
    assert str(data["reconciled_amount"]).startswith("10000000")


def test_api_compile_ecourt_packet():
    samples = client.get("/api/demo/samples").json()
    kr = samples["korean_sample"]

    res = client.post("/api/compile/ecourt-packet", json={
        "loan_fact": kr["loan_fact"],
        "claim_draft": kr["claim_draft"],
        "target_date": "2026-10-31"
    })
    assert res.status_code == 200
    data = res.json()
    assert "claim_purpose" in data
    assert "claim_cause_payment_order" in data
    assert "claim_cause_lawsuit" in data


def test_api_compile_sc100_endpoint():
    samples = client.get("/api/demo/samples").json()
    us = samples["us_sample"]

    res = client.post("/api/compile/sc100", json={
        "loan_fact": us["loan_fact"],
        "claim_draft": us["claim_draft"],
        "target_date": "2026-10-31"
    })
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert len(res.content) > 100000


def test_api_compile_content_proof_endpoint():
    samples = client.get("/api/demo/samples").json()
    kr = samples["korean_sample"]

    res = client.post("/api/compile/content-proof", json={
        "loan_fact": kr["loan_fact"],
        "claim_draft": kr["claim_draft"],
        "target_date": "2026-10-31"
    })
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert len(res.content) > 1000
