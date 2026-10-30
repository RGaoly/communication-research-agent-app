"""IP-pinned HTTPS client, persistent idempotency and hash-bound results."""
import base64
import hashlib
import json
from pathlib import Path
import time
import urllib.request
from urllib.parse import urlsplit
import uuid

from cra_engine.common import EngineError, digest, dumps, require, safe_text, save, sha, within
from cra_engine.isolation import IsolatedRecipeError
from .protocol import MAX_BODY, VERSION, identity, parse, request_hash, verify


class RemoteExecutor:
    def __init__(self, endpoint, token, test_loopback=False):
        url = urlsplit(endpoint)
        local = test_loopback and url.scheme == "http" and url.hostname == "127.0.0.1"
        require(local or url.scheme == "https" and url.port in (None, 443), "Worker requires public HTTPS on port443")
        require(url.hostname and not url.username and not url.password and not url.query and not url.fragment and url.path in ("", "/"), "Worker URL must contain only its origin")
        require(isinstance(token, str) and len(token) >= 32, "Worker credential missing")
        self.endpoint, self._token, self._local = endpoint.rstrip("/"), token, local

    def _request(self, method, path, body=None):
        from cra_workspace.network import PublicHTTPSHandler
        raw = dumps(body).encode() if body is not None else None
        require(raw is None or len(raw) <= MAX_BODY, "Worker request size exceeded")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicHTTPSHandler(), NoRedirect())
        req = urllib.request.Request(self.endpoint + path, data=raw, method=method,
                                     headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=30) as response:
                data = response.read(20_000_001)
                require(len(data) <= 20_000_000, "Worker response size exceeded")
            return verify(parse(data), self._token)
        except (OSError, ValueError) as exc:
            raise EngineError("Worker response uncertain; retained job ID, no blind resubmission") from exc

    def health(self):
        body = self._request("GET", "/v1/health")
        require(body.get("protocol") == VERSION and body.get("identity") == identity(), "Worker recipe/environment identity mismatch; no data sent")
        require(body.get("passed") is True and body.get("controls") == {"network_denied": True, "write_denied": True, "control_read_denied": True}, "Worker isolation check failed; no data sent")
        return body

    def doctor(self, store):
        scope = (store.get("brief") or {}).get("execution", {})
        require(scope.get("endpoint") == self.endpoint, "Configured worker differs from project scope")
        health = self.health()
        return {"result": health["controls"], "isolation": "remote:" + health["isolation"], "worker": health}

    def execute(self, store, action, payload, inputs, timeout, fresh=False):
        brief = store.get("brief", fresh=True)
        require(brief["permissions"].get("remote_statistics") is True and store.approved("authorization"), "Authorize remote analysis-copy transfer for this project first")
        require(not store.meta("paused", False), "Project paused; no remote upload")
        require(action in ("audit", "analysis"), "Only fixed statistical recipes may be remote")
        if action == "analysis": require(store.approved("protocol"), "Current frozen protocol required")
        health = self.doctor(store)["worker"]  # Recipe/capability before any data transfer.
        require(brief["execution"].get("identity_hash") == digest(health["identity"]), "Worker changed after authorization; reconfigure and approve")
        paths = {key: within(store.root, brief["data"][key]) for key in ("csv", "codebook")}
        require(store.meta("measurement_review") == digest({k: sha(p) for k, p in paths.items()}), "Current analysis copy and codebook need a recorded measurement review before transfer")
        require(set(map(lambda p: str(Path(p).resolve()), inputs)) == set(str(p.resolve()) for p in paths.values()), "Unapproved remote inputs refused")
        require(all(str(paths[k]) == payload[{"csv": "csv_path", "codebook": "book_path"}[k]] for k in paths), "Recipe path mismatch")
        from cra_engine.common import load
        book = load(paths["codebook"])
        require(book.get("columns") and all(v.get("sensitive") is False for v in book["columns"].values()), "Unreviewed or sensitive columns cannot be uploaded")
        files = {}
        for key, path in paths.items():
            raw = path.read_bytes()
            require(0 < len(raw) <= (32_000_000 if key == "csv" else 1_000_000), "Analysis copy size exceeded")
            safe_text(raw.decode("utf-8-sig"))
            files[key] = {"base64": base64.b64encode(raw).decode("ascii"), "sha256": hashlib.sha256(raw).hexdigest()}
        params = {k: v for k, v in payload.items() if k not in ("csv_path", "book_path")}
        request = {"protocol": VERSION, "identity": health["identity"], "action": action, "files": files,
                   "parameters": params, "timeout": int(max(1, min(300, timeout)))}
        # Persist before POST. A dropped response is resolved with GET on the SAME
        # job ID on resume, never a new paid/compute job by inference.
        key = digest({"endpoint": self.endpoint, "request": {k: v for k, v in request.items() if k != "timeout"}, "purpose": "reproduce" if fresh else "execution"})
        with store.tx():
            jobs = store.meta("remote_jobs", {})
            existing = jobs.get(key)
            if fresh and existing and existing["state"] in ("succeeded", "failed", "cancelled"):
                existing = None
            if not existing:
                signature = request_hash(request)
                existing = {"id": uuid.uuid4().hex, "request_hash": signature, "state": "prepared", "timeout": request["timeout"]}
                jobs[key] = existing
                store.set_meta("remote_jobs", jobs)
                store.event("remote_job_prepared", {"job": existing["id"], "action": action, "endpoint": self.endpoint, "request_hash": signature, "fresh_computation": fresh})
        request["timeout"] = existing["timeout"]
        signature = request_hash(request)
        require(signature == existing["request_hash"], "Persisted remote request mismatch")
        job = existing["id"]
        state = self._request("GET", "/v1/jobs/" + job)
        if state["status"] == "not_found":
            require(existing["state"] == "prepared", "Previously submitted remote job missing; operator reconciliation required")
            # Mark before transmission: a process interruption cannot hide a POST.
            with store.tx():
                jobs = store.meta("remote_jobs", {}); jobs[key]["state"] = "submitted"; store.set_meta("remote_jobs", jobs)
            state = self._request("POST", "/v1/jobs/" + job, request)
        deadline = time.monotonic() + timeout + 5
        while state["status"] in ("queued", "running"):
            if store.meta("paused", False) or time.monotonic() >= deadline:
                try: self._request("DELETE", "/v1/jobs/" + job)
                except EngineError: pass
                raise EngineError("Remote cancellation requested; job ID retained for reconciliation")
            time.sleep(0.15)
            state = self._request("GET", "/v1/jobs/" + job)
        require(state.get("job") == job and state.get("request_hash") == signature, "Remote response bound to different inputs")
        if state["status"] != "succeeded":
            with store.tx():
                jobs = store.meta("remote_jobs", {}); jobs[key]["state"] = state["status"]; store.set_meta("remote_jobs", jobs)
            metadata = {"isolation": "remote", "job": job, "worker_status": state["status"]}
            progress = state.get("progress")
            if progress is not None:
                require(progress.get("protocol_hash") == digest(params.get("protocol")) and progress.get("data_sha256") == files["csv"]["sha256"] and progress.get("codebook_sha256") == files["codebook"]["sha256"], "Remote progress input mismatch")
                safe_text(progress)
                rel = ".cra/remote/" + job + "/specification-progress.json"
                save(store.root / rel, progress)
                metadata.update(progress_path=rel, progress_sha256=sha(store.root / rel))
            raise IsolatedRecipeError("Remote recipe did not complete; no automatic new job", metadata)
        require(state.get("identity") == health["identity"], "Worker identity changed during computation")
        result = state.get("result", {})
        require(state.get("result_hash") == digest(result), "Remote result digest mismatch")
        data_key = "input_sha256" if action == "audit" else "data_sha256"
        require(result.get(data_key) == files["csv"]["sha256"] and result.get("codebook_sha256") == files["codebook"]["sha256"], "Remote result input mismatch")
        if action == "analysis": require(result.get("protocol_hash") == digest(params["protocol"]) and result.get("recipe_identity") == health["identity"]["recipe"], "Remote analysis binding mismatch")
        safe_text(result)
        record = {"job": job, "request_hash": signature, "result_hash": state["result_hash"], "endpoint": self.endpoint, "identity": health["identity"], "isolation": state["isolation"]}
        save(store.root / (".cra/remote/" + job + "/receipt.json"), record)
        with store.tx():
            jobs = store.meta("remote_jobs", {}); jobs[key]["state"] = "succeeded"; store.set_meta("remote_jobs", jobs)
            store.event("remote_job_received", record)
        return {"result": result, "isolation": "remote:" + state["isolation"], "scratch": ".cra/remote/" + job, "remote_receipt": record}

    def cancel_pending(self, store):
        outcomes = []
        for entry in store.meta("remote_jobs", {}).values():
            if entry["state"] not in ("submitted", "running", "queued", "unknown"): continue
            try: self._request("DELETE", "/v1/jobs/" + entry["id"]); status = "requested"
            except EngineError: status = "unconfirmed"
            outcomes.append({"job": entry["id"], "cancellation": status})
        return outcomes


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise EngineError("Worker redirects refused; credential never forwarded")
