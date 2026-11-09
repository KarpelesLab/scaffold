#!/usr/bin/env python3
"""openEMS model of a region of the board, built from the real copper.

  python hw/rev2/sim/em_sim.py CONFIG.json

CONFIG keys:
  copper   export_copper.py output made with a box (every net in the box)
  out      directory for the simulation files and results
  fmax     highest frequency (Hz); the excitation covers 0..fmax
  res      xy mesh step (mm)
  ports    [{x, y, L, ref, R, excite}]       vertical port from layer ref to L at (x, y)
           or [{x0, y0, x1, y1, L, R, excite, dir}]   in-plane port on layer L
  shorts   [{x0, y0, x1, y1, L}]             PEC bridges (e.g. capacitors at HF)
  loads    [{x0, y0, x1, y1, L, dir, R, C, Lser}]   lumped RLC elements
  freqs    [f, ...] points for the printed table

Stackup: JLC06161H-2116 (dielectrics between the six copper layers: 0.2234 mm
er 4.1, 0.3 mm 4.6, 0.4168 mm 4.4, 0.3 mm 4.6, 0.2234 mm 4.1, tan d 0.02).
Copper is modelled as zero-thickness PEC sheets, vias and plated holes as
PEC cylinders. The box edges are absorbing (PML), so planes and tracks cut
by the box continue as if infinite (the outer 8 cells of the box are the
absorber: keep ports and the area of interest at least 8 cells inside).

Writes results.json (S parameters, port impedance, TDR impedance profile
of port 1) in `out`.
"""
import json
import math
import os
import sys

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import split, unary_union

from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.physical_constants import C0, EPS0

Z = {"F": 1.4636, "In1": 1.2402, "In2": 0.9402, "In3": 0.5234, "In4": 0.2234, "B": 0.0}   # mm, F on top
DIEL = [("B", "In4", 4.1), ("In4", "In3", 4.6), ("In3", "In2", 4.4), ("In2", "In1", 4.6), ("In1", "F", 4.1)]
TAND = 0.02


def no_holes(poly):
    """Split a polygon with holes into hole-free pieces (CSXCAD polygons have no holes)."""
    todo, out = [poly], []
    while todo:
        p = todo.pop()
        if p.is_empty or p.area < 1e-6:
            continue
        if not p.interiors:
            out.append(p)
            continue
        hx = Polygon(p.interiors[0]).centroid.x
        y0, y1 = p.bounds[1] - 1, p.bounds[3] + 1
        parts = split(p, LineString([(hx, y0), (hx, y1)]))
        for g in parts.geoms:
            if isinstance(g, Polygon):
                todo.append(g)
    return out


