#!/usr/bin/env python3
"""Grid maze router for the connections Freerouting leaves (numpy + scipy;
runs outside KiCad).

  python3 hw/rev2/tools/maze.py BOARD.json ROUTES.json NET[=WIDTH[:VIA_D:VIA_DRILL]][@REF,REF.PIN] [...]
  (MAZE_RES=0.05 for a finer grid)

BOARD.json comes from maze_export.py; ROUTES.json is applied with
maze_apply.py. For each net, the copper of the net is rasterised on all six
layers (0.1 mm grid aligned on the BGA pitch) and split into connected
components (plated holes and vias join layers, plane fills count). While
more than one component holds pads, the smallest one is joined to the
nearest other one by an A* search over the top, Signal (In2) and bottom
layers with 8-direction moves, a turn penalty and a via cost. Clearances:
the net class clearance of the routed net against every other copper item,
and every item's own class clearance, plus a margin for the grid; board
edge and hole clearances as in the design rules.
"""
import heapq
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
from scipy import ndimage

RES = float(os.environ.get("MAZE_RES", "0.1"))
# Obstacles are stamped grown by DELTA (half a cell diagonal), so the distance
# from a cell centre to the nearest stamped centre overestimates the true
# distance to copper by at most DELTA; a point on a step between two cell
# centres is at most half a diagonal (0.71 * RES) from one of them.
MARGIN = 0.71 * RES + 0.71 * RES + 0.01
# MAZE_TIGHT=1: drop the half-step term (fine-pitch escapes); the result must
# then be checked with KiCad's DRC (maze_fix.py rips up offending routes).
if os.environ.get("MAZE_TIGHT"):
    MARGIN = 0.71 * RES + 0.01
ROUTE = ["F", "In2", "B"]
ALL = ["F", "In1", "In2", "In3", "In4", "B"]
VIA_COST = 25.0         # cells (2.5 mm)
TURN = 0.4
MAX_EXPAND = 6_000_000
NECK_W = 0.15           # narrower track allowed close to the net's own pads (fine-pitch escape)
NECK_R = 1.2

d = json.load(open(sys.argv[1]))
OUT = sys.argv[2]
# NET or NET=WIDTH (narrower track for that net, e.g. to leave a fine-pitch pin)
# NET@REF1,REF2: only join the components holding these parts to the main one
ARGS = sys.argv[3:]
# Per argument (a net may appear several times with different settings):
#   NET[=WIDTH[:VIA_D:VIA_DRILL[:NECK]]][!^+][@REF,REF.PIN]
#   ! = no vias (stay on one layer); ^ = outer layers only (1 oz copper);
#   + = up to two extra vias at each layer change (current capacity);
#   NECK = track width allowed near own pads
ONLY_SEQ = [set(a.split("@")[1].split(",")) if "@" in a else None for a in ARGS]
ARGS = [a.split("@")[0] for a in ARGS]
FLAGS_SEQ = [set(c for c in a.split("=")[-1] if c in "!^+") if "=" in a else set(c for c in a if c in "!^+")
             for a in ARGS]
NOVIA_SEQ = ["!" in f for f in FLAGS_SEQ]
ARGS = [a.rstrip("!^+") for a in ARGS]
ONLY = {}
TARGETS = [a.split("=")[0] for a in ARGS]
OV_SEQ = [[float(x) for x in a.split("=")[1].split(":")] if "=" in a else [] for a in ARGS]
WIDTH = {}
NOVIA = set()
FLAGS = {}
ox, oy = d["align"]
bx0, by0, bx1, by1 = d["bbox"]
GX0 = ox + math.floor((bx0 - ox) / RES) * RES
GY0 = oy + math.floor((by0 - oy) / RES) * RES
W = int(math.ceil((bx1 - GX0) / RES)) + 1
H = int(math.ceil((by1 - GY0) / RES)) + 1
HW = H * W
NETS = d["nets"]


