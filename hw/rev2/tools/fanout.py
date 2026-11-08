#!/usr/bin/env python3
"""BGA fanout, FPGA decoupling placement and copper planes for Scaffold Rev 2.

Run with KiCad's Python after place.py:  <kicad python> hw/rev2/tools/fanout.py

1. Dog-bone fanout of the XC7A CSG324 (0.8 mm pitch): every power/ground
   ball and every signal ball from the third ring inwards gets a 0.4/0.2 mm
   via at the centre of its 4-ball square, on the side away from the BGA
   centre. The two outer rings escape on the top layer (router).
2. 0402 decoupling: under the BGA (bottom side) where a supply via and a
   ground via are adjacent, the capacitor pads sit on the via pair. The rest
   go in a ring just outside the BGA, on the side whose power plane region
   matches their supply, each with its own supply and ground via. Bulk
   capacitors are placed near the BGA.
3. Planes: In1 (GND1) and In4 (GND2) solid ground; In3 (Power) split into
   1V0 (core island + corridor to its buck), 3V3_FPGA (left half, bottom
   and LED rows), VCC_IO_FPGA (banks 34/35 side up to x = 140 mm), VPRE and
   VIN (power input area); a VIN zone on In2 under the buck inputs; ground
   pours on the outer layers.

Re-running removes what a previous run added (items tagged in a group).
"""
import math
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
MM = pcbnew.FromMM
PITCH = 0.8
VIA_D, VIA_DRILL = 0.4, 0.2
GROUP = "rev2_fanout"

board = pcbnew.LoadBoard(BOARD)
fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
u = fps["U100"]
CX, CY = pcbnew.ToMM(u.GetPosition().x), pcbnew.ToMM(u.GetPosition().y)
SUPPLIES = ["1V0", "1V8", "3V3_FPGA", "VCC_IO_FPGA"]
POWER = set(SUPPLIES) | {"VCCADC", "GND"}

# --- previous run cleanup -----------------------------------------------------
for g in list(board.Groups()):
    if g.GetName() == GROUP:
        for item in list(g.GetItems()):
            if item.GetClass() in ("PCB_VIA", "PCB_TRACK", "ZONE"):
                board.Delete(item)
        board.Delete(g)
group = pcbnew.PCB_GROUP(board)
group.SetName(GROUP)
board.Add(group)


def net(name):
    return board.FindNet(name)


def add_via(x, y, netname, d=VIA_D, drill=VIA_DRILL):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    v.SetWidth(MM(d))
    v.SetDrill(MM(drill))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetNet(net(netname))
    board.Add(v)
    group.AddItem(v)
    return v


# Vias added outside the BGA go through every layer: they must clear the pads
# of both sides (current positions) and the other vias.
def via_ok(x, y, d, netname, ignore_ref=None, clearance=0.2):
    r = d / 2 + clearance
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref == ignore_ref or ref == "U100":
            continue
        fb = fp.GetBoundingBox(False)
        if not (pcbnew.ToMM(fb.GetLeft()) - 3 < x < pcbnew.ToMM(fb.GetRight()) + 3
                and pcbnew.ToMM(fb.GetTop()) - 3 < y < pcbnew.ToMM(fb.GetBottom()) + 3):
            continue
        for p in fp.Pads():
            if p.GetNetname() == netname:
                continue
            b = p.GetBoundingBox()
            if pcbnew.ToMM(b.GetLeft()) - r < x < pcbnew.ToMM(b.GetRight()) + r and \
                    pcbnew.ToMM(b.GetTop()) - r < y < pcbnew.ToMM(b.GetBottom()) + r:
                return False
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA" and t.GetNetname() != netname:
            q = t.GetPosition()
            if math.hypot(pcbnew.ToMM(q.x) - x, pcbnew.ToMM(q.y) - y) < d / 2 + pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2 + clearance:
                return False
    return True


def free_via(candidates, d, netname, ignore_ref):
    """First candidate (x, y) where a via of diameter d fits."""
    for (x, y) in candidates:
        if via_ok(x, y, d, netname, ignore_ref):
            return x, y
    raise RuntimeError("no room for a %s via near %s" % (netname, ignore_ref))


def add_track(x0, y0, x1, y1, w, layer, netname):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(MM(x0), MM(y0)))
    t.SetEnd(pcbnew.VECTOR2I(MM(x1), MM(y1)))
    t.SetWidth(MM(w))
    t.SetLayer(layer)
    t.SetNet(net(netname))
    board.Add(t)
    group.AddItem(t)


