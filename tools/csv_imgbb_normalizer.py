import os
import io
import re
import sys
import csv
import time
import base64
import argparse
from typing import List, Dict, Any, Optional

import pandas as pd
import requests
from PIL import Image, ImageOps, UnidentifiedImageError

# Optional AVIF / HEIC support
try:
    import pillow_avif  # noqa: F401
except Exception:
    pass

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

REQUEST_TIMEOUT = 45
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
JPEG_QUALITY_START = 92
JPEG_QUALITY_MIN = 60
WEBP_QUALITY_START = 95
WEBP_QUALITY_MIN = 60
MAX_DIMENSION_START = 2500
MIN_DIMENSION = 900
MAX_UPLOAD_BYTES = 31 * 1024 * 1024  # κάτω από 32MB

URL_RE = re.compile(r'https?://[^\s,;]+(?:\?[^\s]*)?')

_SCI_RE = re.compile(r'^-?\d+\.?\d*[eE][+\-]?\d+$')

def _fix_sku_string(v: Any) -> str:
    """Fix scientific notation / float artifacts in barcode columns.
    '5.29104E+12' → '5291043000149'  |  '5291043000149.0' → '5291043000149'
    Safe for non-numeric strings (brand names, TEMP-xxx, etc.).
    """
    v = str(v).strip()
    if not v or v.lower() in ('nan', 'none', ''):
        return v
    if _SCI_RE.match(v):
        try:
            return str(int(round(float(v))))
        except (ValueError, OverflowError):
            return v
    if re.match(r'^\d+\.0$', v):
        return v[:-2]
    return v


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def safe_filename(value: str) -> str:
    value = safe_str(value)
    value = re.sub(r"[^\w\-\.]+", "_", value)
    value = value.strip("._")
    return value[:120] if value else "item"


def extract_urls(cell_value: Any) -> List[str]:
    """
    Εντοπίζει ΟΛΑ τα http/https URLs μέσα σε cell, ανεξάρτητα αν είναι χωρισμένα με:
    - comma
    - newline
    - semicolon
    - spaces

    Πλεονέκτημα:
    - δεν βασίζεται σε split logic
    - υποστηρίζει WooCommerce-style comma separated galleries
    - δεν «σπάει» ολόκληρο το cell σαν ένα URL
    """
    text = safe_str(cell_value)
    if not text:
        return []

    found = URL_RE.findall(text)
    cleaned = []
    seen = set()
    for url in found:
        url = url.strip().strip('"\'()[]')
        if not url:
            continue
        if url not in seen:
            cleaned.append(url)
            seen.add(url)
    return cleaned


def detect_format_from_bytes(content: bytes) -> str:
    try:
        with Image.open(io.BytesIO(content)) as img:
            fmt = (img.format or "").lower().strip()
            if fmt == "jpeg":
                return "jpg"
            return fmt or "unknown"
    except Exception:
        return "unknown"


def download_image(url: str, session: requests.Session) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.content


