#!/usr/bin/env python3
"""Ground vias inside pads (KiCad Python).

  <kicad python> hw/rev2/tools/thermal.py

1. The TL1963A tab (pad 6, GND) is the regulator's heat path: each tab gets
   a grid of 0.3 mm vias inside the pad down to the In1/In4 ground planes
   and the bottom pour.
2. The ground legs of the edge-mount SMA connectors get a row of vias along
   the pad, so the shield return current reaches the planes at the
   connector instead of wandering through the top pour (their footprints
   have no ground via of their own).

Via-in-pad: the board is ordered with filled and capped vias. A grid
position is skipped when another net's track, via or pad is too close on
any layer, or when its centre is within 0.6 mm of the board edge (the
copper ring then keeps 0.3 mm; the SMA ground legs run along the edge
notch of the connector body). Items are in group
rev2_thermal, rebuilt on every run.
"""
import math
import os

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
MM, T = pcbnew.FromMM, pcbnew.ToMM
GROUP = "rev2_thermal"
TABS = [("U200", "6"), ("U202", "6"), ("U205", "6"), ("U212", "6")]
VIA, DRILL, PITCH, CLEAR = 0.6, 0.3, 1.0, 0.2

board = pcbnew.LoadBoard(BOARD)
for g in list(board.Groups()):
    if g.GetName() == GROUP:
        for item in list(g.GetItems()):
            board.Delete(item)
        board.Delete(g)
group = pcbnew.PCB_GROUP(board)
group.SetName(GROUP)
board.Add(group)

segs = [(T(t.GetStart().x), T(t.GetStart().y), T(t.GetEnd().x), T(t.GetEnd().y), T(t.GetWidth()) / 2, t.GetNetname())
        for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
vias = [(T(t.GetPosition().x), T(t.GetPosition().y), T(t.GetWidth(pcbnew.F_Cu)) / 2, t.GetNetname())
        for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
pads = []
for fp in board.GetFootprints():
    for p in fp.Pads():
        b = p.GetBoundingBox()
        pads.append((T(b.GetLeft()), T(b.GetTop()), T(b.GetRight()), T(b.GetBottom()), p.GetNetname()))


def seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L = dx * dx + dy * dy
    u = 0 if L == 0 else max(0, min(1, ((px - x0) * dx + (py - y0) * dy) / L))
    return math.hypot(px - (x0 + u * dx), py - (y0 + u * dy))


def free(x, y, net):
    r = VIA / 2
    if any(n != net and seg_dist(x, y, x0, y0, x1, y1) < r + w + CLEAR for x0, y0, x1, y1, w, n in segs):
        return False
    if any(math.hypot(vx - x, vy - y) < r + vr + (CLEAR if vn != net else 0.15) for vx, vy, vr, vn in vias):
        return False
    return not any(n != net and math.hypot(max(b0 - x, 0, x - b2), max(b1 - y, 0, y - b3)) < r + CLEAR
                   for b0, b1, b2, b3, n in pads)


outline = pcbnew.SHAPE_POLY_SET()
board.GetBoardPolygonOutlines(outline, False)
outline.Deflate(MM(0.6), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, MM(0.01))
for fp in board.GetFootprints():
    if "SAMTEC_SMA" in fp.GetFPIDAsString():
        TABS += [(fp.GetReference(), p.GetNumber()) for p in fp.Pads() if p.GetNetname() == "GND"]

added = 0
for ref, num in TABS:
    fp = board.FindFootprintByReference(ref)
    pad = next(p for p in fp.Pads() if p.GetNumber() == num)
    b = pad.GetBoundingBox()
    x0, y0, x1, y1 = T(b.GetLeft()), T(b.GetTop()), T(b.GetRight()), T(b.GetBottom())
    m = VIA / 2 + 0.1                       # keep the via ring inside the pad
    nx = max(1, int((x1 - x0 - 2 * m) / PITCH) + 1)
    ny = max(1, int((y1 - y0 - 2 * m) / PITCH) + 1)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    n = 0
    for i in range(nx):
        for j in range(ny):
            x = cx + (i - (nx - 1) / 2) * PITCH
            y = cy + (j - (ny - 1) / 2) * PITCH
            if not free(x, y, pad.GetNetname()) or not outline.Contains(pcbnew.VECTOR2I(MM(x), MM(y))):
                continue
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
            v.SetWidth(MM(VIA))
            v.SetDrill(MM(DRILL))
            v.SetNet(pad.GetNet())
            board.Add(v)
            group.AddItem(v)
            vias.append((x, y, VIA / 2, pad.GetNetname()))
            n += 1
    print("%s.%s: %d of %d thermal vias" % (ref, num, n, nx * ny))
    added += n
pcbnew.ZONE_FILLER(board).Fill(board.Zones())
pcbnew.SaveBoard(BOARD, board)
print("vias in pads: %d" % added)
