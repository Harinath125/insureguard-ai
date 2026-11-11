# InsureGuard AI — Screenshot Gallery

These screenshots show the current InsureGuard AI prototype after running the sample pipeline.

## Application overview

![InsureGuard AI overview](screenshots/01-overview.png)

## Policy change impact

Compares the two sample policy-manual versions and highlights changed clauses, source references, and downstream impact.

![Policy impact](screenshots/02-policy-impact.png)

## Legacy rule archaeology

Shows business rules discovered in the sample Python rating implementation, with function and line-level evidence.

![Rule archaeology](screenshots/03-rule-archaeology.png)

## Underwriting decision drift

Highlights comparable synthetic cases with different recorded decisions. A flag means investigate; it does not establish that a decision was wrong.

![Underwriting drift](screenshots/04-underwriting-drift.png)

## Metamorphic rating assurance

Displays property-based and differential test results, including reproducible counterexamples for seeded defects.

![Rating assurance](screenshots/05-rating-assurance.png)

## Rules and human approvals

Shows rule versions, source references, confidence, approval status, and the reviewer actions available for candidate rules.

![Rules and approvals](screenshots/06-rules-and-approvals.png)

## Dependency graph

Visualizes relationships between rules, implementation functions, tests, and flagged case groups.

![Dependency graph](screenshots/07-dependency-graph.png)

## Findings

Consolidates findings with severity, module, evidence, and review status.

![Findings](screenshots/08-findings.png)

## Role selector

The prototype's demonstration role selector.

![Role selector](screenshots/09-role-selector.png)

---

## Add this folder to the project

Copy the `screenshots/` directory into the root of your InsureGuard AI repository.

Then add a link to this gallery from the main `README.md`:

```markdown
## Screenshots

See the [complete application screenshot gallery](SCREENSHOTS.md).
```

If you rename this file to `SCREENSHOTS.md` in your repository root, the relative image paths will work as written.
