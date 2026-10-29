"""Check raw regression observations; a report never authenticates its own origin."""
from pathlib import Path
import xml.etree.ElementTree as ET

from . import __version__
from .common import require, source_fingerprint, sha, load, within
from .software_baseline import CASES


def junit_summary(path):
    raw = Path(path).read_bytes()
    require(len(raw) <= 4_000_000 and b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(), "Unsafe or oversized software XML")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        require(False, "Malformed software XML")
    require(root.tag in ("testsuites", "testsuite"), "Expected JUnit regression XML")
    cases = list(root.iter("testcase"))
    identities = [(c.get("classname"), c.get("name")) for c in cases]
    require(all(all(isinstance(v, str) and v for v in key) for key in identities) and len(set(identities)) == len(identities), "Missing or duplicate software case identities")
    require(set(CASES).issubset(identities), "Frozen regression cases are missing")
    counts = {"tests": len(cases), "failures": sum(c.find("failure") is not None for c in cases), "errors": sum(c.find("error") is not None for c in cases), "skipped": sum(c.find("skipped") is not None for c in cases)}
    leaves = [s for s in root.iter("testsuite") if not list(s.iter("testsuite"))[1:]]
    require(leaves, "Software test suites missing")
    declared = {k: sum(int(s.get(k, "0")) for s in leaves) for k in counts}
    require(declared == counts, "Software XML totals differ from observed cases")
    require(not any(counts[k] for k in ("failures", "errors", "skipped")), "Software regression has failures, errors or skipped cases")
    return counts


def write_software_report(root, junit_path):
    """Attach raw XML before independent operator attestation; never sign it here."""
    from .common import atomic, save
    root = Path(root)
    raw = Path(junit_path).read_bytes()
    xml = root / "software/software-tests.xml"
    atomic(xml, raw.decode("utf-8"))
    counts = junit_summary(xml)
    report = {"version": __version__, "source_tree_sha256": source_fingerprint(), "software_tests": counts,
              "junit": "software/software-tests.xml", "junit_sha256": sha(xml),
              "limits": "Raw XML and frozen identities validate completeness/integrity, not execution origin. Independent operator must review source, invocation and raw observations."}
    save(root / "reports/software.json", report)
    return report


def verify_software_report(root, files):
    root = Path(root)
    require("reports/software.json" in files, "Raw software report is required for formal release")
    report = load(root / "reports/software.json")
    require(report.get("version") == __version__ and report.get("source_tree_sha256") == source_fingerprint(), "Software evidence belongs to a different source version")
    relative = report.get("junit")
    require(relative == "software/software-tests.xml" and relative in files, "Software XML not bound to acceptance manifest")
    xml = within(root, relative)
    require(sha(xml) == report.get("junit_sha256"), "Software XML hash differs from report")
    require(report.get("software_tests") == junit_summary(xml), "Software report counts differ from raw XML")
    return True
