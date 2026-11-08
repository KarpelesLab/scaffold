#!/usr/bin/env python3
"""Plane connections and switch-node copper for Scaffold Rev 2 (KiCad Python).

Run after fanout.py, before routing:  <kicad python> hw/rev2/tools/stitch.py

1. Every SMD pad of a plane net gets a short track and a via to its plane:
   GND (In1/In4 everywhere), and the In3 rails (1V0, 1V8, 3V3_FPGA,
   VCC_IO_FPGA, VPRE, VIN) where the pad sits over the region of its net.
   The via goes at the first free spot around the pad (clear of all pads,
   vias and tracks of other nets, on both sides).
2. Buck switch nodes (SW_*): a top-layer copper zone from the regulator SW
   pin to the inductor, so that the 3 A loop is a wide copper area.

The autorouter then only has to route signals and the remaining power links.
Items are grouped (rev2_stitch) and removed on re-run.
"""
import math
import os

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
MM = pcbnew.FromMM
GROUP = "rev2_stitch"
IN3_NETS = {"1V0", "1V8", "3V3_FPGA", "VCC_IO_FPGA", "VPRE", "VIN"}
CLEAR = 0.2

import sys
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
pcbnew.ZONE_FILLER(board).Fill(board.Zones())

in3 = {z.GetNetname(): z for z in board.Zones() if z.GetLayer() == pcbnew.In3_Cu}
in3_zones = [z for z in board.Zones() if z.GetLayer() == pcbnew.In3_Cu]
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


def track_free(x0, y0, x1, y1, w, net, layer, own_box):
    for t in (0.25, 0.5, 0.75, 1.0):
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        for b in pads:
            if b[4] != net and b is not own_box and box_dist(x, y, b) < w / 2 + CLEAR \
                    and (b[5] if layer == pcbnew.F_Cu else b[6]):
                return False
    return True


def in_region(net, x, y):
    if net == "GND":
        return True
    pt = pcbnew.VECTOR2I(MM(x), MM(y))
    for z in in3_zones:
        if z.GetNetname() == net and z.HitTestFilledArea(pcbnew.In3_Cu, pt):
            return True
    return False


def add(item):
    board.Add(item)
    group.AddItem(item)


stitched, skipped = 0, []
fanned = {(round(s[0], 3), round(s[1], 3)) for s in segments} | {(round(s[2], 3), round(s[3], 3)) for s in segments}
for fp in board.GetFootprints():
    if fp.GetReference() == "U100" or "SMA" in fp.GetFPIDAsString():
        continue      # BGA: fanout.py; edge SMA: ground pads at the board edge, joined by the pours
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
                done = True
                break
            if done:
                break
        if not done:
            skipped.append("%s.%s(%s)" % (fp.GetReference(), p.GetNumber(), net))

# Switch nodes: copper zone on the top layer spanning the SW pin and the inductor.
sw = 0
SW_NETS = ["/U_Power/SW_VPRE", "/U_Power/SW_1V0", "/U_Power/SW_1V8", "/U_Power/SW_3V3_FPGA"]
for net in ([] if INCREMENTAL else SW_NETS):
    ni = board.FindNet(net)
    pts = [p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname() == net]
    if len(pts) < 2:
        continue
    box = pts[0].GetBoundingBox()
    for p in pts[1:]:
        box.Merge(p.GetBoundingBox())
    z = pcbnew.ZONE(board)
    z.SetLayer(pcbnew.F_Cu)
    z.SetNet(ni)
    z.SetAssignedPriority(20)
    z.SetLocalClearance(MM(0.2))
    z.SetMinThickness(MM(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetZoneName("switch node")
    o = z.Outline()
    o.NewOutline()
    for x, y in ((box.GetLeft(), box.GetTop()), (box.GetRight(), box.GetTop()),
                 (box.GetRight(), box.GetBottom()), (box.GetLeft(), box.GetBottom())):
        o.Append(x, y)
    add(z)
    sw += 1

pcbnew.ZONE_FILLER(board).Fill(board.Zones())
pcbnew.SaveBoard(BOARD, board)
print("plane vias: %d; switch-node zones: %d; pads without room for a via: %d %s"
      % (stitched, sw, len(skipped), " ".join(skipped[:30])))
