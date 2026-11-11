import pytest

from app.sandbox import EngineError, SandboxedEngine

GOOD = "def f(a, b):\n    return a + b\ndef boom(a):\n    raise ValueError('bad')\n"


def test_calls_and_errors(tmp_path):
    p = tmp_path / "e.py"
    p.write_text(GOOD)
    with SandboxedEngine(p) as e:
        assert e.call("f", 2, 3) == 5
        with pytest.raises(EngineError):
            e.call("boom", 1)
        assert e.call("f", 1, 1) == 2          # still alive after an engine error


def test_runaway_engine_is_killed(tmp_path):
    p = tmp_path / "loop.py"
    p.write_text("def f(a):\n    while True:\n        pass\n")
    with SandboxedEngine(p, timeout=0.5) as e:
        with pytest.raises(EngineError):
            e.call("f", 1)


def test_worker_has_no_inherited_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")
    p = tmp_path / "env.py"
    p.write_text("import os\ndef f():\n    return os.environ.get('SECRET_TOKEN', 'absent')\n")
    with SandboxedEngine(p) as e:
        assert e.call("f") == "absent"
