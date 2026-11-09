#!/usr/bin/env python3
"""Local rip-up (KiCad Python): deletes routed tracks and vias (Freerouting's
and maze.py's, never the scripted fanout, stitching, buck or bus copper)
crossing the given boxes, then prunes what is left dangling.

  <kicad python> hw/rev2/tools/ripup.py [--stitch] [--nets N1,N2] [X0 Y0 X1 Y1 ...]   (mm)

Used when a pad is boxed in by earlier routes: rip up around it, route the
boxed-in net first with maze.py, then re-route the nets that were cut.
"""
import os
import sys

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
PROTECTED = ("rev2_fanout", "rev2_stitch", "rev2_buck", "rev2_manual", "rev2_thermal", "rev2_power")
T = pcbnew.ToMM

STITCH = "--stitch" in sys.argv     # also remove plane vias (re-add with stitch.py --incremental)
if STITCH:
    PROTECTED = tuple(g for g in PROTECTED if g != "rev2_stitch")
# --nets N1,N2: rip up all routed copper of these nets (anywhere)
NETS = set()
args = sys.argv[1:]
if "--nets" in args:
    i = args.index("--nets")
    NETS = set(args[i + 1].split(","))
    del args[i:i + 2]
v = [float(a) for a in args if a != "--stitch"]
boxes = [tuple(v[i:i + 4]) for i in range(0, len(v), 4)]
b = pcbnew.LoadBoard(BOARD)
keep = set()
for g in b.Groups():
    if g.GetName() in PROTECTED:
        keep |= {i.m_Uuid.AsString() for i in g.GetItems()}


def hits(t):
    if t.GetClass() == "PCB_VIA":
        p = t.GetPosition()
        pts = [(T(p.x), T(p.y))]
    else:
        s, e = t.GetStart(), t.GetEnd()
        sx, sy, ex, ey = T(s.x), T(s.y), T(e.x), T(e.y)
        pts = [(sx + (ex - sx) * k / 40.0, sy + (ey - sy) * k / 40.0) for k in range(41)]
    return any(x0 <= x <= x1 and y0 <= y <= y1 for (x, y) in pts for (x0, y0, x1, y1) in boxes)


cut = [t for t in b.GetTracks() if t.m_Uuid.AsString() not in keep and (hits(t) or t.GetNetname() in NETS)]
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