# --- 1. fanout -------------------------------------------------------------------
vias = {}          # (rel x, rel y) rounded -> net
balls = {}         # (rel x, rel y) -> net, all connected balls
for pad in u.Pads():
    n = pad.GetNetname()
    if not n or n.startswith("unconnected"):
        continue
    px, py = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
    rx, ry = round(px - CX, 2), round(py - CY, 2)
    balls[(rx, ry)] = n
    ring = round((6.8 - max(abs(rx), abs(ry))) / PITCH)
    if n not in POWER and ring < 2:
        continue
    sx = 1 if rx >= 0 else -1
    sy = 1 if ry >= 0 else -1
    vx, vy = round(rx + sx * PITCH / 2, 2), round(ry + sy * PITCH / 2, 2)
    assert (vx, vy) not in vias, "via collision at %s" % ((vx, vy),)
    vias[(vx, vy)] = n
    add_via(CX + vx, CY + vy, n)
    add_track(px, py, CX + vx, CY + vy, 0.2 if n in POWER else 0.1, pcbnew.F_Cu, n)
print("fanout: %d vias" % len(vias))

# --- 2. decoupling ---------------------------------------------------------------
caps = {}   # net -> list of refs, 0402 first (smallest value first), then bulk
for ref, fp in fps.items():
    if ref.startswith("C") and ref[1:].isdigit() and 100 <= int(ref[1:]) < 170:
        pads = {p.GetNumber(): p.GetNetname() for p in fp.Pads()}
        if pads.get("2") == "GND" and pads.get("1") in SUPPLIES:
            caps.setdefault(pads["1"], []).append(ref)


def value_key(ref):
    v = fps[ref].GetValue()
    return {"470nF": 0, "4.7uF": 1, "47uF": 2, "100uF": 3}.get(v.split()[0], 9)


for n in caps:
    caps[n].sort(key=value_key)
small = {n: [r for r in caps[n] if "0402" in fps[r].GetFPIDAsString()] for n in caps}
bulk = {n: [r for r in caps[n] if "0402" not in fps[r].GetFPIDAsString()] for n in caps}


def put(ref, x, y, angle, supply_at=None):
    """Place a capacitor on the bottom side. supply_at: (x, y) that pad 1
    (the supply side) must be closest to; footprints are mirrored on the
    bottom side, so the orientation is checked on the placed pads."""
    fp = fps[ref]
    if not fp.IsFlipped():
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    fp.SetOrientationDegrees(angle)
    fp.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    if supply_at:
        pads = {p.GetNumber(): p.GetPosition() for p in fp.Pads()}
        d = lambda q: math.hypot(pcbnew.ToMM(q.x) - supply_at[0], pcbnew.ToMM(q.y) - supply_at[1])
        if d(pads["1"]) > d(pads["2"]):
            fp.SetOrientationDegrees((angle + 180) % 360)


# 2a. Under the BGA: capacitor on an adjacent (supply via, GND via) pair.
# 0402 pads are at +/-0.48 mm: centred between two vias 0.8 mm apart, each
# pad covers one via. Caps are kept 1.6 mm apart (courtyards).
used_cells, under = set(), 0
for n in ("1V0", "1V8", "3V3_FPGA", "VCC_IO_FPGA"):
    for (vx, vy), vn in sorted(vias.items()):
        if vn != n or not small.get(n):
            continue
        for dx, dy, ang in ((PITCH, 0, 0), (-PITCH, 0, 180), (0, PITCH, 270), (0, -PITCH, 90)):
            g = (round(vx + dx, 2), round(vy + dy, 2))
            mid = (round(vx + dx / 2, 2), round(vy + dy / 2, 2))
            if vias.get(g) != "GND" or (vx, vy) in used_cells or g in used_cells:
                continue
            if any(math.hypot(mid[0] - m[0], mid[1] - m[1]) < 1.6 for m in used_cells if len(m) == 3):
                continue
            ref = small[n].pop(0)
            # pad 1 (supply) on the supply via: KiCad 0402 has pad 1 at -x.
            put(ref, CX + mid[0], CY + mid[1], ang, supply_at=(CX + vx, CY + vy))
            used_cells |= {(vx, vy), g, (mid[0], mid[1], 0)}
            under += 1
            break
print("decoupling under the BGA: %d" % under)


# 2b. Ring outside the BGA. Supply region on In3 by side: 3V3 left, VCC_IO right.
def ring_slots(side):
    """Cap centres along one side, at 9.4 mm from the BGA centre."""
    out = []
    for i in range(-6, 7):
        t = i * 1.2
        out.append({"left": (-9.4, t, 180), "right": (9.4, t, 0), "top": (t, -9.4, 90), "bottom": (t, 9.4, 270)}[side])
    return out


# Ring slots per supply, matching the In3 regions defined in section 3:
# 1V0 top (x > -2 mm) and upper right (y <= -1.2 mm), 1V8 top left,
# 3V3 left and lower left, VCC_IO lower right.
SIDES = {"1V0": ["top", "right"], "1V8": ["top", "left"], "3V3_FPGA": ["left", "bottom"],
         "VCC_IO_FPGA": ["right", "bottom"]}


