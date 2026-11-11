# Contributing

Thanks for your interest in InsureGuard AI. This repository is a prototype focused on reproducible insurance-rule analysis and assurance.

## Before you start

- Open an issue describing the bug or proposed change before large contributions.
- Do not commit real policyholder data, confidential insurer material, credentials or production source code.
- Keep examples synthetic and reproducible.
- Be explicit about whether a finding is a deterministic rule, a heuristic or a human-reviewed conclusion.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Checks

```bash
python -m pytest
python scripts/evaluate.py
```

## Pull requests

1. Keep changes focused and explain the problem they solve.
2. Add or update tests for behaviour changes.
3. Update the README when setup, API behaviour, limitations or evaluation results change.
4. Never claim production readiness or real-world accuracy based only on the bundled synthetic scenario.
5. Include a concise summary and test evidence in the pull request.