def window(x0, y0, x1, y1):
    i0, i1 = max(0, int(math.floor((x0 - GX0) / RES))), min(W, int(math.ceil((x1 - GX0) / RES)) + 1)
    j0, j1 = max(0, int(math.floor((y0 - GY0) / RES))), min(H, int(math.ceil((y1 - GY0) / RES)) + 1)
    if i0 >= i1 or j0 >= j1:
        return None
    return (slice(j0, j1), slice(i0, i1)), GX0 + np.arange(i0, i1) * RES, GY0 + np.arange(j0, j1) * RES


def seg_mask(x0, y0, x1, y1, r):
    w = window(min(x0, x1) - r, min(y0, y1) - r, max(x0, x1) + r, max(y0, y1) + r)
    if w is None:
        return None
    sl, xs, ys = w
    X, Y = np.meshgrid(xs, ys)
    dx, dy = x1 - x0, y1 - y0
    L = dx * dx + dy * dy
    t = 0 if L == 0 else np.clip(((X - x0) * dx + (Y - y0) * dy) / L, 0, 1)
    return sl, (X - x0 - t * dx) ** 2 + (Y - y0 - t * dy) ** 2 <= r * r


def poly_fill(pl, pad=0.0, exact_r=None):
    """Cells whose centre is inside the polygon set (even-odd), or, with
    exact_r, within exact_r of it (exact point-to-edge distance)."""
    pts = [p for poly in pl for ring in poly for p in ring]
    if not pts:
        return None
    xs_, ys_ = [p[0] for p in pts], [p[1] for p in pts]
    w = window(min(xs_) - pad - RES, min(ys_) - pad - RES, max(xs_) + pad + RES, max(ys_) + pad + RES)
    if w is None:
        return None
    sl, xs, ys = w
    wd = len(xs)
    tog = np.zeros((len(ys), wd + 1), np.int32)
    for poly in pl:
        for ring in poly:
            n = len(ring)
            for k in range(n):
                (xa, ya), (xb, yb) = ring[k], ring[(k + 1) % n]
                if ya == yb:
                    continue
                lo, hi = (ya, yb) if ya < yb else (yb, ya)
                j = np.nonzero((ys >= lo) & (ys < hi))[0]
                if len(j) == 0:
                    continue
                xc = xa + (ys[j] - ya) * (xb - xa) / (yb - ya)
                col = np.clip(np.ceil((xc - xs[0]) / RES - 1e-9).astype(int), 0, wd)
                np.add.at(tog, (j, col), 1)
    inside = (np.cumsum(tog, axis=1)[:, :wd] % 2).astype(bool)
    if exact_r is None:
        return sl, inside
    X, Y = np.meshgrid(xs, ys)
    best = np.full(inside.shape, np.inf)
    for poly in pl:
        for ring in poly:
            n = len(ring)
            for k in range(n):
                (x0, y0), (x1, y1) = ring[k], ring[(k + 1) % n]
                dx, dy = x1 - x0, y1 - y0
                L = dx * dx + dy * dy
                t = 0 if L == 0 else np.clip(((X - x0) * dx + (Y - y0) * dy) / L, 0, 1)
                np.minimum(best, (X - x0 - t * dx) ** 2 + (Y - y0 - t * dy) ** 2, out=best)
    return sl, inside | (best <= exact_r * exact_r)


_poly_cache = {}
DELTA = 0.71 * RES      # obstacles are stamped grown by half a cell diagonal (see route_net)


def item_mask(it, infl):
    if "seg" in it:
        x0, y0, x1, y1, w = it["seg"]
        return seg_mask(x0, y0, x1, y1, w / 2 + infl)
    if "circ" in it:
        x, y, r = it["circ"]
        return seg_mask(x, y, x, y, r + infl)
    if "poly" in it:
        key = (id(it), infl)
        if key not in _poly_cache:
            if it.get("zone"):
                # large fills: raster, grown conservatively by one extra cell
                m = poly_fill(it["poly"], infl + RES)
                if m is not None and infl > 0:
                    m = (m[0], ndimage.distance_transform_edt(~m[1]) * RES <= infl + RES)
            else:
                m = poly_fill(it["poly"], infl, exact_r=infl) if infl > 0 else poly_fill(it["poly"])
            _poly_cache[key] = m
        return _poly_cache[key]
    return None


