"""Evidence-based acceptance verification; attestations require external trusted keys."""
import base64
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from .common import EngineError, digest, dumps, load, require, sha, source_fingerprint, within
from .package_check import verify_package

MINIMUM = {"installation": 1, "statistics": 30, "faults": 100, "boundaries": 20, "mutations": 3,
           "literature": 100, "live_model": 90, "pilots": 3}
AUTOMATED = {"installation", "statistics", "faults", "boundaries", "mutations"}


def observations_hash(files):
    """Stable automatic-observation subject, excluding later expert declarations."""
    return digest({path:signature for path,signature in files.items() if path.startswith(("statistics/","faults/","boundaries/","cancellation/","software/")) or path in {"candidate.json","environment.txt","reports/software.json",*("reports/"+name+".json" for name in AUTOMATED)} or path.endswith(".whl")})


def verify_signature(statement, trust, subject_sha, candidate_sha, role):
    require(isinstance(statement, dict), "Signed review statement required")
    payload = statement.get("payload", {})
    reviewer = trust.get("reviewers", {}).get(statement.get("signer_id"), {})
    require(role in reviewer.get("roles", []) and reviewer.get("independent") is True, "Reviewer role/independence not trusted")
    require(payload.get("subject_sha256") == subject_sha and payload.get("candidate_wheel_sha256") == candidate_sha and payload.get("role") == role, "Review signature refers to different evidence")
    require(payload.get("decision") == "pass" and bool(payload.get("reviewed_at")) and len(payload.get("note", "")) >= 8, "Incomplete review decision")
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = load_pem_public_key(reviewer["public_key_pem"].encode())
        require(isinstance(key, Ed25519PublicKey), "Ed25519 reviewer key required")
        key.verify(base64.b64decode(statement["signature"], validate=True), dumps(payload).encode())
    except ImportError as exc:
        raise EngineError("Install acceptance extra to verify Ed25519 review signatures") from exc
    except Exception as exc:
        raise EngineError("Review signature invalid") from exc
    return statement["signer_id"]


