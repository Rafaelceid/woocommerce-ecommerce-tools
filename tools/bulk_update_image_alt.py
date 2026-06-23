"""Bulk-set main image alt text to '{Brand} {Product Name}' via WooCommerce REST API.

Only sets alt on products where the main image has no existing alt text.
Skips products with no image or no brand.

Usage
-----
    # Dry-run (default — shows what would change, touches nothing)
    python tools/bulk_update_image_alt.py

    # Apply changes
    python tools/bulk_update_image_alt.py --no-dry-run

    # Limit for testing
    python tools/bulk_update_image_alt.py --no-dry-run --limit 50

    # Force-overwrite existing alt text too
    python tools/bulk_update_image_alt.py --no-dry-run --overwrite
"""
from __future__ import annotations

import argparse
import html
import logging
import sys
from pathlib import Path

# Shared client is one level up
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.wc_client import WCClient, load_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bulk_update_image_alt")

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "products" / "exports" / "IMAGE-ALT-BULK-UPDATE-LOG.txt"
MAX_ALT = 125


def norm(s: str) -> str:
    return html.unescape((s or "").strip())


def build_alt(brand: str, name: str) -> str:
    """Build '{Brand} {name}' alt text, truncated to MAX_ALT chars."""
    alt = f"{brand} {name}".strip()
    if len(alt) <= MAX_ALT:
        return alt
    return alt[: MAX_ALT - 1].rstrip() + "…"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk-set WooCommerce product image alt text.")
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Apply changes (default: dry-run only)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Process at most N products (0 = all)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing alt text")
    parser.add_argument("--rate-limit", type=float, default=0.3, help="Seconds between API calls (default: 0.3)")
    args = parser.parse_args()

    dry_run = not args.no_dry_run
    if dry_run:
        logger.info("[DRY RUN] No changes will be written. Pass --no-dry-run to apply.")

    try:
        ck, cs = load_env()
    except SystemExit as exc:
        logger.error("%s", exc)
        sys.exit(1)

    client = WCClient(ck, cs, rate_limit=args.rate_limit)

    stats: dict[str, int] = {
        "processed": 0,
        "updated": 0,
        "skip_has_alt": 0,
        "skip_no_image": 0,
        "skip_no_brand": 0,
        "errors": 0,
    }
    error_samples: list[str] = []
    lines: list[str] = [
        "=" * 80,
        f"BULK IMAGE ALT TEXT UPDATE  ({'DRY RUN' if dry_run else 'LIVE'})",
        f"Rule: alt = '{{Brand}} {{Product Name}}' (max {MAX_ALT} chars)",
        "=" * 80,
        "",
    ]

    def log(msg: str) -> None:
        logger.info(msg)
        lines.append(msg)

    limit = args.limit
    fetched = 0

    try:
        for batch in client.paginate("/wc/v3/products", {"status": "any"}):
            for p in batch:
                if limit and fetched >= limit:
                    break
                fetched += 1
                stats["processed"] += 1
                pid = p["id"]
                sku = (p.get("sku") or "").strip() or f"id:{pid}"
                name = norm(p.get("name") or "")

                images = p.get("images") or []
                if not images:
                    stats["skip_no_image"] += 1
                    continue

                main_img = images[0]
                existing_alt = norm(main_img.get("alt") or "")
                if existing_alt and not args.overwrite:
                    stats["skip_has_alt"] += 1
                    continue

                brands = p.get("brands") or []
                brand = ""
                for attr in p.get("attributes") or []:
                    if (attr.get("name") or "").strip().lower() == "brand":
                        opts = attr.get("options") or []
                        brand = opts[0].strip() if opts else ""
                        break
                if not brand and brands:
                    brand = norm(brands[0].get("name") or "")
                if not brand:
                    stats["skip_no_brand"] += 1
                    continue

                new_alt = build_alt(brand, name)

                try:
                    updated_images = [dict(img) for img in images]
                    updated_images[0] = {**updated_images[0], "alt": new_alt}
                    result = client.put(
                        f"/wc/v3/products/{pid}",
                        {"images": [{"id": img["id"], "alt": img.get("alt", "")} for img in updated_images]},
                        dry_run=dry_run,
                    )
                    if dry_run:
                        log(f"  [DRY] SKU {sku} id={pid} → alt={new_alt!r}")
                        stats["updated"] += 1
                    else:
                        verified = norm((result.get("images") or [{}])[0].get("alt") or "")
                        if verified == new_alt or verified.replace("…", "") == new_alt.replace("…", ""):
                            stats["updated"] += 1
                            log(f"  ✓ SKU {sku} id={pid} | alt={new_alt!r}")
                        else:
                            stats["errors"] += 1
                            msg = f"  ✗ SKU {sku} id={pid} | verify mismatch: expected={new_alt!r} got={verified!r}"
                            log(msg)
                            if len(error_samples) < 20:
                                error_samples.append(msg)
                except Exception as exc:
                    stats["errors"] += 1
                    msg = f"  ✗ SKU {sku} id={pid}: {exc}"
                    log(msg)
                    if len(error_samples) < 20:
                        error_samples.append(msg)

                if stats["processed"] % 100 == 0:
                    log(
                        f"  … {stats['processed']} processed | updated={stats['updated']} "
                        f"skip_alt={stats['skip_has_alt']} skip_no_img={stats['skip_no_image']} "
                        f"skip_no_brand={stats['skip_no_brand']} errors={stats['errors']}"
                    )

            if limit and fetched >= limit:
                break

    except KeyboardInterrupt:
        log("\n[Interrupted by user]")

    log("")
    log("=" * 80)
    log(f"SUMMARY  ({'DRY RUN' if dry_run else 'LIVE'})")
    log(f"  Total processed:     {stats['processed']}")
    log(f"  Updated:             {stats['updated']}")
    log(f"  Skipped (has alt):   {stats['skip_has_alt']}")
    log(f"  Skipped (no image):  {stats['skip_no_image']}")
    log(f"  Skipped (no brand):  {stats['skip_no_brand']}")
    log(f"  Errors:              {stats['errors']}")
    log("=" * 80)

    if error_samples:
        log("")
        log("ERROR SAMPLES:")
        for s in error_samples:
            log(f"  {s}")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Full log: %s", LOG_PATH)


if __name__ == "__main__":
    main()
