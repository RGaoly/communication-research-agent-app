"""Explicit dispatch. Missing remote configuration NEVER falls back locally."""
from . import isolation
from .common import require


def remote(store):
    brief = store.get("brief") or {}
    if brief.get("execution", {}).get("backend", "local") == "local": return None
    configured = getattr(store, "remote_executor", None)
    if configured is None:
        import os
        from pathlib import Path
        endpoint, credential = os.environ.get("CRA_WORKER_URL"), os.environ.get("CRA_WORKER_TOKEN_FILE")
        if endpoint and credential:
            path = Path(credential)
            require(path.is_file() and not path.is_symlink() and path.stat().st_mode & 0o077 == 0, "Worker credential file must be private")
            from cra_remote.client import RemoteExecutor
            configured = RemoteExecutor(endpoint, path.read_text().strip())
    require(configured is not None, "Remote worker operator configuration missing; execution refused")
    return configured


def doctor(store):
    target = remote(store)
    return target.doctor(store) if target else isolation.doctor(store)


def execute(store, action, payload, inputs=(), timeout=300, fresh=False):
    target = remote(store)
    if target: return target.execute(store, action, payload, inputs, timeout, fresh=fresh)
    return isolation.execute(store, action, payload, inputs, timeout)
