"""FastAPI application: REST API plus the static dashboard."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import archaeology, db, impact, pipeline, report, repository

ROLE_RANK = {"viewer": 0, "analyst": 1, "reviewer": 2, "admin": 3}
STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield


app = FastAPI(title="InsureGuard AI", version="1.0",
              description="Insurance decision intelligence and assurance platform", lifespan=lifespan)


def need(minimum):
    """Role gate. Roles come from X-Role / X-User headers: a demonstration of
    role-based access control, not real authentication."""
    def dep(request: Request):
        role = request.headers.get("x-role", "analyst").lower()
        if role not in ROLE_RANK:
            raise HTTPException(400, f"unknown role {role!r}; use one of {sorted(ROLE_RANK)}")
        if ROLE_RANK[role] < ROLE_RANK[minimum]:
            raise HTTPException(403, f"role {role!r} cannot do this; {minimum!r} or higher is required")
        return {"role": role, "user": request.headers.get("x-user", role)}
    return dep


def _engine(name):
    if name not in pipeline.ENGINES or name == "rating_v1":
        raise HTTPException(400, f"engine must be one of {[e for e in pipeline.ENGINES if e != 'rating_v1']}")
    return name


@app.get("/api/health")
def health():
    return {"status": "ok", "rules": len(repository.list_rules()), "engines": list(pipeline.ENGINES)}


@app.post("/api/pipeline/run")
def run_pipeline(auto_approve: bool = True, engine: str = "rating_v2", manual_format: str = "txt",
                 who=Depends(need("analyst"))):
    if manual_format not in ("txt", "pdf"):
        raise HTTPException(400, "manual_format must be txt or pdf")
    return pipeline.run_all(actor=who["user"], auto_approve=auto_approve, engine=_engine(engine),
                            manual_format=manual_format)


@app.get("/api/rules")
def rules(version: str | None = None, authority: str | None = None, status: str | None = None):
    return repository.list_rules(version, authority, status)


@app.post("/api/rules/{rule_id:path}/decision")
def decide_rule(rule_id: str, body: dict = Body(...), who=Depends(need("reviewer"))):
    decision = body.get("decision")
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be 'approve' or 'reject'")
    rule = repository.get_rule(rule_id)
    if not rule:
        raise HTTPException(404, "no such rule")
    if rule["authority"] != "official":
        raise HTTPException(400, "only official (manual-derived) rules are approved here")
    repository.set_status(rule_id, "approved" if decision == "approve" else "rejected",
                          who["user"], body.get("comment", ""))
    return repository.get_rule(rule_id)


@app.get("/api/policy/changes")
def policy_changes():
    return db.get_artifact("policy_changes", {})


@app.get("/api/impact")
def get_impact():
    return db.get_artifact("impact", {})


@app.get("/api/graph")
def graph():
    return impact.graph_json()


@app.post("/api/archaeology/run")
def run_archaeology(engine: str = "rating_v2", manual_version: str = "v2", who=Depends(need("analyst"))):
    return pipeline.step_archaeology(_engine(engine), manual_version, who["user"])


@app.get("/api/archaeology/analyze")
def analyze_engine(engine: str = "rating_v2"):
    """Rules and static findings straight from the AST, without touching stored data."""
    if engine not in pipeline.ENGINES:
        raise HTTPException(404, "unknown engine")
    return archaeology.analyze_file(pipeline.ENGINES[engine])


@app.post("/api/drift/run")
def run_drift(who=Depends(need("analyst"))):
    return pipeline.step_drift(who["user"])


@app.get("/api/drift")
def get_drift():
    return db.get_artifact("drift", {})


@app.post("/api/assurance/run")
def run_assurance(engine: str = "rating_v2", who=Depends(need("analyst"))):
    return pipeline.step_assurance(_engine(engine), who["user"])


@app.get("/api/assurance")
def get_assurance():
    return db.get_artifact("assurance", {})


@app.get("/api/findings")
def findings(module: str | None = None, status: str | None = None):
    return repository.list_findings(module, status)


@app.post("/api/findings/{finding_id}/review")
def review(finding_id: int, body: dict = Body(...), who=Depends(need("reviewer"))):
    try:
        repository.review_finding(finding_id, who["user"], body.get("decision", ""), body.get("comment", ""))
    except KeyError:
        raise HTTPException(404, "no such finding")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/report")
def get_report():
    return report.build_report()


@app.get("/api/report.html", response_class=HTMLResponse)
def get_report_html():
    return report.render_html(report.build_report())


@app.get("/api/audit")
def get_audit(limit: int = 100):
    return db.query("SELECT ts, actor, action, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))


app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
