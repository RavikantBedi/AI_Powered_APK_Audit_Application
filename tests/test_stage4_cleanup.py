"""Stage 4 tests: data cleanup on two deliberately messy files.

No LLM key in the test environment, so column classification exercises the
heuristic fallback — the cleaning logic itself is fully deterministic.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules import data_cleanup

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _clean(filename: str, data: bytes):
    headers, rows = data_cleanup.parse_file(filename, data)
    col_types, source = data_cleanup.classify_columns(headers, rows)
    assert source == "heuristic"  # no API key available in tests
    cleaned, report = data_cleanup.clean_table(headers, rows, col_types)
    return headers, cleaned, report


def test_messy_contacts_csv():
    data = (SAMPLES / "messy_contacts.csv").read_bytes()
    headers, cleaned, report = _clean("messy_contacts.csv", data)

    assert report["rows_in"] == 5
    assert report["duplicates_removed"] == 1  # Rahul appears twice in different formats
    assert report["rows_out"] == 4

    by_name = {row[0]: row for row in cleaned}
    assert by_name["Rahul Sharma"][1] == "+91 98765 43210"
    assert by_name["Rahul Sharma"][2] == "rahul@gmail.com"     # lowercased
    assert by_name["Rahul Sharma"][3] == "2024-04-03"          # dd/mm/yyyy -> ISO
    assert by_name["Priya Singh"][3] == "2024-04-05"           # already ISO, kept
    assert by_name["Amit Kumar"][1] == "+91 98765 12345"       # leading 0 stripped
    assert by_name["Sunita Devi"][1] == "+91 98111 22233"      # 91 country code stripped
    assert by_name["Sunita Devi"][3] == "2024-05-07"           # "7th May 2024" -> ISO


def test_messy_orders_csv():
    data = (SAMPLES / "messy_orders.csv").read_bytes()
    headers, cleaned, report = _clean("messy_orders.csv", data)

    assert report["rows_in"] == 5
    assert report["duplicates_removed"] == 1  # order 1001 listed twice
    assert report["rows_out"] == 4

    amounts = {row[0]: row[2] for row in cleaned}
    assert amounts["1001"] == "1200"   # ₹1,200 -> 1200
    assert amounts["1002"] == "3450"   # Rs. 3,450 -> 3450
    assert amounts["1004"] == "2100"   # $ 2,100 -> 2100
    dates = {row[0]: row[3] for row in cleaned}
    assert dates["1001"] == "2025-01-12"
    assert dates["1003"] == "2025-01-14"
    assert dates["1004"] == "2025-01-15"


def test_excel_roundtrip(tmp_path):
    import pandas as pd
    xlsx = io.BytesIO()
    pd.DataFrame({"Name": ["A ", "A "], "Phone": ["9876543210", "98765 43210"]}).to_excel(
        xlsx, index=False)
    headers, cleaned, report = _clean("data.xlsx", xlsx.getvalue())
    assert headers == ["Name", "Phone"]
    assert report["rows_out"] == 1  # same row after normalization -> deduped
    assert cleaned[0] == ["A", "+91 98765 43210"]


def test_unsupported_type_rejected():
    try:
        data_cleanup.parse_file("notes.docx", b"whatever")
        assert False, "should have raised"
    except ValueError as e:
        assert "Unsupported" in str(e)
