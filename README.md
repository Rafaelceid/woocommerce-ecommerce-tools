# WooCommerce E-commerce Toolkit

[![CI](https://github.com/Rafaelceid/woocommerce-ecommerce-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/Rafaelceid/woocommerce-ecommerce-tools/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Changelog](https://img.shields.io/badge/changelog-v1.0.0-informational.svg)](CHANGELOG.md)

A production-grade Python toolkit for WooCommerce + Woodmart stores. Built for a pharmacy/cosmetics e-commerce shop in Cyprus — generalised for any WooCommerce operator.

Covers the full pre-launch pipeline: image standardisation, CSV batch preparation, bulk media upload to Cloudinary/ImgBB, brand logo fetching, taxonomy cleanup, REST API automation, and a no-install browser image editor.

---

## Why this exists

WooCommerce product imports are painful:

- Supplier photos arrive at random sizes and formats
- Barcode SKUs get corrupted to scientific notation by Excel (`5.29E+12` instead of `5291043000149`)
- Cloudinary/ImgBB upload pipelines need retries, rate-limiting, and progress tracking
- Category IDs need validation before any write — a wrong ID silently miscategorises hundreds of products
- The store server (shared hosting) can't handle concurrent API calls

This toolkit solves all of it with clean, testable, argparse-driven scripts.

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your credentials
pytest tests/ -v       # 35 tests, ~1s
```

---

## Architecture

```
woocommerce-ecommerce-tools/
│
├── presets.json              Single source of truth for image output sizes
│                             (read by both CLI tools and the browser editor)
│
├── shared/
│   └── wc_client.py          WooCommerce REST v3 client
│                             · per_page=100 pagination
│                             · exponential back-off on 429/5xx
│                             · configurable rate-limit (default 300 ms)
│                             · category-ID validation before writes
│                             · dry_run=True default on all mutations
│
├── tools/
│   ├── browser/
│   │   └── ifiale-image-studio.html   No-install browser image editor
│   │
│   ├── image_tools.py         CLI: resize | convert | logo  (reads presets.json)
│   ├── csv_cloudinary_normalizer.py   Bulk image → Cloudinary → updated CSV
│   ├── csv_imgbb_normalizer.py        Bulk image → ImgBB → updated CSV
│   ├── fetch_brand_logos.py           Brandfetch/Wikimedia → 500×500 WebP logos
│   ├── png_to_svg.py                  PNG → SVG via vtracer (alpha trim + centre)
│   ├── process_taxonomy.py            Clean brand names + remap category paths
│   └── bulk_update_image_alt.py       Live: bulk-set image alt = Brand + Name
│
└── tests/
    ├── test_wc_client.py       WCClient: pagination, retry, dry-run, category validation
    └── test_normalizers.py     SKU normaliser, filename sanitiser
```

---

## Image tools

### Browser editor — zero install for non-technical users

Open `tools/browser/ifiale-image-studio.html` in Chrome. Drag photos in, pick a preset, click Process, download a ZIP.

- Presets driven by `presets.json` — same sizes as the CLI tool
- Auto-trims near-white / transparent edges before padding
- Optional **Cloudinary upload** via unsigned preset (no API secret in browser code)
- Exports **`manifest.csv`** (filename → CDN URL) ready for WooCommerce import

### CLI

```bash
# Resize to 1000×1000 white background
python tools/image_tools.py resize --folder ./raw --preset product

# Custom size
python tools/image_tools.py resize --folder ./raw --size 1200 --bg white --pad 6

# Convert PNG/JPG → WebP (no resize)
python tools/image_tools.py convert --folder ./logos

# Logo → WebP preserving RGBA transparency
python tools/image_tools.py logo --folder ./logos --quality 90

# Always safe to preview first
python tools/image_tools.py resize --folder ./raw --preset product --dry-run
```

### Standard presets

| Preset | Size | Background | Padding | Quality |
|--------|------|------------|---------|---------|
| `product` ⭐ | 1000×1000 | white | 8% | 82 |
| `product800` | 800×800 | white | 8% | 82 |
| `category` | 600×600 | warm card | 10% | 85 |
| `shop` | 500×500 | warm card | 8% | 85 |
| `logo` | 500×500 | transparent | 14% | 90 |

---

## CSV normalizer (Cloudinary / ImgBB)

Downloads images from URLs in a WooCommerce import CSV, re-uploads them to your CDN, and writes an updated CSV. Handles scientific-notation SKUs, progress bar, retries, AVIF/HEIC input.

```bash
# Cloudinary (set env vars from .env.example)
python tools/csv_cloudinary_normalizer.py batch_01.csv --webp

# ImgBB
python tools/csv_imgbb_normalizer.py batch_01.csv --webp --limit 50

# Specific image columns
python tools/csv_cloudinary_normalizer.py batch_01.csv --image-columns "Images,Extra Images"
```

---

## WooCommerce REST client

```python
from shared.wc_client import WCClient, load_env

ck, cs = load_env()           # reads .env or OS environment
client = WCClient(ck, cs)     # rate_limit=0.3s, per_page=100

# Safe pagination
for batch in client.paginate("/wc/v3/products", {"status": "publish"}):
    for product in batch:
        process(product)

# Validate category IDs before any write (prevents silent mis-categorisation)
client.validate_category_ids([651, 652, 653])

# All mutations are dry-run by default — opt in explicitly
client.put("/wc/v3/products/123", {"name": "…"}, dry_run=False)
```

> **Shared hosting note:** The client defaults to 300 ms between calls and never runs concurrent requests. Safe for 1–2 GB shared hosts that degrade under load.

---

## Bulk image alt text

Sets `alt = "{Brand} {Product Name}"` on all product main images that are missing alt text.

```bash
# Preview
python tools/bulk_update_image_alt.py

# Apply
python tools/bulk_update_image_alt.py --no-dry-run --rate-limit 0.4
```

---

## Brand logos

Fetches brand logos from Brandfetch, Wikimedia Commons, and official brand sites. Outputs 500×500 WebP to a local folder.

```bash
python tools/fetch_brand_logos.py
python tools/fetch_brand_logos.py --brands "Korres,Vichy,AHAVA,CeraVe"
python tools/fetch_brand_logos.py --status   # check what's already fetched
```

---

## Environment variables

```bash
cp .env.example .env
```

| Variable | Required by |
|----------|-------------|
| `WC_CONSUMER_KEY` | `wc_client.py`, `bulk_update_image_alt.py` |
| `WC_CONSUMER_SECRET` | `wc_client.py`, `bulk_update_image_alt.py` |
| `CLOUDINARY_CLOUD_NAME` | `csv_cloudinary_normalizer.py` |
| `CLOUDINARY_API_KEY` | `csv_cloudinary_normalizer.py` |
| `CLOUDINARY_API_SECRET` | `csv_cloudinary_normalizer.py` |
| `CLOUDINARY_UPLOAD_PRESET` | browser tool (unsigned only) |
| `IMGBB_API_KEY` | `csv_imgbb_normalizer.py` |
| `BRANDFETCH_API_KEY` | `fetch_brand_logos.py` |

---

## Tests

```bash
pytest tests/ -v
# 35 passed in ~1s
```

Covers: `WCClient` pagination · retry/back-off on 429/5xx · dry-run safety · category-ID validation · rate-limiting · SKU barcode normaliser (Excel scientific-notation edge cases) · filename sanitiser.

---

## Stack

- **Python 3.11+** · Pillow · pandas · openpyxl · requests
- **WooCommerce REST v3** (Basic Auth)
- Image CDN: Cloudinary or ImgBB
- Brand logos: Brandfetch API + Wikimedia Commons

---

## License

MIT — free to use, fork, and adapt for any WooCommerce project.