def clearance(it):
    if it.get("keepout"):
        return 0.0
    cl = NETS[it["n"]]["cl"] if it["n"] in NETS else 0.15
    return max(cl, d["hole_clearance"]) if it.get("hole") else cl


def copper(it):
    return "seg" in it or "circ" in it or "poly" in it


RI = {l: k for k, l in enumerate(ROUTE)}
Bc = np.zeros((len(ROUTE), H, W), np.int16)     # copper (and holes, keepouts)
Ac = np.zeros((len(ROUTE), H, W), np.int16)     # copper grown by its own clearance
by_net = defaultdict(list)


def stamp(it, s):
    if not copper(it):
        return
    lay = [RI[l] for l in it["L"] if l in RI]
    if not lay:
        return
    for arr, infl in ((Bc, DELTA), (Ac, clearance(it) + DELTA)):
        m = item_mask(it, infl)
        if m is None:
            continue
        sl, mk = m
        for k in lay:
            arr[k][sl] += s * mk


for it in d["items"]:
    by_net[it["n"]].append(it)
    stamp(it, 1)
inside = poly_fill(d["outline"])
board = np.zeros((H, W), bool)
board[inside[0]] = inside[1]
edge_dist = ndimage.distance_transform_edt(board) * RES
pads_by_net = defaultdict(list)
for p in d["pads"]:
    pads_by_net[p["n"]].append(p)
print("grid %dx%d, %d items" % (W, H, len(d["items"])), flush=True)


def cell(x, y):
    return int(round((y - GY0) / RES)), int(round((x - GX0) / RES))


def components(net):
    """Connected components of the net's copper. Items are joined where their
    rasters share cells (overlap, as in KiCad: a gap narrower than a cell
    does not count as a connection); vias span layers, plated holes link the
    layers they are flashed on."""
    items = [it for it in by_net[net] if copper(it) and not (it.get("hole") and not it["n"])]
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    lab = np.full((len(ALL), H, W), -1, np.int32)
    masks_it = []
    for n, it in enumerate(items):
        m = item_mask(it, 0.0)
        masks_it.append(m)
        if m is None:
            continue
        sl, mk = m
        for l in it["L"]:
            k = ALL.index(l)
            sub = lab[k][sl]
            for o in np.unique(sub[mk]):
                if o >= 0:
                    union(n, int(o))
            sub[mk] = n
    for it in by_net[net]:
        if "link" in it and not copper(it):
            j, i = cell(*it["link"])
            ids = [int(lab[ALL.index(l)][j, i]) for l in it["L"]]
            ids = [x for x in ids if x >= 0]
            for x in ids[1:]:
                union(ids[0], x)
    comps = defaultdict(list)
    for p in pads_by_net[net]:
        j, i = cell(p["x"], p["y"])
        o = int(lab[ALL.index(p["L"])][j, i])
        if o >= 0:
            comps[find(o)].append(p["ref"])
    own = np.zeros((len(ALL), H, W), bool)
    masks = {r: np.zeros((len(ROUTE), H, W), bool) for r in comps}
    for n, it in enumerate(items):
        m = masks_it[n]
        if m is None:
            continue
        sl, mk = m
        r = find(n)
        for l in it["L"]:
            own[ALL.index(l)][sl] |= mk
            if r in masks and l in RI:
                masks[r][RI[l]][sl] |= mk
    return comps, masks, own


DIRS = [(1, 0, 1.0, 0), (-1, 0, 1.0, 1), (0, 1, 1.0, 2), (0, -1, 1.0, 3),
        (1, 1, 1.4142, 4), (1, -1, 1.4142, 5), (-1, 1, 1.4142, 6), (-1, -1, 1.4142, 7)]


