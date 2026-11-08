#!/usr/bin/env python3
"""Plane connections and switch-node copper for Scaffold Rev 2 (KiCad Python).

Run after fanout.py, before routing:  <kicad python> hw/rev2/tools/stitch.py

1. Every SMD pad of a plane net gets a short track and a via to its plane:
   GND (In1/In4 everywhere), and the In3 rails (1V0, 1V8, 3V3_FPGA,
   VCC_IO_FPGA, VPRE, VIN) where the pad sits over the region of its net.
   The via goes at the first free spot around the pad (clear of all pads,
   vias and tracks of other nets, on both sides).
2. Buck power copper (buck.py template): input loop, bootstrap, switch-node
   zone and output tracks, in group rev2_buck (rebuilt on every run).
3. A few VIN vias joining the In2 VIN zone (buck inputs) to the In3 VIN region.

The autorouter then only has to route signals and the remaining power links.
Items are grouped (rev2_stitch) and removed on re-run.
"""
import math
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buck  # noqa: E402

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
MM = pcbnew.FromMM
GROUP = "rev2_stitch"
IN3_NETS = {"1V0", "1V8", "3V3_FPGA", "VCC_IO_FPGA", "VPRE", "VIN"}
CLEAR = 0.2

INCREMENTAL = "--incremental" in sys.argv   # keep existing stitching (routes attach to it)
board = pcbnew.LoadBoard(BOARD)
group = None
for g in list(board.Groups()):
    if g.GetName() == GROUP:
        if INCREMENTAL:
            group = g
            continue
        for item in list(g.GetItems()):
            board.Delete(item)
        board.Delete(g)
if group is None:
    group = pcbnew.PCB_GROUP(board)
    group.SetName(GROUP)
    board.Add(group)
# Buck copper: always rebuilt (the regulators are placed by template).
for g in list(board.Groups()):
    if g.GetName() == "rev2_buck":
        for item in list(g.GetItems()):
            board.Delete(item)
        board.Delete(g)
for z in list(board.Zones()):
    if z.GetZoneName() == "switch node":
        board.Delete(z)            # older box-shaped switch-node zones
bgroup = pcbnew.PCB_GROUP(board)
bgroup.SetName("rev2_buck")
board.Add(bgroup)


def badd(item):
    board.Add(item)
    bgroup.AddItem(item)


for parts, _, _ in buck.PLAN:
    buck.copper(board, parts, badd)
buck_items = {i.m_Uuid.AsString() for i in bgroup.GetItems()}
pcbnew.ZONE_FILLER(board).Fill(board.Zones())

# Plane regions of the stitched rails: In3, plus the VIN zone on In2.
in3_zones = [z for z in board.Zones() if z.GetLayer() in (pcbnew.In2_Cu, pcbnew.In3_Cu) and z.GetNetname() != "GND"]
edge = board.GetBoardEdgesBoundingBox()

# Obstacles: pad boxes and vias/tracks, kept up to date as vias are added.
pads = []
for fp in board.GetFootprints():
    for p in fp.Pads():
        b = p.GetBoundingBox()
        pads.append((pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()),
                     pcbnew.ToMM(b.GetBottom()), p.GetNetname(), p.IsOnLayer(pcbnew.F_Cu), p.IsOnLayer(pcbnew.B_Cu),
                     p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD))
vias = [(pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y), pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2,
         t.GetNetname()) for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
segments = [(pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y), pcbnew.ToMM(t.GetEnd().x),
             pcbnew.ToMM(t.GetEnd().y), pcbnew.ToMM(t.GetWidth()) / 2, t.GetNetname(), t.GetLayer())
            for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]


def seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L = dx * dx + dy * dy
    u = 0 if L == 0 else max(0, min(1, ((px - x0) * dx + (py - y0) * dy) / L))
    return math.hypot(px - (x0 + u * dx), py - (y0 + u * dy))


def box_dist(px, py, b):
    return math.hypot(max(b[0] - px, 0, px - b[2]), max(b[1] - py, 0, py - b[3]))


def via_free(x, y, r, net):
    if not (pcbnew.ToMM(edge.GetLeft()) + 1 < x < pcbnew.ToMM(edge.GetRight()) - 1
            and pcbnew.ToMM(edge.GetTop()) + 1 < y < pcbnew.ToMM(edge.GetBottom()) - 1):
        return False
    for b in pads:
        if b[4] != net and box_dist(x, y, b) < r + CLEAR:
            return False
        if b[7] and box_dist(x, y, b) < r + 0.3:     # holes: keep away even on same net
            return False
    for (vx, vy, vr, vn) in vias:
        if math.hypot(vx - x, vy - y) < r + vr + (CLEAR if vn != net else 0.15):
            return False
    for (x0, y0, x1, y1, w, n, layer) in segments:
        if n != net and seg_dist(x, y, x0, y0, x1, y1) < r + w + CLEAR:
            return False
    return True


def seg_seg_dist(a0, a1, b0, b1):
    return min(seg_dist(a0[0], a0[1], b0[0], b0[1], b1[0], b1[1]), seg_dist(a1[0], a1[1], b0[0], b0[1], b1[0], b1[1]),
               seg_dist(b0[0], b0[1], a0[0], a0[1], a1[0], a1[1]), seg_dist(b1[0], b1[1], a0[0], a0[1], a1[0], a1[1])) \
        if not _cross(a0, a1, b0, b1) else 0.0


