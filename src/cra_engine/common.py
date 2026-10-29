import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class EngineError(Exception):
    """Messages must not include raw respondent values, secrets or provider bodies."""


def require(value, message):
    if not value:
        raise EngineError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_fingerprint():
    return digest({p.name: sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))})


def load(path):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            require(key not in obj, "JSON contains duplicate keys")
            obj[key] = value
        return obj
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError) as exc:
        raise EngineError("Invalid JSON; inspect the local source without transmitting its contents") from exc


def atomic(path, content):
    path = Path(path)
    require(not path.is_symlink(), "Symlink output refused")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".cra-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def within(root, relative):
    root = Path(root).resolve()
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), "Expected a project-relative path")
    path = root / relative
    require(root in path.resolve().parents, "Path escapes project")
    for part in [path, *path.parents]:
        if part == root:
            break
        require(not part.is_symlink(), "Symlink path refused")
    return path


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


PATTERNS = [r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", r"(?<![A-Za-z0-9])(?<!\d\.)1[3-9]\d{9}(?![A-Za-z0-9])(?!\.\d)",
            r"(?<![A-Za-z0-9])(?<!\d\.)\d{17}[\dXx](?![A-Za-z0-9])(?!\.\d)", r"(?:sk-|AKIA)[A-Za-z0-9_-]{16,}"]


def safe_text(value):
    """Heuristic defense, never a privacy guarantee. Do not return matching snippets."""
    text = value if isinstance(value, str) else dumps(value)
    require(not any(re.search(pattern, text) for pattern in PATTERNS), "Possible sensitive content; inspect locally before egress")
    return value


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value)
