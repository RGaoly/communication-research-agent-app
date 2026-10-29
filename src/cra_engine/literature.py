"""Metadata and located evidence. A resolvable DOI never implies claim support."""
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .common import EngineError, identifier, load, now, require, safe_text, save, sha, within


class RedirectPolicy(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts, loopback=False):
        self.hosts, self.loopback = set(hosts), loopback

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        require(parsed.hostname in self.hosts and parsed.scheme == "https" and not parsed.username, "Redirect outside authorized HTTPS hosts refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_json(url, hosts, timeout=30, payload=None, headers=None, retries=2):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.hostname in hosts and not parsed.username and not parsed.password, "Network host not authorized")
    require(parsed.scheme == "https" or parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"), "HTTPS required")
    # Never forward a bearer credential to another allowed literature/model host.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RedirectPolicy([parsed.hostname] if payload is not None else hosts))
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, data=payload, headers=headers or {"User-Agent": "CommunicationResearchAgent/0.2"})
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(4_000_001)
                require(len(raw) <= 4_000_000, "Response exceeds allowed size")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and payload is None and attempt < retries:
                delay = exc.headers.get("Retry-After", "1")
                time.sleep(min(10, int(delay)) if delay.isdigit() else 1)
                continue
            raise EngineError("Remote HTTP request failed; response body withheld") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            if payload is None and attempt < retries:
                time.sleep(min(2 ** attempt, 4))
                continue
            raise EngineError("Remote result unavailable/invalid; raw response withheld") from exc


def crossref_search(query, hosts, rows=10):
    require("api.crossref.org" in hosts, "Authorize api.crossref.org before literature network use")
    safe_text(query)
    require(type(rows) is int and 1 <= rows <= 50, "Search rows must be 1–50")
    data = fetch_json("https://api.crossref.org/works?" + urllib.parse.urlencode({"query.bibliographic": query, "rows": rows}), hosts)
    return {"query": query, "source": "Crossref", "accessed_at": now(), "items": [crossref_item(item) for item in data["message"]["items"]]}


def crossref_item(item):
    doi = item.get("DOI", "")
    return {"id": "ref_" + __import__("hashlib").sha256(doi.encode()).hexdigest()[:12], "doi": doi,
            "title": (item.get("title") or [""])[0], "authors": [" ".join(filter(None, [a.get("given"), a.get("family")])) for a in item.get("author", [])],
            "year": str(item.get("issued", {}).get("date-parts", [[""]])[0][0]),
            "source": (item.get("container-title") or ["Crossref"])[0], "url": "https://doi.org/" + doi,
            "metadata": {"status": "verified", "method": "Crossref", "accessed_at": now()}, "spans": []}


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).lower() if c.isalnum())


def locate(root, span):
    path = within(root, span.get("path"))
    require(path.is_file() and path.stat().st_size <= 20_000_000, "Evidence source missing/too large")
    locator = span.get("locator", {})
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        pages = PdfReader(path).pages
        page = locator.get("page")
        require(type(page) is int and 1 <= page <= len(pages), "Evidence PDF page required")
        content = pages[page - 1].extract_text() or ""
    else:
        require(path.suffix.lower() in (".md", ".txt"), "Evidence must be PDF, Markdown or text")
        paragraphs = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
        paragraph = locator.get("paragraph")
        require(type(paragraph) is int and 1 <= paragraph <= len(paragraphs), "Evidence paragraph required")
        content = paragraphs[paragraph - 1]
    quote = span.get("quote")
    require(isinstance(quote, str) and len(quote.strip()) >= 8 and " ".join(quote.split()) in " ".join(content.split()), "Evidence quotation not found at declared location")
    require(span.get("status") in ("supported", "pending", "contradicted"), "Evidence support status required")
    if span["status"] == "supported":
        require(bool(span.get("reviewer")) and isinstance(span.get("note"), str) and len(span["note"]) >= 8, "Supported evidence requires a real local review declaration")
    require(type(span.get("permitted_for_model")) is bool, "Explicit excerpt egress authorization required")
    return dict(span, source_sha256=sha(path), support_is="review declaration; not automatic entailment proof")


