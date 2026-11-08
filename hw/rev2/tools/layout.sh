#!/bin/sh
# Rev 2 layout pipeline, from the schematic to a placed, fanned-out board.
# Usage: hw/rev2/tools/layout.sh   (from the repository root)
# Stops at the first failing step.
set -e
KICAD=/Applications/KiCad/KiCad.app/Contents
KPY=$KICAD/Frameworks/Python.framework/Versions/Current/bin/python3
CLI=$KICAD/MacOS/kicad-cli
NET=$(mktemp -t scaffold-net).net
quiet() { grep -vE "swig/python detected|Fontconfig|wxApp|Open Sans" || true; }

$CLI sch export netlist --format kicadsexpr -o "$NET" hw/kicad/Scaffold.kicad_sch >/dev/null
python3 hw/rev2/tools/layout_rules.py "$NET"
"$KPY" hw/rev2/tools/update_pcb.py "$NET" --strip-copper --layers 6 2>&1 | quiet | grep -E "^(updated|removed)" | cut -c1-120
"$KPY" hw/rev2/tools/place.py 2>&1 | quiet
"$KPY" hw/rev2/tools/fanout.py 2>&1 | quiet
"$KPY" hw/rev2/tools/stitch.py 2>&1 | quiet | cut -c1-160
rm -f "$NET"