def _cross(p1, p2, p3, p4):
    d = lambda a, b, c: (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return d(p1, p2, p3) * d(p1, p2, p4) < 0 and d(p3, p4, p1) * d(p3, p4, p2) < 0


def track_free(x0, y0, x1, y1, w, net, layer, own_box):
    for t in (0.25, 0.5, 0.75, 1.0):
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        for b in pads:
            if b[4] != net and b is not own_box and box_dist(x, y, b) < w / 2 + CLEAR \
                    and (b[5] if layer == pcbnew.F_Cu else b[6]):
                return False
    # tracks of other nets on the same layer, and vias of other nets
    for (sx0, sy0, sx1, sy1, sw, n, sl) in segments:
        if n != net and sl == layer and seg_seg_dist((x0, y0), (x1, y1), (sx0, sy0), (sx1, sy1)) < w / 2 + sw + CLEAR:
            return False
    for (vx, vy, vr, vn) in vias:
        if vn != net and seg_dist(vx, vy, x0, y0, x1, y1) < w / 2 + vr + CLEAR:
            return False
    return True


def in_region(net, x, y):
    if net == "GND":
        return True
    pt = pcbnew.VECTOR2I(MM(x), MM(y))
    for z in in3_zones:
        if z.GetNetname() == net and z.HitTestFilledArea(z.GetLayer(), pt):
            return True
    return False


def add(item):
    board.Add(item)
    group.AddItem(item)


stitched, skipped = 0, []
routed = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK" and t.m_Uuid.AsString() not in buck_items]
fanned = {(round(pcbnew.ToMM(p.x), 3), round(pcbnew.ToMM(p.y), 3)) for t in routed for p in (t.GetStart(), t.GetEnd())}
for fp in board.GetFootprints():
    if fp.GetReference() == "U100" or "SAMTEC_SMA" in fp.GetFPIDAsString():
        continue      # BGA: fanout.py; edge SMA connectors: ground pads at the board edge, joined by the pours
        # (not "SMA" alone: that also matches the DO-214AC TVS diodes, whose ground needs plane vias)
    for p in fp.Pads():
        net = p.GetNetname()
        if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD or not (net == "GND" or net in IN3_NETS):
            continue
        cx, cy = pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)
        if (round(cx, 3), round(cy, 3)) in fanned:
            continue          # already connected by fanout.py
        layer = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
        sz = p.GetSize(layer)
        hx, hy = pcbnew.ToMM(sz.x) / 2, pcbnew.ToMM(sz.y) / 2
        rmax = max(hx, hy)
        big = net in ("GND", "VPRE", "VIN") and min(hx, hy) > 0.5
        vd, vdr = (0.6, 0.3) if big else (0.45, 0.2)
        w = min(0.5 if big else 0.3, 2 * min(hx, hy))
        own = next((b for b in pads if abs((b[0] + b[2]) / 2 - cx) < 1e-3 and abs((b[1] + b[3]) / 2 - cy) < 1e-3), None)
        done = False
        # large pads of plane nets (TVS diodes, inductor terminals): three vias
        want = 3 if big and min(hx, hy) > 0.7 else 1
        have = sum(1 for (vx, vy, _, vn) in vias if vn == net and box_dist(vx, vy, own) < 1.8) if own and INCREMENTAL else 0
        got = 0
        if have >= want:
            continue
        for dist in (rmax + 0.45, rmax + 0.75, rmax + 1.1, rmax + 1.6):
            for k in range(16):
                a = 2 * math.pi * k / 16
                x, y = cx + dist * math.cos(a), cy + dist * math.sin(a)
                if not in_region(net, x, y) or not via_free(x, y, vd / 2, net):
                    continue
                if not track_free(cx, cy, x, y, w, net, layer, own):
                    continue
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
                v.SetWidth(MM(vd))
                v.SetDrill(MM(vdr))
                v.SetNet(p.GetNet())
                add(v)
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(p.GetPosition())
                t.SetEnd(pcbnew.VECTOR2I(MM(x), MM(y)))
                t.SetWidth(MM(w))
                t.SetLayer(layer)
                t.SetNet(p.GetNet())
                add(t)
                vias.append((x, y, vd / 2, net))
                segments.append((cx, cy, x, y, w / 2, net, layer))
                stitched += 1
                got += 1
                if have + got >= want:
                    done = True
                    break
            if done:
                break
        if not got:
            skipped.append("%s.%s(%s)" % (fp.GetReference(), p.GetNumber(), net))

# VIN ties: vias in the strip where the In2 VIN zone overlaps the In3 VIN region.
ties = 0
for x10 in range(520, 880, 5):
    x, y = x10 / 10, 57.75
    if ties >= 6 or not (in_region("VIN", x, y) and all(
            z.HitTestFilledArea(z.GetLayer(), pcbnew.VECTOR2I(MM(x), MM(y)))
            for z in in3_zones if z.GetNetname() == "VIN" and z.GetLayer() == pcbnew.In2_Cu)):
        continue
    if not via_free(x, y, 0.3, "VIN") or any(math.hypot(vx - x, vy - y) < 4 for vx, vy, _, vn in vias if vn == "VIN"):
        continue
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    v.SetWidth(MM(0.6))
    v.SetDrill(MM(0.3))
    v.SetNet(board.FindNet("VIN"))
    add(v)
    vias.append((x, y, 0.3, "VIN"))
    ties += 1

pcbnew.ZONE_FILLER(board).Fill(board.Zones())
pcbnew.SaveBoard(BOARD, board)
print("plane vias: %d; VIN ties: %d; pads without room for a via: %d %s"
      % (stitched, ties, len(skipped), " ".join(skipped[:30])))
