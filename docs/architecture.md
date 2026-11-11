# Architecture notes

## Core design

The prototype connects four analysis modules through a shared rule repository:

- Policy change impact extracts and compares candidate rules from two versions of a rate manual.
- Legacy rule archaeology inspects supported Python rating code with the AST and maps discovered logic to policy expectations.
- Underwriting drift analysis groups comparable synthetic cases and highlights decisions that differ without a recorded reason.
- Rating assurance checks an engine against approved rules using property-based and related tests.

## Trust and review boundary

Extracted or inferred rules are candidates, not authoritative facts. Source references and approval status are retained. The reviewer role can approve or reject candidates; rating assurance uses approved rules. Findings should be reviewed by a qualified person before any business action.

## Current implementation boundaries

The application currently uses FastAPI, a static HTML/JavaScript dashboard and SQLite. Extraction is deterministic and tailored to the sample manuals; no LLM is integrated. The code analyzer targets supported Python patterns. The execution worker is process-isolated with resource limits but is not a hardened container sandbox.