def flatten_to_rgb(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    if img.mode == "P":
        try:
            if "transparency" in img.info:
                rgba = img.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                return bg
        except Exception:
            pass
        return img.convert("RGB")
    if img.mode == "CMYK":
        return img.convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def resize_if_needed(img: Image.Image, max_dim: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    ratio = max_dim / float(max(w, h))
    new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
    return img.resize(new_size, Image.LANCZOS)


def convert_image_under_limit(content: bytes, use_webp: bool = False) -> tuple:
    """Convert to WebP or JPEG under upload size limit. Returns (bytes, ext)."""
    with Image.open(io.BytesIO(content)) as original:
        base = flatten_to_rgb(original)
        current_max_dim = MAX_DIMENSION_START

        if use_webp:
            fmt, ext = "WEBP", "webp"
            q_start, q_min = WEBP_QUALITY_START, WEBP_QUALITY_MIN
            save_kwargs = {"format": fmt, "method": 6}
        else:
            fmt, ext = "JPEG", "jpg"
            q_start, q_min = JPEG_QUALITY_START, JPEG_QUALITY_MIN
            save_kwargs = {"format": fmt, "optimize": True, "progressive": True}

        while current_max_dim >= MIN_DIMENSION:
            candidate = resize_if_needed(base, current_max_dim)
            for quality in range(q_start, q_min - 1, -4):
                output = io.BytesIO()
                candidate.save(output, quality=quality, **save_kwargs)
                data = output.getvalue()
                if len(data) <= MAX_UPLOAD_BYTES:
                    return data, ext
            current_max_dim = int(current_max_dim * 0.85)

        tiny = resize_if_needed(base, MIN_DIMENSION)
        output = io.BytesIO()
        tiny.save(output, quality=q_min, **save_kwargs)
        data = output.getvalue()
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"Converted image still too large: {len(data)} bytes")
        return data, ext


def convert_to_jpeg_under_limit(content: bytes) -> bytes:
    """Legacy wrapper — backward compatibility."""
    data, _ = convert_image_under_limit(content, use_webp=False)
    return data


def upload_to_imgbb(
    jpg_bytes: bytes,
    filename: str,
    api_key: str,
    expiration: int,
    session: requests.Session,
) -> Dict[str, Any]:
    endpoint = f"https://api.imgbb.com/1/upload?key={api_key}"
    payload = {
        "name": os.path.splitext(filename)[0],
        "image": base64.b64encode(jpg_bytes).decode("utf-8"),
    }
    if expiration and int(expiration) > 0:
        payload["expiration"] = str(int(expiration))

    headers = {"User-Agent": USER_AGENT}
    response = session.post(endpoint, data=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise ValueError(f"ImgBB upload failed: {data}")
    return data


def pick_first_existing(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    lower_map = {str(col).lower(): col for col in df.columns}
    for c in candidates:
        actual = lower_map.get(str(c).lower())
        if actual is not None:
            return actual
    return None


def auto_detect_image_columns(df: pd.DataFrame, sample_rows: int = 30) -> List[str]:
    detected = []
    check_df = df.head(sample_rows)
    for col in df.columns:
        found = False
        for value in check_df[col].tolist():
            urls = extract_urls(value)
            if urls:
                found = True
                break
        if found:
            detected.append(col)
    return detected


def build_updated_cell(urls: List[str]) -> str:
    # WooCommerce δέχεται πολλαπλές εικόνες στο ίδιο πεδίο ως comma-separated list
    return ", ".join(urls)


def read_tabular_flexible(input_path: str, encoding: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
    ext = os.path.splitext(input_path)[1].lower()

    if ext in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
        return pd.read_excel(input_path, sheet_name=sheet_name or 0, dtype=str, engine="openpyxl").fillna("")

    if ext == ".xls":
        return pd.read_excel(input_path, sheet_name=sheet_name or 0, dtype=str, engine="xlrd").fillna("")

    separators = [",", ";", "\t", "|"]
    last_error = None
    for sep in separators:
        try:
            df = pd.read_csv(
                input_path,
                sep=sep,
                dtype=str,
                encoding=encoding,
                keep_default_na=False,
            )
            if len(df.columns) > 1:
                return df
        except Exception as e:
            last_error = e

    try:
        return pd.read_csv(
            input_path,
            dtype=str,
            encoding=encoding,
            keep_default_na=False,
        )
    except Exception as e:
        last_error = e

    raise RuntimeError(f"Failed to read file: {last_error}")


def process_single_url(
    url: str,
    row_number: int,
    product_id: str,
    sku: str,
    api_key: str,
    expiration: int,
    session: requests.Session,
    use_webp: bool = False,
) -> Dict[str, Any]:
    result = {
        "row_number": row_number,
        "product_id": product_id,
        "sku": sku,
        "original_url": url,
        "new_url": "",
        "delete_url": "",
        "original_format": "",
        "status": "",
        "reason": "",
    }

    try:
        content = download_image(url, session)
        result["original_format"] = detect_format_from_bytes(content)
        img_bytes, img_ext = convert_image_under_limit(content, use_webp=use_webp)

        file_name_parts = []
        if sku:
            file_name_parts.append(safe_filename(sku))
        elif product_id:
            file_name_parts.append(safe_filename(product_id))
        file_name_parts.append(f"row{row_number}")
        filename = "_".join(file_name_parts) + f".{img_ext}"

        upload_response = upload_to_imgbb(
            jpg_bytes=img_bytes,
            filename=filename,
            api_key=api_key,
            expiration=expiration,
            session=session,
        )
        result["new_url"] = upload_response["data"]["url"]
        result["delete_url"] = upload_response["data"].get("delete_url", "")
        result["status"] = "success"
        return result

    except requests.HTTPError as e:
        result["status"] = "failed"
        result["reason"] = f"http_error: {e}"
        return result
    except requests.RequestException as e:
        result["status"] = "failed"
        result["reason"] = f"request_error: {e}"
        return result
    except UnidentifiedImageError:
        result["status"] = "failed"
        result["reason"] = "invalid_image_content"
        return result
    except Exception as e:
        result["status"] = "failed"
        result["reason"] = f"processing_error: {e}"
        return result


def main():
    parser = argparse.ArgumentParser(
        description="Normalize product image URLs, upload to ImgBB, and write updated CSV for WooCommerce import."
    )
    parser.add_argument("input_file", help="Path to input CSV/XLSX file")
    parser.add_argument(
        "--output",
        default="",
        help="Path to output CSV file (default: <input>_normalized.csv)",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Path to report CSV file (default: <input>_normalization_report.csv)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="How many rows to process. 0 = all rows (default: 0)",
    )
    parser.add_argument(
        "--image-columns",
        default="",
        help="Comma-separated list of image columns. If omitted, script auto-detects.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV encoding (default: utf-8-sig)",
    )
    parser.add_argument(
        "--expiration",
        type=int,
        default=0,
        help="ImgBB expiration in seconds (default: 0 = no expiration)",
    )
    parser.add_argument(
        "--sheet",
        default="",
        help="Excel sheet name if input file is xlsx/xls (default: first sheet)",
    )
    parser.add_argument(
        "--webp",
        action="store_true",
        help="Convert images to WebP instead of JPEG (smaller files, modern browsers)",
    )
    parser.add_argument(
        "--skip-imgbb",
        action="store_true",
        help="Skip URLs that are already hosted on imgbb.com or i.ibb.co",
    )
    args = parser.parse_args()

    api_key = os.getenv("IMGBB_API_KEY", "").strip()
    if not api_key:
        print("ERROR: Δεν βρέθηκε το IMGBB_API_KEY environment variable.")
        sys.exit(1)

    if not os.path.exists(args.input_file):
        print(f"ERROR: Δεν βρέθηκε το input file: {args.input_file}")
        sys.exit(1)

    input_file = args.input_file
    base, _ = os.path.splitext(input_file)
    output_csv = args.output if args.output else f"{base}_normalized.csv"
    report_csv = args.report if args.report else f"{base}_normalization_report.csv"

    print(f"Reading file: {input_file}")
    df = read_tabular_flexible(input_file, args.encoding, args.sheet or None)

    if df.empty:
        print("ERROR: Το αρχείο είναι άδειο.")
        sys.exit(1)

    # Fix scientific notation in barcode/ID columns (Excel artifact: 5.29E+12 → 5291043000149)
    for _col in ["SKU", "sku", "Sku", "ID", "id", "Product ID", "product_id"]:
        if _col in df.columns:
            df[_col] = df[_col].apply(_fix_sku_string)

    possible_product_id_columns = ["product_id", "id", "Product ID", "ID"]
    possible_sku_columns = ["sku", "SKU", "Sku"]

    if args.image_columns.strip():
        image_columns = [c.strip() for c in args.image_columns.split(",") if c.strip()]
    else:
        image_columns = auto_detect_image_columns(df)

    if not image_columns:
        print("ERROR: Δεν βρέθηκαν columns με image URLs.")
        print('Δοκίμασε με --image-columns "Image URLs,images,image"')
        print("Available columns:")
        for c in df.columns:
            print(f" - {c}")
        sys.exit(1)

    print(f"Image columns: {image_columns}")
    print(f"Output format: {'WebP' if args.webp else 'JPEG'}")

    product_id_col = pick_first_existing(df, possible_product_id_columns)
    sku_col = pick_first_existing(df, possible_sku_columns)

    if product_id_col:
        print(f"Product ID column: {product_id_col}")
    if sku_col:
        print(f"SKU column: {sku_col}")

    for col in image_columns:
        backup_col = f"{col}_original"
        if backup_col not in df.columns:
            df[backup_col] = df[col]

    if "normalization_status" not in df.columns:
        df["normalization_status"] = ""
    if "normalization_reason" not in df.columns:
        df["normalization_reason"] = ""

    total_rows = len(df) if args.limit <= 0 else min(args.limit, len(df))
    print(f"Processing {total_rows} row(s)...")

    report_rows: List[Dict[str, Any]] = []
    session = requests.Session()
    start = time.time()

    success_count_live = 0
    failed_count_live  = 0
    skipped_count_live = 0

    for idx in range(total_rows):
        row = df.iloc[idx]
        csv_row_number = idx + 2  # header is row 1
        product_id = safe_str(row[product_id_col]) if product_id_col else ""
        sku = safe_str(row[sku_col]) if sku_col else ""
        name_col = next((c for c in ["Name","name","Product Name","product_name"] if c in df.columns), None)
        product_name = safe_str(row[name_col])[:50] if name_col else ""

        # ── live progress bar ──────────────────────────────────────────
        pct  = int((idx + 1) / total_rows * 100)
        bar  = "█" * (pct // 5) + "░" * (20 - pct // 5)
        eta_s = ""
        elapsed_now = time.time() - start
        if idx > 0:
            remaining = (elapsed_now / idx) * (total_rows - idx)
            m, s = divmod(int(remaining), 60)
            eta_s = f"  ETA {m}m{s:02d}s"
        print(f"\r[{bar}] {pct:3d}%  row {idx+1}/{total_rows}{eta_s}  ✅{success_count_live} ❌{failed_count_live} ⏭{skipped_count_live}  {product_name[:30]:<30}", end="", flush=True)
        # ───────────────────────────────────────────────────────────────

        row_has_failure = False
        row_reasons = []

        for col in image_columns:
            original_value = row[col]
            urls = extract_urls(original_value)
            if not urls:
                continue

            new_urls = []
            for url in urls:
                if args.skip_imgbb and ("imgbb.com" in url or "i.ibb.co" in url):
                    new_urls.append(url)
                    skipped_count_live += 1
                    report_rows.append({
                        "row_number": csv_row_number,
                        "product_id": product_id,
                        "sku": sku,
                        "source_column": col,
                        "original_url": url,
                        "new_url": url,
                        "delete_url": "",
                        "original_format": "already_imgbb",
                        "status": "skipped",
                        "reason": "already_on_imgbb",
                    })
                    continue

                result = process_single_url(
                    url=url,
                    row_number=csv_row_number,
                    product_id=product_id,
                    sku=sku,
                    api_key=api_key,
                    expiration=args.expiration,
                    session=session,
                    use_webp=args.webp,
                )
                report_rows.append({
                    "row_number": result["row_number"],
                    "product_id": result["product_id"],
                    "sku": result["sku"],
                    "source_column": col,
                    "original_url": result["original_url"],
                    "new_url": result["new_url"],
                    "delete_url": result["delete_url"],
                    "original_format": result["original_format"],
                    "status": result["status"],
                    "reason": result["reason"],
                })

                if result["status"] == "success":
                    new_urls.append(result["new_url"])
                    success_count_live += 1
                else:
                    failed_count_live += 1
                    row_has_failure = True
                    row_reasons.append(f"{col}: {result['reason']}")
                    new_urls.append(url)  # κρατάμε το original για ασφάλεια

            df.at[idx, col] = build_updated_cell(new_urls)

        if row_has_failure:
            df.at[idx, "normalization_status"] = "partial_or_failed"
            df.at[idx, "normalization_reason"] = " | ".join(row_reasons)
        else:
            df.at[idx, "normalization_status"] = "success"
            df.at[idx, "normalization_reason"] = ""

    print()  # newline after progress bar

    elapsed = round(time.time() - start, 2)
    report_df = pd.DataFrame(report_rows)

    df.to_csv(output_csv, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_ALL)
    report_df.to_csv(report_csv, index=False, encoding="utf-8-sig")

    success_count = int((report_df["status"] == "success").sum()) if not report_df.empty else 0
    failed_count = int((report_df["status"] == "failed").sum()) if not report_df.empty else 0
    skipped_count = int((report_df["status"] == "skipped").sum()) if not report_df.empty else 0

    print("\nDONE")
    print(f"Updated CSV: {output_csv}")
    print(f"Report CSV: {report_csv}")
    print(f"Success uploads: {success_count}")
    print(f"Failed uploads: {failed_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Elapsed: {elapsed}s")


if __name__ == "__main__":
    main()