#!/usr/bin/env python3
"""Widens power tracks where there is room, and doubles up their vias
(KiCad Python).

  <kicad python> hw/rev2/tools/widen.py NET=W1,W2,... [NET=...] [--vias NET=N ...]
                                         [--link NET:LAYER:X0,Y0,X1,Y1:W1,W2 ...]
                                         [--via NET:X,Y ...]

Every track of NET (outer layers only) is tried at each width in turn,
widest first, and keeps the first one that clears every other-net pad,
track, via and zone fill on its layer (the outer ground pours excepted:
they refill around it) by the net-class clearance. With --vias, every via
of NET where the net changes layer gets up to N-1 companions: 0.6/0.3 mm
vias within 1.5 mm, joined to it by a track on each layer that has the
net's copper at the via. --link adds a straight track (the widest width
that clears) between two points of the net, e.g. a second path beside a
via that has no room for companions; --via adds a 0.6/0.3 mm via if it
clears every layer (links are added first, so a via can land on one). Added items go to group rev2_power.
"""
import math
import os
import sys

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
MM, T = pcbnew.FromMM, pcbnew.ToMM
CLEAR = MM(0.2)
OUTER = (pcbnew.F_Cu, pcbnew.B_Cu)

widths, vcount, links, extra = {}, {}, [], []
mode = widths
for a in sys.argv[1:]:
    if a == "--vias":
        mode = vcount
        continue
    if a == "--link":
        mode = links
        continue
    if a == "--via":
        mode = extra
        continue
    if mode is extra:
        n, pt = a.split(":")
        extra.append((n, [float(v) for v in pt.split(",")]))
        continue
    if mode is links:
        n, lay, pts, ws = a.split(":")
        links.append((n, lay, [float(v) for v in pts.split(",")], [float(v) for v in ws.split(",")]))
        continue
    n, v = a.split("=")
    mode[n] = [float(x) for x in v.split(",")] if mode is widths else int(v)

b = pcbnew.LoadBoard(BOARD)
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
group = next((g for g in b.Groups() if g.GetName() == "rev2_power"), None)
if group is None:
    group = pcbnew.PCB_GROUP(b)
    group.SetName("rev2_power")
    b.Add(group)


def obstacles(layer, net, zones=True):
    """Shapes of other-net copper on a layer (pads, tracks, vias, zone fills, holes)."""
    out = []
    if not zones:
        zones_ = []
    else:
        zones_ = list(b.Zones())
    for t in b.GetTracks():
        if t.GetNetname() != net and t.IsOnLayer(layer):
            out.append((t.GetBoundingBox(), t.GetEffectiveShape(layer), t))
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() != net and (p.IsOnLayer(layer) or p.GetDrillSize().x > 0):
                bb = p.GetBoundingBox()
                if p.IsOnLayer(layer) and p.FlashLayer(layer):
                    out.append((bb, p.GetEffectiveShape(layer), p))
                elif p.GetDrillSize().x > 0:
                    out.append((bb, p.GetEffectiveHoleShape(), p))
    for z in zones_:
        if z.GetIsRuleArea() or z.GetNetname() == net or not z.IsOnLayer(layer):
            continue
        if z.GetZoneName() == "GND pour":
            continue
        ps = z.GetFilledPolysList(layer)
        if ps.OutlineCount():
            out.append((z.GetBoundingBox(), ps, z))
    return out


def clear_of(shape, bbox, obs, clearance=CLEAR):
    bb = pcbnew.BOX2I(bbox.GetOrigin(), bbox.GetSize())
    bb.Inflate(clearance)
    for obb, osh, _ in obs:
        if not bb.Intersects(obb):
            continue
        if osh.Collide(shape, clearance - 1):
            return False
    return True


outline = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(outline, False)
outline.Deflate(MM(0.4), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, MM(0.01))


def inside(item):
    """The item's copper stays 0.4 mm inside the board outline (corners of its bounding box)."""
    bb = item.GetBoundingBox()
    return all(outline.Contains(pcbnew.VECTOR2I(x, y)) for x in (bb.GetLeft(), bb.GetRight())
               for y in (bb.GetTop(), bb.GetBottom()))


changed = 0
for net, ws in widths.items():
    for layer in OUTER:
        obs = obstacles(layer, net)
        for t in [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == net and t.GetLayer() == layer]:
            w0 = t.GetWidth()
            for w in sorted(ws, reverse=True):
                if MM(w) <= w0:
                    break
                t.SetWidth(MM(w))
                if clear_of(t.GetEffectiveShape(layer), t.GetBoundingBox(), obs) and inside(t):
                    changed += 1
                    break
                t.SetWidth(w0)