def build_corpus(root, brief):
    file = root / "literature/references.json"
    records = load(file) if file.exists() else []
    require(isinstance(records, list), "Literature references must be a list")
    discovery = None
    if not records and brief["permissions"]["literature_network"]:
        # Metadata discovery never becomes fabricated full-text support.
        discovery = crossref_search(brief["theme"], brief["permissions"]["allowed_hosts"], rows=10)
        save(root / "literature/search-results.json", discovery)
        records = discovery["items"]
    items, ids, span_ids, issues = [], set(), set(), []
    for raw in records:
        require(isinstance(raw, dict) and identifier(raw.get("id")) and raw["id"] not in ids, "Unique literature ID required")
        ids.add(raw["id"])
        require(all(isinstance(raw.get(k), str) and raw[k].strip() for k in ("title", "year", "source", "url")), "Literature metadata incomplete")
        require(isinstance(raw.get("authors"), list) and raw["authors"], "Literature authors required")
        item = dict(raw)
        item["metadata"] = {"status": "pending"}
        doi = raw.get("doi", "").removeprefix("https://doi.org/")
        if doi:
            require(re.fullmatch(r"10\.\d{4,9}/\S+", doi), "Invalid DOI format")
            if discovery:
                item["metadata"] = raw["metadata"]
            elif brief["permissions"]["literature_network"]:
                remote = fetch_json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe=""), brief["permissions"]["allowed_hosts"])["message"]
                remote_title = (remote.get("title") or [""])[0]
                years = {str(remote.get(k, {}).get("date-parts", [[""]])[0][0]) for k in ("issued", "published", "published-online", "published-print")}
                first_family = (remote.get("author") or [{}])[0].get("family", "")
                metadata_match = normalized(remote_title) == normalized(raw["title"]) and re.sub(r"[a-z]$", "", raw["year"]) in years and bool(first_family) and normalized(first_family) in normalized(raw["authors"][0])
                if not metadata_match:
                    issues.append({"code": "metadata_mismatch", "severity": "blocking", "reference": raw["id"]})
                    item["metadata"] = {"status": "mismatch", "method": "Crossref"}
                else:
                    item["metadata"] = {"status": "verified", "method": "Crossref", "accessed_at": now()}
        declaration = raw.get("metadata_declaration", {})
        if item["metadata"]["status"] == "pending" and declaration.get("reviewer") and len(declaration.get("note", "")) >= 8:
            item["metadata"] = {"status": "declared", "method": "human declaration", "declaration": declaration}
        item["spans"] = []
        for span in raw.get("spans", []):
            require(identifier(span.get("id")) and span["id"] not in span_ids, "Unique evidence span ID required")
            span_ids.add(span["id"])
            item["spans"].append(locate(root, span))
        item["full_text"] = bool(item["spans"])
        items.append(item)
    return {"schema_version": 2, "items": items, "issues": issues,
            "discovery": {"query": discovery["query"], "accessed_at": discovery["accessed_at"], "status": "metadata_only; supply authorized full text and located support"} if discovery else None}


def model_corpus(corpus):
    items = []
    for ref in corpus["items"]:
        if ref["metadata"]["status"] not in ("verified", "declared"):
            continue
        for span in ref["spans"]:
            if span["status"] == "supported" and span["permitted_for_model"]:
                items.append({"reference_id": ref["id"], "evidence_id": span["id"], "title": ref["title"],
                              "claim": span.get("claim", ""), "quote": span["quote"], "locator": span["locator"],
                              "source_sha256": span["source_sha256"]})
    return safe_text(items)


def import_bibliography(root, path):
    path = Path(path)
    if path.suffix.lower() == ".bib":
        import bibtexparser
        entries = bibtexparser.loads(path.read_text(encoding="utf-8")).entries
        records = [{"id": e.get("ID"), "title": e.get("title", ""), "authors": e.get("author", "").split(" and "), "year": e.get("year", "n.d."),
                    "source": e.get("journal", e.get("publisher", "import")), "url": e.get("url", "https://doi.org/" + e.get("doi", "")), "doi": e.get("doi", ""), "spans": []} for e in entries]
    elif path.suffix.lower() == ".ris":
        records, current = [], {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if len(line) < 6 or line[2:6] != "  - ":
                continue
            tag, value = line[:2], line[6:]
            if tag == "TY":
                current = {"id": "import_" + str(len(records) + 1), "authors": [], "spans": []}
            elif tag == "ER":
                records.append(current)
            elif tag == "AU":
                current["authors"].append(value)
            elif tag in ("TI", "T1", "PY", "Y1", "JO", "JF", "DO", "UR"):
                key = {"TI": "title", "T1": "title", "PY": "year", "Y1": "year", "JO": "source", "JF": "source", "DO": "doi", "UR": "url"}[tag]
                current[key] = value[:4] if key == "year" else value
        for record in records:
            record.setdefault("url", "https://doi.org/" + record.get("doi", ""))
            record.setdefault("year", "n.d.")
            record.setdefault("source", "import")
    else:
        raise EngineError("Import supports BibTeX .bib and RIS .ris")
    target = root / "literature/references.json"
    existing = load(target) if target.exists() else []
    require(not ({r["id"] for r in existing} & {r["id"] for r in records}), "Import IDs collide; existing references were not overwritten")
    save(target, existing + records)
    return {"imported": len(records), "status": "metadata/evidence verification pending"}
