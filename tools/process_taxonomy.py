#!/usr/bin/env python3
"""
WooCommerce Product Taxonomy & Brand Processor

Reads a WooCommerce product workbook, cleans brand names, remaps
category paths, rebuilds the _Lists dropdown sheet, and writes
a new workbook with audit reports.

Usage:
    python process_taxonomy.py \\
        --target  woocommerce_master.xlsx \\
        --source  wolt_export.xlsx \\
        --output  woocommerce_master_fixed.xlsx
"""
import argparse
import shutil
import sys

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.worksheet.datavalidation import DataValidation


# ─────────────────────────────────────────────────────────────
# Brand cleanup
# ─────────────────────────────────────────────────────────────
JUNK_BRANDS = {"Face", "Cold", "Oral", "Anti", "Safe", "Power",
               "Adults", "Kids", "Women", "Men", "Unisex", "None", "Vam"}

BRAND_MAPPING = {
    "Aderma":              "A-Derma",
    "A-Derma Exomega":    "A-Derma",
    "A-Derma Dermalibour": "A-Derma",
    "Ahava Age Control":   "AHAVA",
    "Cerave":              "CeraVe",
    "Cerave Skin":         "CeraVe",
    "Cerave Hydrating":    "CeraVe",
    "La Roche Posay":      "La Roche-Posay",
    "Lrp":                 "La Roche-Posay",
    "Mollers":             "Moller's",
    "Moller'S":            "Moller's",
    "Innovagoods":         "InnovaGoods",
    "Innova Goods":        "InnovaGoods",
    "Sigg":                "SIGG",
    "Ygia":                "YGIA",
    "Ren":                 "REN",
    "Tepe":                "TePe",
    "Oral B":              "Oral-B",
}


def clean_brand(brand) -> str:
    if pd.isna(brand):
        return np.nan
    b = str(brand).strip().title()
    b = b.replace("&Amp;", "&").replace("'S", "'s")
    if b in JUNK_BRANDS or b.lower() in {j.lower() for j in JUNK_BRANDS}:
        return np.nan
    for key, val in BRAND_MAPPING.items():
        if b.lower() == key.lower() or b.lower().startswith(key.lower() + " "):
            return val
    return b


