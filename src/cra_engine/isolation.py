"""Fail-closed OS isolation for trusted statistical recipes, never arbitrary code."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .common import EngineError, load, require, save, sha


class IsolatedRecipeError(EngineError):
    """Sanitized failure with local, hash-bound progress evidence."""
    def __init__(self, message, metadata):
        super().__init__(message)
        self.metadata = metadata


def command(scratch, inputs):
    scratch = Path(scratch).resolve()
    package = Path(__file__).resolve().parent
    # Keep the venv entrypoint: resolving its symlink would drop site-packages.
    executable = Path(sys.executable).absolute()
    readable = {str(Path(sys.prefix).resolve()), str(Path(sys.base_prefix).resolve()), str(package.parent),
                "/System", "/usr", "/Library", "/private/etc", "/dev", *[str(Path(p).resolve()) for p in inputs]}
    worker = [str(executable), "-B", str(package / "worker.py"), str(scratch / "request.json"), str(scratch / "response.json")]
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        import json
        # SBPL does not decode JSON's ASCII-only \u escapes into file paths.
        # Keep Unicode literal while retaining JSON escaping for quotes/slashes.
        approved = "(require-any " + " ".join("(subpath " + json.dumps(p, ensure_ascii=False) + ")" for p in sorted(readable | {str(scratch)})) + ")"
        private = '(require-any (subpath "/Users") (subpath "/home") (subpath "/root") (subpath "/private/var") (subpath "/tmp"))'
        writable = '(require-any (subpath ' + json.dumps(str(scratch), ensure_ascii=False) + ') (literal "/dev/null"))'
        rules = ["(version 1)", "(allow default)", "(deny network*)",
                 "(deny file-write* (require-not " + writable + "))",
                 "(deny file-read-data (require-all " + private + " (require-not " + approved + ")))" ]
        return ["sandbox-exec", "-p", "\n".join(rules), *worker], "macos-seatbelt"
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        args = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
        paths = sorted(readable | {"/lib", "/lib64"}, key=lambda p: len(Path(p).parts))
        mounted = []
        for path in paths:
            if path == "/dev" or not Path(path).exists() or any(Path(p) in Path(path).parents for p in mounted):
                continue
            args += ["--ro-bind", path, path]
            mounted.append(path)
        # A fresh tmpfs root is not inherently read-only. Keep the one writable
        # run bind, but seal its parent/root mounts non-recursively.
        args += ["--bind", str(scratch), str(scratch), "--remount-ro", "/tmp", "--remount-ro", "/dev",
                 "--remount-ro", "/", "--chdir", str(scratch), "--", *worker]
        return args, "linux-bubblewrap"
    raise EngineError("OS isolation unavailable; autonomous statistics refused. Use planning/manual mode or install a validated isolation backend")


def execute(store, action, payload, inputs=(), timeout=300):
    import uuid
    scratch = store.root / ".cra/runs" / uuid.uuid4().hex
    scratch.mkdir(parents=True)
    save(scratch / "request.json", {"action": action, "payload": payload})
    argv, backend = command(scratch, inputs)
    env = {"PATH": os.defpath, "HOME": str(scratch), "TMPDIR": str(scratch), "LANG": "en_US.UTF-8",
           "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    if sys.platform == "darwin":
        env["CRA_SUPERVISOR_PID"] = str(os.getpid())
    def failure(message):
        metadata = {"isolation": backend, "scratch": scratch.relative_to(store.root).as_posix()}
        progress = scratch / "specification-progress.json"
        if progress.is_file() and not progress.is_symlink():
            metadata.update(progress_path=progress.relative_to(store.root).as_posix(), progress_sha256=sha(progress))
        return IsolatedRecipeError(message, metadata)
    process = None
    try:
        process = subprocess.Popen(argv, env=env, cwd=scratch, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        save(scratch / "worker-identity.json", {"pid": process.pid})
        import time
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if time.monotonic() >= deadline or store.meta("paused", False):
                import signal
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise failure("Worker paused or timed out; checkpoint retained")
            time.sleep(0.05)
        if process.returncode != 0 or not (scratch / "response.json").is_file():
            raise failure("Isolation/worker unavailable; no unisolated fallback was run")
        output = load(scratch / "response.json")
        if output.get("ok") is not True:
            raise failure(output.get("error", "Local recipe failed"))
        return {"result": output["result"], "isolation": backend, "scratch": scratch.relative_to(store.root).as_posix()}
    finally:
        if process is not None and process.poll() is None:
            import signal
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def doctor(store):
    import socket
    # A closed port is not evidence of network isolation. This listener is known
    # reachable on the host; the isolated worker must not be able to reach it.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
        result = execute(store, "probe", {"host_listener_port": port}, timeout=15)
    require(result["result"] == {"network_denied": True, "write_denied": True, "control_read_denied": True}, "Isolation self-test failed")
    return result
