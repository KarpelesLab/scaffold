#!/usr/bin/env python3
"""Sets the Rev 2 design rules and net classes in hw/kicad/Scaffold.kicad_pro.

Rules follow JLCPCB's 6-layer capabilities with margin (their minimums:
0.09 mm track/space, 0.15 mm via drill, 0.25 mm via diameter).

Usage: layout_rules.py NETLIST.net   (kicad-cli sch export netlist --format kicadsexpr)
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify  # noqa: E402

PRO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kicad", "Scaffold.kicad_pro")

RULES = {
    "min_clearance": 0.1,
    "min_track_width": 0.1,
    "min_via_diameter": 0.4,
    "min_via_annular_width": 0.1,
    "min_through_hole_diameter": 0.2,
    "min_hole_to_hole": 0.25,
    "min_hole_clearance": 0.2,
    "min_copper_edge_clearance": 0.3,
    # Silkscreen: JLC prints down to ~0.15 mm strokes; smaller imported
    # texts are legible but thin, they are not fabrication errors.
    "min_text_height": 0.6,
    "min_text_thickness": 0.1,
}

FPGA_POWER = ["1V0", "1V8", "3V3_FPGA", "VCC_IO_FPGA", "VCCADC"]
POWER = ["VBUS_C", "VEXT", "VIN_MUX", "VIN", "VPRE", "Vsupply", "VCC_PLATFORM", "VCC_DUT",
         "VCC_PLATFORM_PERMANENT", "VCC_DUT_PERMANENT", "/U_Power/SW_*", "/U_Power/*_LDO_OUT",
         "/U_Power/PLAT_EXT*", "/U_Power/DUT_EXT*"]

CLASS_TEMPLATE = {"bus_width": 12, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25, "diff_pair_width": 0.2,
                  "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
                  "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
                  "tuning_profile": "", "wire_width": 6}


def cls(name, priority, track, clearance, via_d, via_drill):
    c = dict(CLASS_TEMPLATE)
    c.update(name=name, priority=priority, track_width=track, clearance=clearance,
             via_diameter=via_d, via_drill=via_drill)
    return c


def main():
    comps, pins, nets = verify.parse(sys.argv[1])
    fpga_io = sorted({n for (ref, pin), n in pins.items() if ref == "U100"} - set(FPGA_POWER) - {"GND"})
    fpga_io = [n for n in fpga_io if not n.startswith("unconnected-")]

    d = json.load(open(PRO))
    d["board"]["design_settings"]["rules"].update(RULES)
    d["net_settings"]["classes"] = [
        cls("Default", -1, 0.2, 0.15, 0.6, 0.3),
        cls("FPGA_IO", 2, 0.1, 0.1, 0.4, 0.2),
        # 0.1 mm clearance for the nets of the BGA dog-bone fanout (vias 0.166 mm
        # from the 0.4 mm balls). kicad-cli ignores .kicad_dru custom rules, so
        # the BGA constraints are expressed through net classes only.
        cls("FPGA_PWR", 1, 0.4, 0.1, 0.45, 0.2),
        cls("GND", 3, 0.4, 0.1, 0.6, 0.3),
        cls("POWER", 0, 0.8, 0.2, 0.8, 0.4),
    ]
    patterns = [{"netclass": "FPGA_IO", "pattern": n} for n in fpga_io]
    patterns += [{"netclass": "FPGA_PWR", "pattern": n} for n in FPGA_POWER]
    patterns += [{"netclass": "POWER", "pattern": n} for n in POWER]
    patterns += [{"netclass": "GND", "pattern": "GND"}]
    d["net_settings"]["netclass_patterns"] = patterns
    json.dump(d, open(PRO, "w"), indent=2)
    print("rules set; FPGA_IO %d nets, FPGA_PWR %d, POWER %d patterns" % (len(fpga_io), len(FPGA_POWER), len(POWER)))


if __name__ == "__main__":
    main()
