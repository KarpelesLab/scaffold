#!/usr/bin/env python3
"""Draws exported copper (export_copper.py) to a PNG, one colour per layer,
highlighted nets brighter (pillow).

  python hw/rev2/sim/render.py COPPER.json OUT.png X0 Y0 X1 Y1 [PX_PER_MM] [NET,...]
"""
import json
import sys

from PIL import Image, ImageDraw

COL = {"F": (220, 40, 40), "In1": (40, 160, 40), "In2": (200, 160, 0), "In3": (160, 60, 200), "In4": (40, 160, 160),
       "B": (40, 80, 230)}
ORDER = ["In4", "In3", "In2", "In1", "B", "F"]


def main():
    d = json.load(open(sys.argv[1]))
    x0, y0, x1, y1 = map(float, sys.argv[3:7])
    s = float(sys.argv[7]) if len(sys.argv) > 7 else 20
    hl = set(sys.argv[8].split(",")) if len(sys.argv) > 8 else set()
    img = Image.new("RGB", (int((x1 - x0) * s), int((y1 - y0) * s)), (12, 12, 12))
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(over)
    tf = lambda pts: [((x - x0) * s, (y - y0) * s) for x, y in pts]
    for L in ORDER:
        for c in d["copper"]:
            if c["L"] != L:
                continue
            bright = c["n"] in hl
            r, g, b = COL[L]
            a = 230 if bright else (60 if hl else 140)
            if hl and not bright:
                r, g, b = (r + 128) // 2, (g + 128) // 2, (b + 128) // 2
            for poly in c["poly"]:
                if len(poly[0]) > 2:
                    dr.polygon(tf(poly[0]), fill=(r, g, b, a))
                for hole in poly[1:]:
                    if len(hole) > 2:
                        dr.polygon(tf(hole), fill=(0, 0, 0, 0))
        img = Image.alpha_composite(img.convert("RGBA"), over)
        over = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(over)
    dr = ImageDraw.Draw(img)
    for v in d["vias"] + d["holes"]:
        cx, cy = (v["x"] - x0) * s, (v["y"] - y0) * s
        r = v["drill"] / 2 * s
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255) if v["n"] in hl else (90, 90, 90))
    seen = set()
    for p in d["pads"]:
        if p["ref"] in seen or not (x0 <= p["x"] <= x1 and y0 <= p["y"] <= y1):
            continue
        seen.add(p["ref"])
        dr.text(((p["x"] - x0) * s, (p["y"] - y0) * s), p["ref"], fill=(255, 255, 255))
    img.convert("RGB").save(sys.argv[2])


if __name__ == "__main__":
    main()
