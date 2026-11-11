"""Dependency graph and change-impact analysis (NetworkX).

Edges come from the shared repository's relationships. Given the rules a new
manual changed, we walk the graph to list what else must be re-checked:
dependent rules, the functions that implement them, the tests that validate
them and the historical case groups that exhibit them.
"""
import networkx as nx

from . import db, repository

PREFIX_KIND = (("function:", "function"), ("test:", "test"), ("G:", "case_group"))


def _kind(node_id, rules):
    for prefix, kind in PREFIX_KIND:
        if node_id.startswith(prefix):
            return kind
    return "rule" if node_id in rules else "other"


def _label(node_id, rules):
    if node_id in rules:
        r = rules[node_id]
        return f"{r['name']} ({r['version']})"
    for prefix, _ in PREFIX_KIND:
        if node_id.startswith(prefix):
            return node_id[len(prefix):]
    return node_id


def build_graph():
    rules = {r["id"]: r for r in repository.list_rules(authority="official")}
    g = nx.MultiDiGraph()
    for r in rules.values():
        g.add_node(r["id"], kind="rule", label=_label(r["id"], rules), version=r["version"],
                   status=r["status"], rule_key=r["rule_key"])
    for rel in repository.relationships():
        for n in (rel["source"], rel["target"]):
            if n not in g:
                g.add_node(n, kind=_kind(n, rules), label=_label(n, rules))
        g.add_edge(rel["source"], rel["target"], type=rel["type"], note=rel["note"])
        if rel["type"] == "OBSERVED_IN" and rel["note"]:
            g.nodes[rel["target"]]["label"] = rel["note"]
    return g


def graph_json():
    g = build_graph()
    return {"nodes": [{"id": n, **d} for n, d in g.nodes(data=True)],
            "edges": [{"source": u, "target": v, "type": d["type"], "note": d.get("note")}
                      for u, v, d in g.edges(data=True)]}


def impact(changed_rule_ids):
    """What a set of changed rules touches, with the path that explains each item."""
    g = build_graph()
    out = {"changed": [], "affected_rules": [], "functions": [], "tests": [], "case_groups": [],
           "unimplemented_rules": []}
    seen_rules = {}
    for rid in changed_rule_ids:
        if rid not in g:
            continue
        seen_rules.setdefault(rid, {"id": rid, "impact": "direct", "via": None})
        stack = [rid]
        while stack:  # rules that DEPEND_ON a changed rule are indirectly affected
            cur = stack.pop()
            for u, _, d in g.in_edges(cur, data=True):
                if d["type"] == "DEPENDS_ON" and u not in seen_rules:
                    seen_rules[u] = {"id": u, "impact": "indirect", "via": f"depends on {_label(cur, {})}"}
                    stack.append(u)
    functions, tests, groups = {}, {}, {}
    for rid, info in seen_rules.items():
        impl = 0
        for _, t, d in g.out_edges(rid, data=True):
            if d["type"] == "IMPLEMENTED_BY":
                impl += 1
                functions[t] = {"id": t, "label": g.nodes[t]["label"], "rule": rid, "note": d["note"]}
            elif d["type"] == "VALIDATED_BY":
                tests.setdefault(t, {"id": t, "label": g.nodes[t]["label"], "rules": [], "note": d["note"]})["rules"].append(rid)
            elif d["type"] == "OBSERVED_IN":
                groups[t] = {"id": t, "label": g.nodes[t]["label"], "rule": rid, "note": d["note"]}
        if impl == 0:
            out["unimplemented_rules"].append(rid)
        out["affected_rules"].append({**info, "label": g.nodes[rid]["label"], "status": g.nodes[rid].get("status")})
    out["functions"] = sorted(functions.values(), key=lambda x: x["id"])
    out["tests"] = sorted(tests.values(), key=lambda x: x["id"])
    out["case_groups"] = sorted(groups.values(), key=lambda x: x["id"])
    out["changed"] = list(changed_rule_ids)
    return out


def refresh(actor="system"):
    """Recompute impact for the rules changed by the latest policy comparison."""
    pc = db.get_artifact("policy_changes")
    if not pc:
        return None
    ids = [c["new_id"] for c in pc["rule_changes"] if c["change"] in ("modified", "new") and c["new_id"]]
    result = impact(ids)
    db.put_artifact("impact", result)
    return result
