#!/usr/bin/env python3
"""
Debug script — prints the exact Brandfetch API response for a brand,
so you can inspect the response structure.

Set your credentials via environment variables:
    export BRANDFETCH_CLIENT_ID="your_client_id"
    export BRANDFETCH_API_KEY="your_api_key"

Usage:
    python debug_brandfetch.py
    python debug_brandfetch.py --brand "Korres" --domain "korres.com"
"""
import json
import os
import sys
import argparse
import requests
from urllib.parse import quote

BRANDFETCH_CLIENT_ID = os.getenv("BRANDFETCH_CLIENT_ID", "").strip()
BRANDFETCH_API_KEY   = os.getenv("BRANDFETCH_API_KEY", "").strip()

if not BRANDFETCH_CLIENT_ID or not BRANDFETCH_API_KEY:
    print("ERROR: Set BRANDFETCH_CLIENT_ID and BRANDFETCH_API_KEY environment variables.")
    print("  export BRANDFETCH_CLIENT_ID=your_client_id")
    print("  export BRANDFETCH_API_KEY=your_api_key")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug Brandfetch API response")
    parser.add_argument("--brand",  default="Korres", help="Brand name to search")
    parser.add_argument("--domain", default="",       help="Domain override (skip search)")
    args = parser.parse_args()

    domain = args.domain

    if not domain:
        print(f"\n{'='*60}")
        print(f"SEARCH: '{args.brand}'")
        print("="*60)
        r = requests.get(
            f"https://api.brandfetch.io/v2/search/{quote(args.brand)}",
            params={"c": BRANDFETCH_CLIENT_ID},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        print(f"Status: {r.status_code}")
        search_data = r.json()
        print(json.dumps(search_data[:3] if isinstance(search_data, list) else search_data, indent=2))
        if isinstance(search_data, list) and search_data:
            domain = search_data[0].get("domain", "")
            print(f"\nFirst match domain: {domain}")

    if not domain:
        print("No domain found — exiting.")
        return

    print(f"\n{'='*60}")
    print(f"BRAND DATA: '{domain}'")
    print("="*60)
    r2 = requests.get(
        f"https://api.brandfetch.io/v2/brands/{domain}",
        headers={"Accept": "application/json", "Authorization": f"Bearer {BRANDFETCH_API_KEY}"},
        timeout=30,
    )
    print(f"Status: {r2.status_code}")
    brand_data = r2.json()
    print("\n--- TOP LEVEL KEYS ---")
    print(list(brand_data.keys()) if isinstance(brand_data, dict) else type(brand_data))
    print("\n--- LOGOS ---")
    print(json.dumps(brand_data.get("logos", []) if isinstance(brand_data, dict) else [], indent=2))
    print("\n--- ICONS ---")
    print(json.dumps(brand_data.get("icons", []) if isinstance(brand_data, dict) else [], indent=2))


if __name__ == "__main__":
    main()