print("widened %d track segments" % changed)

added = 0
for net, want in vcount.items():
    vias = [v for v in b.GetTracks() if v.GetClass() == "PCB_VIA" and v.GetNetname() == net]
    tracks = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == net]
    for v in vias:
        p = v.GetPosition()
        lays = {t.GetLayer() for t in tracks if t.GetStart() == p or t.GetEnd() == p}
        if len(lays) < 2:
            continue                       # not a layer change (or a plane via)
        width = max(t.GetWidth() for t in tracks if t.GetStart() == p or t.GetEnd() == p)
        width = min(width, MM(0.8))
        have = sum(1 for o in vias if o is not v and (o.GetPosition() - p).EuclideanNorm() < MM(1.6))
        got = 0
        # inner-layer planes refill around a new via; outer layers keep their zones (switch nodes)
        allcu = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.B_Cu]
        obs = {l: obstacles(l, net, zones=l in OUTER) for l in allcu}
        for dist in (0.9, 1.2, 1.5):
            for k in range(16):
                if have + got + 1 >= want:
                    break
                a = 2 * math.pi * k / 16
                q = pcbnew.VECTOR2I(p.x + MM(dist * math.cos(a)), p.y + MM(dist * math.sin(a)))
                nv = pcbnew.PCB_VIA(b)
                nv.SetPosition(q)
                nv.SetWidth(MM(0.6))
                nv.SetDrill(MM(0.3))
                nv.SetNet(v.GetNet())
                if not all(clear_of(nv.GetEffectiveShape(l), nv.GetBoundingBox(), obs[l]) for l in allcu):
                    continue
                stubs = []
                for l in lays:
                    s = pcbnew.PCB_TRACK(b)
                    s.SetStart(p)
                    s.SetEnd(q)
                    s.SetWidth(width)
                    s.SetLayer(l)
                    s.SetNet(v.GetNet())
                    stubs.append(s)
                if not all(clear_of(s.GetEffectiveShape(s.GetLayer()), s.GetBoundingBox(), obs[s.GetLayer()]) for s in stubs):
                    continue
                too_close = any((o.GetPosition() - q).EuclideanNorm() < MM(0.75) for o in
                                [x for x in b.GetTracks() if x.GetClass() == "PCB_VIA" and x.GetNetname() == net])
                if too_close:
                    continue
                if not all(inside(s) for s in stubs) or not inside(nv):
                    continue
                for item in [nv] + stubs:
                    b.Add(item)
                    group.AddItem(item)
                got += 1
                added += 1
        print("  %s via at (%.2f, %.2f): %d companions added (%d already near)" % (net, T(p.x), T(p.y), got, have))
for net, lay, (x0, y0, x1, y1), ws in links:
    layer = b.GetLayerID(lay)
    obs = obstacles(layer, net)
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pcbnew.VECTOR2I(MM(x0), MM(y0)))
    t.SetEnd(pcbnew.VECTOR2I(MM(x1), MM(y1)))
    t.SetLayer(layer)
    t.SetNet(b.FindNet(net))
    for w in sorted(ws, reverse=True):
        t.SetWidth(MM(w))
        if clear_of(t.GetEffectiveShape(layer), t.GetBoundingBox(), obs) and inside(t):
            b.Add(t)
            group.AddItem(t)
            print("  link %s %s (%.2f, %.2f)-(%.2f, %.2f) at %.2f mm" % (net, lay, x0, y0, x1, y1, w))
            break
    else:
        print("  link %s %s (%.2f, %.2f)-(%.2f, %.2f): no room" % (net, lay, x0, y0, x1, y1))
ALL = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.B_Cu]
for net, (x, y) in extra:
    nv = pcbnew.PCB_VIA(b)
    nv.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    nv.SetWidth(MM(0.6))
    nv.SetDrill(MM(0.3))
    nv.SetNet(b.FindNet(net))
    bad = [b.GetLayerName(l) for l in ALL
           if not clear_of(nv.GetEffectiveShape(l), nv.GetBoundingBox(), obstacles(l, net, zones=l in OUTER))]
    near = any((o.GetPosition() - nv.GetPosition()).EuclideanNorm() < MM(0.75)
               for o in b.GetTracks() if o.GetClass() == "PCB_VIA" and o.GetNetname() == net)
    if bad or near:
        print("  via %s (%.2f, %.2f): blocked on %s" % (net, x, y, " ".join(bad) or "a via of the same net"))
        continue
    b.Add(nv)
    group.AddItem(nv)
    added += 1
    print("  via %s (%.2f, %.2f) added" % (net, x, y))
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(BOARD, b)
print("added %d vias" % added)
