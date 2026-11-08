#!/usr/bin/env python3
"""Scripted routes the autorouter does not find (KiCad Python, group rev2_manual).

J501 <-> J502 (DUT/platform daughter-board headers, odd pins): the two
headers are a shifted copy of each other on one row, so every pair of nets
interleaves and no single-layer route exists. Each net: bottom-layer stub
down from the J501 pin, via, Signal-layer (In2) run east at its own depth,
up to the J502 pin on In2. Depths increase with the pin number, so that the
In2 parts never cross.

Run after stitch.py, before routing. Re-running replaces the group.
"""
import os

import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
MM = pcbnew.FromMM
GROUP = "rev2_manual"

board = pcbnew.LoadBoard(BOARD)
for g in list(board.Groups()):
    if g.GetName() == GROUP:
        for item in list(g.GetItems()):
            board.Delete(item)
        board.Delete(g)
group = pcbnew.PCB_GROUP(board)
group.SetName(GROUP)
board.Add(group)


def add(item):
    board.Add(item)
    group.AddItem(item)


def track(a, b, layer, net, w=0.2):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(a)
    t.SetEnd(b)
    t.SetWidth(MM(w))
    t.SetLayer(layer)
    t.SetNet(net)
    add(t)


def pad(ref, n):
    return next(p for p in board.FindFootprintByReference(ref).Pads() if p.GetNumber() == n)


n = 0
for m, pin in enumerate(range(1, 18, 2)):
    a, b = pad("J501", str(pin)), pad("J502", str(pin))
    assert a.GetNetCode() == b.GetNetCode()
    pa, pb = a.GetPosition(), b.GetPosition()
    y = pa.y + MM(1.65 + 0.7 * m)
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(pa.x, y))
    v.SetWidth(MM(0.6))
    v.SetDrill(MM(0.3))
    v.SetNet(a.GetNet())
    add(v)
    track(pa, pcbnew.VECTOR2I(pa.x, y), pcbnew.B_Cu, a.GetNet())
    track(pcbnew.VECTOR2I(pa.x, y), pcbnew.VECTOR2I(pb.x, y), pcbnew.In2_Cu, a.GetNet())
    track(pcbnew.VECTOR2I(pb.x, y), pb, pcbnew.In2_Cu, a.GetNet())
    n += 1

pcbnew.ZONE_FILLER(board).Fill(board.Zones())
pcbnew.SaveBoard(BOARD, board)
print("manual routes: %d header nets" % n)
