#!/usr/bin/env python3
"""Places the Rev 2 parts on hw/kicad/Scaffold.kicad_pcb (KiCad Python).

Parts kept from Rev 1.1 stay where they are. New and replaced parts are
placed by functional group, in order, inside a rectangular region of the
board: the first free spot (scanning rows) whose courtyard does not overlap
any other courtyard, hole or the board edge. The FPGA decoupling under the
BGA is placed by fanout.py, after the BGA fanout.

Run: <kicad python> hw/rev2/tools/place.py
"""
import os
import re
import sys

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
MM = pcbnew.FromMM
MARGIN = 0.25          # mm, between courtyards
STEP = 0.25            # mm, scan step

board = pcbnew.LoadBoard(BOARD)
fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
edge = board.GetBoardEdgesBoundingBox()


def courtyard(fp):
    for layer in (pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd,):
        poly = fp.GetCourtyard(layer)
        if poly.OutlineCount():
            return poly.BBox()
    pads = list(fp.Pads())
    if pads:
        # Footprints without courtyard (mounting holes): use the pads/holes.
        box = pads[0].GetBoundingBox()
        for p in pads[1:]:
            box.Merge(p.GetBoundingBox())
        box.Inflate(MM(0.5))
        return box
    return fp.GetBoundingBox(False)


def is_tht(fp):
    return any(p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) for p in fp.Pads())


def rect(box, margin=MARGIN):
    return (pcbnew.ToMM(box.GetLeft()) - margin, pcbnew.ToMM(box.GetTop()) - margin,
            pcbnew.ToMM(box.GetRight()) + margin, pcbnew.ToMM(box.GetBottom()) + margin)


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


placed = set()          # references placed by this script (or fixed in place)
to_place = set()        # references that this script must place


def obstacles(side_bottom):
    """Courtyards that block a part on the given side."""
    obs = []
    # Iterate over all footprints, not the reference dict: the mounting holes
    # all have an empty reference.
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref in to_place and ref not in placed:
            continue
        if pcbnew.ToMM(fp.GetPosition().x) > pcbnew.ToMM(edge.GetRight()):
            continue   # still staged off-board
        if fp.IsFlipped() == side_bottom or is_tht(fp):
            obs.append(rect(courtyard(fp), 0))
    return obs


def place(ref, region, rot=0, bottom=False):
    """Place `ref` at the first free spot of region (x0, y0, x1, y1) in mm,
    trying the given rotation first, then rotated by 90 degrees."""
    for r in (rot, (rot + 90) % 360):
        if _place(ref, region, r, bottom):
            return True
    raise RuntimeError("no room for %s in region %s" % (ref, region))


def _place(ref, region, rot, bottom):
    fp = fps[ref]
    if fp.IsFlipped() != bottom:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    box = rect(courtyard(fp))
    w, h = box[2] - box[0], box[3] - box[1]
    obs = obstacles(bottom)
    x0, y0, x1, y1 = region
    y = y0
    while y + h <= y1 + 1e-6:
        x = x0
        while x + w <= x1 + 1e-6:
            cand = (x, y, x + w, y + h)
            if not any(overlaps(cand, o) for o in obs):
                fp.SetPosition(pcbnew.VECTOR2I(MM(x - box[0]), MM(y - box[1])))
                placed.add(ref)
                return True
            x += STEP
        y += STEP
    return False


def place_at(ref, x, y, rot=0, bottom=False):
    fp = fps[ref]
    if fp.IsFlipped() != bottom:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    placed.add(ref)


def group(refs, region, rot=0, bottom=False):
    for r in refs:
        place(r, region, rot, bottom)


def refs(pattern):
    return sorted((r for r in fps if re.fullmatch(pattern, r)), key=lambda r: (r[0], int(re.sub(r"\D", "", r) or 0)))


# ---------------------------------------------------------------------------
# 0. Silkscreen: the Rev 1.1 castle artwork occupied the area now used by
# the buck converters. Remove it; move the board name and Ledger logo to the
# free area next to the ESD/RoHS marks.
LOGO_AREA = (53, 40, 92, 92)
removed = 0
for d in list(board.GetDrawings()):
    if d.GetLayer() == pcbnew.F_SilkS and d.GetClass() == "PCB_SHAPE":
        c = d.GetBoundingBox().GetCenter()
        x, y = pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)
        if LOGO_AREA[0] < x < LOGO_AREA[2] and LOGO_AREA[1] < y < LOGO_AREA[3]:
            board.Delete(d)
            removed += 1
for d in board.GetDrawings():
    if d.GetClass() == "PCB_TEXT" and d.GetText() in ("Scaffold Rev 2", "Donjon"):
        p = d.GetPosition()
        d.SetPosition(pcbnew.VECTOR2I(p.x + MM(100), p.y - MM(4)))
if "Logo1" in fps:
    p = fps["Logo1"].GetPosition()
    fps["Logo1"].SetPosition(pcbnew.VECTOR2I(p.x + MM(100), p.y - MM(4)))
print("removed %d silkscreen shapes from the logo area" % removed)
# Labels of Rev 1.1 that no longer match the hardware.
for d in list(board.GetDrawings()):
    if d.GetClass() == "PCB_TEXT" and d.GetText() == "5V-SEL":
        board.Delete(d)            # source select jumper removed (TPS2121 mux)
    elif d.GetClass() == "PCB_TEXT" and d.GetText() == "5V" and abs(pcbnew.ToMM(d.GetPosition().x) - 92) < 3:
        d.SetText("7-20V")         # external input terminal CN202
    elif d.GetClass() == "PCB_TEXTBOX" and "Active Serial" in d.GetText():
        d.SetText("JTAG")          # P100 is now the JTAG header