def astar(allowed, via_ok, src, tgt, free):
    A = [a.ravel().tobytes() for a in allowed]
    FR = [f.ravel().tobytes() for f in free]
    V = via_ok.ravel().tobytes()
    TG = [t.ravel().tobytes() for t in tgt]
    jj, ii = np.nonzero(tgt.any(axis=0))
    ti0, ti1, tj0, tj1 = ii.min(), ii.max(), jj.min(), jj.max()

    def h(idx):
        j, i = divmod(idx, W)
        dx = max(ti0 - i, 0, i - ti1)
        dy = max(tj0 - j, 0, j - tj1)
        return max(dx, dy) + 0.4142 * min(dx, dy)
    g, par, dirn, heap = {}, {}, {}, []
    for k in range(len(ROUTE)):
        for idx in np.flatnonzero(src[k] & allowed[k]):
            key = k * HW + int(idx)
            g[key] = 0.0
            heapq.heappush(heap, (h(int(idx)), 0.0, key))
    n = 0
    while heap:
        f, gc, key = heapq.heappop(heap)
        if gc > g.get(key, 1e18):
            continue
        k, idx = divmod(key, HW)
        if TG[k][idx]:
            path = [key]
            while path[-1] in par:
                path.append(par[path[-1]])
            return path[::-1], n
        n += 1
        if n > MAX_EXPAND:
            return None, n
        j, i = divmod(idx, W)
        pd = dirn.get(key)
        straight_only = not FR[k][idx]    # inside own copper only: no diagonal exit (corner clearance)
        for di, dj, c, code in DIRS:
            if straight_only and code >= 4:
                continue
            ni, nj = i + di, j + dj
            if not (0 <= ni < W and 0 <= nj < H):
                continue
            nidx = nj * W + ni
            if not A[k][nidx]:
                continue
            nk = k * HW + nidx
            ng = gc + c + (TURN if pd is not None and pd != code else 0.0)
            if ng < g.get(nk, 1e18):
                g[nk], par[nk], dirn[nk] = ng, key, code
                heapq.heappush(heap, (ng + h(nidx), ng, nk))
        if V[idx]:
            for k2 in range(len(ROUTE)):
                if k2 != k and A[k2][idx]:
                    nk = k2 * HW + idx
                    ng = gc + VIA_COST
                    if ng < g.get(nk, 1e18):
                        g[nk], par[nk], dirn[nk] = ng, key, None
                        heapq.heappush(heap, (ng + h(idx), ng, nk))
    return None, n


def fat_vias(path, free, via_free, nc, net):
    """Up to two extra vias next to each layer change, joined to it by stubs
    on both layers (checked against the free maps of both layers)."""
    extra, taken = [], []
    vr = nc["vd"] / 2
    for p0, p1 in zip(path[:-1], path[1:]):
        k0, k1 = p0 // HW, p1 // HW
        if k0 == k1:
            continue
        j, i = divmod(p1 % HW, W)
        x0, y0 = to_xy(p1 % HW)
        got = 0
        for dist in (nc["vd"] + 0.25, nc["vd"] + 0.5):
            for a in range(16):
                ang = 2 * math.pi * a / 16
                x, y = x0 + dist * math.cos(ang), y0 + dist * math.sin(ang)
                jj, ii = int(round((y - GY0) / RES)), int(round((x - GX0) / RES))
                if not (0 <= ii < W and 0 <= jj < H) or not via_free[jj, ii]:
                    continue
                if any(math.hypot(x - tx, y - ty) < nc["vd"] + 0.2 for tx, ty in taken):
                    continue
                ok = True
                for t in np.linspace(0, 1, 12):
                    cj, ci = int(round(j + (jj - j) * t)), int(round(i + (ii - i) * t))
                    if not (free[k0][cj, ci] and free[k1][cj, ci]) and not (cj == j and ci == i):
                        ok = False
                        break
                if not ok:
                    continue
                x, y = round(GX0 + ii * RES, 4), round(GY0 + jj * RES, 4)
                extra.append(dict(n=net, L=list(ALL), circ=[x, y, vr], link=[x, y], via=[nc["vd"], nc["vdr"]]))
                for k in (k0, k1):
                    extra.append(dict(n=net, L=[ROUTE[k]], seg=[x0, y0, x, y, nc["w"]]))
                taken.append((x, y))
                got += 1
                if got >= 2:
                    break
            if got >= 2:
                break
        taken.append((x0, y0))
    return extra


