import os
import io
import re
import sys
import csv
import time
import hashlib
import argparse
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from PIL import Image, ImageOps, UnidentifiedImageError

# Optional AVIF / HEIC support if installed
try:
    import pillow_avif  # noqa: F401
except Exception:
    pass
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

REQUEST_TIMEOUT = 60
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
JPEG_QUALITY_START = 92
JPEG_QUALITY_MIN = 60
WEBP_QUALITY_START = 92
WEBP_QUALITY_MIN = 60
MAX_DIMENSION_START = 2500
MIN_DIMENSION = 900
MAX_UPLOAD_BYTES = 95 * 1024 * 1024
URL_RE = re.compile(r"https?://[^\s,;]+")

_SCI_RE = re.compile(r'^-?\d+\.?\d*[eE][+\-]?\d+$')

def _fix_sku_string(v: Any) -> str:
    """Fix scientific notation / float artifacts in barcode columns.
    '5.29104E+12' → '5291043000149'  |  '5291043000149.0' → '5291043000149'
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
    value = re.sub(r"[^\w\-.]+", "_", value, flags=re.UNICODE)
    value = value.strip("._")
    return value[:120] if value else "item"


def extract_urls(cell_value: Any) -> List[str]:
    return URL_RE.findall(safe_str(cell_value))


def download_image(url: str, session: requests.Session) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
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


def convert_image_under_limit(content: bytes, use_webp: bool = False) -> Tuple[bytes, str]:
    with Image.open(io.BytesIO(content)) as original:
        base = flatten_to_rgb(original)
        current_max_dim = MAX_DIMENSION_START
        quality = WEBP_QUALITY_START if use_webp else JPEG_QUALITY_START
        quality_min = WEBP_QUALITY_MIN if use_webp else JPEG_QUALITY_MIN
        fmt = "WEBP" if use_webp else "JPEG"
        ext = "webp" if use_webp else "jpg"

        while current_max_dim >= MIN_DIMENSION:
            resized = resize_if_needed(base, current_max_dim)
            q = quality
            while q >= quality_min:
                out = io.BytesIO()
                save_kwargs = {"format": fmt, "quality": q, "optimize": True}
                if fmt == "JPEG":
                    save_kwargs["progressive"] = True
                resized.save(out, **save_kwargs)
                data = out.getvalue()
                if len(data) <= MAX_UPLOAD_BYTES:
                    return data, ext
                q -= 5
            current_max_dim = int(current_max_dim * 0.85)

        resized = resize_if_needed(base, MIN_DIMENSION)
        out = io.BytesIO()
        resized.save(out, format=fmt, quality=quality_min, optimize=True)
        return out.getvalue(), ext


def detect_format_from_bytes(content: bytes) -> str:
    try:
        with Image.open(io.BytesIO(content)) as img:
            fmt = (img.format or "").lower().strip()
            return "jpg" if fmt == "jpeg" else (fmt or "unknown")
    except Exception:
        return "unknown"


def cloudinary_signature(params: Dict[str, Any], api_secret: str) -> str:
    filtered = {
        k: v for k, v in params.items()
        if v not in (None, "") and k not in ("file", "api_key", "resource_type", "cloud_name")
    }
    to_sign = "&".join(f"{k}={filtered[k]}" for k in sorted(filtered.keys()))
    return hashlib.sha1((to_sign + api_secret).encode("utf-8")).hexdigest()


def upload_to_cloudinary(
    image_bytes: bytes,
    filename: str,
    cloud_name: str,
    api_key: str,
    api_secret: str,
    session: requests.Session,
    folder: str = "ifiale-products",
    overwrite: bool = True,
) -> Dict[str, Any]:
    endpoint = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    public_id = os.path.splitext(safe_filename(filename))[0]
    timestamp = int(time.time())
    params = {
        "timestamp": timestamp,
        "folder": folder,
        "public_id": public_id,
        "overwrite": "true" if overwrite else "false",
        "invalidate": "true",
    }
    signature = cloudinary_signature(params, api_secret)
    data = {**params, "api_key": api_key, "signature": signature}
    files = {"file": (safe_filename(filename), image_bytes, "application/octet-stream")}
    response = session.post(endpoint, data=data, files=files, timeout=REQUEST_TIMEOUT)
    try:
        payload = response.json()
    except Exception:
        payload = {"raw_text": response.text}
    if response.status_code >= 400 or "secure_url" not in payload:
        raise ValueError(f"Cloudinary upload failed: HTTP {response.status_code}: {payload}")
    return payload


def pick_first_existing(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    lower_map = {str(col).lower(): col for col in df.columns}
    for candidate in candidates:
        actual = lower_map.get(str(candidate).lower())
        if actual is not None:
            return actual
    return None


def auto_detect_image_columns(df: pd.DataFrame, sample_rows: int = 30) -> List[str]:
    detected = []
    check_df = df.head(sample_rows)
    for col in df.columns:
        if any(extract_urls(value) for value in check_df[col].tolist()):
            detected.append(col)
    return detected


def read_tabular_flexible(input_path: str, encoding: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
    ext = os.path.splitext(input_path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return pd.read_excel(input_path, sheet_name=sheet_name or 0, dtype=str, keep_default_na=False, engine="openpyxl")
    if ext == ".xls":
        return pd.read_excel(input_path, sheet_name=sheet_name or 0, dtype=str, keep_default_na=False, engine="xlrd")
    return pd.read_csv(input_path, encoding=encoding, dtype=str, keep_default_na=False)


def is_cloudinary_url(url: str, cloud_name: str) -> bool:
    return f"res.cloudinary.com/{cloud_name}/" in url or "cloudinary.com/" in url


def process_single_url(
    url: str,
    row_number: int,
    product_id: str,
    sku: str,
    source_column: str,
    cloud_name: str,
    api_key: str,
    api_secret: str,
    folder: str,
    session: requests.Session,
    use_webp: bool = False,
) -> Dict[str, Any]:
    result = {
        "row_number": row_number,
        "product_id": product_id,
        "sku": sku,
        "source_column": source_column,
        "original_url": url,
        "new_url": "",
        "public_id": "",
        "asset_id": "",
        "version": "",
        "original_format": "",
        "uploaded_format": "webp" if use_webp else "jpg",
        "status": "",
        "reason": "",
    }
    try:
        content = download_image(url, session)
        result["original_format"] = detect_format_from_bytes(content)
        converted, ext = convert_image_under_limit(content, use_webp=use_webp)
        filename = f"{safe_filename(sku or product_id or 'row')}-row{row_number}.{ext}"
        upload = upload_to_cloudinary(converted, filename, cloud_name, api_key, api_secret, session, folder, overwrite=True)
        result["new_url"] = upload.get("secure_url", "")
        result["public_id"] = upload.get("public_id", "")
        result["asset_id"] = upload.get("asset_id", "")
        result["version"] = str(upload.get("version", ""))
        result["status"] = "success"
    except requests.HTTPError as e:
        result["status"] = "failed"
        result["reason"] = f"http_error: {e}"
    except UnidentifiedImageError as e:
        result["status"] = "failed"
        result["reason"] = f"not_an_image: {e}"
    except Exception as e:
        result["status"] = "failed"
        result["reason"] = f"error: {e}"
    return result


def progress_bar(done: int, total: int, success: int, failed: int, skipped: int, label: str, start_time: float) -> None:
    width = 20
    ratio = done / total if total else 1
    filled = int(width * ratio)
    bar = "█" * filled + "░" * (width - filled)
    elapsed = time.time() - start_time
    eta = (elapsed / done * (total - done)) if done else 0
    label = safe_str(label)[:28]
    sys.stdout.write(
        f"\r[{bar}] {ratio:>4.0%}  row {done}/{total}  ETA {int(eta//60)}m{int(eta%60):02d}s  ✅{success} ❌{failed} ⏭{skipped}  {label:<28}"
    )
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize product image URLs, upload to Cloudinary, and write updated CSV for WooCommerce import.")
    parser.add_argument("input_file", help="Path to input CSV/XLSX file")
    parser.add_argument("--output", default="", help="Path to output CSV file")
    parser.add_argument("--report", default="", help="Path to report CSV file")
    parser.add_argument("--limit", type=int, default=0, help="How many rows to process. 0 = all rows")
    parser.add_argument("--image-columns", default="", help="Comma-separated list of image columns. If omitted, script auto-detects.")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV encoding")
    parser.add_argument("--sheet", default="", help="Excel sheet name if input is xlsx/xls")
    parser.add_argument("--webp", action="store_true", help="Convert images to WebP before upload")
    parser.add_argument("--folder", default="ifiale-products", help="Cloudinary folder")
    parser.add_argument("--skip-cloudinary", action="store_true", help="Skip URLs already hosted on Cloudinary")
    args = parser.parse_args()

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    missing_env = [name for name, value in {
        "CLOUDINARY_CLOUD_NAME": cloud_name,
        "CLOUDINARY_API_KEY": api_key,
        "CLOUDINARY_API_SECRET": api_secret,
    }.items() if not value]
    if missing_env:
        print("ERROR: Missing environment variable(s): " + ", ".join(missing_env))
        raise SystemExit(1)

    input_file = args.input_file
    base, _ = os.path.splitext(input_file)
    output_csv = args.output or f"{base}_cloudinary_normalized.csv"
    report_csv = args.report or f"{base}_cloudinary_report.csv"

    df = read_tabular_flexible(input_file, args.encoding, args.sheet or None)
    unnamed_cols = [c for c in df.columns if str(c).startswith("Unnamed") or str(c).strip() == ""]
    if unnamed_cols:
        df = df.drop(columns=unnamed_cols)

    # Fix scientific notation in barcode/ID columns (Excel artifact: 5.29E+12 → 5291043000149)
    for _col in ["SKU", "sku", "ID", "id", "Product ID", "product_id"]:
        if _col in df.columns:
            df[_col] = df[_col].apply(_fix_sku_string)

    id_col = pick_first_existing(df, ["ID", "id", "product_id"])
    sku_col = pick_first_existing(df, ["SKU", "sku"])

    if args.image_columns.strip():
        image_columns = [c.strip() for c in args.image_columns.split(",") if c.strip()]
    else:
        image_columns = auto_detect_image_columns(df)
    image_columns = [c for c in image_columns if c in df.columns]
    if not image_columns:
        print("ERROR: No image columns found. Use --image-columns Images")
        raise SystemExit(1)

    total_rows = min(args.limit, len(df)) if args.limit and args.limit > 0 else len(df)
    print(f"Input: {input_file}")
    print(f"Output: {output_csv}")
    print(f"Report: {report_csv}")
    print(f"Cloudinary folder: {args.folder}")
    print(f"Image columns: {', '.join(image_columns)}")
    print(f"SKU column: {sku_col or '[none]'}")
    print(f"Processing {total_rows} row(s)...")

    session = requests.Session()
    report_rows: List[Dict[str, Any]] = []
    success_count = failed_count = skipped_count = 0
    start_time = time.time()

    for idx in range(total_rows):
        row_number = idx + 2
        row = df.iloc[idx]
        product_id = safe_str(row[id_col]) if id_col else ""
        sku = safe_str(row[sku_col]) if sku_col else ""
        label = safe_str(row.get("Name", sku or product_id or str(row_number)))

        for col in image_columns:
            original_cell = safe_str(df.at[idx, col])
            urls = extract_urls(original_cell)
            if not urls:
                continue

            new_urls = []
            cell_reasons = []
            for url in urls:
                if args.skip_cloudinary and is_cloudinary_url(url, cloud_name):
                    new_urls.append(url)
                    skipped_count += 1
                    report_rows.append({
                        "row_number": row_number, "product_id": product_id, "sku": sku,
                        "source_column": col, "original_url": url, "new_url": url,
                        "public_id": "", "asset_id": "", "version": "",
                        "original_format": "already_cloudinary", "uploaded_format": "",
                        "status": "skipped", "reason": "already_on_cloudinary",
                    })
                    continue

                result = process_single_url(url, row_number, product_id, sku, col, cloud_name, api_key, api_secret, args.folder, session, use_webp=args.webp)
                report_rows.append(result)
                if result["status"] == "success":
                    success_count += 1
                    new_urls.append(result["new_url"])
                else:
                    failed_count += 1
                    new_urls.append(url)
                    cell_reasons.append(f"{col}: {result['reason']}")

            df.at[idx, col] = ", ".join(new_urls)
            if f"{col}_original" not in df.columns:
                df[f"{col}_original"] = ""
            df.at[idx, f"{col}_original"] = original_cell
            df.at[idx, "normalization_status"] = "success" if not cell_reasons else "partial_or_failed"
            df.at[idx, "normalization_reason"] = "; ".join(cell_reasons)

        progress_bar(idx + 1, total_rows, success_count, failed_count, skipped_count, label, start_time)

    print()
    report_df = pd.DataFrame(report_rows)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_ALL)
    report_df.to_csv(report_csv, index=False, encoding="utf-8-sig")

    elapsed = time.time() - start_time
    print("Done.")
    print(f"Successful uploads: {success_count}")
    print(f"Failed uploads: {failed_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Elapsed: {elapsed:.2f}s")


if __name__ == "__main__":
    main()
