#!/usr/bin/env python3
"""Generates hw/kicad/LEDs.kicad_sch for Scaffold Rev 2.

The TLC5952 constant-current driver of Rev 1.1 is not stocked by JLCPCB. It
is replaced by three daisy-chained 74HC595 on 3V3_FPGA, sinking the LED
current through series resistors (LEDs are active low; the gateware driver
inverts the bits). Bit k of the 24-bit chain (leds(k) in the gateware) drives
LEDk: U400 QA..QH = LED0..LED7, U401 = LED8..LED15, U402 = LED16..LED23.
LED_SDO (QH' of U402) returns to the FPGA as on Rev 1.1.

Run from the repository root:  python3 hw/rev2/tools/gen_leds.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kisch  # noqa: E402
from kisch import LibSymbol, Grid  # noqa: E402

OUT = "hw/kicad/LEDs.kicad_sch"
INSTANCE = "/0930e4eb-3812-4ad2-a87e-ee25991a40db/5c1675e7-0838-4aa3-b6c4-12260e3f42a5"
SHEET_UUID = "02d6c200-c6b8-4225-89a9-fc81c39a2a83"
R0603 = "Resistor_SMD:R_0603_1608Metric"

sheet = kisch.Sheet("LEDs", INSTANCE, power_nets={"3V3_FPGA"}, sheet_uuid=SHEET_UUID)
base = kisch.Baseline("LEDs.kicad_sch")
sym_595 = LibSymbol.from_kicad_lib("74xx", "74HC595")
sym_R = LibSymbol.from_kicad_lib("Device", "R")
sym_C = LibSymbol.from_kicad_lib("Device", "C")

# Shift registers ----------------------------------------------------------
g = Grid(sheet, 25, 40, 520, "LED shift registers (3 x 74HC595, active-low outputs)")
chain_in = ["/LED_SDI", "LED_CHAIN1", "LED_CHAIN2"]
chain_out = ["LED_CHAIN1", "LED_CHAIN2", "/LED_SDO"]
q_pins = ["15", "1", "2", "3", "4", "5", "6", "7"]   # QA..QH
for i, ref in enumerate(("U400", "U401", "U402")):
    nets = {"14": chain_in[i], "11": "/LED_CLK", "12": "/LED_LE", "13": "/LED_/OE",
            "10": "3V3_FPGA", "16": "3V3_FPGA", "8": "GND", "9": chain_out[i]}
    for b, pin in enumerate(q_pins):
        nets[pin] = "LED%d" % (8 * i + b)
    g.add(ref, sym_595, nets, value="74HC595D", footprint="Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
          fields={"LCSC": "C5947", "MANUFACTURER PN": "74HC595D,118", "MANUFACTURER": "Nexperia"},
          label_room=25.4)
for ref in ("C400", "C401"):
    g.add(ref, sym_C, {"1": "3V3_FPGA", "2": "GND"}, value="100nF 50V",
          footprint="Capacitor_SMD:C_0603_1608Metric", fields={"LCSC": "C14663"}, label_room=12.7)
g.add("C402", sym_C, {"1": "3V3_FPGA", "2": "GND"}, value="100nF 50V",
      footprint="Capacitor_SMD:C_0603_1608Metric", fields={"LCSC": "C14663"}, label_room=12.7)
# Outputs disabled (LEDs off) while the FPGA is not configured.
g.add("R425", sym_R, {"1": "3V3_FPGA", "2": "/LED_/OE"}, value="10k", footprint=R0603,
      fields={"LCSC": "C25804"}, label_room=12.7)
for ref, net in (("TP400", "/LED_CLK"), ("TP401", "/LED_LE"), ("TP402", "/LED_/OE"),
                 ("TP403", "/LED_SDI"), ("TP405", "/LED_SDO")):
    base.place(g, ref, {"1": net})

# LEDs ---------------------------------------------------------------------
# Rev 1.1 channel of each LED (cathode net LEDn), kept so that the gateware
# LED map is unchanged. D400/D401 are red/green bicolour LEDs (two channels).
SINGLE = {"D416": 0, "D417": 1, "D418": 2, "D419": 3, "D420": 4, "D421": 5, "D422": 6, "D423": 7,
          "D409": 8, "D410": 9, "D411": 10, "D412": 11, "D403": 12, "D404": 13, "D405": 14,
          "D406": 15, "D407": 16, "D408": 17, "D415": 20, "D402": 21}
BICOLOUR = {"D400": (19, 18), "D401": (23, 22)}   # (pin 3 channel, pin 4 channel)

g = Grid(sheet, 25, g.bottom() + 30, 520, "LEDs (anodes on 3V3_FPGA, cathodes through resistors to the 74HC595)")
rnum = 401
for ref, ch in sorted(SINGLE.items(), key=lambda x: x[1]):
    base.place(g, ref, {"2": "3V3_FPGA", "1": "LED%d_K" % ch})
for ref, (ch3, ch4) in BICOLOUR.items():
    base.place(g, ref, {"1": "3V3_FPGA", "2": "3V3_FPGA", "3": "LED%d_K" % ch3, "4": "LED%d_K" % ch4})
for ch in range(24):
    bic = ch in (18, 19, 22, 23)
    value, lcsc = ("330", "C23138") if bic else ("680", "C23228")
    g.add("R%d" % rnum, sym_R, {"1": "LED%d_K" % ch, "2": "LED%d" % ch}, value=value, footprint=R0603,
          fields={"LCSC": lcsc}, label_room=12.7)
    rnum += 1

sheet.power_flags([], 25, 20)
sheet.write(OUT)
print("wrote", OUT, "-", len(sheet.parts), "parts")
