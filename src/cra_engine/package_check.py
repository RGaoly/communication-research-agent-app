"""Read-only research package verification. Hash integrity is not scientific truth."""
import csv
import io
import json
import math
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from .common import EngineError, digest, require


def read_package(path):
    path = Path(path)
    if path.is_dir():
        files = {}
        for item in path.rglob("*"):
            require(not item.is_symlink(), "Package symlinks refused")
            if item.is_file():
                files[item.relative_to(path).as_posix()] = item.read_bytes()
    else:
        with zipfile.ZipFile(path) as bundle:
            entries = bundle.infolist()
            require(sum(i.file_size for i in entries) <= 512_000_000, "Package exceeds verification size limit")
            names = [i.filename for i in entries if not i.is_dir()]
            require(len(set(names)) == len(names), "Duplicate package member")
            for item in entries:
                name = PurePosixPath(item.filename)
                require(not name.is_absolute() and ".." not in name.parts and "\\" not in item.filename, "Unsafe package path")
                require(not stat.S_ISLNK(item.external_attr >> 16), "Package symlink refused")
            files = {name: bundle.read(name) for name in names}
    return files


def close(a, b, absolute=1e-9, relative=1e-7):
    return math.isfinite(float(a)) and math.isfinite(float(b)) and math.isclose(float(a), float(b), abs_tol=absolute, rel_tol=relative)


