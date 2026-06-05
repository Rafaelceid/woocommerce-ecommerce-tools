#!/usr/bin/env python3
"""
1:1 PNG/JPG → WebP converter — preserves transparency, no resize, no crop.
Ideal for logos and icons where transparency must be kept intact.

Output goes to a ./webp/ subfolder.

Usage:
    python convert_to_webp_lossless.py
    python convert_to_webp_lossless.py --folder ./logos --quality 90
"""
import os
import argparse
from PIL import Image


def convert_lossless(folder: str = ".", quality: int = 90) -> None:
    output_folder = os.path.join(folder, "webp")
    os.makedirs(output_folder, exist_ok=True)
    count = 0

    for filename in sorted(os.listdir(folder)):
        if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        img_path = os.path.join(folder, filename)
        new_name = os.path.splitext(filename)[0] + ".webp"
        save_path = os.path.join(output_folder, new_name)
        try:
            with Image.open(img_path) as img:
                # Do NOT convert to RGB — preserves RGBA transparency for PNGs
                img.save(save_path, "webp", quality=quality, method=6)
            print(f"  ✅ {filename} → webp/{new_name}")
            count += 1
        except Exception as e:
            print(f"  ❌ {filename}: {e}")

    print(f"\nDone. Converted: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="1:1 image → WebP converter (preserves transparency)"
    )
    parser.add_argument("--folder", default=".", help="Input folder (default: current)")
    parser.add_argument("--quality", type=int, default=90, help="WebP quality 1–100 (default: 90)")
    args = parser.parse_args()
    convert_lossless(folder=args.folder, quality=args.quality)
