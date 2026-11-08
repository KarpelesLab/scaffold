#!/usr/bin/env python3
"""TPS62933P buck layout template for Scaffold Rev 2 (KiCad Python, shared
by place.py and stitch.py).

Local frame: regulator (SOT-583-8, pins 1-4 left, 5-8 right) at the origin,
unrotated, millimetres, y down.

    Cin bulk | Cin 100n | IC | Cbst | L (SW pad -> OUT pad) | Cout column
                         FB divider above the IC

- Input caps right at VIN (pin 3) / GND (pin 4): the 3 A switching loop.
- Bootstrap cap at BST (pin 6) / SW (pin 5); SW copper zone from pin 5 over
  the Cbst SW pad to the inductor.
- Output caps against the inductor OUT pad, joined by a wide track.
- Above the IC a 0.9 mm corridor is left for EN (pin 2), PG (pin 7) and FB
  (pin 8); the FB divider sits above it.
"""
import math

import pcbnew

MM = pcbnew.FromMM
T = pcbnew.ToMM

# Passive positions, as (pad 1, pad 2) targets in the local frame.
CIN_S = ((-2.15, -0.05), (-2.15, 1.51))
CIN_B = ((-4.45, -1.0), (-4.45, 1.96))
CBST = ((2.2, -0.6), (2.2, 0.96))
RTOP = ((1.32, -3.05), (-0.32, -3.05))     # pad 1 OUT (right), pad 2 FB (left)
RBOT = ((-0.32, -4.65), (1.32, -4.65))     # pad 1 FB (left), pad 2 GND (right)
L_Y = 0.75


def rot(p, theta):
    """Rotates a local point by theta degrees (0/90/180/270), screen frame."""
    a = math.radians(theta)
    x, y = p
    return (x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a))


def court_half(fp):
    """Half width/height of a footprint courtyard (unrotated part)."""
    c = fp.GetCourtyard(pcbnew.F_CrtYd)
    if c.OutlineCount() == 0:
        c = fp.GetCourtyard(pcbnew.B_CrtYd)
    bb = c.BBox() if c.OutlineCount() else fp.GetBoundingBox(False)
    w, h = T(bb.GetWidth()) / 2, T(bb.GetHeight()) / 2
    o = round(fp.GetOrientation().AsDegrees()) % 180
    return (h, w) if o == 90 else (w, h)


def inductor_pads(lfp):
    """Pad half pitch and courtyard half width of the (unrotated) inductor."""
    p = sorted(lfp.Pads(), key=lambda q: q.GetNumber())
    pitch = math.hypot(T(p[1].GetPosition().x - p[0].GetPosition().x),
                       T(p[1].GetPosition().y - p[0].GetPosition().y)) / 2
    cw, ch = court_half(lfp)
    return pitch, max(cw, ch), min(cw, ch)


def targets(lfp, ncout):
    """Local pad targets of the inductor and output caps."""
    half, cwide, _ = inductor_pads(lfp)
    l1x = 2.2 + 0.775 + 0.05 + (cwide - half)      # Cbst courtyard edge + gap
    l2x = l1x + 2 * half
    lcx = l1x + half
    cx = lcx + cwide + 1.745 + 0.05                  # 0805 horizontal courtyard half
    couts = [((cx - 0.95, L_Y + (k - (ncout - 1) / 2) * 2.3), (cx + 0.95, L_Y + (k - (ncout - 1) / 2) * 2.3))
             for k in range(ncout)]
    return ((l1x, L_Y), (l2x, L_Y)), couts


def pads12(fp):
    p = {q.GetNumber(): q for q in fp.Pads()}
    return p["1"], p["2"]


def put_two_pad(fp, t1, t2, origin, theta):
    """Places a two-pad part so that pad 1/pad 2 land on the targets."""
    g1 = rot(t1, theta)
    g2 = rot(t2, theta)
    mid = ((g1[0] + g2[0]) / 2 + origin[0], (g1[1] + g2[1]) / 2 + origin[1])
    best = None
    for o in (0, 90, 180, 270):
        fp.SetOrientationDegrees(o)
        fp.SetPosition(pcbnew.VECTOR2I(MM(mid[0]), MM(mid[1])))
        a, b = pads12(fp)
        pc = ((T(a.GetPosition().x) + T(b.GetPosition().x)) / 2, (T(a.GetPosition().y) + T(b.GetPosition().y)) / 2)
        # correct for off-centre footprint origins
        fp.SetPosition(pcbnew.VECTOR2I(MM(2 * mid[0] - pc[0]), MM(2 * mid[1] - pc[1])))
        a, b = pads12(fp)
        err = math.hypot(T(a.GetPosition().x) - origin[0] - g1[0], T(a.GetPosition().y) - origin[1] - g1[1])
        if best is None or err < best[0]:
            best = (err, o)
    fp.SetOrientationDegrees(best[1])
    fp.SetPosition(pcbnew.VECTOR2I(MM(mid[0]), MM(mid[1])))
    a, b = pads12(fp)
    pc = ((T(a.GetPosition().x) + T(b.GetPosition().x)) / 2, (T(a.GetPosition().y) + T(b.GetPosition().y)) / 2)
    fp.SetPosition(pcbnew.VECTOR2I(MM(2 * mid[0] - pc[0]), MM(2 * mid[1] - pc[1])))