# ─────────────────────────────────────────────────────────────
# Category mapping
# ─────────────────────────────────────────────────────────────
def get_product_mappings(row, source_df: pd.DataFrame) -> pd.Series:
    sku            = row.get("SKU", "")
    product_name   = str(row.get("Product Name", "")).lower()
    old_l1         = str(row.get("Category Level 1", "")).lower()
    old_l2         = str(row.get("Category Level 2", "")).lower()
    old_l3         = str(row.get("Category Level 3", "")).lower()
    tags           = str(row.get("Tags", "")).lower()
    brand          = str(row.get("Brand", "")).strip()
    a1 = a2 = a3 = b1 = b2 = b3 = np.nan

    source_row = pd.Series(dtype=object)
    if not source_df.empty:
        s = source_df[source_df["SKU"] == sku]
        if not s.empty:
            source_row = s.iloc[0]

    src_parent   = str(source_row.get("Parent category", "")).lower()
    src_children = str(source_row.get("children category", "")).lower()
    ctx = f"{old_l1} {old_l2} {old_l3} {tags} {src_parent} {src_children} {product_name}"

    if "face care" in old_l2 or "πρόσωπο" in src_parent:
        a1, a2 = "Beauty & Personal Care", "Face Care"
    elif "body" in ctx and ("bath" in ctx or "care" in ctx):
        a1, a2 = "Beauty & Personal Care", "Body Care"
    elif "hair care" in ctx:
        a1, a2 = "Beauty & Personal Care", "Hair Care"
    elif "sun" in ctx:
        a1, a2 = "Beauty & Personal Care", "Sun Care"
    elif "fragrance" in ctx or "perfume" in ctx:
        a1, a2 = "Beauty & Personal Care", "Perfumes"
    elif "depilation" in ctx or "veet" in ctx:
        a1, a2 = "Beauty & Personal Care", "Hair Removal"
    elif "baby care" in ctx or "baby & child" in ctx:
        a1, a2 = "Mother, Baby & Kids", "Baby Care"
    elif "pregnancy" in ctx:
        a1, a2 = "Mother, Baby & Kids", "Pregnancy & Maternity"
    elif "kids care" in old_l2:
        a1, a2 = "Mother, Baby & Kids", "Kids Care"
        if "multivitamin" in ctx:
            a3 = "Kids Multivitamins"
    elif "oral" in ctx:
        a1, a2 = "Health & Daily Care", "Oral Care"
    elif "nasal" in ctx:
        a1, a2 = "Health & Daily Care", "Nasal Care"
    elif "throat" in ctx or "cough" in ctx:
        a1, a2 = "Health & Daily Care", "Throat Care"
    elif "ear" in ctx:
        a1, a2 = "Health & Daily Care", "Ear Care"
    elif "intimate" in ctx:
        a1, a2 = "Health & Daily Care", "Intimate Wellness"
    elif "atopic" in ctx or "dry" in ctx:
        a1, a2 = "Health & Daily Care", "Atopic, Dry & Itchy Skin"
    elif "supplement" in ctx:
        a1, a2 = "Vitamins & Supplements", "Supplements"
        if "magnesium"   in ctx: a2 = "Magnesium"
        elif "d3" in ctx:        a2 = "Vitamin D3 & K"
        elif "vitamin b" in ctx: a2 = "Vitamin B"
        elif "iron"      in ctx: a2 = "Iron"
        elif "immune"    in ctx: a2 = "Immune Support"

    if brand == "SIGG":
        a1, a2 = "Mother, Baby & Kids", "Water Bottles"

    return pd.Series([a1, a2, a3, b1, b2, b3])


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="WooCommerce taxonomy & brand processor")
    parser.add_argument("--target", required=True,
                        help="Target WooCommerce workbook (.xlsx)")
    parser.add_argument("--source", default="",
                        help="Optional Wolt export for extra category hints (.xlsx)")
    parser.add_argument("--output", required=True,
                        help="Output workbook path (.xlsx)")
    args = parser.parse_args()

    # Load target
    shutil.copy2(args.target, "_tmp_target.xlsx")
    tgt = pd.ExcelFile("_tmp_target.xlsx")
    pe_df = pd.read_excel(tgt, sheet_name="Product_Entry")
    wc_df = pd.read_excel(tgt, sheet_name="WooCommerce_Import")

    # Load optional source
    source_df = pd.DataFrame()
    if args.source:
        try:
            shutil.copy2(args.source, "_tmp_source.xlsx")
            src = pd.ExcelFile("_tmp_source.xlsx")
            source_df = pd.read_excel(src, sheet_name=src.sheet_names[0])
        except Exception as e:
            print(f"Warning: could not load source file: {e}")

    # Brand cleanup
    print("Step 1: Brand cleanup…")
    pe_df["Brand_original"] = pe_df["Brand"]
    pe_df["Brand"] = pe_df["Brand"].apply(clean_brand)
    brand_report = pe_df[["SKU", "Product Name", "Brand_original", "Brand"]].copy()
    brand_report = brand_report[brand_report["Brand_original"] != brand_report["Brand"]].dropna(subset=["Brand_original"])

    # Category remapping
    print("Step 2: Category remapping…")
    mappings = pe_df.apply(lambda row: get_product_mappings(row, source_df), axis=1)
    cols = ["Category Level 1_A", "Category Level 2_A", "Category Level 3_A",
            "Category Level 1_B", "Category Level 2_B", "Category Level 3_B"]
    pe_df[cols] = mappings
    pe_df["Category Level 1"] = pe_df["Category Level 1_A"]
    pe_df["Category Level 2"] = pe_df["Category Level 2_A"]
    pe_df["Category Level 3"] = pe_df["Category Level 3_A"]
    cat_report = pe_df[["SKU", "Product Name"] + cols].copy()
    val_issues = pe_df[pd.isna(pe_df["Category Level 1_A"])][["SKU", "Product Name", "Brand"]]

    # WooCommerce sync
    print("Step 3: WooCommerce sync…")
    pe_dict = pe_df.set_index("SKU").to_dict("index")

    def generate_wc_categories(row):
        sku = row.get("SKU")
        if not sku or sku not in pe_dict:
            return row.get("Categories", "")
        pr = pe_dict[sku]
        cat_A = [str(x) for x in [pr.get("Category Level 1_A"), pr.get("Category Level 2_A"), pr.get("Category Level 3_A")] if pd.notna(x)]
        cat_B = [str(x) for x in [pr.get("Category Level 1_B"), pr.get("Category Level 2_B"), pr.get("Category Level 3_B")] if pd.notna(x)]
        path_a = " > ".join(cat_A)
        path_b = " > ".join(cat_B)
        return f"{path_a}, {path_b}" if path_a and path_b else (path_a or "")

    wc_df["Categories"] = wc_df.apply(generate_wc_categories, axis=1)

    # Write output
    print(f"Writing output → {args.output}")
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        pe_df.to_excel(writer, sheet_name="Product_Entry",       index=False)
        wc_df.to_excel(writer, sheet_name="WooCommerce_Import",  index=False)
        brand_report.to_excel(writer, sheet_name="Brand_Report", index=False)
        cat_report.to_excel(writer,   sheet_name="Cat_Report",   index=False)
        val_issues.to_excel(writer,   sheet_name="Val_Issues",   index=False)

    print(f"✅ Done!")
    print(f"   Brand changes:         {len(brand_report)}")
    print(f"   Products un-mapped:    {len(val_issues)}")


if __name__ == "__main__":
    main()
