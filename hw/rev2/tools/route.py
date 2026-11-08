#!/usr/bin/env python3
"""Autoroutes hw/kicad/Scaffold.kicad_pcb with Freerouting (KiCad Python).

  <kicad python> hw/rev2/tools/route.py export WORKDIR   -> WORKDIR/scaffold.dsn
  java -jar freerouting.jar -de WORKDIR/scaffold.dsn -do WORKDIR/scaffold.ses -mp 50
  <kicad python> hw/rev2/tools/route.py import WORKDIR   <- WORKDIR/scaffold.ses
  <kicad python> hw/rev2/tools/route.py prune            (dangling routed copper)

export: marks In1/In4 (ground) and In3 (power regions) as plane layers so
that the router does not use them for signals but connects pads to them
with vias, locks the fanout (dog-bones, decoupling tracks), and removes the
outer-layer ground pours (they would block the router).
import: applies the Freerouting session, re-creates the outer ground pours
and refills all zones.
"""
import os
import sys

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
MM = pcbnew.FromMM
POUR_NAME = "GND pour"


def outer_pours(board):
    return [z for z in board.Zones() if z.GetZoneName() == POUR_NAME]


SCRIPTED = ("rev2_fanout", "rev2_stitch", "rev2_buck", "rev2_manual")


def prune(board):
    """Deletes routed tracks and vias with an unconnected end (left over when
    copper was cleared around re-placed parts), repeatedly, so that they do not
    become locked obstacles. Scripted copper (fanout, stitching, buck) is kept."""
    keep = set()
    for g in board.Groups():
        if g.GetName() in SCRIPTED:
            keep |= {i.m_Uuid.AsString() for i in g.GetItems()}
    total = 0
    while True:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.BuildConnectivity()
        conn = board.GetConnectivity()
        dead = [t for t in board.GetTracks()
                if t.m_Uuid.AsString() not in keep and conn.TestTrackEndpointDangling(t, False)]
        if not dead:
            return total
        for t in dead:
            board.Delete(t)
        total += len(dead)


def export(workdir):
    board = pcbnew.LoadBoard(BOARD)
    print("pruned %d dangling tracks/vias" % prune(board))
    for layer in (pcbnew.In1_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu):
        board.SetLayerType(layer, pcbnew.LT_POWER)
    board.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_SIGNAL)
    for t in board.GetTracks():
        t.SetLocked(True)          # fanout and decoupling connections
    for z in outer_pours(board):
        board.Delete(z)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(BOARD, board)  # keeps the layer types and locks
    dsn = os.path.join(workdir, "scaffold.dsn")
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        raise SystemExit("DSN export failed")
    # Freerouting rejects planes on signal layers (the VIN zone on In2): turn
    # them into wire keepouts, so that no signal is routed through the zone
    # (vias may still pass; the zone fills around them after import).
    text = open(dsn).read()
    n = 0
    while True:
        i = text.find("(plane ", 0)
        while i >= 0 and not text[i:i + 200].split("(polygon ", 1)[-1].startswith("Signal "):
            i = text.find("(plane ", i + 1)
        if i < 0:
            break
        j = text.index("(polygon ", i)
        k = _close(text, i)
        text = text[:i] + "(wire_keepout " + text[j:_close(text, j)] + ")" + text[k:]
        n += 1
    open(dsn, "w").write(text)
    print("exported", dsn, "- signal-layer planes as keepouts:", n)


def _close(text, i):
    """Index just past the s-expression starting at text[i]."""
    depth = 0
    while True:
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return i


def add_outer_pours(board):
    bb = board.GetBoardEdgesBoundingBox()
    u = board.FindFootprintByReference("U100")
    cx, cy = u.GetPosition().x, u.GetPosition().y
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(board.FindNet("GND"))
        z.SetZoneName(POUR_NAME)
        z.SetAssignedPriority(0)
        z.SetLocalClearance(MM(0.25))
        z.SetMinThickness(MM(0.25))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)
        o = z.Outline()
        o.NewOutline()
        for x, y in ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()),
                     (bb.GetRight(), bb.GetBottom()), (bb.GetLeft(), bb.GetBottom())):
            o.Append(x, y)
        # No pour under the BGA (no room for thermal spokes between balls).
        o.NewHole()
        h = MM(11.5)
        for x, y in ((cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)):
            o.Append(x, y, -1, 0)
        board.Add(z)


def import_(workdir):
    board = pcbnew.LoadBoard(BOARD)
    ses = os.path.join(workdir, "scaffold.ses")
    # Drop the (placement ...) section: parts do not move, and it lists the
    # mounting holes under placeholder references (REF**_n) that KiCad cannot
    # match, which makes the whole import fail.
    text = open(ses).read()
    i = text.find("(placement")
    if i >= 0:
        depth, j = 0, i
        while True:
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
            if depth == 0:
                break
        text = text[:i] + text[j:]
    clean = os.path.join(workdir, "scaffold-noplacement.ses")
    open(clean, "w").write(text)
    if not pcbnew.ImportSpecctraSES(board, clean):
        raise SystemExit("SES import failed")
    for z in outer_pours(board):
        board.Delete(z)
    add_outer_pours(board)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(BOARD, board)
    print("imported", ses, "- tracks:", len(list(board.GetTracks())))


def prune_cmd(_):
    board = pcbnew.LoadBoard(BOARD)
    print("pruned %d dangling tracks/vias" % prune(board))
    pcbnew.SaveBoard(BOARD, board)


if __name__ == "__main__":
    {"export": export, "import": import_, "prune": prune_cmd}[sys.argv[1]](os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "."))