IC_PIN1 = (-0.74, -0.75)


def put_ic(fp, origin, theta):
    best = None
    for o in (0, 90, 180, 270):
        fp.SetOrientationDegrees(o)
        fp.SetPosition(pcbnew.VECTOR2I(MM(origin[0]), MM(origin[1])))
        p1 = next(q for q in fp.Pads() if q.GetNumber() == "1")
        g = rot(IC_PIN1, theta)
        err = math.hypot(T(p1.GetPosition().x) - origin[0] - g[0], T(p1.GetPosition().y) - origin[1] - g[1])
        if best is None or err < best[0]:
            best = (err, o)
    fp.SetOrientationDegrees(best[1])
    fp.SetPosition(pcbnew.VECTOR2I(MM(origin[0]), MM(origin[1])))


def ic_frame(fp):
    """(origin, theta) of a placed regulator, inverse of put_ic."""
    origin = (T(fp.GetPosition().x), T(fp.GetPosition().y))
    p1 = next(q for q in fp.Pads() if q.GetNumber() == "1")
    best = None
    for theta in (0, 90, 180, 270):
        g = rot(IC_PIN1, theta)
        err = math.hypot(T(p1.GetPosition().x) - origin[0] - g[0], T(p1.GetPosition().y) - origin[1] - g[1])
        if best is None or err < best[0]:
            best = (err, theta)
    return origin, best[1]


def place(board, parts, theta, topleft):
    """parts: dict ic, l, cin_b, cin_s, cbst, couts (list), rtop, rbot (references).
    Places the buck with the template bounding box at topleft (mm)."""
    fp = {k: (board.FindFootprintByReference(v) if isinstance(v, str) else [board.FindFootprintByReference(r) for r in v])
          for k, v in parts.items()}
    lf = fp["l"]
    lf.SetOrientationDegrees(0)
    (l1, l2), couts = targets(lf, len(fp["couts"]))
    origin = (0.0, 0.0)
    put_ic(fp["ic"], origin, theta)
    for key, t in (("cin_s", CIN_S), ("cin_b", CIN_B), ("cbst", CBST), ("rtop", RTOP), ("rbot", RBOT), ("l", (l1, l2))):
        put_two_pad(fp[key], t[0], t[1], origin, theta)
    for f, t in zip(fp["couts"], couts):
        put_two_pad(f, t[0], t[1], origin, theta)
    allfp = [fp[k] for k in ("ic", "l", "cin_b", "cin_s", "cbst", "rtop", "rbot")] + fp["couts"]
    box = None
    for f in allfp:
        c = f.GetCourtyard(pcbnew.F_CrtYd)
        bb = c.BBox() if c.OutlineCount() else f.GetBoundingBox(False)
        if box is None:
            box = pcbnew.BOX2I(bb.GetPosition(), bb.GetSize())
        else:
            box.Merge(bb)
    dx, dy = MM(topleft[0]) - box.GetLeft(), MM(topleft[1]) - box.GetTop()
    for f in allfp:
        f.Move(pcbnew.VECTOR2I(dx, dy))
    return T(box.GetWidth()), T(box.GetHeight())


