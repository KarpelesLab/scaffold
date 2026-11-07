#!/usr/bin/env python3
"""Synchronises hw/kicad/Scaffold.kicad_pcb with the schematic netlist.

kicad-cli has no "Update PCB from Schematic", so this does it with the
pcbnew API. Run with KiCad's bundled Python:

  kicad-cli sch export netlist --format kicadsexpr -o /tmp/scaffold.net hw/kicad/Scaffold.kicad_sch
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \\
      hw/rev2/tools/update_pcb.py /tmp/scaffold.net [--strip-copper] [--layers 6]

- Footprints are linked to their symbols (path = sheet path + symbol UUID),
  so later updates from the KiCad GUI work normally.
- A part whose footprint changed is replaced in place (same position,
  rotation and side). New parts are staged in a column to the right of the
  board, grouped by sheet, for placement.
- Footprints that are not in the netlist are removed, except mechanical
  items without pads (mounting holes, logos).
- Pad nets are set from the netlist.
- --strip-copper removes all tracks, vias and zones (the Rev 1.1 copper was
  imported from Altium as ~1500 zones and routes to the old FPGA).
- --layers N sets the copper layer count.
"""
import argparse
import os
import re
import sys

import pcbnew

# Note: BOARD.Remove() corrupts the SWIG type registry in KiCad 10's Python
# bindings; BOARD.Delete() (remove and free on the C++ side) is used instead.

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
KICAD_DIR = os.path.join(REPO, "hw", "kicad")
STD_FP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
PROJECT_LIBS = {"Scaffold-import-fps": os.path.join(KICAD_DIR, "Scaffold-import-fps.pretty"),
                "Scaffold_Rev2": os.path.join(KICAD_DIR, "Scaffold_Rev2.pretty")}