def main():
    cfg = json.load(open(sys.argv[1]))
    d = json.load(open(cfg["copper"]))
    out = os.path.abspath(cfg["out"])
    os.makedirs(out, exist_ok=True)
    x0, y0, x1, y1 = d["box"]
    fmax = cfg["fmax"]
    h = cfg["res"]

    FDTD = openEMS(NrTS=cfg.get("nrts", 300000), EndCriteria=cfg.get("end", 1e-4),
                   TimeStepMethod=cfg.get("tsmethod", 1))
    if cfg.get("tsfactor"):
        FDTD.SetTimeStepFactor(cfg["tsfactor"])
    FDTD.SetGaussExcite(fmax / 2, fmax / 2)
    FDTD.SetBoundaryCond([cfg.get("bc", "PML_8")] * 6)
    CSX = ContinuousStructure()
    FDTD.SetCSX(CSX)
    grid = CSX.GetGrid()
    grid.SetDeltaUnit(1e-3)

    # board y grows downwards; mirror it so the model is right-handed with F on top
    def my(y):
        return -y

    # uniform xy mesh; ports, shorts and loads are snapped onto it (no near-coincident lines,
    # which would shrink the timestep)
    snap = lambda v: round(round(v / h) * h, 6)
    # the mesh ends at the copper box: the 8 PML cells at each side lie over the clipped copper,
    # so tracks and planes cut by the box run into the absorber (a line ending at the PML
    # boundary would be an open stub)
    gx0, gx1 = snap(x0), snap(x1)
    gy0, gy1 = snap(my(y1)), snap(my(y0))
    grid.AddLine("x", np.round(np.arange(gx0, gx1 + h / 2, h), 6))
    grid.AddLine("y", np.round(np.arange(gy0, gy1 + h / 2, h), 6))
    zl = sorted(Z.values())
    zs = set(zl)
    for a, b in zip(zl, zl[1:]):
        n = max(2, int(math.ceil((b - a) / 0.1)))
        zs |= {a + (b - a) * k / n for k in range(1, n)}
    # air above and below, growing
    top, bot, step = zl[-1], zl[0], 0.1
    for _ in range(cfg.get("air_lines", 8)):
        top += step
        bot -= step
        zs |= {top, bot}
        step = min(step * 1.4, 1.0)
    grid.AddLine("z", np.array(sorted(round(z, 4) for z in zs)))

    f0 = fmax / 2
    for la, lb, er in DIEL:
        tand = cfg.get("tand", TAND)
        m = CSX.AddMaterial("diel_%s_%s" % (la, lb), epsilon=er, kappa=2 * math.pi * f0 * EPS0 * er * tand)
        m.AddBox(priority=0, start=[gx0 - 1, gy0 - 1, Z[la]], stop=[gx1 + 1, gy1 + 1, Z[lb]])

    metal = CSX.AddMetal("copper")
    nshapes = 0
    for c in d["copper"]:
        if c["L"] not in Z:
            continue
        polys = []
        for poly in c["poly"]:
            shell = [(x, my(y)) for x, y in poly[0]]
            holes = [[(x, my(y)) for x, y in r] for r in poly[1:] if len(r) > 2]
            if len(shell) > 2:
                pg = Polygon(shell, holes).buffer(0)
                polys.extend(pg.geoms if isinstance(pg, MultiPolygon) else [pg])
        for pg in polys:
            for piece in no_holes(pg):
                xs, ys = piece.exterior.coords.xy
                metal.AddPolygon([np.array(xs[:-1]), np.array(ys[:-1])], "z", Z[c["L"]], priority=10)
                nshapes += 1
    margin = 10 * h      # vertical conductors inside the PML make it unstable: leave them out there
    for v in d["vias"] + d["holes"]:
        if not (x0 + margin < v["x"] < x1 - margin and y0 + margin < v["y"] < y1 - margin):
            continue
        lays = [Z[l] for l in v["L"] if l in Z] or [Z["F"], Z["B"]]
        if len(lays) < 2:
            lays = [Z["F"], Z["B"]]
        metal.AddCylinder(start=[v["x"], my(v["y"]), min(lays)], stop=[v["x"], my(v["y"]), max(lays)],
                          radius=max(v["drill"] / 2, h / 2), priority=10)
    for s in cfg.get("shorts", []):
        z = Z[s["L"]]
        metal.AddBox(priority=10, start=[snap(s["x0"]), snap(my(s["y0"])), z], stop=[snap(s["x1"]), snap(my(s["y1"])), z])

    ports = []
    for k, p in enumerate(cfg["ports"], start=1):
        if "x" in p:
            za, zb = Z[p["ref"]], Z[p["L"]]
            start = [snap(p["x"]), snap(my(p["y"])), za]     # one-cell-wide wire, ref plane -> signal layer
            stop = [snap(p["x"]), snap(my(p["y"])), zb]
            direc = "z"
        else:
            z = Z[p["L"]]
            start = [snap(p["x0"]), snap(my(p["y0"])), z]
            stop = [snap(p["x1"]), snap(my(p["y1"])), z]
            direc = p["dir"]
        ports.append(FDTD.AddLumpedPort(k, p.get("R", 50), start, stop, direc, excite=p.get("excite", 0), priority=20))
    for k, e in enumerate(cfg.get("loads", [])):
        z = Z[e["L"]]
        kw = {}
        if "R" in e:
            kw["R"] = e["R"]
        if "C" in e:
            kw["C"] = e["C"]
        if "Lser" in e:
            kw["L"] = e["Lser"]
        el = CSX.AddLumpedElement("load%d" % k, ny=e["dir"].replace("-", ""), caps=True, **kw)
        el.AddBox(start=[snap(e["x0"]), snap(my(e["y0"])), z], stop=[snap(e["x1"]), snap(my(e["y1"])), z], priority=20)

    print("model: %d copper shapes, mesh %d x %d x %d" % (
        nshapes, len(grid.GetLines("x")), len(grid.GetLines("y")), len(grid.GetLines("z"))), flush=True)
    kw = {"engine": cfg["engine"]} if cfg.get("engine") else {}     # "gpu": Metal/OpenCL engine
    FDTD.Run(out, cleanup=True, verbose=cfg.get("verbose", 0), numThreads=cfg.get("threads", 0), **kw)

    f = np.linspace(fmax / 400, fmax, 400)
    for p in ports:
        p.CalcPort(out, f, ref_impedance=p.R if hasattr(p, "R") else 50)
    exc = [k for k, p in enumerate(cfg["ports"]) if p.get("excite")][0]
    pe = ports[exc]
    res = dict(f=f.tolist())
    for k, p in enumerate(ports):
        s = p.uf_ref / pe.uf_inc
        if k == exc:
            s = p.uf_ref / p.uf_inc
        res["S%d%d" % (k + 1, exc + 1)] = dict(re=np.real(s).tolist(), im=np.imag(s).tolist())
    zin = pe.uf_tot / pe.if_tot
    res["Zin"] = dict(re=np.real(zin).tolist(), im=np.imag(zin).tolist())
    # TDR of the excited port: step response from S11 (DC point extrapolated), raised-cosine window
    s11 = pe.uf_ref / pe.uf_inc
    fu = np.concatenate([[0.0], f])
    su = np.concatenate([[np.real(s11[0])], s11])
    win = 0.5 * (1 + np.cos(np.pi * fu / fu[-1]))
    nfft = 8192
    imp = np.fft.irfft(su * win, n=nfft)
    step = np.cumsum(imp)
    dt = 1.0 / (nfft * (fu[1] - fu[0]))
    zref = cfg["ports"][exc].get("R", 50)
    zt = zref * (1 + step) / (1 - step)
    nshow = int(cfg.get("tdr_ns", 2.0) * 1e-9 / dt)
    res["tdr"] = dict(t_ns=(np.arange(nshow) * dt * 1e9).tolist(), z=zt[:nshow].tolist())
    json.dump(res, open(os.path.join(out, "results.json"), "w"))
    for fq in cfg.get("freqs", []):
        i = int(np.argmin(abs(f - fq)))
        line = "f %7.1f MHz  Zin %8.3f %+8.3fj" % (f[i] / 1e6, zin[i].real, zin[i].imag)
        for key in res:
            if key.startswith("S"):
                s = complex(res[key]["re"][i], res[key]["im"][i])
                line += "  %s %6.2f dB" % (key, 20 * math.log10(abs(s) + 1e-12))
        print(line)


if __name__ == "__main__":
    main()