def copper(board, parts, add):
    """Buck power copper on F.Cu: input loop, bootstrap, SW zone, output.
    add(item) adds an item to the board (and to the caller's group)."""
    get = board.FindFootprintByReference
    ic = get(parts["ic"])
    origin, theta = ic_frame(ic)
    pad = lambda ref, n: next(q for q in get(ref).Pads() if q.GetNumber() == n)
    G = lambda p: pcbnew.VECTOR2I(MM(origin[0] + rot(p, theta)[0]), MM(origin[1] + rot(p, theta)[1]))
    P = lambda q: q.GetPosition()

    def track(points, width, net):
        for a, b in zip(points[:-1], points[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(a)
            t.SetEnd(b)
            t.SetWidth(MM(width))
            t.SetLayer(pcbnew.F_Cu)
            t.SetNet(net)
            add(t)

    vin, gnd, bst, sw = (pad(parts["ic"], n) for n in ("3", "4", "6", "5"))
    cs1, cs2 = pad(parts["cin_s"], "1"), pad(parts["cin_s"], "2")
    cb1, cb2 = pad(parts["cin_b"], "1"), pad(parts["cin_b"], "2")
    k1 = pad(parts["cbst"], "1")
    # Input loop: pin 3 -> 100n -> 10u (VIN), pin 4 -> 100n -> 10u (GND).
    # 0.25 mm next to the pins: 0.225 mm from the neighbouring pins (0.5 mm pitch).
    track([P(vin), G((-1.6, 0.25)), P(cs1)], 0.25, vin.GetNet())
    track([P(cs1), P(cb1)], 0.6, vin.GetNet())
    track([P(gnd), G((-1.15, 1.16)), P(cs2)], 0.25, gnd.GetNet())
    track([P(cs2), P(cb2)], 0.6, gnd.GetNet())
    # Bootstrap: pin 6 -> Cbst pad 1, kept 0.2 mm from PG (pin 7).
    track([P(bst), G((1.4, 0.25)), P(k1)], 0.25, bst.GetNet())
    # Output: inductor OUT pad -> each output cap.
    lout = pad(parts["l"], "2")
    for r in parts["couts"]:
        track([P(lout), P(pad(r, "1"))], 0.8, lout.GetNet())
    # SW zone: band from pin 5 (over the Cbst SW pad) to the inductor SW pad.
    l1 = pad(parts["l"], "1")
    lb = l1.GetBoundingBox()
    lx0 = T(lb.GetLeft()) - origin[0]
    corners_g = [(T(lb.GetLeft()), T(lb.GetTop())), (T(lb.GetRight()), T(lb.GetTop())),
                 (T(lb.GetRight()), T(lb.GetBottom())), (T(lb.GetLeft()), T(lb.GetBottom()))]
    # Local inductor pad box (undo rotation) to build one polygon in the local frame.
    loc = [rot((x - origin[0], y - origin[1]), -theta) for x, y in corners_g]
    lx0, lx1 = min(p[0] for p in loc), max(p[0] for p in loc)
    ly0, ly1 = min(p[1] for p in loc), max(p[1] for p in loc)
    poly = [(0.42, 0.45), (lx0, 0.45), (lx0, ly0), (lx1, ly0), (lx1, ly1), (lx0, ly1), (lx0, 1.6), (0.42, 1.6)]
    z = pcbnew.ZONE(board)
    z.SetLayer(pcbnew.F_Cu)
    z.SetNet(sw.GetNet())
    z.SetAssignedPriority(20)
    z.SetLocalClearance(MM(0.2))
    z.SetMinThickness(MM(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetZoneName("switch node")
    o = z.Outline()
    o.NewOutline()
    for p in poly:
        g = G(p)
        o.Append(g.x, g.y)
    add(z)


# Placement plan: (parts, template rotation, top-left corner of the template box).
# U211 (VPRE, 10 uH 10x10 mm inductor) across the top of the power area, U214
# and U215 rotated below it, clear of the mounting hole at (61, 92.5); U213
# (1V0) next to the BGA.
PLAN = [
    (dict(ic="U211", l="L201", cin_b="C225", cin_s="C226", cbst="C227", couts=["C228", "C229", "C230"],
          rtop="R230", rbot="R231"), 0, (56.6, 60.2)),
    (dict(ic="U214", l="L203", cin_b="C237", cin_s="C238", cbst="C239", couts=["C240", "C241"],
          rtop="R234", rbot="R235"), 90, (64.8, 72.1)),
    (dict(ic="U215", l="L204", cin_b="C242", cin_s="C243", cbst="C244", couts=["C245", "C246"],
          rtop="R236", rbot="R237"), 90, (74.6, 72.1)),
    (dict(ic="U213", l="L202", cin_b="C231", cin_s="C232", cbst="C233", couts=["C234", "C235", "C236"],
          rtop="R232", rbot="R233"), 0, (114.6, 96.7)),
]


def refs(parts):
    return [v for k, v in parts.items() if k != "couts"] + list(parts["couts"])


def place_all(board):
    out = []
    for parts, theta, tl in PLAN:
        w, h = place(board, parts, theta, tl)
        out.append((parts["ic"], round(w, 2), round(h, 2)))
    return out


def overlaps(board, refset):
    """Courtyard overlaps between the given parts and any other part (same side)."""
    res = []
    fps = list(board.GetFootprints())

    def court(f):
        c = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
        return c.BBox() if c.OutlineCount() else f.GetBoundingBox(False)
    for f in fps:
        if f.GetReference() not in refset:
            continue
        a = court(f)
        for g in fps:
            if g is f or g.IsFlipped() != f.IsFlipped() or (g.GetReference() in refset and g.GetReference() <= f.GetReference()):
                continue
            if not any(p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH for p in g.Pads()) and g.GetReference():
                continue
            b = court(g)
            if a.Intersects(b):
                ix = min(a.GetRight(), b.GetRight()) - max(a.GetLeft(), b.GetLeft())
                iy = min(a.GetBottom(), b.GetBottom()) - max(a.GetTop(), b.GetTop())
                if ix > MM(0.01) and iy > MM(0.01):
                    res.append((f.GetReference(), g.GetReference() or "hole", round(T(ix), 2), round(T(iy), 2)))
    return res
