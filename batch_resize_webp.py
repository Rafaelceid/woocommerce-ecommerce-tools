#!/usr/bin/env python3
"""
Batch resize images and convert to WebP.
Useful for standardising product thumbnails before upload.

Usage:
    python batch_resize_webp.py                           # 800x800, quality 80
    python batch_resize_webp.py --width 600 --height 600
    python batch_resize_webp.py --folder ./images --width 1000 --height 1000 --quality 85
    python batch_resize_webp.py --no-resize               # convert only, no resize
"""
import os
import argparse
from PIL import Image


def batch_resize_webp(
    folder: str = ".",
    width: int = 800,
    height: int = 800,
    quality: int = 80,
    do_resize: bool = True,
) -> None:
    output_folder = os.path.join(folder, "webp")
    os.makedirs(output_folder, exist_ok=True)
    count = 0

    print(f"📁 Input:  {os.path.abspath(folder)}")
    print(f"📁 Output: {os.path.abspath(output_folder)}")
    if do_resize:
        print(f"📐 Resize: {width}x{height}  |  Quality: {quality}")
    else:
        print(f"📐 No resize  |  Quality: {quality}")

    for filename in sorted(os.listdir(folder)):
        if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        img_path = os.path.join(folder, filename)
        new_name = os.path.splitext(filename)[0] + ".webp"
        save_path = os.path.join(output_folder, new_name)
        try:
            with Image.open(img_path) as img:
                img = img.convert("RGB")  # drop alpha for JPEG-safe output
                if do_resize:
                    img = img.resize((width, height), Image.LANCZOS)
                img.save(save_path, "webp", quality=quality, method=6)
            print(f"  ✅ {filename} → webp/{new_name}")
            count += 1
        except Exception as e:
            print(f"  ❌ {filename}: {e}")

    print(f"\nDone. Converted: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch resize + WebP converter")
    parser.add_argument("--folder",   default=".", help="Input folder (default: current)")
    parser.add_argument("--width",    type=int, default=800)
    parser.add_argument("--height",   type=int, default=800)
    parser.add_argument("--quality",  type=int, default=80, help="WebP quality (default: 80)")
    parser.add_argument("--no-resize", action="store_true", help="Skip resize, convert only")
    args = parser.parse_args()
    batch_resize_webp(
        folder=args.folder, width=args.width, height=args.height,
        quality=args.quality, do_resize=not args.no_resize
    )
