import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INSUREGUARD_DB", str(tmp_path / "api.db"))
    from app.main import app
    with TestClient(app) as c:
        yield c


def H(role):
    return {"X-Role": role, "X-User": f"{role}-user"}


def test_full_flow_and_report(client):
    r = client.post("/api/pipeline/run", headers=H("analyst"))
    assert r.status_code == 200 and r.json()["assurance"]["defects"] == 2
    rep = client.get("/api/report").json()
    assert rep["summary"]["distinct_defects"] == 2 and rep["summary"]["drift_groups_flagged"] == 1
    assert rep["summary"]["rule_changes"] == 4 and len(rep["limitations"]) >= 5
    html = client.get("/api/report.html").text
    assert "InsureGuard AI: assurance report" in html and "renewal_quote" in html
    assert client.get("/").status_code == 200                     # dashboard is served


def test_role_checks_and_approval_flow(client):
    client.post("/api/pipeline/run?auto_approve=false", headers=H("analyst"))
    rid = "MULT_HIGH@v2"
    assert client.post(f"/api/rules/{rid}/decision", json={"decision": "approve"}, headers=H("analyst")).status_code == 403
    assert client.post(f"/api/rules/{rid}/decision", json={"decision": "approve"}, headers=H("viewer")).status_code == 403
    assert client.post("/api/pipeline/run", headers=H("viewer")).status_code == 403
    assert client.get("/api/health", headers={"X-Role": "nobody"}).status_code == 200
    assert client.post("/api/pipeline/run", headers=H("nobody")).status_code == 400
    for k in ("BASE_RATE", "MULT_HIGH", "MULT_STANDARD", "DEDUCTIBLE_CREDIT"):
        ok = client.post(f"/api/rules/{k}@v2/decision", json={"decision": "approve", "comment": "checked"},
                         headers=H("reviewer"))
        assert ok.status_code == 200 and ok.json()["status"] == "approved"
    out = client.post("/api/assurance/run?engine=rating_v2", headers=H("analyst")).json()
    assert out["failed"] == 4 and len(out["defects"]) == 2
    audit = client.get("/api/audit").json()
    assert any(a["action"] == "rule_approved" and a["actor"] == "reviewer-user" for a in audit)


def test_finding_review_and_validation(client):
    client.post("/api/pipeline/run", headers=H("analyst"))
    fid = next(f["id"] for f in client.get("/api/findings?module=assurance").json())
    assert client.post(f"/api/findings/{fid}/review", json={"decision": "confirmed"}, headers=H("analyst")).status_code == 403
    assert client.post(f"/api/findings/{fid}/review", json={"decision": "maybe"}, headers=H("reviewer")).status_code == 400
    assert client.post("/api/findings/99999/review", json={"decision": "confirmed"}, headers=H("reviewer")).status_code == 404
    assert client.post(f"/api/findings/{fid}/review", json={"decision": "confirmed", "comment": "ok"},
                       headers=H("reviewer")).status_code == 200
    assert client.get("/api/findings?status=confirmed").json()[0]["id"] == fid


def test_rejects_bad_input(client):
    assert client.post("/api/pipeline/run?engine=rating_v1", headers=H("analyst")).status_code == 400
    assert client.post("/api/pipeline/run?manual_format=doc", headers=H("analyst")).status_code == 400
    client.post("/api/pipeline/run", headers=H("analyst"))
    assert client.post("/api/rules/NOPE/decision", json={"decision": "approve"}, headers=H("reviewer")).status_code == 404
    assert client.post("/api/rules/IMPL:rating_v2:renewal_quote:MULT_HIGH/decision", json={"decision": "approve"},
                       headers=H("reviewer")).status_code == 400   # code-derived rules are not approved here


def test_pdf_manuals_give_the_same_result(client):
    out = client.post("/api/pipeline/run?manual_format=pdf", headers=H("analyst")).json()
    assert out["assurance"]["defects"] == 2 and out["policy"]["clauses_new"] == 5
