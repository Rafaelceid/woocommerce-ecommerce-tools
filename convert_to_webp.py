#!/usr/bin/env python3
"""
Convert all PNG files in a folder to WebP.

Usage:
    python convert_to_webp.py                  # current folder, quality 85
    python convert_to_webp.py --quality 90
    python convert_to_webp.py --folder ./images --quality 80
"""
import os
import argparse
from PIL import Image


def convert_png_to_webp(folder: str = ".", quality: int = 85) -> None:
    count = 0
    errors = 0
    print(f"🚀 Scanning folder: {os.path.abspath(folder)}")

    for filename in sorted(os.listdir(folder)):
        if not filename.lower().endswith(".png"):
            continue
        png_path = os.path.join(folder, filename)
        webp_name = os.path.splitext(filename)[0] + ".webp"
        webp_path = os.path.join(folder, webp_name)
        try:
            with Image.open(png_path) as img:
                img.save(webp_path, "webp", quality=quality)
            print(f"  ✅ {filename} → {webp_name}")
            count += 1
        except Exception as e:
            print(f"  ❌ {filename}: {e}")
            errors += 1

    print(f"\nDone. Converted: {count} | Errors: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch PNG → WebP converter")
    parser.add_argument("--folder", default=".", help="Folder to scan (default: current)")
    parser.add_argument("--quality", type=int, default=85,
                        help="WebP quality 1–100 (default: 85)")
    args = parser.parse_args()
    convert_png_to_webp(folder=args.folder, quality=args.quality)
