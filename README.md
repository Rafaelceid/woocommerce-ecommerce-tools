# WooCommerce E-commerce Tools

[![CI](https://github.com/Rafaelceid/woocommerce-ecommerce-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/Rafaelceid/woocommerce-ecommerce-tools/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-Image%20Studio-turquoise)](https://rafaelceid.github.io/woocommerce-ecommerce-tools/)

A production-ready toolkit for WooCommerce store management — built during a real freelance engagement. Covers image processing, CSV data normalisation, and a zero-install browser tool for preparing shop-ready product photos.

---

## Live demo — Image Studio

**[rafaelceid.github.io/woocommerce-ecommerce-tools](https://rafaelceid.github.io/woocommerce-ecommerce-tools/)**

Drop any product photos in, get back uniform WebP images at WooCommerce-standard sizes. No install, no upload, no account — runs entirely in the browser.

---

## What's inside

| Tool | Type | Description |
|---|---|---|
| `tools/image_tools.py` | CLI | Batch resize, convert, and optimise images with presets from `presets.json` |
| `shared/wc_client.py` | Library | WooCommerce REST client — pagination, retry/backoff, rate-limit, `--dry-run` |
| `tools/csv_cloudinary_normalizer.py` | CLI | Normalise a CSV of image URLs via Cloudinary transformations |
| `tools/csv_imgbb_normalizer.py` | CLI | Upload images from a CSV to ImgBB and rewrite URLs |
| `studio/index.html` | Browser | Zero-install image processor + optional Cloudinary upload + manifest.csv |

---

## Quick start

```bash
git clone https://github.com/Rafaelceid/woocommerce-ecommerce-tools.git
cd woocommerce-ecommerce-tools
pip install -r requirements.txt
cp .env.example .env   # fill in your WooCommerce / Cloudinary keys
```

### Image tools (CLI)

```bash
# Resize a folder of photos to the recommended product preset (1000×1000 WebP)
python tools/image_tools.py resize ./raw ./output --preset product

# Convert all PNGs to WebP, lossless
python tools/image_tools.py convert ./raw ./output --lossless

# Trim + centre a logo on a transparent background
python tools/image_tools.py logo ./logo.png ./output --size 500
```

### WooCommerce client

```python
from shared.wc_client import WCClient, load_env

env = load_env()
wc  = WCClient(env["WC_URL"], env["WC_KEY"], env["WC_SECRET"])

# Always dry-run by default — pass dry_run=False to write
products = wc.get_all("products", params={"status": "publish"})
```

### CSV normalisers

```bash
python tools/csv_cloudinary_normalizer.py products.csv --col image_url --out products_cdn.csv
python tools/csv_imgbb_normalizer.py products.csv --col image_url --out products_imgbb.csv
```

---

## Image presets (`presets.json`)

| Preset | Size | Use for |
|---|---|---|
| `product` | 1000×1000 | Main product image (recommended) |
| `product800` | 800×800 | Secondary product images |
| `category` | 600×600 | Category thumbnails |
| `shop` | 500×500 | Shop/archive page thumbnails |
| `logo` | 500×500 | Brand logos (transparent background) |

Both the CLI tool and the browser Studio read from this same file — so you always get identical output regardless of who processes the images.

---

## Environment variables

Copy `.env.example` to `.env` and fill in your credentials:

```env
WC_URL=https://your-store.com
WC_KEY=ck_...
WC_SECRET=cs_...
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
IMGBB_API_KEY=...
```

---

## Running tests

```bash
pip install pytest pytest-mock
pytest tests/ -v
```

35 tests cover the WooCommerce client (pagination, retry, rate-limit, dry-run) and CSV normalisers (SKU sanitisation, filename edge cases).

---

## Project structure

```
.
├── shared/
│   └── wc_client.py       # WooCommerce REST client
├── tools/
│   ├── image_tools.py     # Batch image CLI
│   ├── csv_cloudinary_normalizer.py
│   └── csv_imgbb_normalizer.py
├── studio/
│   └── index.html         # Browser-based Image Studio (GitHub Pages)
├── tests/
│   ├── test_wc_client.py
│   └── test_normalizers.py
├── presets.json            # Single source of truth for image sizes
├── .env.example
├── requirements.txt
└── LICENSE
```

---

## About

Built as part of a freelance WooCommerce store setup project. The goal was a toolkit that any developer or store owner could pick up and use without reinventing common WooCommerce workflows.

MIT License — feel free to use, fork, or adapt.
