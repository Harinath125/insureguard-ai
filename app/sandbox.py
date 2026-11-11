"""Run uploaded rating code outside the API process."""
import json
import select
import subprocess
import sys
from pathlib import Path

WORKER = str(Path(__file__).with_name("sandbox_worker.py"))


class EngineError(RuntimeError):
    pass


class SandboxedEngine:
    """Long-lived worker process, so thousands of generated test calls stay fast."""

    def __init__(self, path, timeout=10.0):
        self.path = str(path)
        self.timeout = timeout
        self.proc = subprocess.Popen(
            [sys.executable, "-I", WORKER, self.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, env={})

    def call(self, fn, *args):
        if self.proc.poll() is not None:
            raise EngineError("engine process is not running")
        self.proc.stdin.write(json.dumps({"fn": fn, "args": list(args)}) + "\n")
        self.proc.stdin.flush()
        ready, _, _ = select.select([self.proc.stdout], [], [], self.timeout)
        if not ready:
            self.proc.kill()
            raise EngineError(f"{fn} timed out after {self.timeout}s")
        line = self.proc.stdout.readline()
        if not line:
            raise EngineError("engine process ended unexpectedly")
        out = json.loads(line)
        if "err" in out:
            raise EngineError(out["err"])
        return out["ok"]

    def close(self):
        try:
            if self.proc.poll() is None:
                self.proc.stdin.close()
                self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
