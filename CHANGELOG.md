# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — 2026-06-23

### Added

- **`shared/wc_client.py`** — production-grade WooCommerce REST v3 client
  - Per-page=100 automatic pagination
  - Exponential back-off on 429 / 5xx (up to 5 retries)
  - Configurable rate-limit (default 300 ms — safe for shared hosting)
  - `validate_category_ids()` pre-write guard
  - `dry_run=True` default on all mutations
  - Auto-discovers `.env` by walking up the directory tree

- **`tools/image_tools.py`** — unified image CLI (replaces 3 separate scripts)
  - `resize` — square canvas + padding + background + optional trim, WebP output
  - `convert` — PNG/JPG → WebP, no resize
  - `logo` — 1:1 WebP preserving RGBA transparency
  - All subcommands read `presets.json` for standard sizes

- **`presets.json`** — single source of truth for image output sizes
  - `product` 1000×1000, `product800` 800×800, `category` 600×600, `shop` 500×500, `logo` 500×500
  - Read by both `image_tools.py` (CLI) and `ifiale-image-studio.html` (browser)

- **`tools/browser/ifiale-image-studio.html`** — zero-install browser image editor
  - Preset chips driven by `presets.json` embedded data
  - Optional Cloudinary upload via unsigned preset (no API secret in browser)
  - Exports `manifest.csv` (filename → CDN URL) for WooCommerce import
  - Full offline operation — photos never leave the computer unless Cloudinary is enabled

- **`tools/bulk_update_image_alt.py`** — bulk-set product image alt text
  - `--no-dry-run` required to apply changes (safe default)
  - `--overwrite` flag for re-running on already-set alt text

- **`tests/test_wc_client.py`** — 15 tests for WCClient
  - Pagination, retry/back-off, dry-run, category validation, rate-limiting

- **`tests/test_normalizers.py`** — 20 tests for data utilities
  - SKU barcode normaliser (scientific notation, float suffix, None, empty)
  - Filename sanitiser (Unicode, length, special chars)

- **`.github/workflows/ci.yml`** — GitHub Actions CI
  - pytest on Python 3.11 + 3.12
  - ruff lint check

### Changed

- `csv_cloudinary_normalizer_v2.py` → `tools/csv_cloudinary_normalizer.py` (organised into `tools/`)
- `csv_imgbb_normalizer_v3.py` → `tools/csv_imgbb_normalizer.py`
- `fetch_brand_logos.py` → `tools/fetch_brand_logos.py`
- `png_to_svg.py` → `tools/png_to_svg.py`
- `process_taxonomy.py` → `tools/process_taxonomy.py`

### Removed

- `batch_resize_webp.py` — functionality merged into `tools/image_tools.py resize`
- `convert_to_webp.py` — merged into `tools/image_tools.py convert`
- `convert_to_webp_lossless.py` — merged into `tools/image_tools.py logo`
- `debug_brandfetch.py` — one-off debug helper, not needed in toolkit

---

## [0.1.0] — 2026-06-01

### Added

- Initial scripts: `batch_resize_webp.py`, `convert_to_webp.py`, `convert_to_webp_lossless.py`
- `csv_cloudinary_normalizer_v2.py`, `csv_imgbb_normalizer_v3.py`
- `fetch_brand_logos.py`, `png_to_svg.py`, `process_taxonomy.py`
