"""Acceptance CLI. Automated observations never count as independent human review."""
import argparse
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile
import hashlib

from cra_engine.common import EngineError, digest, load, save, sha, source_fingerprint, require
from cra_engine.evidence_bundle import verify_bundle, auxiliary_sources
from cra_engine.package_check import verify_package


def freeze(root):
    files = {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file() and p != root/"manifest.json" and p.suffix not in (".sqlite-journal", ".lock")}
    save(root/"manifest.json", {"schema_version": 1, "files": files})


def run(wheel, output, software_junit=None):
    root = Path(output).resolve()
    require(not root.exists(), "Use a new acceptance output directory; earlier evidence is preserved")
    root.mkdir(parents=True)
    wheel = Path(wheel).resolve()
    candidate = root/wheel.name; shutil.copyfile(wheel, candidate)
    with ZipFile(wheel) as archive:
        engine = {name.rsplit("/", 1)[1]: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name.startswith("cra_engine/") and name.endswith(".py") and name.count("/") == 1}
        harness = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name.startswith("cra_acceptance/") and name.endswith(".py")}
        auxiliary = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name.startswith(("cra_workspace/", "cra_remote/")) and name.endswith(".py")}
    require(digest(engine) == source_fingerprint(), "Installed engine differs from candidate wheel")
    require(auxiliary and digest(auxiliary) == digest(auxiliary_sources()), "Installed workspace/worker differs from candidate wheel")
    import cra_engine
    with ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith("cra_engine/web/"):
                require((Path(cra_engine.__file__).parent/name.removeprefix("cra_engine/")).read_bytes()==archive.read(name), "Installed GUI assets differ from candidate")
    import cra_acceptance
    installed = Path(cra_acceptance.__file__).parent
    require(all(sha(installed/Path(name).name) == signature for name, signature in harness.items()), "Installed acceptance harness differs from candidate wheel")
    require("site-packages" in str(installed), "Run acceptance from a clean wheel install, not editable source checkout")
    save(root/"candidate.json", {"wheel": candidate.name, "wheel_sha256": sha(candidate), "source_tree_sha256": digest(engine), "auxiliary_sources_sha256": digest(auxiliary), "harness_sha256": digest(harness), "python": sys.executable, "version": importlib.metadata.version("communication-research-agent-tools"), "platform": sys.platform, "independent_human_operator": False})
    environment = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"], capture_output=True, text=True, timeout=30)
    (root/"environment.txt").write_text(environment.stdout)
    if software_junit:
        from cra_engine.software_evidence import write_software_report
        write_software_report(root, software_junit)
        freeze(root)
    from . import numerics, engineering, faults
    reports = {}
    for name, operation in [("statistics", lambda: {"statistics": numerics.run(root/"statistics")}), ("engineering", lambda: engineering.run(root/"boundaries")), ("faults", lambda: {"faults": faults.run(root/"faults")})]:
        try:
            result = operation()
            for suite, report in result.items():
                save(root/"reports"/(suite+".json"), report)
                reports[suite] = report
        except Exception as exc:
            save(root/"reports"/(name+"-failure.json"), {"exception_type": type(exc).__name__, "message": str(exc) if isinstance(exc, EngineError) else "Unexpected local failure; raw content withheld"})
        freeze(root)
    if "boundaries" in reports:
        from .cancellation import run as cancellation_run
        reports["boundaries"]["cases"].extend(cancellation_run(root/"cancellation"))
        save(root/"reports/boundaries.json", reports["boundaries"])
        freeze(root)
    result = verify_bundle(root)
    save(root/"result.json", result)
    freeze(root)
    return result


