#!/usr/bin/env python3
"""Compares two KiCad netlists (kicad-cli sch export netlist --format kicadsexpr).

Usage: verify.py BASELINE.net NEW.net [--ignore-sheet /U_Power/ ...] [--ignore-added]

Reports, for parts present in both netlists and not on an ignored sheet,
every pin whose connectivity changed: a pin is "changed" when the set of
(non-ignored) pins sharing its net differs between the two netlists. Also
lists single-pin nets (likely dangling labels or power symbols) in NEW.
"""
import argparse
import collections
import os
import re
import sys


def parse(path):
    text = open(path).read()
    sec = text[text.index("(nets"):]
    comps = {}
    for m in re.finditer(r'\(comp \(ref "([^"]+)"\)(.*?)\(sheetpath \(names "([^"]*)"\)', text, re.S):
        comps[m.group(1)] = m.group(3)
    if not comps:  # multi-line format
        for m in re.finditer(r'\(comp\s+\(ref "([^"]+)"\)', text):
            blk = text[m.start():text.find("(tstamps", m.start())]
            sp = re.search(r'\(sheetpath\s+\(names "([^"]*)"\)', blk)
            comps[m.group(1)] = sp.group(1) if sp else ""
    pins, nets = {}, collections.defaultdict(list)
    name = ref = None
    for line in sec.splitlines():
        t = line.strip()
        m = re.match(r'\(name "(.*)"\)$', t)
        if m:
            name = m.group(1)
            continue
        m = re.match(r'\(ref "(.*)"\)$', t)
        if m:
            ref = m.group(1)
            continue
        m = re.match(r'\(pin "(.*)"\)$', t)
        if m and ref:
            pins[(ref, m.group(1))] = name
            nets[name].append((ref, m.group(1)))
            ref = None
    return comps, pins, nets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("new")
    ap.add_argument("--ignore-sheet", action="append", default=[])
    ap.add_argument("--ignore-ref", action="append", default=[])
    ap.add_argument("--ignore-added", action="store_true",
                    help="group connectivity over parts present in both netlists only")
    a = ap.parse_args()
    bc, bp, bn = parse(a.baseline)
    nc, np_, nn = parse(a.new)
    if a.ignore_added:
        # Compare groups over the parts present in both netlists only.
        a.ignore_ref += sorted(set(nc) ^ set(bc))
        # Parts kept under the same reference but replaced (different pins).
        bpins = collections.defaultdict(set)
        npins = collections.defaultdict(set)
        for r, p in bp:
            bpins[r].add(p)
        for r, p in np_:
            npins[r].add(p)
        a.ignore_ref += sorted(r for r in set(bc) & set(nc) if bpins[r] != npins[r])

    def keep(ref, comps):
        return comps.get(ref, "") not in a.ignore_sheet and ref not in a.ignore_ref

    def group(pins, nets, comps, key):
        return frozenset(k for k in nets[pins[key]] if keep(k[0], comps))

    changed = []
    for key in sorted(set(bp) & set(np_)):
        if not keep(key[0], bc) or not keep(key[0], nc):
            continue
        gb = group(bp, bn, bc, key)
        gn = group(np_, nn, nc, key)
        if gb != gn:
            changed.append((key, bp[key], np_[key], sorted(gb ^ gn)))
    removed = sorted(r for r in set(bc) - set(nc))
    added = sorted(r for r in set(nc) - set(bc))
    print("parts removed:", " ".join(removed) or "-")
    print("parts added:  ", " ".join(added) or "-")
    print("connectivity changes outside ignored sheets: %d" % len(changed))
    for key, old, new, diff in changed:
        print("  %s.%s: %s -> %s   (differs: %s)" % (key[0], key[1], old, new,
              " ".join("%s.%s" % d for d in diff[:8])))
    singles = sorted(n for n, m in nn.items() if len(m) == 1 and not n.startswith("unconnected-"))
    print("single-pin nets in new netlist: %d" % len(singles))
    for n in singles:
        print("  %s: %s.%s" % (n, *nn[n][0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
