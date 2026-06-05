# 🛍️ WooCommerce / Woodmart E-commerce Toolkit

A collection of Python scripts built for a **WooCommerce + Woodmart** pharmacy e-commerce project in Cyprus. Covers product image processing, brand logo fetching, CSV batch preparation, and taxonomy cleanup.

---

## 📦 Scripts

| Script | Purpose |
|---|---|
| `csv_imgbb_normalizer_v3.py` | Download product images → re-upload to **ImgBB** → write updated WC import CSV |
| `csv_cloudinary_normalizer_v2.py` | Same as above but uploads to **Cloudinary** |
| `fetch_brand_logos.py` | Fetch brand logos from curated sources (Wikimedia, official sites) → 500×500 WebP |
| `png_to_svg.py` | Convert PNG logos to vector SVG via `vtracer` (with alpha trim + centering) |
| `convert_to_webp.py` | Batch convert PNG files to WebP |
| `convert_to_webp_lossless.py` | 1:1 conversion to WebP — preserves transparency, no resize. Best for logos. |
| `batch_resize_webp.py` | Resize images to a target resolution + convert to WebP |
| `process_taxonomy.py` | Clean brand names + remap WooCommerce category paths from an older workbook |
| `debug_brandfetch.py` | Debug helper: inspect raw Brandfetch API response for any brand |

---

## 🚀 Quick Start

```bash
pip install -r requirements.txt
```

### Image upload to ImgBB

```bash
export IMGBB_API_KEY=your_key_here
python csv_imgbb_normalizer_v3.py batch_01.csv --webp
```

### Image upload to Cloudinary

```bash
export CLOUDINARY_CLOUD_NAME=your_cloud_name
export CLOUDINARY_API_KEY=your_api_key
export CLOUDINARY_API_SECRET=your_api_secret
python csv_cloudinary_normalizer_v2.py batch_01.csv --webp --skip-cloudinary
```

### Fetch brand logos

```bash
python fetch_brand_logos.py
python fetch_brand_logos.py --brands "Korres,Vichy,AHAVA"
python fetch_brand_logos.py --status
```

### Convert images

```bash
python convert_to_webp.py --folder ./images --quality 85
python convert_to_webp_lossless.py --folder ./logos
python batch_resize_webp.py --width 800 --height 800 --quality 80
```

### PNG → SVG

```bash
pip install vtracer
python png_to_svg.py                     # all PNGs in current folder
python png_to_svg.py logo.png --preset large
python png_to_svg.py *.png --mode embed  # embed PNG inside SVG (no vectorization)
```

### Taxonomy cleanup

```bash
python process_taxonomy.py \
    --target  woocommerce_master.xlsx \
    --source  wolt_export.xlsx \
    --output  woocommerce_master_fixed.xlsx
```

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and fill in your credentials.

| Variable | Used by | Where to get it |
|---|---|---|
| `IMGBB_API_KEY` | `csv_imgbb_normalizer_v3.py` | [api.imgbb.com](https://api.imgbb.com/) |
| `CLOUDINARY_CLOUD_NAME` | `csv_cloudinary_normalizer_v2.py` | [cloudinary.com/console](https://cloudinary.com/console) |
| `CLOUDINARY_API_KEY` | `csv_cloudinary_normalizer_v2.py` | Cloudinary dashboard |
| `CLOUDINARY_API_SECRET` | `csv_cloudinary_normalizer_v2.py` | Cloudinary dashboard |
| `BRANDFETCH_CLIENT_ID` | `debug_brandfetch.py` | [brandfetch.com/dev](https://brandfetch.com/dev) |
| `BRANDFETCH_API_KEY` | `debug_brandfetch.py` | Brandfetch dashboard |

---

## ⚠️ Important: Excel & Barcode SKUs

EAN-13 barcodes (13-digit numbers) are automatically treated as numbers by Excel and displayed in scientific notation (`5.29E+12`). If you save or copy-paste from Excel, **the last digits will be corrupted**.

**Rules:**
1. Never re-save batch CSV files from Excel before running a script
2. Never copy-paste SKU columns from Excel
3. If you need to inspect a CSV: use **Data → From Text/CSV** in Excel and set the SKU column to **Text**

Both normalizer scripts automatically detect and fix scientific notation artifacts in SKU columns (`5.29104E+12` → `5291043000149`). Output CSVs are written with `QUOTE_ALL` so Excel treats all values as text on open.

---

## 📁 What NOT to commit

The `.gitignore` excludes all Excel workbooks, CSV product data, and image files. Only commit scripts and configuration templates — never client data.

---

## 🛠️ Stack

- **Python 3.10+**
- **WooCommerce** (CSV product importer)
- **Woodmart theme** (WordPress)
- Image hosting: ImgBB or Cloudinary
- Brand logos: Wikimedia Commons / curated URLs

---

## 📄 License

MIT — free to use, adapt, and share.
