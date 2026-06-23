"""Ifiale image tools — single CLI with argparse subcommands.

Subcommands
-----------
resize      Resize images to a square, add padding, export as WebP.
            Reads preset defaults from ``presets.json`` (project root).
convert     Convert PNG/JPG/JPEG → WebP in-place (no resize, no crop).
logo        1:1 PNG/JPG → WebP preserving RGBA transparency (for logos/icons).

All subcommands:
- Accept ``--preset`` to auto-fill size/quality from ``presets.json``
- Log via Python ``logging`` (no bare ``print`` on hot paths)
- Exit with code 0 on success, 1 on any error

Usage examples
--------------
    # Resize product images using the 'product' preset (1000×1000, white bg)
    python tools/image_tools.py resize --folder ./raw --preset product

    # Resize using custom size
    python tools/image_tools.py resize --folder ./raw --size 800 --bg white

    # Convert only (no resize)
    python tools/image_tools.py convert --folder ./raw --quality 85

    # Logo conversion (preserves transparency)
    python tools/image_tools.py logo --folder ./logos --quality 90

    # Dry-run (shows what would be written, no files created)
    python tools/image_tools.py resize --folder ./raw --preset product --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("image_tools")

# ---------------------------------------------------------------------------
# Preset loading
# ---------------------------------------------------------------------------

_PRESETS_FILE = Path(__file__).resolve().parents[1] / "presets.json"
_PRESETS_CACHE: dict[str, Any] | None = None


def _load_presets() -> dict[str, Any]:
    global _PRESETS_CACHE
    if _PRESETS_CACHE is None:
        if _PRESETS_FILE.exists():
            _PRESETS_CACHE = json.loads(_PRESETS_FILE.read_text(encoding="utf-8"))
        else:
            logger.warning("presets.json not found at %s – using built-in defaults", _PRESETS_FILE)
            _PRESETS_CACHE = {}
    return _PRESETS_CACHE


def get_preset(name: str) -> dict[str, Any]:
    """Return a preset dict by name, or raise ValueError if unknown."""
    presets = _load_presets().get("presets", {})
    if name not in presets:
        available = ", ".join(presets) or "(none)"
        raise ValueError(f"Unknown preset '{name}'. Available: {available}")
    return presets[name]


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
_BG_COLORS: dict[str, str] = {"white": "#FFFFFF", "card": "#FBF8F3"}


def _iter_images(folder: Path) -> list[Path]:
    """Return sorted list of image files in *folder* (non-recursive)."""
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in _IMAGE_EXTS and p.is_file())


def _bg_color(name: str) -> tuple[int, int, int]:
    presets = _load_presets()
    hex_color = presets.get("bg_colors", {}).get(name, "#FFFFFF")
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _load_rgba(path: Path) -> Image.Image:
    """Open image and convert to RGBA for consistent compositing."""
    return Image.open(path).convert("RGBA")


def _compute_trim_box(img: Image.Image, threshold: int = 244) -> tuple[int, int, int, int] | None:
    """Return (left, upper, right, lower) bounding box of non-background pixels.

    Background is defined as near-white (all channels ≥ threshold) or
    near-transparent (alpha < 12).  Returns ``None`` if image is all background.
    """
    data = img.load()
    w, h = img.size
    min_x, min_y = w, h
    max_x, max_y = -1, -1
    for y in range(h):
        for x in range(w):
            r, g, b, a = data[x, y]  # type: ignore[index]
            if a < 12 or (r >= threshold and g >= threshold and b >= threshold):
                continue
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
    if max_x < 0:
        return None
    margin = max(1, round(max(w, h) * 0.015))
    return (
        max(0, min_x - margin),
        max(0, min_y - margin),
        min(w, max_x + margin + 1),
        min(h, max_y + margin + 1),
    )


def _resize_to_square(
    img: Image.Image,
    size: int,
    padding_pct: float,
    bg_name: str,
    do_trim: bool,
) -> Image.Image:
    """Pad and resize *img* into a square canvas of *size*×*size* pixels."""
    if do_trim:
        box = _compute_trim_box(img)
        if box:
            img = img.crop(box)

    pad_px = round(size * padding_pct / 100)
    inner = size - pad_px * 2

    iw, ih = img.size
    scale = min(inner / iw, inner / ih)
    nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)

    if bg_name == "transparent":
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    else:
        r, g, b = _bg_color(bg_name)
        canvas = Image.new("RGBA", (size, size), (r, g, b, 255))

    dx = (size - nw) // 2
    dy = (size - nh) // 2
    canvas.paste(resized, (dx, dy), mask=resized.split()[3])
    return canvas


# ---------------------------------------------------------------------------
# Subcommand: resize
# ---------------------------------------------------------------------------

def cmd_resize(args: argparse.Namespace) -> int:
    """Resize images to a square, add padding, export as WebP."""
    folder = Path(args.folder)
    if not folder.is_dir():
        logger.error("Folder not found: %s", folder)
        return 1

    # Resolve settings: preset overrides defaults, CLI flags override preset
    size: int = 1000
    bg: str = "white"
    pad: float = 8.0
    quality: int = 82
    do_trim: bool = True

    if args.preset:
        try:
            p = get_preset(args.preset)
            size = p.get("size", size)
            bg = p.get("bg", bg)
            pad = float(p.get("pad", pad))
            quality = int(p.get("quality", quality))
        except ValueError as exc:
            logger.error("%s", exc)
            return 1

    if args.size is not None:
        size = args.size
    if args.bg is not None:
        bg = args.bg
    if args.pad is not None:
        pad = float(args.pad)
    if args.quality is not None:
        quality = args.quality
    if args.no_trim:
        do_trim = False

    out_dir = folder / args.output_folder
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    images = _iter_images(folder)
    if not images:
        logger.warning("No images found in %s", folder)
        return 0

    logger.info(
        "resize: %d images | %d×%d | bg=%s | pad=%g%% | quality=%d | trim=%s%s",
        len(images), size, size, bg, pad, quality, do_trim,
        " [DRY RUN]" if args.dry_run else "",
    )

    ok = fail = 0
    for src in images:
        if src.parent == out_dir:
            continue
        stem = (args.prefix or "") + src.stem
        dest = out_dir / (stem + ".webp")
        try:
            img = _load_rgba(src)
            canvas = _resize_to_square(img, size, pad, bg, do_trim)
            if bg == "transparent":
                mode, fmt_kwargs = "RGBA", {}
            else:
                mode = "RGB"
                fmt_kwargs = {}
            out_img = canvas.convert(mode)
            if args.dry_run:
                logger.info("  [DRY] %s → %s", src.name, dest.name)
            else:
                out_img.save(dest, "WEBP", quality=quality, method=6, **fmt_kwargs)
                kb_in = src.stat().st_size // 1024
                kb_out = dest.stat().st_size // 1024
                logger.info("  ✓ %s → %s (%dKB → %dKB)", src.name, dest.name, kb_in, kb_out)
            ok += 1
        except Exception as exc:
            logger.error("  ✗ %s: %s", src.name, exc)
            fail += 1

    logger.info("Done. ok=%d fail=%d", ok, fail)
    return 0 if fail == 0 else 1


# ---------------------------------------------------------------------------
# Subcommand: convert
# ---------------------------------------------------------------------------

def cmd_convert(args: argparse.Namespace) -> int:
    """Convert PNG/JPG → WebP (no resize, no crop, drops alpha by compositing on white)."""
    folder = Path(args.folder)
    if not folder.is_dir():
        logger.error("Folder not found: %s", folder)
        return 1

    quality: int = args.quality if args.quality is not None else 85
    out_dir = folder if args.in_place else folder / "webp"
    if not args.dry_run and not args.in_place:
        out_dir.mkdir(parents=True, exist_ok=True)

    exts = {".png", ".jpg", ".jpeg"}
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in exts and p.is_file())
    if not images:
        logger.warning("No PNG/JPG images found in %s", folder)
        return 0

    logger.info("convert: %d images | quality=%d%s", len(images), quality, " [DRY RUN]" if args.dry_run else "")
    ok = fail = 0
    for src in images:
        dest = (folder if args.in_place else out_dir) / (src.stem + ".webp")
        try:
            if args.dry_run:
                logger.info("  [DRY] %s → %s", src.name, dest.name)
            else:
                with Image.open(src) as img:
                    rgb = img.convert("RGB")
                    rgb.save(dest, "WEBP", quality=quality, method=6)
                logger.info("  ✓ %s → %s", src.name, dest.name)
            ok += 1
        except Exception as exc:
            logger.error("  ✗ %s: %s", src.name, exc)
            fail += 1

    logger.info("Done. ok=%d fail=%d", ok, fail)
    return 0 if fail == 0 else 1


# ---------------------------------------------------------------------------
# Subcommand: logo
# ---------------------------------------------------------------------------

def cmd_logo(args: argparse.Namespace) -> int:
    """Convert PNG/JPG → WebP preserving RGBA transparency (no resize)."""
    folder = Path(args.folder)
    if not folder.is_dir():
        logger.error("Folder not found: %s", folder)
        return 1

    quality: int = args.quality if args.quality is not None else 90
    out_dir = folder / "webp"
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    exts = {".png", ".jpg", ".jpeg"}
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in exts and p.is_file())
    if not images:
        logger.warning("No PNG/JPG images found in %s", folder)
        return 0

    logger.info("logo: %d images | quality=%d%s", len(images), quality, " [DRY RUN]" if args.dry_run else "")
    ok = fail = 0
    for src in images:
        dest = out_dir / (src.stem + ".webp")
        try:
            if args.dry_run:
                logger.info("  [DRY] %s → %s", src.name, dest.name)
            else:
                with Image.open(src) as img:
                    img.save(dest, "WEBP", quality=quality, method=6)
                logger.info("  ✓ %s → %s", src.name, dest.name)
            ok += 1
        except Exception as exc:
            logger.error("  ✗ %s: %s", src.name, exc)
            fail += 1

    logger.info("Done. ok=%d fail=%d", ok, fail)
    return 0 if fail == 0 else 1


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image_tools",
        description="Ifiale image tools — resize, convert, logo WebP subcommands.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- resize ----
    p_resize = sub.add_parser("resize", help="Resize to square + padding, export WebP")
    p_resize.add_argument("--folder", default=".", help="Input folder (default: current dir)")
    p_resize.add_argument(
        "--preset",
        metavar="NAME",
        help="Preset name from presets.json (product, product800, category, shop, logo)",
    )
    p_resize.add_argument("--size", type=int, help="Output square size in px (overrides preset)")
    p_resize.add_argument(
        "--bg",
        choices=["white", "card", "transparent"],
        help="Background colour (overrides preset)",
    )
    p_resize.add_argument("--pad", type=float, help="Padding as %% of canvas (overrides preset)")
    p_resize.add_argument("--quality", type=int, help="WebP quality 1-100 (overrides preset)")
    p_resize.add_argument("--no-trim", action="store_true", help="Disable auto background trim")
    p_resize.add_argument("--prefix", default="", help="Filename prefix for output files")
    p_resize.add_argument(
        "--output-folder", default="webp", help="Output subfolder name (default: webp)"
    )
    p_resize.add_argument("--dry-run", action="store_true", help="Log actions without writing files")
    p_resize.set_defaults(func=cmd_resize)

    # ---- convert ----
    p_convert = sub.add_parser("convert", help="Convert PNG/JPG to WebP (no resize)")
    p_convert.add_argument("--folder", default=".", help="Input folder")
    p_convert.add_argument("--quality", type=int, help="WebP quality 1-100 (default: 85)")
    p_convert.add_argument("--in-place", action="store_true", help="Save alongside source files")
    p_convert.add_argument("--dry-run", action="store_true", help="Log without writing")
    p_convert.set_defaults(func=cmd_convert)

    # ---- logo ----
    p_logo = sub.add_parser("logo", help="Convert PNG/JPG to WebP preserving transparency")
    p_logo.add_argument("--folder", default=".", help="Input folder")
    p_logo.add_argument("--quality", type=int, help="WebP quality 1-100 (default: 90)")
    p_logo.add_argument("--dry-run", action="store_true", help="Log without writing")
    p_logo.set_defaults(func=cmd_logo)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
