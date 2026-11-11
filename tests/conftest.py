import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Empty database, isolated per test."""
    monkeypatch.setenv("INSUREGUARD_DB", str(tmp_path / "t.db"))
    from app import db
    db.init_db(reset=True)
    return db


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    """One full pipeline run (engine with seeded defects), shared by a test module."""
    mp = pytest.MonkeyPatch()
    mp.setenv("INSUREGUARD_DB", str(tmp_path_factory.mktemp("db") / "run.db"))
    from app import pipeline
    steps = pipeline.run_all(actor="test", auto_approve=True, engine="rating_v2")
    yield steps
    mp.undo()
