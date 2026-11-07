#!/usr/bin/env python3
"""Produces the JLCPCB fabrication and assembly files for Scaffold Rev 2.

Run with KiCad's bundled Python (needs pcbnew), from the repository root:

  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \\
      hw/rev2/make_jlc.py [--out hw/rev2/jlc]

Outputs (in --out):
  scaffold-rev2-gerbers.zip  Gerbers (6 layers) + Excellon drill files, for the PCB order
  bom-jlc.csv                Comment, Designator, Footprint, LCSC (parts assembled by JLCPCB)
  cpl-jlc.csv                Designator, Mid X, Mid Y, Layer, Rotation
  hand-assembly.csv          parts to buy elsewhere and fit by hand (not stocked by JLCPCB)
  drc.txt                    KiCad DRC report
  report.txt                 summary, parts without an LCSC number

LCSC numbers come from the footprint's LCSC field (set in the schematic),
or from hw/rev2/lcsc_map.csv by manufacturer part number for the parts
carried over from Rev 1.1.
"""
import argparse
import collections
import csv
import os
import shutil
import subprocess
import sys
import zipfile

import pcbnew

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BOARD = os.path.join(REPO, "hw", "kicad", "Scaffold.kicad_pcb")
LCSC_MAP = os.path.join(REPO, "hw", "rev2", "lcsc_map.csv")
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
LAYERS = "F.Cu,In1.Cu,In2.Cu,In3.Cu,In4.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"
NO_PART = ("TP_001", "MIRE", "LOGO", "Logo", "logo")   # copper pads, fiducials, graphics


def cli(*args):
    r = subprocess.run([KICAD_CLI] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit("kicad-cli %s failed" % args[1])
    return r.stdout


def field(fp, name):
    return fp.GetFieldText(name) if fp.HasField(name) else ""


def part_center(fp):
    """Centre of the pads (JLC places by part centre, not footprint origin:
    the footprints imported from Altium do not all have a centred origin)."""
    pads = [p for p in fp.Pads() if p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH]
    if not pads:
        return fp.GetPosition()
    box = pads[0].GetBoundingBox()
    for p in pads[1:]:
        box.Merge(p.GetBoundingBox())
    return box.GetCenter()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "hw", "rev2", "jlc"))
    ap.add_argument("--board", default=BOARD)
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)

    lmap = {r["mpn"]: r for r in csv.DictReader(open(LCSC_MAP))}
    board = pcbnew.LoadBoard(a.board)
    # kicad-cli exports the zone fills saved in the file: refill on a copy
    # next to the project (so that the project rules and libraries apply).
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    filled = os.path.join(os.path.dirname(os.path.abspath(a.board)), ".jlc-export.kicad_pcb")
    pcbnew.SaveBoard(filled, board)
    shutil.copy(os.path.splitext(a.board)[0] + ".kicad_pro", os.path.splitext(filled)[0] + ".kicad_pro")
    a.board = filled

    bom = collections.OrderedDict()
    cpl, hand, missing = [], collections.defaultdict(list), []
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        ref = fp.GetReference()
        fpname = fp.GetFPIDAsString().split(":")[-1]
        if not ref or ref.startswith("#") or any(fpname.startswith(x) for x in NO_PART) \
                or not any(p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH for p in fp.Pads()):
            continue
        if fp.IsDNP() or fp.IsExcludedFromBOM():
            continue
        mpn = field(fp, "MANUFACTURER PN")
        lcsc = field(fp, "LCSC")
        assembly = "jlc"
        if not lcsc and mpn in lmap:
            lcsc, assembly = lmap[mpn]["lcsc"], lmap[mpn]["assembly"]
        if assembly == "hand" or (not lcsc and mpn):
            note = lmap.get(mpn, {}).get("note", "")
            hand[(mpn, fp.GetValue(), note)].append(ref)
            continue
        if not lcsc:
            missing.append(ref)
            continue
        key = (lcsc, fp.GetValue(), fpname)
        bom.setdefault(key, []).append(ref)
        c = part_center(fp)
        rot = fp.GetOrientation().AsDegrees() % 360
        cpl.append((ref, "%.4f" % pcbnew.ToMM(c.x), "%.4f" % -pcbnew.ToMM(c.y),
                    "Bottom" if fp.IsFlipped() else "Top", "%g" % rot))

    with open(os.path.join(out, "bom-jlc.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC"])
        for (lcsc, value, fpname), refs in bom.items():
            w.writerow([value, ",".join(refs), fpname, lcsc])
    with open(os.path.join(out, "cpl-jlc.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(cpl)
    with open(os.path.join(out, "hand-assembly.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Quantity", "Designator", "Manufacturer PN", "Value", "Note"])
        for (mpn, value, note), refs in sorted(hand.items()):
            w.writerow([len(refs), ",".join(refs), mpn, value, note])

    # Gerbers and drill files (Protel extensions, as JLCPCB expects).
    gdir = os.path.join(out, "gerbers")
    shutil.rmtree(gdir, ignore_errors=True)
    os.makedirs(gdir)
    cli("pcb", "export", "gerbers", "--layers", LAYERS, "--subtract-soldermask", "--no-x2",
        "-o", gdir + "/", a.board)
    cli("pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
        "--excellon-units", "mm", "--drill-origin", "absolute", "--generate-map", "--map-format", "gerberx2",
        "-o", gdir + "/", a.board)
    zpath = os.path.join(out, "scaffold-rev2-gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(os.listdir(gdir)):
            z.write(os.path.join(gdir, name), name)

    drc = os.path.join(out, "drc.txt")
    subprocess.run([KICAD_CLI, "pcb", "drc", "--schematic-parity", "--severity-error", "-o", drc, a.board],
                   capture_output=True, text=True)
    drc_summary = [l for l in open(drc) if l.startswith("**")]

    with open(os.path.join(out, "report.txt"), "w") as f:
        f.write("Scaffold Rev 2 - JLCPCB outputs\n\n")
        f.write("Assembled by JLCPCB: %d parts, %d BOM lines\n" % (len(cpl), len(bom)))
        f.write("Hand assembly: %d parts, %d lines (see hand-assembly.csv)\n"
                % (sum(len(v) for v in hand.values()), len(hand)))
        f.write("Parts without LCSC number nor manufacturer PN: %s\n" % (" ".join(missing) or "none"))
        f.write("Board sides with assembled parts: %s\n" % ", ".join(sorted({r[3] for r in cpl})))
        f.write("\nDRC (errors only):\n" + "".join(drc_summary))
        f.write("\nCheck the part rotations in JLCPCB's placement preview before confirming the order.\n")
    print(open(os.path.join(out, "report.txt")).read())
    for ext in (".kicad_pcb", ".kicad_pro", ".kicad_prl"):
        try:
            os.remove(os.path.splitext(a.board)[0] + ext)
        except OSError:
            pass


if __name__ == "__main__":
    main()
