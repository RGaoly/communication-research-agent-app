"""Read-only original uploads and explicit, versioned analysis-copy conversion."""
import csv
import io
import math
from pathlib import Path
import re

from cra_engine.common import EngineError, require, safe_text, identifier

MAX_UPLOAD = 32 * 1024 * 1024
MAX_ROWS = 250_000
MAX_COLUMNS = 500
MAX_CELLS = 5_000_000


def scalar(value):
    if value is None:
        return ""
    if isinstance(value, float):
        require(not math.isinf(value), "数据包含无穷值，未静默转换为缺失")
        if math.isnan(value):
            return ""
    return str(value)


def read_upload(path):
    """Never evaluates data or applies value labels as numeric responses."""
    path = Path(path)
    require(0 < path.stat().st_size <= MAX_UPLOAD, "文件为空或超过32MB接入上限")
    labels, values, missing, types = {}, {}, {}, {}
    if path.suffix.lower() == ".csv":
        try:
            text = path.read_text(encoding="utf-8-sig")
            reader = csv.reader(io.StringIO(text))
            names = next(reader)
            require(names and len(set(names)) == len(names) and all(n.strip() for n in names), "CSV列名为空或重复，请先核查原件")
            rows = []
            for row in reader:
                require(len(row) == len(names), "CSV行列数不一致；没有自动丢弃记录")
                rows.append(row)
                require(len(rows) <= MAX_ROWS and len(rows) * len(names) <= MAX_CELLS, "超过当前行数或总单元格接入上限")
        except (UnicodeError, csv.Error, StopIteration) as exc:
            raise EngineError("CSV应为UTF-8且具有完整表头；原始内容不回显") from exc
    else:
        require(path.suffix.lower() == ".dta", "当前数据接入支持CSV和DTA")
        try:
            import pyreadstat
            _, head = pyreadstat.read_dta(str(path), metadataonly=True)
            require(len(head.column_names) <= MAX_COLUMNS and (head.number_rows or 0) <= MAX_ROWS and (head.number_rows or 0) * len(head.column_names) <= MAX_CELLS, "DTA超过当前行列或总单元格接入上限")
            frame, meta = pyreadstat.read_dta(str(path), apply_value_formats=False, user_missing=True,
                                            row_limit=MAX_ROWS + 1)
            names = list(frame.columns)
            rows = [[scalar(v) for v in row] for row in frame.itertuples(index=False, name=None)]
            labels = meta.column_names_to_labels or {}
            values = {k: {str(a): str(b) for a, b in v.items()} for k, v in (meta.variable_value_labels or {}).items()}
            missing = {k: [str(x) for x in v] for k, v in (meta.missing_user_values or {}).items()}
            types = meta.readstat_variable_types or {}
        except ImportError as exc:
            raise EngineError("需显式安装ui依赖中的pyreadstat后接入DTA") from exc
        except Exception as exc:
            raise EngineError("DTA读取失败，请核查文件格式或加密情况；原始内容不回显") from exc
    require(rows and len(rows) <= MAX_ROWS and len(names) <= MAX_COLUMNS and len(rows) * len(names) <= MAX_CELLS, "空数据或超过当前行列容量")
    machine, columns, mapping = [], {}, []
    used = set()
    for index, original in enumerate(names):
        name = original if identifier(original) and original not in used else "v%03d" % (index + 1)
        while name in used:
            name += "_"
        used.add(name); machine.append(name)
        observed = [scalar(row[index]).strip() for row in rows if scalar(row[index]).strip()]
        distinct = list(dict.fromkeys(observed))
        numeric = []
        numeric_ok = bool(observed)
        for value in observed:
            try:
                number = float(value)
                if not math.isfinite(number) or re.match(r"^[+-]?0\d", value):
                    numeric_ok = False
                numeric.append(number)
            except ValueError:
                numeric_ok = False
        kind = "number" if numeric_ok else "category" if 0 < len(distinct) <= 50 else "text"
        if re.search(r"(^|_)id$", original, re.I) and len(distinct) == len(rows):
            kind = "id"
        sensitive = bool(re.search(r"name|email|phone|mobile|姓名|电话|身份证|住址", original, re.I))
        spec = {"type": kind, "sensitive": sensitive, "question": labels.get(original) or original,
                "original_name": original, "question_source": "file_label" if labels.get(original) else "column_name_unconfirmed"}
        if kind == "number":
            spec.update(min=min(numeric), max=max(numeric), range_source="observed_not_instrument")
        if kind == "category":
            spec["allowed"] = distinct
        if original in values:
            spec["value_labels"] = values[original]
        if original in missing:
            spec["proposed_missing_codes"] = missing[original]
        columns[name] = spec
        mapping.append({"original_name": original, "machine_name": name, "label": labels.get(original),
                        "storage_type": types.get(original), "missing_codes": missing.get(original, [])})
    return {"names": machine, "rows": rows, "book": {"schema_version": 2, "columns": columns},
            "summary": {"records": len(rows), "fields": len(machine), "format": path.suffix.lower()[1:],
                        "mapping": mapping, "measurement_confirmed": False,
                        "limits": "推断类型、范围与列名不是测量效度；确认规则后才用于正式分析"}}


def csv_text(names, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(names)
    writer.writerows(rows)
    return stream.getvalue()


def analysis_copy(source_path, book, missing_codes=None):
    require(isinstance(book, dict) and isinstance(book.get("columns"), dict) and book["columns"], "请保留至少一个分析字段")
    missing_codes = missing_codes or {}
    with Path(source_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        require(set(book["columns"]) <= set(reader.fieldnames or []), "分析字段必须对应原始转换列")
        rows = list(reader)
    names = list(book["columns"])
    for name, spec in book["columns"].items():
        require(identifier(name) and spec.get("type") in ("id", "text", "number", "category"), "变量名称或类型不支持")
        require(spec.get("sensitive") is False, "请排除敏感字段或提供经核查的去标识副本")
        require(isinstance(spec.get("question"), str) and spec["question"].strip(), "每项分析字段需要题项或含义")
        if spec["type"] == "category":
            require(isinstance(spec.get("allowed"), list) and spec["allowed"], "类别变量需明确允许取值")
        if spec["type"] == "number":
            require(all(type(spec.get(k)) in (int, float) and math.isfinite(spec[k]) for k in ("min", "max")) and spec["min"] <= spec["max"], "数值变量需核查量尺上下界")
    result = [["" if row[name].strip() in missing_codes.get(name, []) else row[name] for name in names] for row in rows]
    content = csv_text(names, result)
    safe_text(content)
    return content, {"original_records": len(rows), "retained_records": len(result),
                     "excluded_columns": sorted(set(rows[0]) - set(names)) if rows else [],
                     "missing_rules": missing_codes, "silent_row_deletion": False}
