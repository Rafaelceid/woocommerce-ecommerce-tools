
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IFIALE — Brand Logo Fetcher v6.0 CURATED / TRUSTED ONLY

Αυτή η έκδοση είναι διαφορετική από τις προηγούμενες:
- ΔΕΝ κάνει generic Commons/image search by default.
- Χρησιμοποιεί curated λίστα με συγκεκριμένα γνωστά logo files / direct image URLs.
- Τα curated sources θεωρούνται trusted και ΔΕΝ απορρίπτονται από “photo-like” heuristic.
- Καθαρίζει τα παλιά .webp για τα selected brands ώστε να μην μένουν λάθος leftovers.
- Κάνει trim whitespace και καλύτερο centering για καθαρότερο 500x500 output.

Requirements:
    pip install requests pillow

Usage:
    python fetch_brand_logos.py
    python fetch_brand_logos.py --brands "Korres,Vichy,AHAVA"
    python fetch_brand_logos.py --status
    python fetch_brand_logos.py --links
    python fetch_brand_logos.py --convert-manual

Manual override:
    Βάλε manual file ως manual_logos/<slug>.png ή .jpg ή .webp
    και τρέξε: python fetch_brand_logos.py --convert-manual
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import requests
from PIL import Image, ImageOps, ImageChops, ImageStat

LOGO_SIZE = 500
WEBP_QUALITY = 92
TIMEOUT = 25
SLEEP = 0.20
THUMB_WIDTH = 1800
UA = "Mozilla/5.0 (compatible; IFIALE-Logo-Fetcher/6.0; +https://ifiale.com)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

BRANDS = [
    {"name": "NAM",            "slug": "nam"},
    {"name": "Korres",         "slug": "korres"},
    {"name": "APIVITA",        "slug": "apivita"},
    {"name": "Vichy",          "slug": "vichy"},
    {"name": "AHAVA",          "slug": "ahava"},
    {"name": "Pharmalead",     "slug": "pharmalead"},
    {"name": "La Roche-Posay", "slug": "la-roche-posay"},
    {"name": "Avene",          "slug": "avene"},
    {"name": "CeraVe",         "slug": "cerave"},
    {"name": "Mad Beauty",     "slug": "mad-beauty"},
    {"name": "Starskin",       "slug": "starskin"},
    {"name": "Dr. Brown's",    "slug": "dr-browns"},
    {"name": "Tommee Tippee",  "slug": "tommee-tippee"},
    {"name": "Medela",         "slug": "medela"},
    {"name": "Chicco",         "slug": "chicco"},
    {"name": "NUK",            "slug": "nuk"},
    {"name": "Mustela",        "slug": "mustela"},
    {"name": "Frezyderm",      "slug": "frezyderm"},
    {"name": "Pharmasept",     "slug": "pharmasept"},
    {"name": "Weleda",         "slug": "weleda"},
]

