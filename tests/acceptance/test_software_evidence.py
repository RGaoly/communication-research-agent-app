"""Synthetic parser inputs only; these are not accepted regression-run reports."""
import xml.etree.ElementTree as ET

import pytest

from cra_engine.common import EngineError, load, save, sha
from cra_engine.evidence_bundle import observations_hash
from cra_engine.software_baseline import CASES
from cra_engine.software_evidence import junit_summary, write_software_report, verify_software_report


def xml_fixture(path, identities=CASES, child=None):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests=str(len(identities)), failures="0", errors="0", skipped="0")
    for classname, name in identities:
        ET.SubElement(suite, "testcase", classname=classname, name=name)
    if child:
        ET.SubElement(suite[0], child)
        suite.set({"failure": "failures", "error": "errors", "skipped": "skipped"}[child], "1")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def bound_fixture(root):
    xml_fixture(root / "input.xml")
    report = write_software_report(root, root / "input.xml")
    files = {name: sha(root/name) for name in ("reports/software.json", "software/software-tests.xml")}
    return report, files


def test_raw_software_report_requires_frozen_cases(tmp_path):
    xml_fixture(tmp_path / "raw.xml", [("TEST_ONLY", "one_case")])
    with pytest.raises(EngineError, match="Frozen"):
        write_software_report(tmp_path, tmp_path / "raw.xml")


def test_same_count_cannot_replace_a_frozen_case(tmp_path):
    xml_fixture(tmp_path / "raw.xml", list(CASES)[1:] + [("TEST_ONLY", "unrelated_case")])
    with pytest.raises(EngineError, match="Frozen"):
        junit_summary(tmp_path / "raw.xml")


@pytest.mark.parametrize("child", ["failure", "error", "skipped"])
def test_regression_failures_errors_and_skips_block(tmp_path, child):
    xml_fixture(tmp_path / "raw.xml", child=child)
    with pytest.raises(EngineError, match="failures, errors or skipped"):
        junit_summary(tmp_path / "raw.xml")


def test_duplicate_cases_cannot_inflate_coverage(tmp_path):
    xml_fixture(tmp_path / "raw.xml", list(CASES) + [CASES[0]])
    with pytest.raises(EngineError, match="duplicate"):
        junit_summary(tmp_path / "raw.xml")


def test_declared_software_totals_must_match_cases(tmp_path):
    xml_fixture(tmp_path / "raw.xml")
    tree = ET.parse(tmp_path / "raw.xml")
    tree.find("testsuite").set("tests", str(len(CASES) + 1))
    tree.write(tmp_path / "raw.xml")
    with pytest.raises(EngineError, match="totals"):
        junit_summary(tmp_path / "raw.xml")


def test_raw_software_manifest_and_source_are_required(tmp_path):
    report, files = bound_fixture(tmp_path)
    assert verify_software_report(tmp_path, files)
    files.pop("software/software-tests.xml")
    with pytest.raises(EngineError, match="manifest"):
        verify_software_report(tmp_path, files)
    files["software/software-tests.xml"] = sha(tmp_path / "software/software-tests.xml")
    report["source_tree_sha256"] = "wrong"
    save(tmp_path / "reports/software.json", report)
    with pytest.raises(EngineError, match="source version"):
        verify_software_report(tmp_path, files)


def test_software_tamper_cannot_be_hidden_by_summary_fields(tmp_path):
    report, files = bound_fixture(tmp_path)
    xml = tmp_path / report["junit"]
    xml.write_text(xml.read_text().replace(CASES[0][1], "TEST_ONLY_replacement", 1))
    with pytest.raises(EngineError, match="hash"):
        verify_software_report(tmp_path, files)
    report["junit_sha256"] = sha(xml)
    save(tmp_path / "reports/software.json", report)
    with pytest.raises(EngineError, match="Frozen"):
        verify_software_report(tmp_path, files)


def test_operator_subject_covers_software_report_and_raw_xml():
    original = {"reports/software.json": "summary", "software/software-tests.xml": "raw"}
    for path in original:
        assert observations_hash(original) != observations_hash({**original, path: "changed"})


def test_xml_entities_are_refused_without_expansion(tmp_path):
    path = tmp_path / "raw.xml"
    path.write_text('<!DOCTYPE testsuite [<!ENTITY private "TEST_ONLY">]><testsuite/>')
    with pytest.raises(EngineError, match="Unsafe"):
        junit_summary(path)
