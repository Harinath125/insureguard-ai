"""Worker process that runs one rating engine in isolation.

Started by app.sandbox with `python -I`. It applies CPU and memory limits,
loads the engine file, then answers JSON-line requests on stdin/stdout.
Best-effort isolation (separate process, resource limits, empty environment);
a container would be the production answer.
"""
import importlib.util
import json
import sys


def main(path):
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    except Exception:
        pass
    spec = importlib.util.spec_from_file_location("engine_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for line in sys.stdin:
        try:
            req = json.loads(line)
            fn = getattr(mod, req["fn"])
            out = {"ok": fn(*req["args"])}
        except Exception as e:  # report engine errors instead of crashing
            out = {"err": f"{type(e).__name__}: {e}"}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main(sys.argv[1])
