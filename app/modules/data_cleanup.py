"""Module 3: Data Cleanup Agent.

File-in, file-out pipeline (no conversation memory):
  1. Parse CSV / Excel / PDF into a header + rows table.
  2. LLM classifies what each column means (date, phone, email, number, text).
  3. Deterministic Python cleans values per column type and drops duplicates —
     the LLM never rewrites the data itself, so cleaning is reproducible and
     a hallucination can't corrupt a customer's file.

If the LLM is unavailable, column types fall back to header-name heuristics,
so the module still works (slightly less accurately) with no API key.
"""
import csv
import io
import re

from dateutil import parser as dateparser
from pydantic import BaseModel, ValidationError

from app.llm_providers import PROVIDERS, LLMCallError, chat_json

COLUMN_TYPES = ("date", "phone", "email", "number", "text")


class ColumnMap(BaseModel):
    columns: dict[str, str]  # header -> one of COLUMN_TYPES


# ---------- parsing ----------

def parse_file(filename: str, data: bytes) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows). Raises ValueError for unsupported/broken files."""
    name = filename.lower()
    if name.endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        table = [row for row in reader if any(cell.strip() for cell in row)]
    elif name.endswith((".xlsx", ".xls")):
        import pandas as pd
        df = pd.read_excel(io.BytesIO(data), dtype=str).fillna("")
        table = [list(df.columns.astype(str))] + df.astype(str).values.tolist()
    elif name.endswith(".pdf"):
        table = _parse_pdf(data)
    else:
        raise ValueError(f"Unsupported file type: {filename} (use .csv, .xlsx, or .pdf)")
    if len(table) < 2:
        raise ValueError("File has no data rows")
    headers = [h.strip() for h in table[0]]
    width = len(headers)
    rows = [(r + [""] * width)[:width] for r in table[1:]]
    return headers, rows


def _parse_pdf(data: bytes) -> list[list[str]]:
    """Best-effort: extract text lines and split on 2+ spaces or tabs.
    Works for simple tabular PDFs; anything fancier needs the real client's format."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    lines: list[str] = []
    for page in reader.pages:
        lines.extend(l for l in (page.extract_text() or "").splitlines() if l.strip())
    table = [re.split(r"\t|\s{2,}", line.strip()) for line in lines]
    widths = [len(r) for r in table]
    if not widths or max(widths) < 2:
        raise ValueError("Could not detect a table in this PDF")
    return [r for r in table if len(r) == max(set(widths), key=widths.count)]


# ---------- column classification ----------

def classify_columns(headers: list[str], sample_rows: list[list[str]],
                     llm: dict | None = None) -> tuple[dict[str, str], str]:
    """Return ({header: type}, source) where source is 'llm' or 'heuristic'."""
    llm = llm or {}
    provider = llm.get("provider") or "gemini"
    sample = "\n".join(",".join(r) for r in sample_rows[:5])
    system = (
        "You classify spreadsheet columns. Given headers and sample rows, assign each "
        f"header exactly one type from: {', '.join(COLUMN_TYPES)}.\n"
        'Respond with ONLY JSON: {"columns": {"<header>": "<type>", ...}}'
    )
    user = f"HEADERS: {', '.join(headers)}\nSAMPLE ROWS:\n{sample}"
    if provider in PROVIDERS:
        try:
            data = chat_json(provider, llm.get("api_key"), system,
                             [{"role": "user", "content": user}], llm.get("model"))
            mapping = ColumnMap.model_validate(data).columns
            return (
                {h: mapping.get(h, "text") if mapping.get(h) in COLUMN_TYPES else "text"
                 for h in headers},
                "llm",
            )
        except (LLMCallError, ValidationError):
            pass
    return {h: _guess_type(h) for h in headers}, "heuristic"


def _guess_type(header: str) -> str:
    h = header.lower()
    if any(k in h for k in ("date", "dob", "joined", "created")):
        return "date"
    if any(k in h for k in ("phone", "mobile", "contact", "whatsapp")):
        return "phone"
    if "email" in h or "mail" in h:
        return "email"
    if any(k in h for k in ("amount", "price", "qty", "quantity", "total", "cost")):
        return "number"
    return "text"


# ---------- cleaning ----------

def clean_table(headers: list[str], rows: list[list[str]],
                col_types: dict[str, str]) -> tuple[list[list[str]], dict]:
    report = {"rows_in": len(rows), "duplicates_removed": 0,
              "dates_normalized": 0, "phones_normalized": 0, "unparseable_values": 0}
    cleaned: list[list[str]] = []
    seen: set[tuple] = set()
    for row in rows:
        out = []
        for header, value in zip(headers, row):
            out.append(_clean_value(value, col_types.get(header, "text"), report))
        key = tuple(v.lower() for v in out)
        if key in seen:
            report["duplicates_removed"] += 1
            continue
        seen.add(key)
        cleaned.append(out)
    report["rows_out"] = len(cleaned)
    return cleaned, report


def _clean_value(value: str, col_type: str, report: dict) -> str:
    v = re.sub(r"\s+", " ", str(value)).strip()
    if not v:
        return v
    if col_type == "date":
        # Already ISO — dayfirst parsing would swap month/day, so keep as-is.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            return v
        try:
            dt = dateparser.parse(v, dayfirst=True, fuzzy=True)
            iso = dt.strftime("%Y-%m-%d")
            if iso != v:
                report["dates_normalized"] += 1
            return iso
        except (ValueError, OverflowError):
            report["unparseable_values"] += 1
            return v
    if col_type == "phone":
        digits = re.sub(r"\D", "", v)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10:
            normalized = f"+91 {digits[:5]} {digits[5:]}"
            if normalized != v:
                report["phones_normalized"] += 1
            return normalized
        report["unparseable_values"] += 1
        return v
    if col_type == "email":
        return v.lower()
    if col_type == "number":
        return re.sub(r"[₹$,\s]|Rs\.?", "", v, flags=re.IGNORECASE)
    return v


def to_csv_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")
