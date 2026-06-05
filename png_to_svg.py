#!/usr/bin/env python3
"""
PNG → SVG Converter
--------------------
Requires: pip install vtracer Pillow numpy

Usage:
  python png_to_svg.py                          # όλα τα PNG στον φάκελο
  python png_to_svg.py logo.png                 # συγκεκριμένο αρχείο
  python png_to_svg.py *.png --preset large     # πολλά αρχεία με preset
  python png_to_svg.py logo.png --mode embed    # embed (χωρίς vectorization)
  python png_to_svg.py *.png --out svg_out/     # custom output folder
  python png_to_svg.py *.png --palette brand    # με color snapping
"""

import argparse
import sys
import base64
import tempfile
from pathlib import Path
from PIL import Image
import numpy as np
import xml.etree.ElementTree as ET

# ─────────────────────────────────────────
# Brand palette (προαιρετικό color snapping)
# ─────────────────────────────────────────
PALETTES = {
    "brand": [
        (161, 207, 222),  # #A1CFDE blue
        (47,  79,  90),   # #2F4F5A navy
        (239, 230, 221),  # #EFE6DD cream
        (200, 185, 138),  # #C8B98A muted gold
    ],
}

# ─────────────────────────────────────────
# Presets
# ─────────────────────────────────────────
PRESETS = {
    # Logos / icons — color mode, ΟΧΙ binary
    "icon": {
        "canvas": 1024,
        "padding_ratio": 0.12,
        "colormode": "color",
        "hierarchical": "cutout",
        "filter_speckle": 8,
        "color_precision": 3,
        "layer_difference": 20,
        "corner_threshold": 65,
        "length_threshold": 5.0,
        "path_precision": 2,
    },
    "large": {
        "canvas": 1400,
        "padding_ratio": 0.08,
        "colormode": "color",
        "hierarchical": "cutout",
        "filter_speckle": 4,
        "color_precision": 6,
        "layer_difference": 16,
        "corner_threshold": 60,
        "length_threshold": 4.0,
        "path_precision": 3,
    },
    "thumb": {
        "canvas": 1200,
        "padding_ratio": 0.06,
        "colormode": "color",
        "hierarchical": "stacked",
        "filter_speckle": 4,
        "color_precision": 5,
        "layer_difference": 12,
        "corner_threshold": 55,
        "length_threshold": 3.0,
        "path_precision": 3,
    },
    # Μόνο για B&W logos / σφραγίδες / text
    "binary": {
        "canvas": 1024,
        "padding_ratio": 0.12,
        "colormode": "binary",
        "hierarchical": "cutout",
        "filter_speckle": 8,
        "color_precision": 2,
        "layer_difference": 24,
        "corner_threshold": 70,
        "length_threshold": 5.0,
        "path_precision": 2,
    },
}


def nearest_palette_color_fast(img: Image.Image, palette: list) -> Image.Image:
    """Vectorized palette snap με numpy — γρήγορο."""
    arr = np.array(img, dtype=np.float32)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    palette_arr = np.array(palette, dtype=np.float32)
    diff = rgb[:, :, np.newaxis, :] - palette_arr[np.newaxis, np.newaxis, :, :]
    dist = np.sum(diff ** 2, axis=-1)
    nearest_idx = np.argmin(dist, axis=-1)
    snapped_rgb = palette_arr[nearest_idx]
    result = np.concatenate([snapped_rgb, alpha[:, :, np.newaxis]], axis=-1)
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), "RGBA")


def preprocess_png(
    png_path: Path,
    out_png_path: Path,
    preset_name: str,
    palette_name: str = None,
    alpha_threshold: int = 30,
):
    cfg = PRESETS[preset_name]
    canvas = cfg["canvas"]
    padding_ratio = cfg["padding_ratio"]

    img = Image.open(png_path).convert("RGBA")

    # Crop στο visible content
    alpha_ch = img.getchannel("A")
    bbox = alpha_ch.point(lambda a: 255 if a > alpha_threshold else 0).getbbox()
    if bbox:
        img = img.crop(bbox)

    # Palette snap (μόνο αν ζητηθεί ρητά)
    if palette_name and palette_name in PALETTES:
        img = nearest_palette_color_fast(img, PALETTES[palette_name])

    # Resize
    inner = int(canvas * (1 - 2 * padding_ratio))
    scale = min(inner / max(img.width, 1), inner / max(img.height, 1))
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center σε τετράγωνο canvas
    square = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    x = (canvas - img.width) // 2
    y = (canvas - img.height) // 2
    square.alpha_composite(img, (x, y))
    square.save(out_png_path)