def to_xy(idx):
    j, i = divmod(idx, W)
    return round(GX0 + i * RES, 4), round(GY0 + j * RES, 4)


def route_net(net, out):
    nc = dict(NETS[net])
    ov = WIDTH.get(net, [])
    if ov:
        nc["w"] = ov[0]
    if len(ov) >= 3:
        nc["vd"], nc["vdr"] = ov[1], ov[2]
    hw = nc["w"] / 2
    c = max(nc["cl"], 0.1)
    vr = nc["vd"] / 2
    own_items = [it for it in by_net[net] if copper(it)]
    for it in own_items:
        stamp(it, -1)               # the net's own copper is not an obstacle
    try:
        obstB = Bc > 0
        obstA = Ac > 0
        dB = np.stack([ndimage.distance_transform_edt(~obstB[k]) * RES for k in range(len(ROUTE))])
        dA = np.stack([ndimage.distance_transform_edt(~obstA[k]) * RES for k in range(len(ROUTE))])
        edge_ok = edge_dist >= d["edge_clearance"] + hw + MARGIN
        free = (dB >= hw + c + MARGIN) & (dA >= hw + MARGIN) & edge_ok
        neck_w = ov[3] if len(ov) > 3 else NECK_W
        nhw = min(hw, neck_w / 2)
        free_neck = (dB >= nhw + c + MARGIN) & (dA >= nhw + MARGIN) \
            & (edge_dist >= d["edge_clearance"] + nhw + MARGIN)
        via_free = ((dB >= vr + c + MARGIN) & (dA >= vr + MARGIN)).all(axis=0) \
            & (edge_dist >= d["edge_clearance"] + vr + MARGIN)
        if net in NOVIA:
            via_free[:] = False
    finally:
        for it in own_items:
            stamp(it, 1)
    fails = 0
    while True:
        comps, masks, own = components(net)
        if len(comps) <= 1:
            return True
        own_route = np.stack([own[ALL.index(l)] for l in ROUTE])
        deep = np.stack([ndimage.distance_transform_edt(own_route[k]) * RES >= hw for k in range(len(ROUTE))])
        padm = np.zeros((len(ROUTE), H, W), bool)
        for it in by_net[net]:
            if it.get("pad"):
                m = item_mask(it, 0.0)
                if m is not None:
                    for l in it["L"]:
                        if l in RI:
                            padm[RI[l]][m[0]] |= m[1]
        near = np.stack([ndimage.distance_transform_edt(~padm[k]) * RES <= NECK_R for k in range(len(ROUTE))])
        neck_ok = free_neck & near & ~free
        allowed = free | deep | neck_ok
        if "^" in FLAGS.get(net, ()):
            allowed[RI["In2"]] = False
        roots = sorted(comps, key=lambda r: masks[r].sum())
        if net in ONLY:
            main = max(comps, key=lambda r: len(comps[r]))
            cand = [r for r in roots if r != main and any(x in ONLY[net] or x.split(".")[0] in ONLY[net]
                                                          for x in comps[r])]
            if not cand:
                return True
            roots = [cand[0], main]
        src = roots[0]
        sj, si = np.nonzero(masks[src].any(axis=0))

        def gap(r):
            jj, ii = np.nonzero(masks[r].any(axis=0))
            dx = max(ii.min() - si.max(), si.min() - ii.max(), 0)
            dy = max(jj.min() - sj.max(), sj.min() - jj.max(), 0)
            return math.hypot(dx, dy)
        tgt = min(roots[1:], key=gap)
        path, n = astar(allowed, via_free, masks[src], masks[tgt], free | neck_ok)
        if path is None:
            print("  %s: no route %s -> %s (%d expanded)" % (net, comps[src][:3], comps[tgt][:3], n), flush=True)
            return False
        # trim to the part outside the two components
        layer = lambda key: key // HW
        inside_src = [masks[src][layer(kk)].ravel()[kk % HW] for kk in path]
        start = max(i for i, v in enumerate(inside_src) if v)
        end = next(i for i in range(start, len(path)) if masks[tgt][layer(path[i])].ravel()[path[i] % HW])
        path = path[start:end + 1]
        new = []
        isneck = lambda kk: not free[layer(kk)].ravel()[kk % HW]
        # one step per pair of path cells (neck width if either end needs it),
        # vias at layer changes, then merge collinear steps of equal width
        steps = []
        for p0, p1 in zip(path[:-1], path[1:]):
            if layer(p0) != layer(p1):
                x, y = to_xy(p1 % HW)
                steps.append(("via", x, y))
                continue
            nw = ov[3] if len(ov) > 3 else NECK_W
            wdt = nw if (isneck(p0) or isneck(p1)) and nw < nc["w"] else nc["w"]
            (xa, ya), (xb, yb) = to_xy(p0 % HW), to_xy(p1 % HW)
            dirn = (round((xb - xa) / RES), round((yb - ya) / RES))
            last = steps[-1] if steps else None
            if last and last[0] == "seg" and last[1] == layer(p0) and last[2] == wdt and last[3] == dirn:
                steps[-1] = ("seg", last[1], wdt, dirn, last[4], (xb, yb))
            else:
                steps.append(("seg", layer(p0), wdt, dirn, (xa, ya), (xb, yb)))
        for st in steps:
            if st[0] == "via":
                new.append(dict(n=net, L=list(ALL), circ=[st[1], st[2], vr], link=[st[1], st[2]],
                                via=[nc["vd"], nc["vdr"]]))
            else:
                (xa, ya), (xb, yb) = st[4], st[5]
                new.append(dict(n=net, L=[ROUTE[st[1]]], seg=[xa, ya, xb, yb, st[2]]))
        if "+" in FLAGS.get(net, ()):
            new += fat_vias(path, free, via_free, nc, net)
        for it in new:
            by_net[net].append(it)
            stamp(it, 1)
            out.append(it)
        print("  %s: joined %s -> %s, %d items, %d expanded" % (net, comps[src][:2], comps[tgt][:2], len(new), n),
              flush=True)


