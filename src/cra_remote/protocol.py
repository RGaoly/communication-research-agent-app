import hashlib
import hmac
import json
import re

from cra_engine.common import EngineError, digest, dumps, require
from cra_engine.statistics import recipe_identity

VERSION = 1
MAX_BODY = 48_000_000
MAX_RESULT = 8_000_000
JOB = re.compile(r"^[a-f0-9]{32}$")


def parse(raw):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            require(key not in obj, "Duplicate JSON field refused")
            obj[key] = value
        return obj
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise EngineError("Invalid remote protocol JSON") from exc


def identity():
    from pathlib import Path
    from cra_engine.common import sha
    return {"protocol": VERSION, "recipe": recipe_identity(),
            "remote_sources": {name: sha(Path(__file__).with_name(name))
                               for name in ("protocol.py", "worker.py")}}


def sign(body, token):
    # Authentication of the configured endpoint; not independent attestation.
    return {"body": body, "mac": hmac.new(token.encode(), dumps(body).encode(), hashlib.sha256).hexdigest()}


def verify(envelope, token):
    require(isinstance(envelope, dict) and set(envelope) == {"body", "mac"}, "Unsigned worker response refused")
    expected = sign(envelope["body"], token)["mac"]
    require(isinstance(envelope["mac"], str) and hmac.compare_digest(expected, envelope["mac"]), "Worker response authentication failed")
    return envelope["body"]


def request_hash(request):
    return digest(request)
