#!/usr/bin/env python3
"""Exports the board copper for maze.py (KiCad Python).

  <kicad python> hw/rev2/tools/maze_export.py OUT.json

Every copper item with its net, layers and geometry (mm): tracks as
segments, vias as circles (plus a layer link), pads as polygons per layer
(plus a layer link for plated holes), holes, zone fills (except ground and
the outer pours, which refill around new tracks), track keepouts, the board
outline and the net classes.
"""
import fnmatch
import json
import os
import sys

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
T = pcbnew.ToMM
CU = [(pcbnew.F_Cu, "F"), (pcbnew.In1_Cu, "In1"), (pcbnew.In2_Cu, "In2"), (pcbnew.In3_Cu, "In3"),
      (pcbnew.In4_Cu, "In4"), (pcbnew.B_Cu, "B")]


def polys(ps):
    out = []
    for i in range(ps.OutlineCount()):
        rings = [ps.Outline(i)] + [ps.Hole(i, h) for h in range(ps.HoleCount(i))]
        out.append([[(round(T(r.CPoint(k).x), 4), round(T(r.CPoint(k).y), 4)) for k in range(r.PointCount())]
                    for r in rings])
    return out


def main():
    b = pcbnew.LoadBoard(BOARD)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    items, nets = [], {}

    # Net classes from the project file (the NETCLASS object is not wrapped).
    pro = json.load(open(os.path.splitext(BOARD)[0] + ".kicad_pro"))["net_settings"]
    classes = {c["name"]: c for c in pro["classes"]}
    patterns = [(p["pattern"], p["netclass"]) for p in pro.get("netclass_patterns", [])]

    def netclass(name):
        if name not in nets:
            cname = next((c for pat, c in patterns if fnmatch.fnmatchcase(name, pat)), "Default")
            c = classes[cname]
            nets[name] = dict(w=c["track_width"], cl=c["clearance"], vd=c["via_diameter"], vdr=c["via_drill"], cls=cname)
        return nets[name]

    for t in b.GetTracks():
        n = t.GetNetname()
        if n:
            netclass(n)
        if t.GetClass() == "PCB_VIA":
            lay = [nm for l, nm in CU if t.IsOnLayer(l)]
            p = t.GetPosition()
            items.append(dict(n=n, L=lay, circ=[T(p.x), T(p.y), T(t.GetWidth(pcbnew.F_Cu)) / 2], link=[T(p.x), T(p.y)]))
        else:
            s, e = t.GetStart(), t.GetEnd()
            items.append(dict(n=n, L=[nm for l, nm in CU if l == t.GetLayer()],
                              seg=[T(s.x), T(s.y), T(e.x), T(e.y), T(t.GetWidth())]))
    pads = []
    for fp in b.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n:
                netclass(n)
            pos = p.GetPosition()
            flashed = []
            for l, nm in CU:
                if p.IsOnLayer(l) and p.FlashLayer(l):
                    ps = pcbnew.SHAPE_POLY_SET()
                    p.TransformShapeToPolygon(ps, l, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_OUTSIDE)
                    items.append(dict(n=n, L=[nm], poly=polys(ps), pad=True))
                    flashed.append(nm)
            if p.GetDrillSize().x > 0:
                pth = p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
                r = T(max(p.GetDrillSize().x, p.GetDrillSize().y)) / 2
                items.append(dict(n=n if pth else "", L=[nm for _, nm in CU], circ=[T(pos.x), T(pos.y), r], hole=True))
                if pth and len(flashed) > 1:
                    items.append(dict(n=n, L=flashed, link=[T(pos.x), T(pos.y)]))
            if n and flashed:
                pads.append(dict(n=n, x=T(pos.x), y=T(pos.y), L=flashed[0], ref="%s.%s" % (fp.GetReference(), p.GetNumber())))
    for z in b.Zones():
        lay = [(l, nm) for l, nm in CU if z.IsOnLayer(l)]
        if z.GetIsRuleArea():
            if z.GetDoNotAllowTracks():
                items.append(dict(n="", L=[nm for _, nm in lay], poly=polys(z.Outline()), keepout=True))
            continue
        if z.GetNetname() == "GND" or z.GetZoneName() == "GND pour":
            continue
        for l, nm in lay:
            items.append(dict(n=z.GetNetname(), L=[nm], poly=polys(z.GetFilledPolysList(l)), zone=True))
    outline = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(outline, False)
    bb = b.GetBoardEdgesBoundingBox()
    u = b.FindFootprintByReference("U100").GetPosition()
    json.dump(dict(items=items, pads=pads, nets=nets, outline=polys(outline),
                   bbox=[T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())],
                   align=[T(u.x), T(u.y)], hole_clearance=0.2, edge_clearance=0.3), open(sys.argv[1], "w"))
    print("exported %d items, %d pads, %d nets" % (len(items), len(pads), len(nets)))


if __name__ == "__main__":
    main()