def slot_ok(n, side, x, y):
    if n == "1V0":
        return (side == "top" and x > -2.0) or (side == "right" and y <= -1.2)
    if n == "1V8":
        return (side == "top" and x <= -3.0) or (side == "left" and y <= -6.0)
    if n == "3V3_FPGA":
        return (side == "left" and y >= -4.8) or (side == "bottom" and x <= 0.0)
    if n == "VCC_IO_FPGA":
        return (side == "right" and y >= 0.0) or (side == "bottom" and x >= 2.4)
    return False
taken = set()
ring = 0
for n, sides in SIDES.items():
    for side in sides:
        for (x, y, ang) in ring_slots(side):
            if not small.get(n):
                break
            if not slot_ok(n, side, x, y):
                continue
            if (x, y) in taken:
                continue
            taken.add((x, y))
            ref = small[n].pop(0)
            put(ref, CX + x, CY + y, ang, supply_at=(CX, CY))
            # Supply via towards the BGA, ground via outside, short bottom tracks.
            ux, uy = (x / abs(x) if abs(x) > 9 else 0), (y / abs(y) if abs(y) > 9 else 0)
            px, py = CX + x - ux * 0.48, CY + y - uy * 0.48
            gx, gy = CX + x + ux * 0.48, CY + y + uy * 0.48
            # Tangent direction, to slide a via sideways if the straight spot is taken.
            tx, ty = (0, 1) if ux else (1, 0)
            sx, sy = free_via([(px - ux * 0.75 + tx * k, py - uy * 0.75 + ty * k) for k in (0, 0.5, -0.5)],
                              VIA_D, n, ref)
            add_via(sx, sy, n)
            add_track(px, py, sx, sy, 0.3, pcbnew.B_Cu, n)
            hx, hy = free_via([(gx + ux * (0.75 + k), gy + uy * (0.75 + k)) for k in (0, 0.4, 0.8)]
                              + [(gx + ux * 0.75 + tx * k, gy + uy * 0.75 + ty * k) for k in (0.6, -0.6)],
                              VIA_D, "GND", ref)
            add_via(hx, hy, "GND")
            add_track(gx, gy, hx, hy, 0.3, pcbnew.B_Cu, "GND")
            ring += 1
left = {n: v for n, v in small.items() if v}
print("decoupling ring: %d, left over: %s" % (ring, left))

# 2c. Bulk capacitors, bottom side, beyond the decoupling ring (12.6 mm from
# the BGA centre), horizontal, with a via beyond each pad along x.
BULK_AT = {"1V0": [(CX + 1.5, CY - 12.6), (CX + 9.5, CY - 12.6)],
           "1V8": [(CX - 6.5, CY - 12.6)],
           "3V3_FPGA": [(CX - 10.0, CY + 12.6), (CX - 2.0, CY + 12.6)],
           "VCC_IO_FPGA": [(CX + 5.0, CY + 12.6)]}
for n, refs in bulk.items():
    for ref, (x, y) in zip(refs, BULK_AT[n]):
        put(ref, x, y, 0)
        for p in fps[ref].Pads():
            q = p.GetPosition()
            vx, vy = pcbnew.ToMM(q.x), pcbnew.ToMM(q.y)
            dx = 1.5 if vx > x else -1.5
            dy = 1.5 if y > CY else -1.5
            fx, fy = free_via([(vx + dx, vy), (vx, vy + dy), (vx + dx, vy + dy), (vx, vy - dy), (vx + 2 * dx, vy)],
                              0.6, p.GetNetname(), ref)
            add_via(fx, fy, p.GetNetname(), 0.6, 0.3)
            add_track(vx, vy, fx, fy, 0.6, pcbnew.B_Cu, p.GetNetname())


# --- 3. planes --------------------------------------------------------------------
def poly_rects(rects):
    ps = pcbnew.SHAPE_POLY_SET()
    for (x0, y0, x1, y1) in rects:
        r = pcbnew.SHAPE_POLY_SET()
        r.NewOutline()
        for (x, y) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            r.Append(MM(x), MM(y))
        ps.BooleanAdd(r)
    ps.Simplify()
    return ps


def add_zone(netname, layer, polyset, priority, clearance=0.15, min_width=0.15, name=""):
    for i in range(polyset.OutlineCount()):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(net(netname))
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(MM(clearance))
        z.SetMinThickness(MM(min_width))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetZoneName(name or netname)
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)
        outline = z.Outline()
        outline.NewOutline()
        o = polyset.COutline(i)
        for k in range(o.PointCount()):
            pt = o.CPoint(k)
            outline.Append(pt.x, pt.y)
        board.Add(z)
        group.AddItem(z)