def verify_bundle(root, trust_store=None):
    root = Path(root).resolve()
    problems, suites = [], {}
    try:
        manifest = load(root / "manifest.json")
        require(manifest.get("schema_version") == 1, "Unknown acceptance evidence version")
        files = manifest.get("files", {})
        require(isinstance(files, dict) and files, "Evidence files missing")
        require("candidate.json" in files, "Candidate record not bound to manifest")
        for relative, signature in files.items():
            path = within(root, relative)
            require(path.is_file() and sha(path) == signature, "Acceptance artifact hash mismatch: " + relative)
        candidate = load(root / "candidate.json")
        wheel = within(root, candidate["wheel"])
        require(candidate["wheel"] in files and sha(wheel) == candidate["wheel_sha256"], "Candidate wheel mismatch")
        with ZipFile(wheel) as bundle:
            package = {name.rsplit("/", 1)[1]: hashlib.sha256(bundle.read(name)).hexdigest() for name in bundle.namelist() if name.startswith("cra_engine/") and name.endswith(".py") and name.count("/") == 1}
        require(digest(package) == candidate["source_tree_sha256"] == source_fingerprint(), "Evidence belongs to different engine source")
        trust = load(trust_store) if trust_store else {}
        if trust_store:
            require(root not in Path(trust_store).resolve().parents, "Reviewer trust store must be external to submitted evidence")
        for name, minimum in MINIMUM.items():
            relative = "reports/" + name + ".json"
            if relative not in files:
                suites[name] = {"status": "pending", "reason": "report unavailable"}
                continue
            report = load(root / relative)
            cases = report.get("cases", [])
            require(isinstance(cases, list) and all(isinstance(c,dict) and isinstance(c.get("id"),str) and c["id"] for c in cases) and len({c.get("id") for c in cases}) == len(cases), "Duplicate or malformed acceptance cases")
            passed = len(cases) >= minimum and all(c.get("status") == "passed" for c in cases)
            # A status flag without its observed outputs is not test evidence.
            for case in cases:
                if case.get("status") == "passed":
                    artifacts = case.get("artifacts", [])
                    require(artifacts and all(a in files for a in artifacts), "Case lacks registered observations")
            if name == "statistics":
                passed = passed and all(c.get("oracle") == "independent_numpy_scipy" and c.get("numeric_match") is True and c.get("sample_match") is True for c in cases)
                for case in cases:
                    observation = load(root/case["artifacts"][0])
                    actual, oracle = observation["actual"], observation["oracle"]
                    from .package_check import close
                    if "models" in actual:
                        model = actual["models"][0]
                        fields = ("estimate", "se", "statistic", "p", "ci_low", "ci_high")
                        passed = passed and model["n"] == oracle["n"] and [p["term"] for p in model["parameters"]] == oracle["terms"] and all(close(p[key], row[index],1e-7,1e-6) for p,row in zip(model["parameters"],oracle["values"]) for index,key in enumerate(fields))
                    else:
                        passed = passed and all(close(actual["weighted"][k]["weighted_mean"],v,1e-10) for k,v in oracle.items())
            if name == "faults":
                recovered = sum(c.get("recovered") is True for c in cases)
                passed = len(cases) >= minimum and recovered / len(cases) >= 0.95 and all(c.get("critical_violation") is False for c in cases)
                passed = passed and len({load(root/c["artifacts"][0]).get("scenario") for c in cases}) >= 10
                for case in cases:
                    observed = load(root/case["artifacts"][0])
                    if case.get("recovered"):
                        passed = passed and bool(observed.get("checks")) and all(v is True for v in observed["checks"].values())
            if name == "mutations":
                passed = passed and {c.get("mutation") for c in cases} >= {"wrong_coefficient", "unauthorized_request", "stale_approval"} and all(c.get("detected") is True for c in cases)
            if name == "live_model":
                passed = passed and report.get("origin") == "live_remote_model" and report.get("dataset_role") == "independent_holdout" and len({c.get("task_id") for c in cases}) >= 30
                passed = passed and all(sum(c.get("task_id") == task for c in cases) >= 3 for task in {c.get("task_id") for c in cases})
                passed = passed and len({c.get("model_snapshot") for c in cases}) == 1 and all(c.get("model_snapshot") and c.get("synthetic_provider") is False and c.get("no_critical_violation") is True for c in cases)
            if name == "literature":
                try:
                    from cra_acceptance.scoring import literature_score
                    passed = literature_score(cases)["passed"] and all(c.get("synthetic") is False and c.get("independent_holdout") is True for c in cases)
                except EngineError as exc:
                    passed = False; problems.append("literature: "+str(exc))
            if name == "pilots":
                for case in cases:
                    if case.get("status") != "passed":
                        continue
                    require(case.get("synthetic") is False and case.get("data_authorized") is True, "Synthetic/unauthorized project cannot count as a pilot")
                    package_path = case.get("package")
                    require(package_path in files and sha(root / package_path) == case.get("package_sha256"), "Pilot package not actually present or mismatched")
                    require(verify_package(root / package_path)["passed"], "Pilot package failed independent consistency checks")
            if name not in AUTOMATED:
                try:
                    roles = {"literature": ("literature_expert_a", "literature_expert_b"), "live_model": ("holdout_curator", "method_reviewer"), "pilots": ("research_owner", "method_reviewer")}[name]
                    statements = report.get("attestations", {})
                    result_path = relative.replace(".json", "-results.json")
                    require(result_path in files, "Signed result observations not registered")
                    require(load(root / result_path).get("cases") == cases, "Signed observations differ from reported cases")
                    signers = [verify_signature(statements.get(role), trust, sha(root / result_path), candidate["wheel_sha256"], role) for role in roles]
                    require(len(set(signers)) == len(signers), "Independent roles require distinct trusted signers")
                except (EngineError, OSError, KeyError) as exc:
                    passed = False
                    problems.append(name + ": " + (str(exc) if isinstance(exc, EngineError) else "signed review results unavailable"))
            suites[name] = {"status": "passed" if passed else "pending_or_failed", "cases": len(cases), "minimum": minimum}
        automated = all(suites[name]["status"] == "passed" for name in AUTOMATED)
        software = False
        try:
            from .software_evidence import verify_software_report
            software = verify_software_report(root, files)
        except (EngineError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            problems.append(str(exc) if isinstance(exc, EngineError) else "Invalid software evidence; inspect locally")
        # Manual public-CLI approval is never synthesized by the automated harness.
        manual = False
        if "manual-cli-results.json" in files and "manual-cli-attestation.json" in files:
            try:
                manual_results = load(root/"manual-cli-results.json")
                require(manual_results.get("automated_observations_sha256") == observations_hash(files), "Operator review not bound to current raw automatic observations")
                require(manual_results.get("checkpoints") == {"authorization":True,"protocol":True,"final":True} and manual_results.get("independent_operator") is True, "Actual independent public-CLI checkpoints required")
                verify_signature(load(root / "manual-cli-attestation.json"), trust, sha(root / "manual-cli-results.json"), candidate["wheel_sha256"], "acceptance_operator")
                manual = True
            except EngineError as exc:
                problems.append(str(exc))
        return {"bundle_valid": True, "automated_engineering_passed": automated, "manual_cli_verified": manual,
                "engineering_acceptance_passed": automated and manual and software,
                "software_evidence_passed": software,
                "release_eligible": automated and manual and software and all(v["status"] == "passed" for v in suites.values()),
                "suites": suites, "problems": problems, "candidate_wheel_sha256": candidate["wheel_sha256"],
                "automated_observations_sha256": observations_hash(files),
                "limits": "Hash/signature integrity proves evidence binding and configured signer origin, not truth of expert judgments. Same-author automation is not independent human acceptance."}
    except (EngineError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, __import__('zipfile').BadZipFile) as exc:
        return {"bundle_valid": False, "release_eligible": False, "automated_engineering_passed": False,
                "problems": [str(exc) if isinstance(exc, EngineError) else "Invalid acceptance evidence; inspect locally"]}
