#!/usr/bin/env python3
"""DC voltage drop and current density of the power nets (numpy/scipy/pillow).

  python hw/rev2/sim/irdrop.py COPPER.json [NET ...]

COPPER.json comes from export_copper.py. Each net's copper is rasterised
per layer, every copper cell becomes a node of a resistor network (sheet
resistance of the layer), vias and plated holes join the layers (barrel
resistance), the source pads are held at 0 V and every load draws its
current spread over its pads. Reported: the drop at each load, the highest
sheet current density per layer (A per mm of copper width, the figure track
width tables use) with its position, the highest via current and the total
dissipation.

The load currents below are worst cases from DESIGN.md (12 V input,
DUT/platform 1.5 A each, XC7A100T core). Copper: JLC 6-layer, 1 oz outer
(35 um), 0.5 oz inner (15.2 um), 18 um via plating.
"""
import json
import math
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

RHO = 1.72e-8                        # ohm.m, copper at 20 C
THICK = {"F": 35e-6, "In1": 15.2e-6, "In2": 15.2e-6, "In3": 15.2e-6, "In4": 15.2e-6, "B": 35e-6}
ZPOS = {"F": 0.0, "In1": 0.2234, "In2": 0.5234, "In3": 0.9402, "In4": 1.2402, "B": 1.4636}   # mm, JLC06161H-2116
PLATING = 18e-6
LAYERS = list(THICK)

# net: (source pads, [(load ref, [pad numbers] or None for all of the net, amps), ...])
CASES = {
    "VBUS_C": (["J200.A4", "J200.A9", "J200.B4", "J200.B9"], [("U210", None, 3.0)]),
    "VEXT": (["CN202.1"], [("U210", None, 4.0)]),
    "VIN_MUX": (["U210.1", "U210.8"], [("S200", None, 4.0)]),
    "VIN": (["S200.2"], [("U211", None, 1.9), ("U213", None, 0.25), ("U214", None, 0.1), ("U215", None, 0.3)]),
    "VPRE": (["L201.2"], [("U200", None, 1.5), ("U202", None, 1.5), ("U205", None, 0.3), ("U212", None, 0.2)]),
    "/U_Power/PLAT_LDO_OUT": (["U200.4"], [("CN201", None, 1.5)]),
    "/U_Power/DUT_LDO_OUT": (["U202.4"], [("CN206", None, 1.5)]),
    "VCC_PLATFORM_PERMANENT": (["CN201.2"], [("Q200", None, 1.5)]),
    "VCC_DUT_PERMANENT": (["CN206.2"], [("Q203", None, 1.5)]),
    "VCC_PLATFORM": (["Q201.1", "Q201.2", "Q201.5", "Q201.6"], [("J500", None, 1.5)]),
    "VCC_DUT": (["Q204.1", "Q204.2", "Q204.5", "Q204.6"], [("J503", None, 1.5)]),
    "1V0": (["L202.2"], [("U100", None, 2.0)]),
    "1V8": (["L203.2"], [("U100", None, 0.3)]),
    "3V3_FPGA": (["L204.2"], [("U100", None, 0.3), ("U105", None, 0.03), ("U400", None, 0.05),
                              ("U401", None, 0.05), ("U402", None, 0.05)]),
    "VCC_IO_FPGA": (["U205.4"], [("U100", None, 0.3)]),
}


