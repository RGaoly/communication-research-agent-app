"""Behavior tests: synthetic fixtures only; TEST reviewers are never real approvals."""
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("demo", REPO / "examples/run_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
cra = demo.cra


class ResearchAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "synthetic-project"
        self.baseline = demo.build(self.root)

    def run_cli(self, *args, code=0):
        result = subprocess.run([sys.executable, str(demo.CLI), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return json.loads(result.stdout or result.stderr)

    def json(self, rel):
        return cra.read_json(self.root / rel)

    def put(self, rel, value):
        cra.write_json(self.root / rel, value)

    def report(self):
        return cra.validate(self.root, cra.load_state(self.root), "submission")

    def assert_issue(self, code):
        report = self.report()
        self.assertEqual(report["automatic_status"], "fail", report)
        self.assertIn(code, {v["code"] for v in report["findings"]})
        return report

    def update_artifact_hash(self, rel):
        manifest = self.json("artifacts/manifest.json")
        for item in manifest["items"]:
            if item["path"] == rel:
                item["sha256"] = cra.file_hash(self.root / rel)
        self.put("artifacts/manifest.json", manifest)

    def test_demo_passes_automatic_but_requires_all_human_reviews(self):
        self.assertEqual(self.baseline["automatic_status"], "pass", self.baseline)
        self.assertEqual(self.baseline["overall_status"], "needs_human_review")
        self.assertEqual(len(self.baseline["human_checks"]), 6)
        self.assertTrue(all(v["status"] == "required" for v in self.baseline["human_checks"]))
        self.assertEqual(self.baseline["metrics"]["data"]["n_rows"], 60)

    def test_privacy_scan_does_not_treat_decimal_results_as_identifiers(self):
        path = self.root / "artifacts/numerical-check.json"
        path.write_text('{"b":0.123456789012345678,"se":-0.13812345678}')
        findings = []
        metrics = cra.privacy_scan(self.root, cra.load_state(self.root), lambda *v: findings.append(v))
        self.assertEqual(metrics["heuristic_hits"], 0)
        self.assertFalse(findings)

    def test_privacy_scan_still_flags_identifiers_after_prose_period(self):
        path = self.root / "artifacts/TEST-synthetic-sentinels.txt"
        path.write_text('TEST ONLY phone.13812345678 ID.110101199001010017 email.test@example.invalid')
        findings = []
        metrics = cra.privacy_scan(self.root, cra.load_state(self.root), lambda *v: findings.append(v))
        self.assertEqual(metrics["heuristic_hits"], 3)
        self.assertIn("possible_sensitive_content", {v[0] for v in findings})

    def test_ols_known_values(self):
        model, _ = cra.ols([{"x": "1", "y": "2"}, {"x": "2", "y": "3"}, {"x": "3", "y": "5"}], "x", "y")
        self.assertEqual(model["n"], 3)
        self.assertAlmostEqual(model["b"], 1.5)
        self.assertAlmostEqual(model["intercept"], 1 / 3)
        self.assertAlmostEqual(model["se"], math.sqrt(1 / 12))
        self.assertAlmostEqual(model["r2"], 27 / 28)

    def test_ols_complete_cases(self):
        rows = [{"x": "1", "y": "2"}, {"x": "2", "y": "3"}, {"x": "3", "y": "5"}, {"x": "", "y": "4"}]
        self.assertEqual(cra.ols(rows, "x", "y")[0]["n"], 3)

    def test_ols_rejects_constant_and_insufficient_inputs(self):
        for rows in ([{"x": "1", "y": "2"}] * 3, [{"x": "1", "y": "2"}] * 2):
            with self.assertRaises(cra.CRAError):
                cra.ols(rows, "x", "y")

    def test_init_never_overwrites(self):
        before = cra.file_hash(self.root / "project.json")
        self.run_cli("init", self.root, code=2)
        self.assertEqual(before, cra.file_hash(self.root / "project.json"))

    def test_fresh_project_templates_block(self):
        project = Path(self.temp.name).resolve() / "fresh"
        self.run_cli("init", project)
        report = self.run_cli("validate", project, code=1)
        self.assertIn("unfinished_evidence", {v["code"] for v in report["findings"]})

    def test_stage_cannot_skip_human_review(self):
        self.run_cli("advance", self.root, code=2)
        self.assertEqual(self.json("project.json")["stage"], "design")

    def test_resume_all_stages_and_reject_changed_evidence(self):
        for stage in cra.STAGES:
            self.assertEqual(self.run_cli("status", self.root)["stage"], stage)
            self.run_cli("review", self.root, "--stage", stage, "--reviewer", "TEST ONLY", "--decision", "pass", "--note", "TEST synthetic fixture only; not a real research approval")
            self.run_cli("advance", self.root)
        self.assertTrue(self.run_cli("status", self.root)["complete"])
        with (self.root / "protocol/design.md").open("a") as stream:
            stream.write("\n改变了证据。\n")
        status = self.run_cli("status", self.root)
        self.assertFalse(status["complete"])
        self.assertEqual(set(status["stale_reviews"]), set(cra.STAGES))
        self.run_cli("advance", self.root, code=2)

    def test_future_review_and_changes_required_do_not_advance(self):
        self.run_cli("review", self.root, "--stage", "writing", "--reviewer", "TEST ONLY", "--decision", "pass", "--note", "TEST fixture only", code=2)
        self.run_cli("review", self.root, "--stage", "design", "--reviewer", "TEST ONLY", "--decision", "changes_required", "--note", "TEST unresolved design issue")
        self.run_cli("advance", self.root, code=2)

    def test_profile_switch_invalidates_review(self):
        self.run_cli("review", self.root, "--stage", "design", "--reviewer", "TEST ONLY", "--decision", "pass", "--note", "TEST no actual approval")
        self.run_cli("configure", self.root, "--profile", "ica", "--target", "TEST year/division")
        self.assertEqual(self.run_cli("status", self.root)["stale_reviews"], ["design"])

    def test_ica_requires_specific_target(self):
        self.run_cli("configure", self.root, "--profile", "ica", "--target", "")
        self.assert_issue("submission_target")

    def test_sample_n_mismatch(self):
        results = self.json("artifacts/results.json")
        results["sample_n"] = 61
        self.put("artifacts/results.json", results)
        self.assert_issue("sample_n")

    def test_model_n_cannot_exceed_sample(self):
        results = self.json("artifacts/results.json")
        results["models"]["m1"]["n"] = 100
        self.put("artifacts/results.json", results)
        self.assert_issue("invalid_input")

    def test_stale_input_hash(self):
        path = self.root / "data/input.csv"
        path.write_text(path.read_text().replace("S000", "S100"), encoding="utf-8")
        self.assert_issue("stale_data")

    def test_recomputed_regression_catches_internally_consistent_fabrication(self):
        results = self.json("artifacts/results.json")
        model = results["models"]["m1"]
        model["b"] += 0.2
        model["t"] = model["b"] / model["se"]
        self.put("artifacts/results.json", results)
        self.assert_issue("recompute_mismatch")

    def test_b_over_se_identity(self):
        results = self.json("artifacts/results.json")
        results["models"]["m1"]["t"] = 999
        self.put("artifacts/results.json", results)
        self.assert_issue("regression_identity")

    def test_negative_se_and_nonfinite_json_rejected(self):
        results = self.json("artifacts/results.json")
        results["models"]["m1"]["se"] = -0.1
        self.put("artifacts/results.json", results)
        self.assert_issue("invalid_input")
        cra.write_text(self.root / "artifacts/results.json", '{"sample_n":NaN}')
        self.assert_issue("invalid_input")

    def test_table_numbers_even_with_updated_hash(self):
        path = self.root / "artifacts/table.csv"
        lines = path.read_text().splitlines()
        lines[1] = "n,59"
        path.write_text("\n".join(lines) + "\n")
        self.update_artifact_hash("artifacts/table.csv")
        self.assert_issue("table_number")

    def test_unmapped_table_number(self):
        with (self.root / "artifacts/table.csv").open("a") as stream:
            stream.write("unmapped,2\n")
        self.update_artifact_hash("artifacts/table.csv")
        self.assert_issue("invalid_input")

    def test_svg_coordinates_even_with_updated_hash(self):
        path = self.root / "artifacts/figure.svg"
        path.write_text(path.read_text().replace('cx="30.000000"', 'cx="31.000000"', 1))
        self.update_artifact_hash("artifacts/figure.svg")
        self.assert_issue("figure_number")

    def test_nan_svg_coordinates_rejected(self):
        path = self.root / "artifacts/figure.svg"
        path.write_text(path.read_text().replace('cx="30.000000"', 'cx="nan"', 1))
        self.update_artifact_hash("artifacts/figure.svg")
        self.assert_issue("figure_number")

    def test_wrong_svg_point_count(self):
        path = self.root / "artifacts/figure.svg"
        path.write_text(path.read_text().replace('<circle ', '<g ', 1))
        self.update_artifact_hash("artifacts/figure.svg")
        self.assert_issue("invalid_input")

    def test_missing_and_unknown_artifact_references(self):
        path = self.root / "manuscript/draft.md"
        path.write_text(path.read_text().replace("[[Table:T1]]", "[[Table:T9]]"))
        self.assert_issue("uncited_artifact")
        self.assert_issue("unknown_artifact")

    def test_claim_value_and_body_anchor(self):
        claims = self.json("artifacts/claims.json")
        claims[0]["value"] = 59
        claims[0]["text"] = "工作数据样本 N = 59"
        self.put("artifacts/claims.json", claims)
        self.assert_issue("claim_number")
        self.assert_issue("claim_anchor")

    def test_duplicate_claim_and_unknown_claim(self):
        claims = self.json("artifacts/claims.json")
        self.put("artifacts/claims.json", claims + claims[:1])
        self.assert_issue("invalid_input")
        self.put("artifacts/claims.json", claims)
        with (self.root / "manuscript/draft.md").open("a") as stream:
            stream.write("\n[[stat:unknown]]")
        self.assert_issue("unknown_claim")

    def test_citations_missing_in_both_directions(self):
        with (self.root / "manuscript/draft.md").open("a") as stream:
            stream.write("\n[[cite:missing]]")
        self.put("references.json", [{"id": "uncited", "authors": ["Fixture only"], "year": "n.d.", "title": "TEST fixture, not literature", "source": "TEST", "url": "https://example.invalid/"}])
        self.assert_issue("missing_reference")
        self.assert_issue("uncited_reference")

    def test_doi_syntax_and_duplicate_checks(self):
        ref = {"id": "fixture", "authors": ["Fixture only"], "year": "2024a", "title": "TEST fixture, not real literature", "source": "TEST", "url": "https://example.invalid/", "doi": "10.invalid"}
        self.put("references.json", [ref])
        with (self.root / "manuscript/draft.md").open("a") as stream:
            stream.write("\n[[cite:fixture]] [[cite:fixture2]]")
        self.assert_issue("doi_format")
        ref["doi"] = "https://doi.org/10.1234/fixture-only"
        self.put("references.json", [ref, dict(ref, id="fixture2")])
        self.assert_issue("duplicate_doi")

    def test_valid_reference_format_does_not_claim_truth(self):
        ref = {"id": "apa", "authors": ["American Psychological Association"], "year": "n.d.", "title": "Style and Grammar Guidelines", "source": "APA Style", "url": "https://apastyle.apa.org/style-grammar-guidelines"}
        self.put("references.json", [ref])
        with (self.root / "manuscript/draft.md").open("a") as stream:
            stream.write("\n[[cite:apa]]")
        report = self.report()
        self.assertEqual(report["automatic_status"], "pass")
        self.assertIn("reference_unverified", {v["code"] for v in report["findings"]})
        self.assertEqual(report["overall_status"], "needs_human_review")

    def test_sensitive_flag_blocks_without_echo(self):
        book = self.json("data/codebook.json")
        book["columns"]["study_id"]["sensitive"] = True
        self.put("data/codebook.json", book)
        self.assert_issue("sensitive_column")

    def test_sensitive_pattern_does_not_echo_value_in_report_or_logs(self):
        marker = "fixture.private@example.invalid"
        with (self.root / "manuscript/draft.md").open("a") as stream:
            stream.write("\n" + marker)
        report = self.run_cli("validate", self.root, "--full", code=1)
        self.assertIn("possible_sensitive_content", {v["code"] for v in report["findings"]})
        self.assertNotIn(marker, json.dumps(report))
        self.assertNotIn(marker, (self.root / "logs/audit.jsonl").read_text())

    def test_anonymous_identity_tag(self):
        state = self.json("project.json")
        state["anonymized"] = True
        self.put("project.json", state)
        with (self.root / "manuscript/draft.md").open("a") as stream:
            stream.write("\n作者：TEST")
        self.assert_issue("anonymous_identity")

    def test_duplicate_ids_and_range_violations(self):
        path = self.root / "data/input.csv"
        path.write_text(path.read_text().replace("S001", "S000").replace("0.000000", "99.000000", 1))
        self.assert_issue("duplicate_id")
        self.assert_issue("invalid_value")

    def test_category_violation_and_codebook_mismatch(self):
        path = self.root / "data/input.csv"
        path.write_text(path.read_text().replace(",B\n", ",C\n", 1))
        self.assert_issue("invalid_category")
        book = self.json("data/codebook.json")
        del book["columns"]["group"]
        self.put("data/codebook.json", book)
        self.assert_issue("invalid_input")

    def test_synthetic_markers_cannot_silently_change(self):
        results = self.json("artifacts/results.json")
        results["synthetic"] = False
        self.put("artifacts/results.json", results)
        self.assert_issue("invalid_input")

    def test_external_recipe_warns_instead_of_claiming_reproduction(self):
        results = self.json("artifacts/results.json")
        results["recipe"] = {"id": "external-fixture-v1"}
        self.put("artifacts/results.json", results)
        manifest = self.json("artifacts/manifest.json")
        manifest["items"][1]["recipe"] = "external-figure-v1"
        self.put("artifacts/manifest.json", manifest)
        report = self.report()
        self.assertEqual(report["automatic_status"], "pass")
        self.assertTrue({"external_model", "external_figure"} <= {v["code"] for v in report["findings"]})

    def test_analysis_no_overwrite_and_explicit_regeneration(self):
        original = (self.root / "data/input.csv").read_bytes()
        manuscript = (self.root / "manuscript/draft.md").read_bytes()
        self.run_cli("analyze", self.root, "--x", "exposure", "--y", "trust", code=2)
        self.run_cli("analyze", self.root, "--x", "exposure", "--y", "trust", "--replace-generated")
        self.assertEqual(original, (self.root / "data/input.csv").read_bytes())
        self.assertEqual(manuscript, (self.root / "manuscript/draft.md").read_bytes())
        self.assertEqual(self.report()["automatic_status"], "pass")

    def test_path_traversal_rejected(self):
        manifest = self.json("artifacts/manifest.json")
        manifest["items"][0]["path"] = "../../outside.csv"
        self.put("artifacts/manifest.json", manifest)
        self.assert_issue("invalid_input")

    def test_symlink_rejected(self):
        (self.root / "data/link").symlink_to(self.root / "data/input.csv")
        self.run_cli("status", self.root, code=2)

    def test_log_tampering_and_truncation_fail_closed(self):
        path = self.root / "logs/audit.jsonl"
        original = path.read_text()
        path.write_text(original.replace('"action": "init"', '"action": "fake"', 1))
        self.run_cli("status", self.root, code=2)
        path.write_text("\n".join(original.splitlines()[:-1]) + "\n")
        self.run_cli("status", self.root, code=2)

    def test_project_lock_blocks_concurrent_writer(self):
        (self.root / ".cra.lock").write_text("TEST")
        self.run_cli("status", self.root, code=2)

    def test_malformed_input_has_no_traceback_or_raw_content(self):
        secret = "DO_NOT_ECHO_RAW_CONTENT"
        cra.write_text(self.root / "artifacts/claims.json", "{" + secret)
        output = self.run_cli("validate", self.root, "--full", code=1)
        self.assertNotIn(secret, json.dumps(output))

    def test_invalid_bool_numeric_and_tolerance_contract(self):
        results = self.json("artifacts/results.json")
        results["models"]["m1"]["n"] = True
        self.put("artifacts/results.json", results)
        self.assert_issue("invalid_input")
        for value in (-1, 11, True):
            with self.assertRaises(cra.CRAError):
                cra.tolerance(value)

    def test_duplicate_json_keys_and_unknown_codebook_version_fail(self):
        book = self.json("data/codebook.json")
        book["schema_version"] = 999
        self.put("data/codebook.json", book)
        self.assert_issue("invalid_input")
        cra.write_text(self.root / "data/codebook.json", '{"schema_version":1,"schema_version":2}')
        self.assert_issue("invalid_input")

    def test_review_pass_is_blocked_by_automatic_error(self):
        with (self.root / "protocol/design.md").open("a") as stream:
            stream.write("\nTODO: unresolved")
        self.run_cli("review", self.root, "--stage", "design", "--reviewer", "TEST ONLY", "--decision", "pass", "--note", "TEST fixture only", code=2)
        self.assertEqual(self.json("project.json")["reviews"], {})

    def test_unmarked_prose_number_is_explicitly_out_of_scope(self):
        with (self.root / "manuscript/draft.md").open("a") as stream:
            stream.write("\n未登记的自然语言数字99999。")
        report = self.report()
        self.assertEqual(report["automatic_status"], "pass")
        self.assertIn("未标记", report["limits"])
        self.assertEqual(report["overall_status"], "needs_human_review")


if __name__ == "__main__":
    unittest.main()
