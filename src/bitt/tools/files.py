"""File readers for data.raw.import: bytes → rows (list of {header: value}). The node records the file's hash; the rows go to the line."""
import csv
import datetime as _dt
import io
import json

FORMATS = ("json", "jsonl", "csv", "xlsx")


def guess_format(path):
    ext = str(path).rsplit(".", 1)[-1].lower()
    return {"xlsm": "xlsx", "tsv": "csv", "ndjson": "jsonl"}.get(ext, ext) if ext in FORMATS + ("xlsm", "tsv", "ndjson") else None


def sheets(data):
    from openpyxl import load_workbook
    return load_workbook(io.BytesIO(data), read_only=True).sheetnames


def read_rows(data, fmt, sheet=None):
    """Rows of a file. json = a list of objects; jsonl = one object per line; csv = a header row (comma or tab); xlsx = the first row of the
    sheet is the header (the first sheet unless `sheet` names one)."""
    if fmt == "json":
        rows = json.loads(data)
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ValueError("a json file must hold a list of objects")
        return rows
    if fmt == "jsonl":
        return [json.loads(x) for x in data.decode("utf-8-sig").splitlines() if x.strip()]
    if fmt == "csv":
        text = data.decode("utf-8-sig")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;") if text.strip() else csv.excel
        return [dict(r) for r in csv.DictReader(io.StringIO(text), dialect=dialect)]
    if fmt == "xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ValueError("reading xlsx needs openpyxl: uv sync --extra xlsx") from None
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        if sheet is not None and sheet not in wb.sheetnames:
            raise ValueError(f"no sheet {sheet!r}; the sheets are {wb.sheetnames}")
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        it = ws.iter_rows(values_only=True)
        header = next(it, None) or ()
        names = [str(h).strip() if h is not None else f"column_{i + 1}" for i, h in enumerate(header)]
        rows = []
        for vals in it:
            rows.append({n: _cell(v) for n, v in zip(names, vals)})
        return rows
    raise ValueError(f"unknown format {fmt!r}; one of {FORMATS}")


def _cell(v):
    if isinstance(v, _dt.datetime):
        return v.date().isoformat() if (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0) else v.isoformat()
    if isinstance(v, (_dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, str):
        return v.strip() or None
    return v