# Curated / trusted sources. Order matters.
# type=commons_file -> rendered via Wikimedia thumburl, good for SVG.
# type=url -> direct raster image. Direct SVG is intentionally not used.
SOURCES: Dict[str, List[Dict[str, str]]] = {
    "nam": [
        {"type": "url", "value": "https://namcosmetics.eu/wp-content/uploads/2023/02/NAM-LOGO-PLATA.png", "label": "official_namcosmetics_eu"},
    ],
    "korres": [
        {"type": "url", "value": "https://mma.prnewswire.com/media/1373568/KORRES_Logo.jpg?p=publish", "label": "prnewswire_korres_logo"},
        {"type": "url", "value": "https://www.gtp.gr/MGfiles/logos/51508_KORRES-Cosmetics-Logo-04_600x600.png", "label": "gtp_korres_logo"},
    ],
    "apivita": [
        {"type": "url", "value": "https://img.newpharma.net/images/brands/apivita.2.png", "label": "newpharma_apivita_logo"},
        {"type": "url", "value": "https://productosaptos.com/wp-content/uploads/2024/09/APIVITA-LOGO.png", "label": "productosaptos_apivita_logo"},
    ],
    "vichy": [
        {"type": "commons_file", "value": "Vichy Laboratoires (logo).jpg", "label": "commons_vichy_logo"},
    ],
    "ahava": [
        {"type": "commons_file", "value": "AhavaLogo.png", "label": "commons_ahava_logo"},
    ],
    "pharmalead": [
        {"type": "url", "value": "https://www.primepharmacy.gr/files/vendors/66ca63ae7cb395a3a4906282adf9c41e.png", "label": "primepharmacy_pharmalead_logo"},
        {"type": "url", "value": "https://www.ofarmakopoiosmou.gr/sites/default/files/pharmalead_2.jpg", "label": "ofarmakopoiosmou_pharmalead_logo"},
    ],
    "la-roche-posay": [
        {"type": "commons_file", "value": "La Roche-Posay (brand).svg", "label": "commons_larocheposay_logo"},
    ],
    "avene": [
        {"type": "commons_file", "value": "Av_new-logo-2022_eau-thermale-avene.png", "label": "commons_avene_logo"},
    ],
    "cerave": [
        {"type": "commons_file", "value": "CeraVe_logo.png", "label": "commons_cerave_logo"},
    ],
    "mad-beauty": [
        {"type": "url", "value": "https://www.pharmaspot.gr/files/vendors/b35b5d40eddf8cf2dd7e5cecd0f52e9f.JPG", "label": "pharmaspot_madbeauty_logo"},
        {"type": "url", "value": "https://beautyprincess.gr/image/cache/data/manufacturers/madbeauty-600x315h.jpg", "label": "beautyprincess_madbeauty_logo"},
    ],
    "starskin": [
        {"type": "url", "value": "https://www.starskin.com/cdn/shop/files/starskin_logo_91bd8eb6-6007-4b9a-a3e5-01486e1c011b_1444x.png?v=1630529749", "label": "official_starskin_logo"},
        {"type": "url", "value": "https://mma.prnewswire.com/media/493452/STARSKIN_Logo.jpg?p=facebook", "label": "prnewswire_starskin_logo"},
    ],
    "dr-browns": [
        {"type": "url", "value": "https://www.drbrowns.com.au/cdn/shop/files/Dr_Browns_Logo_Australia_1200x600_crop_center.jpg?v=1627301394", "label": "official_drbrowns_au_logo"},
        {"type": "url", "value": "https://manuals.plus/wp-content/uploads/2024/03/Dr-Browns-LOGO-1.png", "label": "manualsplus_drbrowns_logo"},
        {"type": "url", "value": "https://nua.pe/cdn/shop/collections/dr-browns-logo_zps0154879a.png?v=1666131588", "label": "nua_drbrowns_logo"},
    ],
    "tommee-tippee": [
        {"type": "url", "value": "https://www.mayborngroup.com/storage/app/uploads/public/65f/af3/f09/65faf3f0939b8851583595.png", "label": "mayborn_press_tommee_logo"},
        {"type": "url", "value": "https://tommeetippeehkeshop.com/cdn/shop/files/logo_TT_2021_2000x2000_f1df42b0-cde9-48d5-9fab-2f2f36962c4c.png?v=1712824335&width=600", "label": "official_hk_tommee_logo"},
    ],
    "medela": [
        {"type": "commons_file", "value": "Logo Medela kurz.svg", "label": "commons_medela_logo"},
    ],
    "chicco": [
        {"type": "commons_file", "value": "Chicco logo.svg", "label": "commons_chicco_logo"},
    ],
    "nuk": [
        {"type": "commons_file", "value": "Logo nuk.png", "label": "commons_nuk_logo"},
    ],
    "mustela": [
        {"type": "url", "value": "https://www.mustela.es/cdn/shop/files/Blue_Logo_High_Resolution_CMJN.png?height=628&pad_color=ffffff&v=1721124050&width=1200", "label": "official_mustela_es_logo"},
        {"type": "url", "value": "https://cdn.shopify.com/s/files/1/0593/0582/0309/t/16/assets/Logo.png?v=151105772697650581441672827810", "label": "official_mustela_it_logo"},
    ],
    "frezyderm": [
        {"type": "url", "value": "https://www.cphi-online.com/company/frezyderm-s-a/logo.png", "label": "cphi_frezyderm_logo"},
        {"type": "url", "value": "https://frezydermguatemala.com/cdn/shop/files/03_logo_frezyderm.png?v=1729620207&width=832", "label": "frezyderm_guatemala_logo"},
        {"type": "url", "value": "https://www.entersoft.eu/wp-content/uploads/2017/07/Frezyderm_png.png", "label": "entersoft_frezyderm_logo"},
    ],
    "pharmasept": [
        {"type": "url", "value": "https://pharmasept.gr/wp-content/uploads/pharmasept-768x86.png", "label": "official_pharmasept_gr_logo"},
        {"type": "url", "value": "https://cdn.pharm24.gr/images/manufacturers/344x344-90/PHARMASEPT_LOGO.png", "label": "pharm24_pharmasept_logo"},
    ],
    "weleda": [
        {"type": "commons_file", "value": "Logo Weleda.svg", "label": "commons_weleda_logo"},
    ],
}