def verify_package(path):
    try:
        files = read_package(path)
        manifest = json.loads(files["manifest.json"])
        declared = manifest["files"]
        require(set(files) == set(declared) | {"manifest.json"}, "Package has missing or unregistered members")
        import hashlib
        require(all(hashlib.sha256(files[name]).hexdigest() == signature for name, signature in declared.items()), "Package member hash mismatch")
        kind = manifest.get("kind", "research")
        if kind == "diagnostic":
            require({"diagnostic.json", "README.md"} <= set(files), "Diagnostic handoff incomplete")
            report = json.loads(files["diagnostic.json"])
            require(report.get("research_completed") is False and report.get("outcome") in ("infeasibility_diagnostic", "waiting_external_condition"), "Diagnostic must not claim completed research")
            return {"passed": True, "kind": kind, "checks": ["member_hashes", "explicit_incomplete_outcome"], "limits": "Handoff consistency only; no research-quality or identity certification"}
        required = {"analysis.json", "claims.json", "protocol.json", "codebook.json", "manuscript.md", "manuscript.docx", "table.csv", "figure.svg", "reproduce.py", "requirements.txt", "specification-ledger.json", "runs.json"}
        require(required <= set(files), "Research package incomplete")
        analysis, claims = (json.loads(files[name]) for name in ("analysis.json", "claims.json"))
        identity = analysis.get("recipe_identity")
        if identity is not None:
            require(isinstance(identity, dict) and identity.get("id") == "python-survey-v2", "Unknown statistical recipe identity")
            sources = identity.get("sources", {})
            require(isinstance(sources, dict) and set(sources) == {"__init__.py", "common.py", "statistics.py", "worker.py", "isolation.py"}, "Statistical recipe source set incomplete")
            require(all("recipe/cra_engine/"+name in files and hashlib.sha256(files["recipe/cra_engine/"+name]).hexdigest() == signature for name, signature in sources.items()), "Statistical recipe source differs from executed analysis")
            require(identity.get("packages") == analysis.get("environment") and isinstance(identity.get("python_version"), str), "Statistical environment binding differs")
        require(hashlib.sha256(files["codebook.json"]).hexdigest() == analysis["codebook_sha256"], "Codebook differs from analysis input")
        if manifest.get("input_included"):
            require(hashlib.sha256(files["input.csv"]).hexdigest() == analysis["data_sha256"], "Included data differs from analysis input")
        require(digest(json.loads(files["protocol.json"])) == analysis["protocol_hash"], "Protocol differs from executed analysis")
        require(claims["analysis_hash"] == digest(analysis), "Claims refer to another analysis")
        expected = [(model, p) for model in analysis["models"] for p in model["parameters"]]
        rows = list(csv.DictReader(io.StringIO(files["table.csv"].decode())))
        require(len(rows) == len(expected), "Table row count mismatch")
        for row, (model, parameter) in zip(rows, expected):
            require(row["model"] == model["id"] and row["term"] == parameter["term"] and int(row["n"]) == model["n"], "Table identifiers or sample N mismatch")
            require(all(close(row[key], parameter[key]) for key in ("estimate", "se", "ci_low", "ci_high", "p")), "Table numeric mismatch")
        svg = ET.fromstring(files["figure.svg"])
        circles = svg.findall("{http://www.w3.org/2000/svg}circle")
        intervals = [line for line in svg.findall("{http://www.w3.org/2000/svg}line") if line.attrib.get("stroke") == "black"]
        require(len(circles) == len(intervals) == len(expected), "Figure element count mismatch")
        low = min([0] + [p["ci_low"] for _, p in expected])
        high = max([0] + [p["ci_high"] for _, p in expected])
        if high == low:
            high += 1
        coordinate = lambda value: 240 + 480 * (value - low) / (high - low)
        for index, (circle, interval, (_, parameter)) in enumerate(zip(circles, intervals, expected)):
            require(all(close(circle.attrib[attr], parameter[key]) for attr, key in (("data-estimate", "estimate"), ("data-low", "ci_low"), ("data-high", "ci_high"))), "Figure metadata numeric mismatch")
            require(close(circle.attrib["cx"], coordinate(parameter["estimate"]), 1e-5) and close(circle.attrib["cy"], 35 + 34 * index), "Figure plotted coordinate mismatch")
            require(close(interval.attrib["x1"], coordinate(parameter["ci_low"]), 1e-5) and close(interval.attrib["x2"], coordinate(parameter["ci_high"]), 1e-5), "Figure plotted interval mismatch")
        manuscript = files["manuscript.md"].decode()
        models = {m["id"]: m for m in analysis["models"]}
        for claim in claims["items"]:
            model = models[claim["model"]]
            actual = model["n"] if claim["field"] == "n" else next(p[claim["field"]] for p in model["parameters"] if p["term"] == claim["term"])
            require(close(actual, claim["value"]), "Claim value differs from computation")
            require(claim["text"] + " [[stat:" + claim["id"] + "]]" in manuscript, "Canonical claim missing from manuscript")
        with zipfile.ZipFile(io.BytesIO(files["manuscript.docx"])) as docx:
            document = ET.fromstring(docx.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        doc_rows = document.findall(".//w:tbl/w:tr", ns)[1:]
        require(len(doc_rows) == len(expected), "Word result table row count mismatch")
        for row, (model, parameter) in zip(doc_rows, expected):
            cells = ["".join(t.text or "" for t in cell.findall(".//w:t", ns)) for cell in row.findall("w:tc", ns)]
            require(len(cells) == 6 and cells[0] == model["id"] + "/" + parameter["term"] and int(cells[1]) == model["n"], "Word sample/term mismatch")
            require(close(cells[2], parameter["estimate"], 5.1e-5) and close(cells[3], parameter["se"], 5.1e-5), "Word coefficient/SE mismatch")
            bounds = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", cells[4])
            require(len(bounds) == 2 and close(bounds[0], parameter["ci_low"], 5.1e-5) and close(bounds[1], parameter["ci_high"], 5.1e-5), "Word confidence interval mismatch")
            require(close(cells[5], parameter["p"], 1e-300, 6e-4), "Word p value mismatch")
        return {"passed": True, "kind": kind, "checks": ["member_hashes", "input_hashes", "protocol", "claims", "table_numbers", "plotted_coordinates", "word_table"] + (["statistical_recipe_sources"] if identity is not None else []),
                "limits": "Internal consistency only; independently reproduce statistics and review source entailment before scientific acceptance"}
    except (EngineError, ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError, OSError, StopIteration, zipfile.BadZipFile, ET.ParseError) as exc:
        return {"passed": False, "error": str(exc) if isinstance(exc, EngineError) else "Invalid package structure; raw content withheld"}