def solve(d, net, res):
    src_names, loads = CASES[net]
    cu = [c for c in d["copper"] if c["n"] == net]
    pads = [p for p in d["pads"] if p["n"] == net]
    xs = [pt[0] for c in cu for poly in c["poly"] for ring in poly for pt in ring]
    ys = [pt[1] for c in cu for poly in c["poly"] for ring in poly for pt in ring]
    x0, y0 = min(xs) - 1, min(ys) - 1
    W, H = int((max(xs) + 1 - x0) / res) + 1, int((max(ys) + 1 - y0) / res) + 1

    def ij(x, y):
        return int(round((y - y0) / res)), int(round((x - x0) / res))

    masks = {}
    for L in LAYERS:
        img = Image.new("1", (W, H), 0)
        dr = ImageDraw.Draw(img)
        for c in cu:
            if c["L"] != L:
                continue
            for poly in c["poly"]:
                pts = [((x - x0) / res, (y - y0) / res) for x, y in poly[0]]
                if len(pts) > 2:
                    dr.polygon(pts, fill=1)
                for hole in poly[1:]:
                    pts = [((x - x0) / res, (y - y0) / res) for x, y in hole]
                    if len(pts) > 2:
                        dr.polygon(pts, fill=0)
        m = np.array(img, dtype=bool)
        if m.any():
            masks[L] = m
    # node numbering
    idx = {}
    n = 0
    for L, m in masks.items():
        a = -np.ones(m.shape, dtype=np.int64)
        k = int(m.sum())
        a[m] = np.arange(n, n + k)
        idx[L] = a
        n += k
    rows, cols, vals = [], [], []

    def link(a, b, g):
        rows.extend([a, b, a, b])
        cols.extend([a, b, b, a])
        vals.extend([g, g, -g, -g])

    for L, a in idx.items():
        g = THICK[L] / RHO           # sheet conductance, square cells
        for sl_a, sl_b in (((slice(None), slice(0, -1)), (slice(None), slice(1, None))),
                           ((slice(0, -1), slice(None)), (slice(1, None), slice(None)))):
            p, q = a[sl_a], a[sl_b]
            ok = (p >= 0) & (q >= 0)
            pa, qa = p[ok], q[ok]
            rows.extend(np.concatenate([pa, qa, pa, qa]))
            cols.extend(np.concatenate([pa, qa, qa, pa]))
            vals.extend(np.concatenate([np.full(len(pa), g)] * 2 + [np.full(len(pa), -g)] * 2))
    vlinks = []                       # (node a, node b, conductance, via index)

    def barrel(x, y, drill, layers, tag):
        r = int(math.ceil(drill / 2 / res))
        present = []
        for L in LAYERS:
            if L not in idx or L not in layers:
                continue
            i, j = ij(x, y)
            a = idx[L]
            sub = a[max(i - r, 0):i + r + 1, max(j - r, 0):j + r + 1]
            nodes = sub[sub >= 0]
            if len(nodes):
                present.append((L, nodes))
        for (La, na), (Lb, nb) in zip(present, present[1:]):
            dz = (ZPOS[Lb] - ZPOS[La]) * 1e-3
            g = math.pi * drill * 1e-3 * PLATING / (RHO * dz)
            # spread the barrel over the cells of the hole on both layers
            ga = g / (len(na) * len(nb)) if len(na) * len(nb) < 50 else None
            if ga is None:
                ca, cb = na[len(na) // 2], nb[len(nb) // 2]
                link(ca, cb, g)
                vlinks.append((ca, cb, g, tag + (La,)))
            else:
                for p_ in na:
                    for q_ in nb:
                        link(p_, q_, ga)
                        vlinks.append((p_, q_, ga, tag + (La,)))

    for k, v in enumerate(d["vias"]):
        if v["n"] == net:
            barrel(v["x"], v["y"], v["drill"], v["L"], ("via", k))
    for k, h in enumerate(d["holes"]):
        if h["n"] == net:
            barrel(h["x"], h["y"], h["drill"], h["L"], ("hole", k))

    def pad_nodes(p):
        out = []
        for L in p["L"]:
            if L not in idx:
                continue
            x_0, y_0, x_1, y_1 = p["bbox"]
            i0, j0 = ij(x_0, y_0)
            i1, j1 = ij(x_1, y_1)
            sub = idx[L][max(i0, 0):i1 + 1, max(j0, 0):j1 + 1]
            out.extend(sub[sub >= 0].tolist())
        return out

    src = set()
    for s in src_names:
        ref, num = s.split(".")
        for p in pads:
            if p["ref"] == ref and p["num"] == num:
                src |= set(pad_nodes(p))
    if not src:
        raise SystemExit("%s: source pads not found" % net)
    inj = np.zeros(n)
    load_nodes = {}
    for ref, nums, amps in loads:
        nodes = []
        for p in pads:
            if p["ref"] == ref and (nums is None or p["num"] in nums):
                nodes.extend(pad_nodes(p))
        nodes = sorted(set(nodes) - src)
        if not nodes:
            print("  %s: load %s not found" % (net, ref))
            continue
        inj[nodes] -= amps / len(nodes)
        load_nodes[ref] = (nodes, amps)
    G = coo_matrix((np.asarray(vals, dtype=float), (np.asarray(rows), np.asarray(cols))), shape=(n, n)).tocsr()
    # Dirichlet: V = 0 on the source nodes
    free = np.ones(n, dtype=bool)
    free[list(src)] = False
    fi = np.nonzero(free)[0]
    Gf = G[fi][:, fi]
    # floating islands (copper not connected to the source) make G singular: ground them weakly
    Gf = Gf + coo_matrix((np.full(len(fi), 1e-9), (np.arange(len(fi)), np.arange(len(fi))))).tocsr()
    V = np.zeros(n)
    V[fi] = spsolve(Gf.tocsc(), inj[fi])
    print("== %s  (grid %.3f mm, %d nodes, source %s)" % (net, res, n, " ".join(src_names)))
    for ref, (nodes, amps) in load_nodes.items():
        print("   load %-6s %4.2f A: drop %6.1f mV (worst pad cell %6.1f mV)" %
              (ref, amps, -V[nodes].mean() * 1e3, -V[nodes].min() * 1e3))
    # sheet current density per layer
    exclude = set(src)
    for nodes, _ in load_nodes.values():
        exclude |= set(nodes)
    for L, a in idx.items():
        g = THICK[L] / RHO
        Vl = np.where(a >= 0, V[np.maximum(a, 0)], np.nan)
        jx = np.zeros(a.shape)
        jy = np.zeros(a.shape)
        dx = (Vl[:, 1:] - Vl[:, :-1]) * g / (res)        # A per mm of width (cell edge = res mm)
        dy = (Vl[1:, :] - Vl[:-1, :]) * g / (res)
        jx[:, :-1] = np.nan_to_num(dx)
        jy[:-1, :] = np.nan_to_num(dy)
        j = np.hypot(jx, jy)
        j[a < 0] = 0
        # ignore cells within 0.3 mm of a source/load pad or a via (current crowding at the contacts)
        keep = a >= 0
        ex = np.zeros(a.shape, dtype=bool)
        ex[a >= 0] = np.isin(a[a >= 0], list(exclude))
        for vv in d["vias"] + d["holes"]:
            if vv["n"] == net:
                i, jj = ij(vv["x"], vv["y"])
                r = int(0.3 / res) + int(vv["drill"] / 2 / res)
                ex[max(i - r, 0):i + r + 1, max(jj - r, 0):jj + r + 1] = True
        grow = int(0.3 / res)
        if grow:
            from scipy.ndimage import binary_dilation
            ex = binary_dilation(ex, iterations=grow) & keep
        jm = np.where(keep & ~ex, j, 0)
        if jm.max() > 0:
            i, jj = np.unravel_index(np.argmax(jm), jm.shape)
            hx, hy = x0 + jj * res, y0 + i * res
            near = min(d["pads"], key=lambda p: (p["x"] - hx) ** 2 + (p["y"] - hy) ** 2)
            print("   %-4s max %5.2f A/mm at (%.1f, %.1f), near %s.%s" % (L, jm.max(), hx, hy, near["ref"], near["num"]))
    # via currents
    seg = {}
    for p_, q_, g, tag in vlinks:          # current through each barrel section, then the worst section per via
        seg[tag] = seg.get(tag, 0) + abs(V[p_] - V[q_]) * g
    worst = {}
    for tag, cur in seg.items():
        worst[tag[:2]] = max(worst.get(tag[:2], 0), cur)
    if worst:
        tag, cur = max(worst.items(), key=lambda kv: kv[1])
        o = d["vias"][tag[1]] if tag[0] == "via" else d["holes"][tag[1]]
        print("   max barrel current %.2f A (%s %.2f mm drill at %.1f, %.1f)" % (cur, tag[0], o["drill"], o["x"], o["y"]))
    P = float((V * inj).sum())
    print("   dissipation %.0f mW" % (P * 1e3))


def main():
    d = json.load(open(sys.argv[1]))
    nets = sys.argv[2:] or list(CASES)
    for net in nets:
        res = 0.1 if net in ("3V3_FPGA", "VCC_IO_FPGA", "1V8") else 0.05
        solve(d, net, res)


if __name__ == "__main__":
    main()