# ---------------------------------------------------------------------------
def tokenize(s):
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|([()])|([^\s()"]+)', s):
        if m.group(2):
            yield m.group(2)
        elif m.group(1) is not None:
            yield ("S", m.group(1).replace('\\"', '"').replace("\\\\", "\\"))
        else:
            yield ("S", m.group(3))


def parse_sexpr(s):
    stack = [[]]
    for t in tokenize(s):
        if t == "(":
            stack.append([])
        elif t == ")":
            x = stack.pop()
            stack[-1].append(x)
        else:
            stack[-1].append(t[1])
    return stack[0][0]


def find(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def val(node, key, default=None):
    f = find(node, key)
    return f[0][1] if f and len(f[0]) > 1 and isinstance(f[0][1], str) else default


def load_netlist(path):
    root = parse_sexpr(open(path).read())
    comps = {}
    for c in find(find(root, "components")[0], "comp"):
        ref = val(c, "ref")
        sp = find(c, "sheetpath")[0]
        fields = {}
        for p in find(c, "property"):
            fields[val(p, "name")] = val(p, "value", "")
        comps[ref] = dict(ref=ref, value=val(c, "value", ""), footprint=val(c, "footprint", ""),
                          sheet=val(sp, "names", ""), path=val(sp, "tstamps", "/") + val(c, "tstamps", ""),
                          fields=fields)
    pins = {}
    for n in find(find(root, "nets")[0], "net"):
        name = val(n, "name")
        for node in find(n, "node"):
            pins[(val(node, "ref"), val(node, "pin"))] = name
    return comps, pins


def load_footprint(fpid):
    lib, name = fpid.split(":", 1)
    path = PROJECT_LIBS.get(lib, os.path.join(STD_FP, lib + ".pretty"))
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise RuntimeError("footprint not found: " + fpid)
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def fp_name(fp):
    return fp.GetFPIDAsString().split(":", 1)[-1]


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("netlist")
    ap.add_argument("--board", default=os.path.join(KICAD_DIR, "Scaffold.kicad_pcb"))
    ap.add_argument("--strip-copper", action="store_true")
    ap.add_argument("--layers", type=int, default=0)
    a = ap.parse_args()

    comps, pins = load_netlist(a.netlist)
    board = pcbnew.LoadBoard(a.board)
    bbox = board.GetBoardEdgesBoundingBox()
    stage_x = bbox.GetRight() + pcbnew.FromMM(20)
    stage_y = {"": bbox.GetTop()}
    report = {"replaced": [], "added": [], "removed": [], "updated": 0}

    existing = {}
    for fp in list(board.GetFootprints()):
        ref = fp.GetReference()
        if ref in comps:
            existing[ref] = fp
        elif any(pd.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH for pd in fp.Pads()) \
                and not re.match(r"^M\d+$", ref):
            # Parts removed from the schematic. Kept: mechanical footprints
            # (all pads non-plated: mounting holes, DUT socket opening),
            # fiducials (M1-M4) and pad-less graphics such as logos.
            report["removed"].append(ref)
            board.Delete(fp)

    columns = {}
    for ref, c in sorted(comps.items()):
        if not c["footprint"]:
            continue
        old = existing.get(ref)
        want = c["footprint"].split(":", 1)[1]
        if old is not None and fp_name(old) == want:
            fp = old
        else:
            fp = load_footprint(c["footprint"])
            # Attach to the board first: Flip() needs the board (it crashes
            # on a free-standing footprint).
            board.Add(fp)
            if old is not None:
                fp.SetPosition(old.GetPosition())
                if old.IsFlipped() != fp.IsFlipped():
                    fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
                fp.SetOrientation(old.GetOrientation())
                board.Delete(old)
                report["replaced"].append(ref)
            else:
                sheet = c["sheet"]
                col = columns.setdefault(sheet, len(columns))
                y = stage_y.setdefault(sheet, bbox.GetTop())
                fp.SetPosition(pcbnew.VECTOR2I(stage_x + col * pcbnew.FromMM(60), y))
                h = fp.GetBoundingBox(False).GetHeight()
                stage_y[sheet] = y + h + pcbnew.FromMM(2)
                report["added"].append(ref)
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH(c["path"]))
        sheetname = c["sheet"].strip("/")
        fp.SetSheetname(sheetname)
        fp.SetSheetfile(c["fields"].get("Sheetfile", ""))
        for k, v in c["fields"].items():
            if k in ("Sheetname", "Sheetfile", "Footprint", "Datasheet", "Description", "Reference", "Value"):
                continue
            new_field = not fp.HasField(k)
            fp.SetField(k, v)
            if new_field:
                fld = fp.GetField(k)
                fld.SetVisible(False)
                fld.SetLayer(fp.Reference().GetLayer())
        report["updated"] += 1

    # Nets
    netinfo = {}
    for name in sorted(set(pins.values())):
        ni = board.FindNet(name)
        if ni is None:
            ni = pcbnew.NETINFO_ITEM(board, name)
            board.Add(ni)
        netinfo[name] = ni
    unassigned = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            num = pad.GetNumber()
            if not num:
                continue
            net = pins.get((fp.GetReference(), num))
            if net is None:
                if fp.GetReference() in comps and pad.IsOnCopperLayer():
                    unassigned.append("%s.%s" % (fp.GetReference(), num))
                pad.SetNetCode(0)
            else:
                pad.SetNet(netinfo[net])

    if a.strip_copper:
        for t in list(board.GetTracks()):
            board.Delete(t)
        for z in list(board.Zones()):
            board.Delete(z)
    if a.layers:
        board.SetCopperLayerCount(a.layers)

    # Drop nets that are no longer used by any pad
    used = {p.GetNetname() for fp in board.GetFootprints() for p in fp.Pads()}
    if a.strip_copper:
        for name in [n for n in board.GetNetsByName().keys() if str(n) and str(n) not in used]:
            ni = board.FindNet(str(name))
            if ni is not None and ni.GetNetCode() > 0:
                board.Delete(ni)

    board.BuildConnectivity()
    pcbnew.SaveBoard(a.board, board)
    print("updated %d footprints; replaced %d: %s" % (report["updated"], len(report["replaced"]),
                                                     " ".join(report["replaced"])))
    print("added %d (staged right of the board): %s" % (len(report["added"]), " ".join(report["added"][:400])))
    print("removed %d: %s" % (len(report["removed"]), " ".join(report["removed"])))
    print("pads without a netlist pin: %d %s" % (len(unassigned), " ".join(unassigned[:40])))


if __name__ == "__main__":
    main()
