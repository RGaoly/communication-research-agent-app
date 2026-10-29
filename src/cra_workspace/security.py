"""Session-scoped credentials and expiring, snapshot-bound review challenges."""
import hmac
import secrets
import threading
import time

from cra_engine.common import require


class Credentials:
    def __init__(self):
        self._keys = {}
        self._lock = threading.Lock()

    def put(self, project, config_hash, value, ttl=7200):
        require(isinstance(value, str) and 0 < len(value.strip()) <= 2048 and "\n" not in value and "\r" not in value, "请提供有效模型密钥；不写入项目文件")
        require(0 < ttl <= 86400, "凭据会话期限无效")
        with self._lock:
            self._keys[project] = (config_hash, value.strip(), time.monotonic() + ttl)

    def get(self, project, config_hash):
        with self._lock:
            row = self._keys.get(project)
            if row is None or row[0] != config_hash or row[2] <= time.monotonic():
                self._keys.pop(project, None)
                return None
            return row[1]

    def clear(self, project):
        with self._lock:
            self._keys.pop(project, None)


class Reviews:
    def __init__(self):
        self._pending = {}
        self._lock = threading.Lock()

    def issue(self, project, scope, snapshot):
        nonce = secrets.token_urlsafe(32)
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if v[3] > time.monotonic()}
            self._pending[nonce] = (project, scope, snapshot, time.monotonic() + 600)
        return {"nonce": nonce, "scope": scope, "snapshot": snapshot,
                "confirmation": "APPROVE " + snapshot[:12], "expires_in_seconds": 600,
                "identity_certified": False}

    def consume(self, nonce, project, scope, snapshot):
        with self._lock:
            row = self._pending.pop(nonce, None)
        require(row and row[:2] == (project, scope) and row[3] > time.monotonic() and hmac.compare_digest(row[2], snapshot), "审阅已过期或材料版本变化，请重新打开当前范围核查")
