#!/bin/sh
# Runs the board simulations: DC drop of the power nets and the openEMS cases.
# Usage (repository root): hw/rev2/sim/run.sh [case ...]   (default: irdrop and every case)
# Needs openEMS with its Python bindings (built with the GPU engine, see
# DESIGN.md section 8) in a venv at $OPENEMS_VENV (default ~/opt/openEMS/venv),
# which also provides numpy, scipy, shapely and pillow.
set -e
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
PY="${OPENEMS_VENV:-$HOME/opt/openEMS/venv}/bin/python"
OUT="${SIM_OUT:-$(mktemp -d -t scaffold-sim)}"
mkdir -p "$OUT"
DIR=$(cd "$(dirname "$0")" && pwd)
quiet() { grep -vE "swig/python detected|Fontconfig|wxApp|Open Sans|Font '" || true; }
CASES="$*"
[ -n "$CASES" ] || CASES="irdrop $(cd "$DIR/cases" && ls *.json | sed 's/\.json$//')"
for c in $CASES; do
  if [ "$c" = irdrop ]; then
    "$KPY" "$DIR/export_copper.py" "$OUT/power.json" \
      "VBUS_C,VEXT,VIN_MUX,VIN,VPRE,VCC_DUT,VCC_PLATFORM,VCC_DUT_PERMANENT,VCC_PLATFORM_PERMANENT,1V0,1V8,3V3_FPGA,VCC_IO_FPGA,Vsupply,/U_Power/DUT_LDO_OUT,/U_Power/PLAT_LDO_OUT" 2>&1 | quiet
    (cd / && "$PY" -I "$DIR/irdrop.py" "$OUT/power.json") | grep -v "0.00 A/mm"
    continue
  fi
  nets=$("$PY" -I -c "import json,sys; c=json.load(open(sys.argv[1])); print(c['nets'])" "$DIR/cases/$c.json")
  box=$("$PY" -I -c "import json,sys; c=json.load(open(sys.argv[1])); print(*c['box'])" "$DIR/cases/$c.json")
  "$KPY" "$DIR/export_copper.py" "$OUT/$c-copper.json" "$nets" $box 2>&1 | quiet
  "$PY" -I -c "import json,sys; c=json.load(open(sys.argv[1])); c.update(copper=sys.argv[2], out=sys.argv[3]); json.dump(c, open(sys.argv[4], 'w'))" \
    "$DIR/cases/$c.json" "$OUT/$c-copper.json" "$OUT/$c" "$OUT/$c-cfg.json"
  echo "== $c"
  (cd / && "$PY" -I "$DIR/em_sim.py" "$OUT/$c-cfg.json") | grep -E "^(model|f )"
done
echo "work files in $OUT"