# Parts handled by this script (listed explicitly below) and the FPGA
# decoupling capacitors (placed by fanout.py): none of them is an obstacle
# until placed.
FPGA_DECAPS = {"C%d" % i for i in list(range(100, 136)) + list(range(143, 147)) + list(range(155, 170))}
PLAN_REFS = {"J200", "D203", "D204", "U209", "C221", "R218", "D207", "R219", "D208", "R220", "R221", "R222", "D209",
             "U210", "C222", "D210", "R223", "R224", "R225", "R226", "R227", "R228", "R229", "C223", "C224",
             "U211", "U213", "U214", "U215", "L201", "L202", "L203", "L204", "U212", "R238", "R239", "C247", "C248",
             "R240", "U100", "R101", "R102", "R103", "R104", "R105", "R106", "R107", "R108", "R109", "R113", "L100",
             "C170", "C171", "P100", "U401", "U402", "C400", "C401", "C402", "R425"}
PLAN_REFS |= {"C%d" % i for i in range(225, 247)} | {"R%d" % i for i in range(230, 238)}
PLAN_REFS |= {"R%d" % i for i in range(401, 425)}
to_place |= PLAN_REFS | FPGA_DECAPS
for r in sorted(to_place - set(fps)):
    raise SystemExit("unknown reference in plan: " + r)

# ---------------------------------------------------------------------------
# 1. USB-C on the top edge (old micro-USB spot), opening facing the edge.
place_at("J200", 70.1, 30.0 + 3.675, rot=180)

# 2. USB-PD, ESD, VBUS sense: below the connector.
R_PD = (64.5, 38.6, 83.5, 50.5)
group(["D203", "D204"], (64.5, 38.6, 76, 41.5), rot=0)
group(["U209", "C221", "R218", "D207", "R219", "D208", "R220", "R221", "R222", "D209"], R_PD)

# 3. Input mux next to the external input terminal and the ON switch.
group(["U210", "C222", "D210", "R223", "R224", "R225", "R226", "R227", "R228", "R229", "C223", "C224"],
      (64.5, 50.5, 83.5, 60.0))

# 4. Buck converters in the former logo area: IC, inductor, caps, resistors.
# The 1V0 core buck sits right next to the BGA (up to 1.5 A on a rail with
# +/-50 mV tolerance); only its 12 V input (~0.1 A) travels from the input.
BUCKS = {"U211": ("L201", (56.5, 60.0, 76.0, 76.0)),
         "U215": ("L204", (76.0, 60.0, 92.0, 76.0)),
         "U214": ("L203", (56.5, 76.0, 87.5, 91.0)),
         "U213": ("L202", (114.5, 96.5, 133.0, 113.0))}
# Passives of each buck, from the generator's numbering (gen_power.py).
BUCK_PASSIVES = {"U211": (["C225", "C226", "C227", "C228", "C229", "C230"], ["R230", "R231"]),
                 "U213": (["C231", "C232", "C233", "C234", "C235", "C236"], ["R232", "R233"]),
                 "U214": (["C237", "C238", "C239", "C240", "C241"], ["R234", "R235"]),
                 "U215": (["C242", "C243", "C244", "C245", "C246"], ["R236", "R237"])}
for u, (l, region) in BUCKS.items():
    caps, res = BUCK_PASSIVES[u]
    try:
        group([u, l] + caps + res, region)
    except RuntimeError:
        if os.environ.get("PLACE_DEBUG"):
            pcbnew.SaveBoard(os.environ["PLACE_DEBUG"], board)
        raise

# 5. Vsupply LDO and VCC_IO pull-up, in the old FPGA LDO area.
group(["U212", "R238", "R239", "C247", "C248", "R240"], (99.5, 74.0, 114.5, 91.5))

# 6. FPGA: BGA in place of the TQFP, rotated 180 degrees so that banks 34/35
# face the DUT/platform headers. Configuration parts around the flash.
place_at("U100", 105.5, 113.8, rot=180)
# JTAG header below the mounting hole at (61, 92.5), then the configuration
# resistors around the flash.
group(["P100"], (60.5, 96.5, 69.0, 116.0), rot=0)
group(["R101", "R102", "R103", "R104", "R105", "R106", "R107", "R108", "R109", "R113"], (69.0, 96.0, 95.0, 113.0))
# VCCADC filter on the bottom side, next to the BGA.
group(["L100", "C170", "C171"], (88.0, 112.0, 96.5, 124.0), bottom=True)

# 7. LED shift registers next to U400, LED resistors on the bottom side under
# the LED rows.
group(["U401", "U402", "C400", "C401", "C402", "R425"], (113.0, 124.0, 140.0, 147.0))
group(refs(r"R4(0[1-9]|1\d|2[0-4])"), (84.0, 128.0, 135.0, 147.5), rot=90, bottom=True)

missing = sorted(to_place - placed - FPGA_DECAPS)
print("placed %d parts; FPGA decoupling left for fanout.py; not placed: %s" % (len(placed), " ".join(missing)))
pcbnew.SaveBoard(BOARD, board)