def prepare(root):
    root = Path(root).resolve()
    require(not root.exists(), "Use a new template directory")
    root.mkdir(parents=True)
    patterns = [
        ("The cross-sectional study reports an association.", "The survey reports an association and does not identify causation.", "supported"),
        ("The intervention improved the outcome.", "The confidence interval includes zero; the estimate is imprecise.", "unsupported"),
        ("All populations show the effect.", "Evidence concerns one convenience sample in one setting.", "unsupported"),
        ("The full article describes the instrument.", "Only an abstract is available; instrument details were not accessible.", "insufficient"),
        ("The reported finding is positive.", "The study did not find a positive association.", "unsupported")]
    cases = [{"id": "CAL-%03d" % i, "claim": patterns[i%5][0], "source_excerpt": patterns[i%5][1], "expected_for_calibration_only": patterns[i%5][2], "synthetic": True, "source_identity": "Generated calibration text, not an academic citation", "independent_holdout": False} for i in range(100)]
    save(root/"literature-calibration-100.json", {"role": "calibration_only_never_acceptance", "cases": cases, "limits": "Repeated templates test annotation plumbing only; replace with independently curated authorized real sources for acceptance"})
    for role in ("literature_expert_a", "literature_expert_b"):
        save(root/(role+"-ratings.json"), {"role": role, "reviewer": None, "ratings": [{"case_id": c["id"], "support": None, "note": None} for c in cases]})
    categories = ["normal", "null_or_imprecise", "measurement_problem", "misquotation", "infeasible", "material_change"]
    save(root/"holdout-task-template.json", {"role": "template_only_not_a_holdout", "tasks": [{"id": "TASK-%02d" % i, "category": categories[i%6], "authorized_materials": [], "expected_behaviour": None, "repeats": 3} for i in range(30)], "curator": None, "candidate_visible_answers": False})
    save(root/"pilots-template.json", {"cases": [{"id": "PILOT-%s" % i, "status": "pending", "synthetic": None, "data_authorized": None, "package": None, "package_sha256": None, "research_owner": None, "method_reviewer": None, "active_operation_minutes": None, "revisions": None} for i in range(1,4)]})
    save(root/"trust-store-template.json", {"reviewers": {}, "instructions": "Owner supplies independent reviewers and Ed25519 public keys. Keep actual trust store outside evidence bundle; never trust bundle-provided keys."})
    return {"directory": str(root), "formal_acceptance_evidence": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    runp = sub.add_parser("run"); runp.add_argument("--wheel", type=Path, required=True); runp.add_argument("--output", type=Path, required=True)
    runp.add_argument("--software-junit", type=Path, help="Raw full-regression XML, attached before operator attestation")
    verify = sub.add_parser("verify"); verify.add_argument("bundle", type=Path); verify.add_argument("--trust-store", type=Path)
    package = sub.add_parser("package"); package.add_argument("path", type=Path)
    prep = sub.add_parser("prepare"); prep.add_argument("output", type=Path)
    live = sub.add_parser("live-smoke"); live.add_argument("output", type=Path); live.add_argument("--key-file", type=Path)
    score = sub.add_parser("score-literature"); score.add_argument("ratings", type=Path)
    sign = sub.add_parser("sign-review")
    for name in ("results", "key", "output"): sign.add_argument("--"+name, type=Path, required=True)
    for name in ("candidate-sha256", "role", "signer-id", "note"): sign.add_argument("--"+name, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run": result = run(args.wheel, args.output, args.software_junit)
        elif args.command == "verify": result = verify_bundle(args.bundle, args.trust_store)
        elif args.command == "package": result = verify_package(args.path)
        elif args.command == "prepare": result = prepare(args.output)
        elif args.command == "score-literature":
            from .scoring import literature_score
            result = literature_score(load(args.ratings)["cases"])
        elif args.command == "sign-review":
            import base64
            from datetime import datetime, timezone
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cra_engine.common import dumps
            require(not args.output.exists(), "Never overwrite a review statement")
            require(len(args.candidate_sha256)==64 and len(args.note)>=8, "Candidate SHA256 and substantive review note required")
            key = load_pem_private_key(args.key.read_bytes(),password=None)
            require(isinstance(key,Ed25519PrivateKey), "Ed25519 reviewer key required")
            payload={"subject_sha256":sha(args.results),"candidate_wheel_sha256":args.candidate_sha256,"role":args.role,"decision":"pass","reviewed_at":datetime.now(timezone.utc).isoformat(),"note":args.note}
            save(args.output,{"signer_id":args.signer_id,"payload":payload,"signature":base64.b64encode(key.sign(dumps(payload).encode())).decode()})
            result={"statement":str(args.output),"limits":"Signature binds reviewer declaration to exact evidence; does not establish scientific truth or authority beyond owner trust policy"}
        else:
            from .live import smoke
            result = smoke(args.output, args.key_file)
        print(__import__("json").dumps(result, ensure_ascii=False, indent=2))
        if args.command in ("run", "verify"): return 0 if result.get("automated_engineering_passed") else 1
        if args.command == "package": return 0 if result["passed"] else 1
        return 0
    except (EngineError, OSError, ValueError) as exc:
        print(__import__("json").dumps({"error": str(exc) if isinstance(exc, EngineError) else "Acceptance operation failed; inspect local configuration"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
