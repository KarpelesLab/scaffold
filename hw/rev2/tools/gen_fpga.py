#!/usr/bin/env python3
"""Generates hw/kicad/FPGA.kicad_sch for Scaffold Rev 2 (Artix-7, CSG324).

Also writes the pin assignment to hw/rev2/fpga_pins.csv (net, ball, bank),
used to produce the Vivado constraints (fpga-arch/artix7/scaffold.xdc).

Banks:
  0, 14, 15, 16 : 3V3_FPGA      (configuration, flash, UART, LEDs, A0-A3, control)
  34, 35        : VCC_IO_FPGA   (DUT and platform I/Os, adjustable 1.2-3.3 V)
Configuration: Master SPI x4 from a W25Q128JV (M[2:0] = 001), CFGBVS = VCCO_0.

Run from the repository root:  python3 hw/rev2/tools/gen_fpga.py
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kisch  # noqa: E402
from kisch import LibSymbol, Grid  # noqa: E402

OUT = "hw/kicad/FPGA.kicad_sch"
PINS_CSV = "hw/rev2/fpga_pins.csv"
INSTANCE = "/0930e4eb-3812-4ad2-a87e-ee25991a40db/3e0aade1-ddc3-4b7e-9d6f-533461f45ea6"
SHEET_UUID = "2f0375a1-289b-4c58-9d56-887f0ac1e9a4"

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
CAPS = {"100uF": ("Capacitor_SMD:C_1206_3216Metric", "C15008", "100uF 6.3V"),
        "47uF": ("Capacitor_SMD:C_0805_2012Metric", "C16780", "47uF 6.3V"),
        "4.7uF": (C0603, "C19666", "4.7uF 16V"),
        "0.47uF": (C0603, "C1623", "470nF 25V"),
        "1uF": (C0603, "C15849", "1uF 50V"),
        "100nF": (C0603, "C14663", "100nF 50V")}
RES = {"330": "C23138", "1k": "C21190", "4.7k": "C23162", "10k": "C25804"}

sheet = kisch.Sheet("FPGA", INSTANCE, sheet_uuid=SHEET_UUID,
                    power_nets={"1V0", "1V8", "3V3_FPGA", "VCC_IO_FPGA", "VCCADC"})
base = kisch.Baseline("FPGA.kicad_sch")
sym_fpga = LibSymbol.from_kicad_lib("FPGA_Xilinx_Artix7", "XC7A35T-CSG324")
sym_flash = LibSymbol.from_kicad_lib("Memory_Flash", "W25Q128JVS")
sym_R = LibSymbol.from_kicad_lib("Device", "R")
sym_C = LibSymbol.from_kicad_lib("Device", "C")
sym_FB = LibSymbol.from_kicad_lib("Device", "FerriteBead_Small")
sym_hdr = LibSymbol.from_kicad_lib("Connector_Generic", "Conn_01x06")


class RefPool:
    """Reuses the references of removed Rev 1.1 parts before new numbers."""

    def __init__(self, prefix, numbers):
        self.prefix, self.numbers = prefix, list(numbers)

    def next(self):
        return "%s%d" % (self.prefix, self.numbers.pop(0))


cref = RefPool("C", list(range(100, 136)) + list(range(143, 147)) + list(range(155, 200)))
rref = RefPool("R", list(range(101, 110)) + list(range(113, 200)))

# ---------------------------------------------------------------------------
# Pin assignment

ROWS = "ABCDEFGHJKLMNPRTUV"


def depth(ball):
    m = re.match(r"([A-V])(\d+)$", ball)
    r, c = ROWS.index(m.group(1)), int(m.group(2)) - 1
    return min(r, 17 - r, c, 17 - c)


def bank_of(name):
    m = re.search(r"_(\d+)$", name)
    return m.group(1) if m else None


RESERVED = re.compile(r"D0[0-3]|FCS_B|PUDC_B|EMCCLK|RDWR_B|CSO_B|DOUT")
io = {}   # ball -> name
for p in sym_fpga.pins:
    if p["name"].startswith("IO_"):
        io[p["number"]] = p["name"]


def free_balls(bank, clock=False):
    balls = [b for b, n in io.items() if bank_of(n) == bank and not RESERVED.search(n)
             and b not in assigned.values()]
    if clock:
        balls = [b for b in balls if "MRCC" in io[b]]
    return sorted(balls, key=lambda b: (depth(b), b))


assigned = {}   # net -> ball


def assign(bank, nets, clock=False):
    for net in nets:
        balls = free_balls(bank, clock)
        if not balls:
            raise RuntimeError("bank %s full" % bank)
        assigned[net] = balls[0]


# Configuration flash: dedicated multi-function pins of bank 14.
FLASH = {"FLASH_IO0": "D00_MOSI", "FLASH_IO1": "D01_DIN", "FLASH_IO2": "D02", "FLASH_IO3": "D03",
         "FLASH_CS": "FCS_B", "PUDC_B": "PUDC_B"}
for net, func in FLASH.items():
    assigned[net] = next(b for b, n in io.items() if func in n)

# Clocks on MRCC pins of bank 15.
assign("15", ["CLK_25M", "CLK_EXT"], clock=True)
# 3.3 V control signals (banks 15 and 14). Names starting with "/" are
# hierarchical labels shared with the other sheets.
assign("15", ["RESET_N", "/LED_CLK", "/LED_LE", "/LED_SDI", "/LED_SDO", "/LED_/OE",
              "/IO_A0", "/IO_A1", "/IO_A2", "/IO_A3", "/DIR_A0", "/DIR_A1", "/DIR_A2", "/DIR_A3",
              "/TEARING", "/EN_VCC_PLATFORM", "/EN_VCC_DUT"])
assign("14", ["/TXD", "/RXD", "@PD_SCL", "@PD_SDA"])
SPARE = ["SPARE_%d" % i for i in range(7)]   # to test points TP102..TP108
assign("14", SPARE)
# DUT / platform I/Os on the adjustable VCC_IO_FPGA banks.
assign("35", ["/IO%d_DUT" % i for i in range(16)] + ["PULL_D0", "PULL_D1", "PULL_D2"])
assign("34", ["/IO%d_PLAT" % i for i in range(16)])

ball_net = {b: n for n, b in assigned.items()}

# ---------------------------------------------------------------------------
# FPGA symbol nets


def fpga_net(p):
    name, ball = p["name"], p["number"]
    if ball in ball_net:
        return ball_net[ball]
    if name.startswith("IO_"):
        return None
    if name in ("VCCINT", "VCCBRAM"):
        return "1V0"
    if name == "VCCAUX":
        return "1V8"
    if name in ("VCCO_0", "VCCO_14", "VCCO_15", "VCCO_16", "CFGBVS_0"):
        return "3V3_FPGA"
    if name in ("VCCO_34", "VCCO_35"):
        return "VCC_IO_FPGA"
    if name == "VCCADC_0":
        return "VCCADC"
    # XADC unused (internal reference), temperature diode unused, no
    # bitstream encryption: tied to ground.
    if name in ("GND", "GNDADC_0", "VREFP_0", "VREFN_0", "VP_0", "VN_0", "DXP_0", "DXN_0", "VCCBATT_0"):
        return "GND"
    return {"CCLK_0": "FLASH_CLK", "PROGRAM_B_0": "PROGRAM_B", "INIT_B_0": "INIT_B", "DONE_0": "DONE",
            "M0_0": "MODE_M0", "M1_0": "MODE_M1", "M2_0": "MODE_M2", "TCK_0": "JTAG_TCK",
            "TMS_0": "JTAG_TMS", "TDI_0": "JTAG_TDI", "TDO_0": "JTAG_TDO"}[name]


fpga_nets = {}
for p in sym_fpga.pins:
    fpga_nets[p["number"]] = fpga_net(p)

FPGA_FIELDS = {"LCSC": "C1521726", "MANUFACTURER PN": "XC7A35T-1CSG324I", "MANUFACTURER": "AMD Xilinx",
               "ALTERNATIVE": "XC7A100T-1CSG324C (C1521768), same footprint and decoupling"}
y = 40
for unit, title in [(1, "Banks 14 and 15 (3V3_FPGA)"), (2, "Bank 34 (VCC_IO_FPGA), VCCO_16"),
                    (3, "Bank 35 (VCC_IO_FPGA)"), (4, "Bank 0: configuration and JTAG"), (5, "Power")]:
    g = Grid(sheet, 25, y, 560, "U100 %s" % title)
    g.add("U100", sym_fpga, fpga_nets, unit=unit, value="XC7A35T-1CSG324I",
          footprint="Package_BGA:Xilinx_CSG324", fields=FPGA_FIELDS, label_room=33.02)
    y = g.bottom() + 25


def R(g, value, a, b, ref=None):
    g.add(ref or rref.next(), sym_R, {"1": a, "2": b}, value=value, footprint=R0603,
          fields={"LCSC": RES[value]}, label_room=12.7)


def C(g, kind, net, ref=None):
    fp, lcsc, value = CAPS[kind]
    g.add(ref or cref.next(), sym_C, {"1": net, "2": "GND"}, value=value, footprint=fp,
          fields={"LCSC": lcsc}, label_room=12.7)


# ---------------------------------------------------------------------------
X2 = 600
g = Grid(sheet, X2, 40, 300, "Configuration: Master SPI x4 (M[2:0] = 001), W25Q128JV")
g.add("U105", sym_flash, {"1": "FLASH_CS", "2": "FLASH_IO1", "3": "FLASH_IO2", "4": "GND",
                          "5": "FLASH_IO0", "6": "FLASH_CLK", "7": "FLASH_IO3", "8": "3V3_FPGA"},
      value="W25Q128JVSIQ", footprint="Package_SO:SOIC-8_5.23x5.23mm_P1.27mm",
      fields={"LCSC": "C97521", "MANUFACTURER PN": "W25Q128JVSIQ", "MANUFACTURER": "Winbond"})
base.place(g, "C151", {"1": "GND", "2": "3V3_FPGA"})
R(g, "10k", "3V3_FPGA", "FLASH_CS")
R(g, "10k", "3V3_FPGA", "FLASH_IO2")    # /WP high in x1 mode
R(g, "10k", "3V3_FPGA", "FLASH_IO3")    # /HOLD high in x1 mode
R(g, "4.7k", "3V3_FPGA", "PROGRAM_B")
R(g, "4.7k", "3V3_FPGA", "INIT_B")
R(g, "330", "3V3_FPGA", "DONE")
R(g, "1k", "3V3_FPGA", "MODE_M0")
R(g, "1k", "MODE_M1", "GND")
R(g, "1k", "MODE_M2", "GND")
R(g, "1k", "3V3_FPGA", "PUDC_B")       # I/O pull-ups disabled during configuration
base.place(g, "TP111", {"1": "INIT_B"})

g = Grid(sheet, X2, g.bottom() + 30, 300, "JTAG (Digilent JTAG-HS2/HS3 6-pin header: VDD GND TCK TDO TDI TMS)")
g.add("P100", sym_hdr, {"1": "3V3_FPGA", "2": "GND", "3": "JTAG_TCK", "4": "JTAG_TDO", "5": "JTAG_TDI",
                        "6": "JTAG_TMS"},
      value="JTAG", footprint="Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
      fields={"LCSC": "C492405", "MANUFACTURER PN": "PZ254V-11-06P"})
for ref, net in (("TCK100", "JTAG_TCK"), ("TDI100", "JTAG_TDI"), ("TDO100", "JTAG_TDO"), ("TMS100", "JTAG_TMS")):
    base.place(g, ref, {"1": net})

g = Grid(sheet, X2, g.bottom() + 30, 300, "Clocks and reset")
base.place(g, "Y100", {"1": "3V3_FPGA", "2": "GND", "3": "CLK_25M", "4": "3V3_FPGA"},
           fields={"LCSC": "C2441341"})
base.place(g, "C136", {"1": "3V3_FPGA", "2": "GND"})
base.place(g, "TP101", {"1": "CLK_25M"})
base.place(g, "CN100", {"1": "CLK_EXT", "2": "GND", "3": "GND"})
base.place(g, "S100", {"1": "RESET_N", "2": "GND", "3": "RESET_N", "4": "GND"})
base.place(g, "R100", {"1": "RESET_N", "2": "3V3_FPGA"})
base.place(g, "C137", {"1": "GND", "2": "RESET_N"})
base.place(g, "TP100", {"1": "RESET_N"})

g = Grid(sheet, X2, g.bottom() + 30, 300, "D0-D2 pull resistors, spare I/O test points")
base.place(g, "R110", {"1": "PULL_D0", "2": "/D0_PULL"})
base.place(g, "R111", {"1": "PULL_D1", "2": "/D1_PULL"})
base.place(g, "R112", {"1": "/D2_PULL", "2": "PULL_D2"})
for i, tp in enumerate(("TP102", "TP103", "TP104", "TP105", "TP106", "TP107", "TP108")):
    base.place(g, tp, {"1": SPARE[i]})

# Decoupling, UG483 Table 2-2, sized for the XC7A100T (largest device on the
# CSG324 footprint): VCCINT 330 uF (2 x 100 uF ceramic here) + 6 x 4.7 uF +
# 8 x 0.47 uF, VCCBRAM 100 uF + 2 x 0.47 uF (VCCBRAM shares the 1V0 rail),
# VCCAUX 47 + 2 x 4.7 + 4 x 0.47, VCCO bank 0 47 uF, other banks one 47 uF
# per 4 banks + 2 x 4.7 + 4 x 0.47 per bank.
g = Grid(sheet, X2, g.bottom() + 30, 300, "Decoupling (UG483 Table 2-2, sized for XC7A100T)")
for kind, n in (("100uF", 2), ("4.7uF", 6), ("0.47uF", 10)):
    for _ in range(n):
        C(g, kind, "1V0")
for kind, n in (("47uF", 1), ("4.7uF", 2), ("0.47uF", 4)):
    for _ in range(n):
        C(g, kind, "1V8")
for kind, n in (("47uF", 2), ("4.7uF", 5), ("0.47uF", 10)):   # banks 0, 14, 15 (+16)
    for _ in range(n):
        C(g, kind, "3V3_FPGA")
for kind, n in (("47uF", 1), ("4.7uF", 4), ("0.47uF", 8)):    # banks 34, 35
    for _ in range(n):
        C(g, kind, "VCC_IO_FPGA")
g.add("L100", sym_FB, {"1": "1V8", "2": "VCCADC"}, value="600R@100MHz",
      footprint="Inductor_SMD:L_0603_1608Metric", fields={"LCSC": "C1002"}, label_room=12.7)
C(g, "1uF", "VCCADC")
C(g, "100nF", "VCCADC")
base.place(g, "C153", {"1": "GND", "2": "3V3_FPGA"})
base.place(g, "C154", {"1": "GND", "2": "3V3_FPGA"})

sheet.power_flags(["VCCADC"], X2, 20)
sheet.write(OUT)

with open(PINS_CSV, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["net", "ball", "bank", "pin_name"])
    for net, ball in sorted(assigned.items(), key=lambda x: x[0].lstrip("/@")):
        w.writerow([net.lstrip("/@"), ball, bank_of(io[ball]), io[ball]])
print("wrote", OUT, "-", len(sheet.parts), "parts;", PINS_CSV, "-", len(assigned), "pins")
