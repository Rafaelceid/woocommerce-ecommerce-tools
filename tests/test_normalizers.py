"""Tests for SKU normalizer and filename sanitizer utilities.

These functions are used across csv_cloudinary_normalizer.py,
csv_imgbb_normalizer.py, and process_taxonomy.py.

Run with:  pytest tests/test_normalizers.py -v
"""
from __future__ import annotations

import re
import pytest


# ---------------------------------------------------------------------------
# Inline copies of the normalizer functions (so tests are standalone)
# The same logic must live in the actual tool files.
# ---------------------------------------------------------------------------

_SCI_RE = re.compile(r"^-?\d+\.?\d*[eE][+\-]?\d+$")


def fix_sku(v: object) -> str:
    """Normalise a SKU/barcode value from Excel/CSV to a clean string.

    Handles scientific notation (5.29E+12 → 5291040000000)
    and float suffixes (5291040000000.0 → 5291040000000).
    """
    v = str(v or "").strip()
    if not v or v.lower() in ("nan", "none", ""):
        return ""
    if _SCI_RE.match(v):
        try:
            return str(int(round(float(v))))
        except (ValueError, OverflowError):
            return v
    if re.match(r"^\d+\.0$", v):
        return v[:-2]
    return v


def safe_filename(value: str, max_len: int = 120) -> str:
    """Sanitise a string for use as a filesystem filename."""
    value = str(value or "").strip()
    value = re.sub(r"[^\w\-.]+", "_", value, flags=re.UNICODE)
    value = value.strip("._")
    if not value:
        return "item"
    return value[:max_len]


# ---------------------------------------------------------------------------
# fix_sku tests
# ---------------------------------------------------------------------------

class TestFixSku:
    def test_normal_barcode_unchanged(self):
        assert fix_sku("5291043000149") == "5291043000149"

    def test_scientific_notation(self):
        assert fix_sku("5.29104E+12") == "5291040000000"

    def test_float_zero_suffix(self):
        assert fix_sku("5291043000149.0") == "5291043000149"

    def test_empty_string(self):
        assert fix_sku("") == ""

    def test_nan(self):
        assert fix_sku("nan") == ""
        assert fix_sku("NaN") == ""

    def test_none_value(self):
        assert fix_sku(None) == ""

    def test_already_integer(self):
        assert fix_sku(5291043000149) == "5291043000149"

    def test_large_scientific(self):
        # 1.23456789E+13 → 12345678900000
        result = fix_sku("1.23456789E+13")
        assert result.isdigit()
        assert len(result) == 14

    def test_negative_scientific(self):
        # Negative barcodes are unusual but should not crash
        result = fix_sku("-1.5E+3")
        assert result == "-1500"

    def test_regular_string_unchanged(self):
        assert fix_sku("SKU-ABC-001") == "SKU-ABC-001"


# ---------------------------------------------------------------------------
# safe_filename tests
# ---------------------------------------------------------------------------

class TestSafeFilename:
    def test_normal_name(self):
        assert safe_filename("product-001") == "product-001"

    def test_spaces_replaced(self):
        result = safe_filename("hello world")
        assert " " not in result

    def test_special_chars(self):
        result = safe_filename("sku/abc\\def:xyz")
        assert "/" not in result
        assert "\\" not in result
        assert ":" not in result

    def test_empty_returns_item(self):
        assert safe_filename("") == "item"
        assert safe_filename("   ") == "item"

    def test_max_length_enforced(self):
        long_name = "a" * 200
        assert len(safe_filename(long_name, max_len=120)) == 120

    def test_leading_dots_stripped(self):
        result = safe_filename("...hidden")
        assert not result.startswith(".")

    def test_unicode_allowed(self):
        # Greek letters are word characters (\w) in Python re with UNICODE flag
        result = safe_filename("Κρέμα-προσώπου")
        assert len(result) > 0

    def test_dots_in_name_kept(self):
        assert safe_filename("product.v2.final") == "product.v2.final"


# ---------------------------------------------------------------------------
# Integration: sku round-trip through filename
# ---------------------------------------------------------------------------

class TestSkuToFilename:
    @pytest.mark.parametrize("raw,expected_sku", [
        ("5.29104E+12", "5291040000000"),
        ("5291043000149.0", "5291043000149"),
        ("5291043000149", "5291043000149"),
    ])
    def test_barcode_to_filename(self, raw: str, expected_sku: str):
        sku = fix_sku(raw)
        fname = safe_filename(sku) + ".webp"
        assert fname == f"{expected_sku}.webp"
