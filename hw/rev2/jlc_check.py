#!/usr/bin/env python3
"""Check JLCPCB assembly stock and unit price for LCSC part numbers.

Usage:
    jlc_check.py                 # check the Rev 2 key parts listed below
    jlc_check.py C97521 C86720   # check specific LCSC codes
    jlc_check.py --bom bom-jlc.csv --qty 5   # check a JLC BOM for N boards

Queries JLCPCB's public parts search (the one behind jlcpcb.com/parts).
"""
import argparse
import csv
import json
import sys
import urllib.request

API = ("https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/"
       "smtGood/selectSmtComponentList")

KEY_PARTS = {
    "C1521726": "U100 FPGA XC7A35T-1CSG324I",
    "C1521768": "U100 FPGA XC7A100T-1CSG324C (alternative)",
    "C97521": "U105 config flash W25Q128JVSIQ",
    "C3020560": "J200 USB-C GCT USB4105-GF-A",
    "C42459160": "U209 USB-PD sink CH224A",
    "C485916": "U210 power mux TPS2121RUXR",
    "C5219254": "U211,U213-U215 buck TPS62933PDRLR",
    "C86720": "U200,U202,U205,U212 LDO TL1963ADCQR",
    "C8690": "U603 FT232RL",
    "C654294": "U203 ADA4895-1ARJZ",
    "C7843": "U600-U604 SN74LVC1T45DBVR",
}


def lookup(code):
    body = json.dumps({"keyword": code, "currentPage": 1,
                       "pageSize": 10}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        items = json.load(r)["data"]["componentPageInfo"]["list"] or []
    for c in items:
        if c.get("componentCode") == code:
            return c
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("codes", nargs="*")
    p.add_argument("--bom", help="JLC BOM CSV (Comment,Designator,Footprint,LCSC)")
    p.add_argument("--qty", type=int, default=1, help="number of boards")
    a = p.parse_args()

    wanted = {}  # code -> (label, quantity per board)
    if a.bom:
        with open(a.bom, newline="") as f:
            for row in csv.DictReader(f):
                code = (row.get("LCSC") or "").strip()
                if code:
                    n = len([d for d in row["Designator"].split(",") if d.strip()])
                    wanted[code] = (row["Comment"], n)
    elif a.codes:
        wanted = {c: ("", 1) for c in a.codes}
    else:
        wanted = {c: (l, 1) for c, l in KEY_PARTS.items()}

    problems = 0
    for code, (label, n) in wanted.items():
        need = n * a.qty
        c = lookup(code)
        if c is None:
            print(f"{code:10} NOT FOUND                         {label}")
            problems += 1
            continue
        stock = c.get("stockCount") or 0
        price = (c.get("componentPrices") or [{}])[0].get("productPrice")
        kind = c.get("componentLibraryType")
        flag = "OK " if stock >= need else "LOW"
        problems += stock < need
        print(f"{code:10} {flag} stock {stock:<8} need {need:<5} "
              f"${price} {kind:7} {c.get('componentModelEn')}  {label}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