DOMAIN_HINTS = {
    "nam": "namcosmetics.eu",
    "korres": "korres.com",
    "apivita": "apivita.com",
    "vichy": "vichy.com",
    "ahava": "ahava.com",
    "pharmalead": "pharmalead.gr",
    "la-roche-posay": "laroche-posay.com",
    "avene": "eau-thermale-avene.com",
    "cerave": "cerave.com",
    "mad-beauty": "madbeauty.com",
    "starskin": "starskin.com",
    "dr-browns": "drbrownsbaby.com",
    "tommee-tippee": "tommeetippee.com",
    "medela": "medela.com",
    "chicco": "chicco.com",
    "nuk": "nuk.com",
    "mustela": "mustela.com",
    "frezyderm": "frezyderm.com",
    "pharmasept": "pharmasept.gr",
    "weleda": "weleda.com",
}

REPORT_FIELDS = ["name", "slug", "source", "source_type", "url", "file", "status", "note"]


def slugify_text(s: str) -> str:
    if not s:
        return ""
    s = s.lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", "", s)


def filter_brands(want: str) -> List[Dict[str, str]]:
    if not want.strip():
        return BRANDS[:]
    keys = {slugify_text(x) for x in want.split(",") if x.strip()}
    return [b for b in BRANDS if slugify_text(b["name"]) in keys or slugify_text(b["slug"]) in keys]


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,el;q=0.8",
    })
    return s


def fetch_url(session: requests.Session, url: str) -> bytes:
    r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").lower()
    data = r.content
    if b"<html" in data[:500].lower():
        raise ValueError(f"got_html_not_image content-type={ctype}")
    if "svg" in ctype or url.lower().split("?")[0].endswith(".svg"):
        raise ValueError("direct_svg_not_supported_use_commons_or_manual")
    return data


def commons_raster(session: requests.Session, file_name: str, thumb_width: int = THUMB_WIDTH) -> Tuple[bytes, str]:
    title = file_name if file_name.startswith("File:") else f"File:{file_name}"
    r = session.get(COMMONS_API, params={
        "action": "query",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|mime|size",
        "iiurlwidth": thumb_width,
        "redirects": 1,
        "format": "json",
    }, timeout=TIMEOUT)
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages", {})
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        ii = infos[0]
        url = ii.get("thumburl") or ii.get("url")
        if not url:
            continue
        raw = fetch_url(session, url)
        return raw, url
    raise FileNotFoundError(file_name)


def image_from_bytes(raw: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    if img.mode == "P":
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "RGBA", "LA", "L"):
        img = img.convert("RGBA")
    return img


def trim_logo(img: Image.Image) -> Image.Image:
    """Trim near-white/transparent padding but keep safe margin."""
    if img.mode not in ("RGBA", "LA"):
        rgba = img.convert("RGBA")
    else:
        rgba = img.convert("RGBA")

    # If alpha exists, use alpha bbox first.
    alpha = rgba.getchannel("A")
    abox = alpha.point(lambda p: 255 if p > 10 else 0).getbbox()

    # Also detect non-white pixels for white-background logos.
    rgb = Image.new("RGB", rgba.size, (255, 255, 255))
    rgb.paste(rgba, mask=alpha)
    bg = Image.new("RGB", rgb.size, (255, 255, 255))
    diff = ImageChops.difference(rgb, bg).convert("L")
    bbox = diff.point(lambda p: 255 if p > 14 else 0).getbbox()

    box = bbox or abox
    if not box:
        return img

    x1, y1, x2, y2 = box
    w, h = rgba.size
    pad = max(4, int(max(x2-x1, y2-y1) * 0.06))
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)
    return img.crop((x1, y1, x2, y2))