if os.environ.get("MAZE_SHORT_FIRST"):
    # shortest nets first (half perimeter of their pads): short local links
    # go in before long runs can wall them off
    def hp(n):
        ps = pads_by_net.get(n, [])
        if not ps:
            return 0
        xs, ys = [p["x"] for p in ps], [p["y"] for p in ps]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))
    order = sorted(range(len(TARGETS)), key=lambda i: (ONLY_SEQ[i] is None, hp(TARGETS[i])))
    TARGETS = [TARGETS[i] for i in order]
    ONLY_SEQ = [ONLY_SEQ[i] for i in order]
    OV_SEQ = [OV_SEQ[i] for i in order]
    NOVIA_SEQ = [NOVIA_SEQ[i] for i in order]
    FLAGS_SEQ = [FLAGS_SEQ[i] for i in order]
out, failed = [], []
for net, only, ovr, novia, flg in zip(TARGETS, ONLY_SEQ, OV_SEQ, NOVIA_SEQ, FLAGS_SEQ):
    if net not in NETS:
        print("unknown net", net)
        continue
    ONLY.pop(net, None)
    if only:
        ONLY[net] = only
    WIDTH[net] = ovr
    FLAGS[net] = flg
    NOVIA.discard(net)
    if novia:
        NOVIA.add(net)
    print(net, flush=True)
    if not route_net(net, out):
        failed.append(net)
json.dump(dict(items=out, failed=failed), open(OUT, "w"))
print("routed items: %d; nets not completed: %s" % (len(out), " ".join(failed) or "none"))
