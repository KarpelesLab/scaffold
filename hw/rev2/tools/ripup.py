#!/usr/bin/env python3
"""Local rip-up (KiCad Python): deletes routed tracks and vias (Freerouting's
and maze.py's, never the scripted fanout, stitching, buck or bus copper)
crossing the given boxes, then prunes what is left dangling.

  <kicad python> hw/rev2/tools/ripup.py X0 Y0 X1 Y1 [X0 Y0 X1 Y1 ...]   (mm)

Used when a pad is boxed in by earlier routes: rip up around it, route the
boxed-in net first with maze.py, then re-route the nets that were cut.
"""
import os
import sys

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
PROTECTED = ("rev2_fanout", "rev2_stitch", "rev2_buck", "rev2_manual")
T = pcbnew.ToMM

v = [float(a) for a in sys.argv[1:]]
boxes = [tuple(v[i:i + 4]) for i in range(0, len(v), 4)]
b = pcbnew.LoadBoard(BOARD)
keep = set()
for g in b.Groups():
    if g.GetName() in PROTECTED:
        keep |= {i.m_Uuid.AsString() for i in g.GetItems()}


def hits(t):
    if t.GetClass() == "PCB_VIA":
        pts = [t.GetPosition()]
    else:
        s, e = t.GetStart(), t.GetEnd()
        pts = [s + (e - s) * (k / 40.0) for k in range(41)]
    return any(x0 <= T(p.x) <= x1 and y0 <= T(p.y) <= y1 for p in pts for (x0, y0, x1, y1) in boxes)


cut = [t for t in b.GetTracks() if t.m_Uuid.AsString() not in keep and hits(t)]
nets = sorted({t.GetNetname() for t in cut})
for t in cut:
    b.Delete(t)
pruned = 0
while True:
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    dead = [t for t in b.GetTracks() if t.m_Uuid.AsString() not in keep and conn.TestTrackEndpointDangling(t, False)]
    if not dead:
        break
    for t in dead:
        b.Delete(t)
    pruned += len(dead)
pcbnew.SaveBoard(BOARD, b)
print("ripped up %d items, pruned %d; nets cut: %s" % (len(cut), pruned, " ".join(nets)))
