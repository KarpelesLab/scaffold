#!/usr/bin/env python3
"""Exports the copper of some nets for the simulation scripts (KiCad Python).

  <kicad python> hw/rev2/sim/export_copper.py OUT.json NET1,NET2,... [X0 Y0 X1 Y1]

For each net and copper layer: the merged copper polygons (tracks, pads,
filled zones), plus vias and plated holes (position, drill, layer span) and
the pads (reference, number, position, layer). With a box, every net that
has copper inside it is exported (clipped to the box) and NETS only selects
the nets to keep their names; others are exported as "other".
"""
import json
import os
import sys

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
T = pcbnew.ToMM
CU = [(pcbnew.F_Cu, "F"), (pcbnew.In1_Cu, "In1"), (pcbnew.In2_Cu, "In2"), (pcbnew.In3_Cu, "In3"),
      (pcbnew.In4_Cu, "In4"), (pcbnew.B_Cu, "B")]
ERR = pcbnew.FromMM(0.005)


def polys(ps):
    out = []
    for i in range(ps.OutlineCount()):
        rings = [ps.Outline(i)] + [ps.Hole(i, h) for h in range(ps.HoleCount(i))]
        out.append([[(round(T(r.CPoint(k).x), 4), round(T(r.CPoint(k).y), 4)) for k in range(r.PointCount())]
                    for r in rings])
    return out


def main():
    out_path, nets = sys.argv[1], set(sys.argv[2].split(","))
    box = [float(v) for v in sys.argv[3:7]] if len(sys.argv) >= 7 else None
    b = pcbnew.LoadBoard(BOARD)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    clip = None
    if box:
        clip = pcbnew.SHAPE_POLY_SET()
        r = pcbnew.SHAPE_LINE_CHAIN()
        for x, y in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])):
            r.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        r.SetClosed(True)
        clip.AddOutline(r)

    def name(n):
        return n if n in nets else ("other" if n else "")

    def keep(n):
        return n in nets or (box is not None and n)

    acc = {}

    def add(n, lname, ps):
        key = (name(n), lname)
        if key not in acc:
            acc[key] = pcbnew.SHAPE_POLY_SET()
        acc[key].Append(ps)

    vias, holes, pads = [], [], []
    for t in b.GetTracks():
        n = t.GetNetname()
        if not keep(n):
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            vias.append(dict(n=name(n), x=T(p.x), y=T(p.y), d=T(t.GetWidth(pcbnew.F_Cu)), drill=T(t.GetDrillValue()),
                             L=[nm for l, nm in CU if t.IsOnLayer(l)]))
        for l, nm in CU:
            if t.IsOnLayer(l):
                ps = pcbnew.SHAPE_POLY_SET()
                t.TransformShapeToPolygon(ps, l, 0, ERR, pcbnew.ERROR_INSIDE)
                add(n, nm, ps)
    for fp in b.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if not keep(n):
                continue
            pos = p.GetPosition()
            flashed = []
            for l, nm in CU:
                if p.IsOnLayer(l) and p.FlashLayer(l):
                    ps = pcbnew.SHAPE_POLY_SET()
                    p.TransformShapeToPolygon(ps, l, 0, ERR, pcbnew.ERROR_INSIDE)
                    add(n, nm, ps)
                    flashed.append(nm)
            if p.GetDrillSize().x > 0 and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                holes.append(dict(n=name(n), x=T(pos.x), y=T(pos.y), drill=T(min(p.GetDrillSize().x, p.GetDrillSize().y)),
                                  L=flashed))
            if flashed:
                bb = p.GetBoundingBox()
                pads.append(dict(n=name(n), ref=fp.GetReference(), num=p.GetNumber(), x=T(pos.x), y=T(pos.y),
                                 L=flashed, bbox=[T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())]))
    for z in b.Zones():
        if z.GetIsRuleArea() or not keep(z.GetNetname()):
            continue
        for l, nm in CU:
            if z.IsOnLayer(l):
                add(z.GetNetname(), nm, z.GetFilledPolysList(l))
    copper = []
    for (n, lname), ps in acc.items():
        ps.Simplify()
        if clip is not None:
            ps.BooleanIntersection(clip)
        if ps.OutlineCount():
            copper.append(dict(n=n, L=lname, poly=polys(ps)))
    if box:
        inside = lambda o: box[0] <= o["x"] <= box[2] and box[1] <= o["y"] <= box[3]
        vias, holes, pads = [v for v in vias if inside(v)], [h for h in holes if inside(h)], [p for p in pads if inside(p)]
    json.dump(dict(copper=copper, vias=vias, holes=holes, pads=pads, box=box), open(out_path, "w"))
    print("exported %d polygon sets, %d vias, %d holes, %d pads" % (len(copper), len(vias), len(holes), len(pads)))


if __name__ == "__main__":
    main()