def embed_png_in_svg(png_path: Path, out_path: Path):
    with Image.open(png_path) as img:
        width, height = img.size
    with open(png_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    svg = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
        f'  <image href="data:image/png;base64,{b64}" '
        f'x="0" y="0" width="{width}" height="{height}"/>\n'
        f'</svg>'
    )
    out_path.write_text(svg, encoding="utf-8")
    print(f"  [embed]  {png_path.name} → {out_path.name}")


def vectorize_png(png_path: Path, out_path: Path, preset_name: str):
    import vtracer
    cfg = PRESETS[preset_name]
    vtracer.convert_image_to_svg_py(
        str(png_path),
        str(out_path),
        colormode=cfg["colormode"],
        hierarchical=cfg["hierarchical"],
        mode="spline",
        filter_speckle=cfg["filter_speckle"],
        color_precision=cfg["color_precision"],
        layer_difference=cfg["layer_difference"],
        corner_threshold=cfg["corner_threshold"],
        length_threshold=cfg["length_threshold"],
        max_iterations=10,
        splice_threshold=45,
        path_precision=cfg["path_precision"],
    )
    print(f"  [vector] {png_path.name} → {out_path.name}  (preset={preset_name})")


def normalize_svg_viewbox(svg_path: Path):
    """Προσθέτει viewBox αν λείπει — ΔΕΝ αφαιρεί width/height."""
    try:
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        tree = ET.parse(svg_path)
        root = tree.getroot()
        w = root.get("width", "")
        h = root.get("height", "")
        if "viewBox" not in root.attrib and w and h:
            try:
                root.set("viewBox", f"0 0 {int(float(w))} {int(float(h))}")
            except ValueError:
                pass
        root.set("preserveAspectRatio", "xMidYMid meet")
        tree.write(svg_path, encoding="utf-8", xml_declaration=True)
    except Exception as e:
        print(f"  [warn] normalize_svg: {svg_path.name}: {e}")


def main():
    parser = argparse.ArgumentParser(description="PNG → SVG Converter", epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*", help="PNG files (κενό = όλα στον φάκελο)")
    parser.add_argument("--mode", choices=["vector", "embed"], default="vector")
    parser.add_argument("--preset", choices=list(PRESETS.keys()), default="icon",
                        help="icon | large | thumb | binary")
    parser.add_argument("--palette", choices=list(PALETTES.keys()), default=None,
                        help="Προαιρετικό color snap (π.χ. --palette brand)")
    parser.add_argument("--out", default=None, help="Output folder")
    args = parser.parse_args()

    if not args.inputs:
        script_dir = Path(__file__).parent
        args.inputs = [str(p) for p in sorted(script_dir.glob("*.png"))]
        if not args.inputs:
            print(f"Δεν βρέθηκαν PNG στον φάκελο: {script_dir}")
            sys.exit(1)
        print(f"Auto-detected {len(args.inputs)} PNG(s)\n")

    png_files = []
    for pattern in args.inputs:
        p = Path(pattern)
        if p.is_file():
            png_files.append(p)
        else:
            png_files.extend(f for f in Path(".").glob(pattern) if f.suffix.lower() == ".png")
    png_files = list(dict.fromkeys(png_files))

    if not png_files:
        print("No PNG files found.")
        sys.exit(1)

    if args.mode == "vector":
        try:
            import vtracer  # noqa
        except ImportError:
            print("ERROR: pip install vtracer")
            sys.exit(1)

    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Converting {len(png_files)} file(s) | mode={args.mode} | preset={args.preset}\n")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for png_path in png_files:
            if png_path.suffix.lower() != ".png":
                continue
            final_out_dir = out_dir if out_dir else png_path.parent
            final_out_path = final_out_dir / (png_path.stem + ".svg")
            try:
                if args.mode == "embed":
                    embed_png_in_svg(png_path, final_out_path)
                else:
                    preprocessed = tmp_dir / png_path.name
                    preprocess_png(png_path, preprocessed, args.preset, args.palette)
                    vectorize_png(preprocessed, final_out_path, args.preset)
                    normalize_svg_viewbox(final_out_path)
            except Exception as e:
                print(f"  [ERROR] {png_path.name}: {e}")

    print("\nDone! ✓")


if __name__ == "__main__":
    main()