# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) — Versioning: [SemVer](https://semver.org/).

## [1.0.0] — 2026-06-23

### Added
- `shared/wc_client.py` — production-grade WooCommerce REST client with `per_page=100` pagination, exponential-backoff retry on 429/5xx, configurable rate-limiting (300 ms default), `dry_run` guard on all write operations, and category ID validation
- `tools/image_tools.py` — unified CLI (`resize`, `convert`, `logo` subcommands) replacing three separate ad-hoc scripts; reads settings from `presets.json`
- `presets.json` — single source of truth for standard image output sizes (`product`, `product800`, `category`, `shop`, `logo`), shared by CLI and browser tool
- `studio/index.html` — zero-install browser-based Image Studio: client-side WebP conversion, smart background trim, uniform padding, optional Cloudinary unsigned upload, manifest CSV export; deployed to GitHub Pages
- `tools/csv_cloudinary_normalizer.py` — bulk Cloudinary URL rewriter for WooCommerce CSV imports
- `tools/csv_imgbb_normalizer.py` — bulk ImgBB uploader with CSV output
- `tests/test_wc_client.py` + `tests/test_normalizers.py` — 35 pytest tests covering pagination, retry, rate-limit, dry-run, SKU normalisation, filename sanitisation
- GitHub Actions CI (Python 3.11 + 3.12, ruff lint)
- GitHub Actions Pages deploy — tool live at `https://rafaelceid.github.io/woocommerce-ecommerce-tools/`
- MIT License, `.env.example`, `requirements.txt`

## [0.1.0] — 2025-01-01

### Added
- Initial collection of ad-hoc WooCommerce scripts
