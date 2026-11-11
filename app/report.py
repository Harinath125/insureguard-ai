"""Cross-module assurance report (JSON and HTML)."""
import html
from collections import Counter

from . import db, repository

LIMITATIONS = [
    "Manual rules are extracted with deterministic patterns written for the synthetic manual format; no LLM is used.",
    "Code analysis targets straight-line Python rating functions (conditions on named inputs, constant factors).",
    "Underwriting cases and manuals are synthetic. Detection rates below were measured on planted defects only.",
    "Rating code runs in a separate process with CPU and memory limits, not in a container.",
    "Roles are taken from a request header for demonstration; this is not real authentication.",
    "Findings are candidates for human review. A difference from the manual can be an approved exception.",
]


def build_report():
    cfg = db.get_artifact("run_config", {})
    engine = cfg.get("engine")
    findings = repository.list_findings()
    sev = Counter(f["severity"] for f in findings if f["status"] == "open")
    by_module = Counter(f["module"] for f in findings if f["module"] != "policy")
    rules = repository.list_rules()
    assur = db.get_artifact("assurance", {})
    arch = db.get_artifact("archaeology", {})
    drift = db.get_artifact("drift", {})
    pc = db.get_artifact("policy_changes", {})
    scope = assur.get(engine) if engine else None
    return {
        "generated_at": db.now(),
        "scenario": {"product": "Commercial property", "old_version": cfg.get("old_version"),
                     "new_version": cfg.get("new_version"), "engine_under_test": engine,
                     "auto_approve": cfg.get("auto_approve")},
        "summary": {
            "open_findings_by_severity": dict(sev),
            "findings_by_module": dict(by_module),
            "rules": dict(Counter(f"{r['authority']}:{r['status']}" for r in rules)),
            "rule_changes": sum(1 for c in pc.get("rule_changes", []) if c["change"] != "unchanged"),
            "drift_groups_flagged": len(drift.get("flagged", [])),
            "tests": ({k: scope[k] for k in ("tests", "passed", "failed", "skipped")} if scope else {}),
            "distinct_defects": len(scope["defects"]) if scope else 0,
        },
        "policy": pc,
        "impact": db.get_artifact("impact", {}),
        "archaeology": arch,
        "drift": drift,
        "assurance": assur,
        "findings": findings,
        "pending_approvals": [r for r in rules if r["authority"] == "official" and r["status"] == "candidate"],
        "audit": db.query("SELECT ts, actor, action, detail FROM audit_log ORDER BY id DESC LIMIT 40"),
        "limitations": LIMITATIONS,
    }


def _e(x):
    return html.escape(str(x))


def render_html(rep):
    s = rep["summary"]
    sc = rep["scenario"]
    out = ["<!doctype html><html><head><meta charset='utf-8'><title>InsureGuard AI assurance report</title>",
           "<style>body{font-family:Calibri,Arial,sans-serif;max-width:960px;margin:2rem auto;color:#10252b;padding:0 1rem}"
           "h1,h2{color:#0b4f5c}table{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}"
           "td,th{border:1px solid #d5e3e6;padding:6px 8px;text-align:left;vertical-align:top;font-size:14px}"
           "th{background:#0b4f5c;color:#fff}.high{color:#b3261e;font-weight:700}.medium{color:#a15c00;font-weight:700}"
           "code{background:#eaf3f4;padding:1px 4px}</style></head><body>",
           "<h1>InsureGuard AI: assurance report</h1>",
           f"<p>Product: {_e(sc['product'])}. Manual {_e(sc['old_version'])} to {_e(sc['new_version'])}. "
           f"Engine under test: <code>{_e(sc['engine_under_test'])}</code>. Generated {_e(rep['generated_at'])}.</p>",
           "<h2>Summary</h2><ul>",
           f"<li>Rule changes found in the new manual: {s['rule_changes']}</li>",
           f"<li>Open findings by severity: {_e(s['open_findings_by_severity'])}</li>",
           f"<li>Property tests: {_e(s.get('tests'))}; distinct defects: {s['distinct_defects']}</li>",
           f"<li>Underwriting groups flagged for review: {s['drift_groups_flagged']}</li></ul>"]
    out.append("<h2>Policy changes</h2><table><tr><th>Rule</th><th>Change</th><th>Source</th></tr>")
    for c in rep["policy"].get("rule_changes", []):
        if c["change"] != "unchanged":
            out.append(f"<tr><td>{_e(c['summary'])}</td><td>{_e(c['change'])}</td><td>{_e(c.get('source_ref', ''))}</td></tr>")
    out.append("</table>")
    imp = rep["impact"]
    if imp:
        out.append("<h2>Impact</h2><ul>")
        out.append("<li>Rules: " + _e(", ".join(f"{r['label']} ({r['impact']})" for r in imp["affected_rules"])) + "</li>")
        out.append("<li>Functions: " + _e(", ".join(f["label"] for f in imp["functions"]) or "none") + "</li>")
        out.append("<li>Tests: " + _e(len(imp["tests"])) + "</li>")
        out.append("<li>Rules with no implementation found: " + _e(", ".join(imp["unimplemented_rules"]) or "none") + "</li></ul>")
    out.append("<h2>Findings</h2><table><tr><th>Severity</th><th>Module</th><th>Finding</th><th>Status</th></tr>")
    for f in rep["findings"]:
        if f["module"] == "policy":
            continue
        out.append(f"<tr><td class='{_e(f['severity'])}'>{_e(f['severity'])}</td><td>{_e(f['module'])}</td>"
                   f"<td>{_e(f['title'])}<br><small>{_e(f['detail'])}</small></td><td>{_e(f['status'])}</td></tr>")
    out.append("</table><h2>Limitations</h2><ul>")
    out += [f"<li>{_e(x)}</li>" for x in rep["limitations"]]
    out.append("</ul></body></html>")
    return "".join(out)
