#!/usr/bin/env python3
"""Post-routing fixes (KiCad Python): <kicad python> hw/rev2/tools/postroute.py

- Freerouting emits a few segments thinner than the net class (0.06-0.075 mm
  pad entries): widen every track below 0.1 mm to 0.1 mm (JLC minimum
  0.09 mm). DRC then checks the clearances.
"""
import os
import pcbnew

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pcb")
board = pcbnew.LoadBoard(BOARD)
n = 0
for t in board.GetTracks():
    if t.GetClass() == "PCB_TRACK" and t.GetWidth() < pcbnew.FromMM(0.1):
        t.SetWidth(pcbnew.FromMM(0.1))
        n += 1
# Slivers: segments shorter than 0.15 mm that were among the thin pad
# entries; if widening them brings them closer than 0.1 mm to another net,
# delete them and let the next routing pass reconnect.
removed = 0
doomed = []
others = [t for t in board.GetTracks()]
pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
for t in list(board.GetTracks()):
    if t.GetClass() != "PCB_TRACK" or t.GetLength() >= pcbnew.FromMM(0.15):
        continue
    sh = t.GetEffectiveShape()
    bad = False
    for o in others + pads:
        if o is t or o.GetNetCode() == t.GetNetCode() or not o.IsOnLayer(t.GetLayer()):
            continue
        if sh.Collide(o.GetEffectiveShape(t.GetLayer()), pcbnew.FromMM(0.1) - 1):
            bad = True
            break
    if bad:
        doomed.append(t)
for t in doomed:          # delete after the scan: deleted items must not be touched again
    board.Delete(t)
    removed += 1
# Test pins on GND: solid zone connection (one thermal spoke only otherwise).
for fp in board.GetFootprints():
    if fp.GetReference().startswith("THP"):
        fp.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
pcbnew.SaveBoard(BOARD, board)
print("widened %d thin segments, removed %d slivers too close to other nets" % (n, removed))