def to_square_webp(raw: bytes, size: int = LOGO_SIZE, quality: int = WEBP_QUALITY) -> bytes:
    img = image_from_bytes(raw)
    img = trim_logo(img)

    # Composite on white. Logos with black/dark background remain as-is.
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").getchannel("A"))
        img = bg
    elif img.mode == "L":
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if w < 32 or h < 32:
        raise ValueError(f"image_too_small:{w}x{h}")

    # Fit logo into 82% of square for consistent brand tiles.
    target = int(size * 0.82)
    scale = min(target / w, target / h)
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))
    img = img.resize((nw, nh), Image.LANCZOS)

    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    canvas.paste(img, ((size - nw) // 2, (size - nh) // 2))
    out = io.BytesIO()
    canvas.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


def quick_quality_check(webp_bytes: bytes) -> Tuple[bool, str]:
    """Reject blank/near-blank outputs only. Curated sources are trusted otherwise."""
    with Image.open(io.BytesIO(webp_bytes)) as img:
        gray = img.convert("L")
        stat = ImageStat.Stat(gray)
        # very low variance and almost white = blank
        if stat.stddev[0] < 2.0 and stat.mean[0] > 248:
            return False, f"blank_like mean={stat.mean[0]:.1f} std={stat.stddev[0]:.1f}"
    return True, "ok"


def manual_candidates(manual_dir: Path, slug: str) -> List[Path]:
    out = []
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"):
        p = manual_dir / f"{slug}{ext}"
        if p.exists():
            out.append(p)
    return out


def fetch_source(session: requests.Session, src: Dict[str, str]) -> Tuple[bytes, str]:
    if src["type"] == "commons_file":
        return commons_raster(session, src["value"])
    if src["type"] == "url":
        return fetch_url(session, src["value"]), src["value"]
    raise ValueError(f"unknown_source_type:{src['type']}")


def clean_outputs(brands: List[Dict[str, str]], out_dir: Path) -> None:
    for b in brands:
        p = out_dir / f"{b['slug']}.webp"
        if p.exists():
            p.unlink()


def process_brand(brand: Dict[str, str], session: requests.Session, out_dir: Path,
                  manual_dir: Path, size: int, quality: int, prefer_manual: bool = False) -> Dict[str, str]:
    row = {k: "" for k in REPORT_FIELDS}
    row["name"] = brand["name"]
    row["slug"] = brand["slug"]
    row["status"] = "failed"

    candidates: List[Dict[str, str]] = []
    manual_files = manual_candidates(manual_dir, brand["slug"])
    if prefer_manual and manual_files:
        candidates.append({"type": "manual", "value": str(manual_files[0]), "label": "manual_override"})
    candidates.extend(SOURCES.get(brand["slug"], []))
    if not prefer_manual and manual_files:
        candidates.append({"type": "manual", "value": str(manual_files[0]), "label": "manual_override"})

    notes = []
    for src in candidates:
        try:
            if src["type"] == "manual":
                raw = Path(src["value"]).read_bytes()
                resolved = src["value"]
            else:
                raw, resolved = fetch_source(session, src)

            webp = to_square_webp(raw, size=size, quality=quality)
            ok, qnote = quick_quality_check(webp)
            if not ok:
                raise ValueError(qnote)

            out = out_dir / f"{brand['slug']}.webp"
            out.write_bytes(webp)
            row.update({
                "source": src["label"],
                "source_type": src["type"],
                "url": resolved,
                "file": out.name,
                "status": "ok",
                "note": qnote,
            })
            print(f"      ✓ {src['label']} -> {out.name}")
            return row
        except Exception as e:
            msg = f"{src.get('label', src.get('type'))}: {type(e).__name__}: {str(e)[:120]}"
            notes.append(msg)
            print(f"      ✗ {msg}")
            time.sleep(SLEEP)

    row["status"] = "no_logo"
    row["note"] = " | ".join(notes)[:900] if notes else "no_curated_source"
    return row


def write_report(path: Path, rows: List[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
        w.writeheader()
        w.writerows(rows)


def read_report(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def convert_manual(brands: List[Dict[str, str]], manual_dir: Path, out_dir: Path, size: int, quality: int) -> List[Dict[str, str]]:
    rows = []
    for b in brands:
        row = {k: "" for k in REPORT_FIELDS}
        row["name"] = b["name"]
        row["slug"] = b["slug"]
        files = manual_candidates(manual_dir, b["slug"])
        if not files:
            row["status"] = "missing_manual"
            row["note"] = "Δεν βρέθηκε manual file"
            print(f"✗ {b['name']}: missing manual")
        else:
            try:
                raw = files[0].read_bytes()
                webp = to_square_webp(raw, size=size, quality=quality)
                out = out_dir / f"{b['slug']}.webp"
                out.write_bytes(webp)
                row.update({
                    "source": "manual_override",
                    "source_type": "manual",
                    "url": str(files[0]),
                    "file": out.name,
                    "status": "ok",
                    "note": "manual_ok",
                })
                print(f"✓ {b['name']}: {files[0].name} -> {out.name}")
            except Exception as e:
                row["status"] = "convert_error"
                row["note"] = str(e)[:200]
                print(f"✗ {b['name']}: {e}")
        rows.append(row)
    return rows


def print_status(brands: List[Dict[str, str]], out_dir: Path, report_path: Path) -> None:
    rows = {r.get("slug"): r for r in read_report(report_path)}
    ok = 0
    print("\nStatus")
    print("-" * 100)
    for b in brands:
        file_ok = (out_dir / f"{b['slug']}.webp").exists()
        r = rows.get(b["slug"], {})
        if file_ok:
            ok += 1
            print(f"✓ {b['name']:<18} {r.get('source',''):<34} {r.get('note','')[:35]}")
        else:
            print(f"✗ {b['name']:<18} {r.get('status','missing'):<34} {r.get('note','')[:60]}")
    print("-" * 100)
    print(f"Done: {ok}/{len(brands)}")


def print_links(brands: List[Dict[str, str]], out_dir: Path, manual_dir: Path) -> None:
    print("\nManual fallback links")
    print("-" * 100)
    for b in brands:
        if (out_dir / f"{b['slug']}.webp").exists():
            continue
        q = quote_plus(f"{b['name']} official logo png")
        print(f"\n{b['name']} ({b['slug']})")
        print(f"  Site       : https://{DOMAIN_HINTS.get(b['slug'], '')}")
        print(f"  Image      : https://www.google.com/search?tbm=isch&q={q}")
        print(f"  Save as    : {manual_dir / (b['slug'] + '.png')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=LOGO_SIZE)
    ap.add_argument("--quality", type=int, default=WEBP_QUALITY)
    ap.add_argument("--out", default="logos_webp")
    ap.add_argument("--manual-dir", default="manual_logos")
    ap.add_argument("--brands", default="")
    ap.add_argument("--thumb-width", type=int, default=THUMB_WIDTH)
    ap.add_argument("--no-clean", action="store_true", help="Μην καθαρίσεις παλιά .webp πριν το run")
    ap.add_argument("--prefer-manual", action="store_true", help="Χρησιμοποίησε manual file πριν από curated sources")
    ap.add_argument("--convert-manual", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--links", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out)
    manual_dir = Path(args.manual_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manual_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "brands_report.csv"

    brands = filter_brands(args.brands)
    if not brands:
        print("No matching brands.")
        return 2

    if args.status:
        print_status(brands, out_dir, report_path)
        return 0
    if args.links:
        print_links(brands, out_dir, manual_dir)
        return 0
    if args.convert_manual:
        rows = convert_manual(brands, manual_dir, out_dir, args.size, args.quality)
        write_report(report_path, rows)
        return 0

    print("=" * 96)
    print("IFIALE — Brand Logo Fetcher v6.0 CURATED / TRUSTED ONLY")
    print(f"Brands       : {len(brands)}")
    print(f"Output       : {out_dir.resolve()}")
    print(f"Manual       : {manual_dir.resolve()}")
    print(f"Size         : {args.size}x{args.size} q={args.quality}")
    print(f"Clean old    : {not args.no_clean}")
    print(f"Prefer manual: {args.prefer_manual}")
    print("=" * 96)

    if not args.no_clean:
        clean_outputs(brands, out_dir)
        print("Cleaned old .webp outputs for selected brands.")

    session = get_session()
    rows = []
    ok = fail = 0
    for i, b in enumerate(brands, 1):
        print(f"\n[{i}/{len(brands)}] {b['name']}")
        row = process_brand(b, session, out_dir, manual_dir, args.size, args.quality, prefer_manual=args.prefer_manual)
        rows.append(row)
        if row["status"] == "ok":
            ok += 1
        else:
            fail += 1

    write_report(report_path, rows)
    print("\n" + "=" * 96)
    print(f"Success : {ok}/{len(rows)}")
    print(f"Failed  : {fail}/{len(rows)}")
    print(f"Output  : {out_dir.resolve()}")
    print(f"Report  : {report_path.resolve()}")
    if fail:
        print("\nFor missing/problematic brands:")
        print("  python fetch_brand_logos.py --links")
        print("  Put verified files in manual_logos/<slug>.png")
        print("  python fetch_brand_logos.py --convert-manual")
    print("=" * 96)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