bb = board.GetBoardEdgesBoundingBox()
B = (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))
full = poly_rects([B])
for layer in (pcbnew.In1_Cu, pcbnew.In4_Cu):
    add_zone("GND", layer, full, 0, name="GND plane")
outer = poly_rects([B])
outer.BooleanSubtract(poly_rects([(CX - 11.5, CY - 11.5, CX + 11.5, CY + 11.5)]))
for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
    add_zone("GND", layer, outer, 0, clearance=0.25, min_width=0.25, name="GND pour")

# In3 power regions. 1V0: core island + corridor through the unused ball
# rows to its buck (U213/L202, right of the BGA).
corridor_y0, corridor_y1 = CY - 2.4, CY - 1.2
add_zone("1V0", pcbnew.In3_Cu, poly_rects([
    (CX - 1.6, CY - 3.2, CX + 2.4, CY + 3.2),            # core
    (CX + 2.4, corridor_y0, 115.0, corridor_y1),          # corridor (unused balls)
    (CX - 2.0, CY - 14.6, 134.0, CY - 7.8),               # top decoupling ring + bulk
    (CX + 7.8, CY - 11.2, 134.0, CY - 1.2),               # upper right ring
    (114.0, 96.0, 134.0, CY - 1.2)]), 10)                 # buck U213/L202
# 1V8: VCCAUX via column (left of the core) up to the top-left ring.
add_zone("1V8", pcbnew.In3_Cu, poly_rects([
    (CX - 2.9, CY - 7.8, CX - 1.9, CY + 3.4),
    (CX - 11.2, CY - 14.6, CX - 2.0, CY - 7.8),
    (CX - 11.2, CY - 7.8, CX - 7.8, CY - 5.4)]), 9)
# VPRE: from the U211 buck (top row of the power area) to the LDOs.
add_zone("VPRE", pcbnew.In3_Cu, poly_rects([(93.0, 37.0, 136.0, 76.0), (93.0, 76.0, 121.0, 92.0),
                                             (B[0], 59.5, 94.0, 72.0)]), 5)
add_zone("VIN", pcbnew.In3_Cu, poly_rects([(B[0], B[1], 93.0, 59.5)]), 5)
# VIN (12 V) to the buck input capacitors on the signal layer In2, which has
# no signals to carry in the power area; it overlaps the In3 VIN region so
# that the plane vias there join both.
add_zone("VIN", pcbnew.In2_Cu, poly_rects([(B[0], 56.0, 88.0, 91.5)]), 0, name="VIN In2")
# Under the BGA, 3V3 (banks 0/14/15/16) and VCC_IO (banks 34/35) VCCO balls
# interleave: each 0.8 mm cell of the via grid goes to the rail of the
# nearest VCCO via (Voronoi), so that every VCCO via sits in its own plane.
vcco = [(x, y, n) for (x, y), n in vias.items() if n in ("3V3_FPGA", "VCC_IO_FPGA")]
cells = {"3V3_FPGA": [], "VCC_IO_FPGA": []}
for i in range(-10, 10):
    for j in range(-10, 10):
        gx, gy = i * PITCH + PITCH / 2, j * PITCH + PITCH / 2
        if max(abs(gx), abs(gy)) > 8.0:
            continue
        n = min(vcco, key=lambda v: math.hypot(v[0] - gx, v[1] - gy))[2]
        cells[n].append((CX + gx - PITCH / 2, CY + gy - PITCH / 2, CX + gx + PITCH / 2, CY + gy + PITCH / 2))
BGA_BOX = (CX - 8.0, CY - 8.0, CX + 8.0, CY + 8.0)
# 3V3 parts below the BGA (LED registers, level shifters, FT232 area) and
# the LED rows on the right are in the 3V3 region; VCC_IO only has loads near
# the BGA and in the level-shifter area left of x = 140 mm.
left = poly_rects([(B[0], 72.0, CX, B[3]), (76.0, 59.5, 93.0, 76.0), (CX, CY + 8.6, 140.0, B[3]),
                   (140.0, B[1], B[2], B[3])])
left.BooleanSubtract(poly_rects([BGA_BOX]))
left.BooleanAdd(poly_rects(cells["3V3_FPGA"]))
right = poly_rects([(CX, B[1], B[2], B[3]), (136.0, B[1], B[2], 76.0)])
right.BooleanSubtract(poly_rects([BGA_BOX]))
right.BooleanAdd(poly_rects(cells["VCC_IO_FPGA"]))
right.BooleanSubtract(left)
add_zone("3V3_FPGA", pcbnew.In3_Cu, left, 2)
add_zone("VCC_IO_FPGA", pcbnew.In3_Cu, right, 1)

filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
pcbnew.SaveBoard(BOARD, board)
print("zones filled and board saved")
