#!/usr/bin/env python3
"""Adds the routes found by maze.py to the board (KiCad Python, group rev2_maze).

  <kicad python> hw/rev2/tools/maze_apply.py ROUTES.json
"""
import json
import os
import sys

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
MM = pcbnew.FromMM
LAYERS = {"F": pcbnew.F_Cu, "In2": pcbnew.In2_Cu, "B": pcbnew.B_Cu}

b = pcbnew.LoadBoard(BOARD)
group = next((g for g in b.Groups() if g.GetName() == "rev2_maze"), None)
if group is None:
    group = pcbnew.PCB_GROUP(b)
    group.SetName("rev2_maze")
    b.Add(group)
r = json.load(open(sys.argv[1]))
nt = nv = 0
for it in r["items"]:
    net = b.FindNet(it["n"])
    if "seg" in it:
        x0, y0, x1, y1, w = it["seg"]
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(pcbnew.VECTOR2I(MM(x0), MM(y0)))
        t.SetEnd(pcbnew.VECTOR2I(MM(x1), MM(y1)))
        t.SetWidth(MM(w))
        t.SetLayer(LAYERS[it["L"][0]])
        nt += 1
    else:
        x, y, _ = it["circ"]
        t = pcbnew.PCB_VIA(b)
        t.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
        t.SetWidth(MM(it["via"][0]))
        t.SetDrill(MM(it["via"][1]))
        nv += 1
    t.SetNet(net)
    b.Add(t)
    group.AddItem(t)
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(BOARD, b)
print("added %d tracks, %d vias; not completed: %s" % (nt, nv, " ".join(r["failed"]) or "none"))
