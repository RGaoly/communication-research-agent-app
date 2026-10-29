"""Two explicitly authorized DeepSeek smoke requests, never research blind-test evidence."""
import datetime
import json
import os
from pathlib import Path
import time
import urllib.request

from cra_engine.common import EngineError, load, save, dumps, digest, require


def peak(instant):
    utc = instant.astimezone(datetime.timezone.utc)
    minute = utc.hour*60+utc.minute
    return utc.weekday() < 5 and (60 <= minute < 240 or 360 <= minute < 600)


def price(usage, started, ended):
    require(all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("prompt_tokens", "completion_tokens")), "Provider usage missing/invalid; cost uncertain, stop")
    hit = usage.get("prompt_cache_hit_tokens", 0)
    miss = usage.get("prompt_cache_miss_tokens", usage["prompt_tokens"]-hit)
    require(type(hit) is int and type(miss) is int and hit >= 0 and miss >= 0 and hit+miss == usage["prompt_tokens"], "Cache usage inconsistent; reconcile billing")
    multiplier = 2 if peak(started) or peak(ended) else 1
    reasoning = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
    require(type(reasoning) is int and 0 <= reasoning <= usage["completion_tokens"], "Reasoning token accounting ambiguous")
    # reasoning_tokens is a subset of completion_tokens, never charged twice.
    return {"estimated_usd": multiplier*(hit*.003+miss*.15+usage["completion_tokens"]*.60)/1e6,
            "period_multiplier": multiplier, "cache_hit_tokens": hit, "cache_miss_tokens": miss,
            "completion_tokens": usage["completion_tokens"], "reasoning_tokens_subset": reasoning,
            "pricing_basis": "User-authorized 2026-10-28 rates; conservative peak if boundary crossed. Provider bill is authoritative."}


def smoke(root, key_file=None):
    import fcntl
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    key = Path(key_file).read_text().strip() if key_file else os.environ.get("CRA_API_KEY")
    require(key and "\n" not in key, "CRA_API_KEY is unavailable in this process; no network request sent")
    # No project approval is inserted: this scope is the user's two-call transport
    # authorization, not authority to execute or approve a research protocol.
    authority = {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-flash", "announced_snapshot": "DeepSeek-V4.1-Flash-1017", "budget_usd": 5, "max_requests": 2, "scope": "one connectivity + one small task; not tool contract or research blind test"}
    save(root/"authorization.json", authority)
    with (root/"smoke.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger_path = root/"smoke-ledger.json"
        ledger = load(ledger_path) if ledger_path.exists() else {"authority_hash": digest(authority), "calls": []}
        require(ledger["authority_hash"] == digest(authority), "Smoke authority changed; explicit reconciliation required")
        require(not any(c["status"] in ("reserved", "uncertain") for c in ledger["calls"]), "Unknown paid request; no automatic resend")
        specifications = [
            {"id": "connectivity", "prompt": "只回复两个字：收到", "max_tokens": 32},
            {"id": "small-task", "prompt": 'Return a JSON object with keys inference and limitation. Evidence: a cross-sectional synthetic survey regression has an interval spanning zero. Choose inference from association/causation; explain the limitation in one sentence. Do not invent numbers or sources.', "max_tokens": 256}]
        for spec in specifications[len(ledger["calls"]):]:
            require(len(ledger["calls"]) < 2, "Two-call authorization exhausted")
            payload = {"model": authority["model"], "messages": [{"role": "user", "content": spec["prompt"]}], "max_tokens": spec["max_tokens"], "stream": False, "thinking": {"type": "disabled"}}
            if spec["id"] == "small-task": payload["response_format"] = {"type": "json_object"}
            body = dumps(payload).encode()
            reserved = ((len(body)+256)*.30+spec["max_tokens"]*1.20)/1e6
            spent = sum(c.get("estimated_usd", 0) for c in ledger["calls"])
            require(spent+reserved <= authority["budget_usd"], "Budget exhausted; live requests stopped; simulated tests must be labeled separately")
            start = datetime.datetime.now(datetime.timezone.utc)
            entry = {"id": spec["id"], "status": "reserved", "reserved_usd": reserved, "started": start.isoformat(), "request_sha256": digest(payload)}
            ledger["calls"].append(entry); save(ledger_path, ledger)
            request = urllib.request.Request(authority["base_url"]+"/chat/completions", body, {"Authorization": "Bearer "+key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    raw = response.read(1_000_001)
                require(len(raw) <= 1_000_000, "Provider response too large")
                result = json.loads(raw)
                end = datetime.datetime.now(datetime.timezone.utc)
                billing = price(result.get("usage", {}), start, end)
                message = result["choices"][0]["message"].get("content", "")
                require(result["choices"][0]["finish_reason"] == "stop", "Incomplete smoke response")
                entry.update(billing, status="settled", usage=result["usage"], response_id=result.get("id"), observed_model=result.get("model"), elapsed_seconds=(end-start).total_seconds(), finished=end.isoformat())
                save(ledger_path, ledger)
                # Never persist provider reasoning or authorization headers.
                save(root/(spec["id"]+".json"), {"request": payload, "response_content": message, "billing": entry, "scope": authority["scope"], "provider_snapshot_verification": "Returned model identifier is recorded; this alias is not an immutable version guarantee"})
                require(entry["estimated_usd"] <= reserved, "Provider exceeded conservative reservation; reconcile before another call")
            except BaseException:
                if entry["status"] == "reserved": entry["status"] = "uncertain"
                save(ledger_path, ledger)
                raise EngineError("Live request failed or incomplete; local ledger retained, no automatic retry; inspect sanitized evidence")
        return {"scope": authority["scope"], "requests": len(ledger["calls"]), "estimated_usd": sum(c.get("estimated_usd", 0) for c in ledger["calls"]), "research_blind_test_passed": False, "ledger": str(ledger_path)}
