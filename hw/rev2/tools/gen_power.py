#!/usr/bin/env python3
"""Generates hw/kicad/Power.kicad_sch for Scaffold Rev 2.

USB-C input with USB-PD sink (12 V), external 7-20 V input, input mux,
switching pre-regulator and FPGA rails, low-noise LDOs for the DUT and
platform supplies (carried over from Rev 1.1), current measurement amplifier
(carried over). See hw/rev2/DESIGN.md.

Run from the repository root:  python3 hw/rev2/tools/gen_power.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kisch  # noqa: E402
from kisch import LibSymbol, Grid  # noqa: E402

OUT = "hw/kicad/Power.kicad_sch"
INSTANCE = "/0930e4eb-3812-4ad2-a87e-ee25991a40db/8c77f1ad-0c16-4bfe-b679-4023649aaec1"
SHEET_UUID = "dbb7c6be-82cd-4939-8266-3a98d77bc30e"

POWER_NETS = {"VBUS_C", "VEXT", "VIN_MUX", "VIN", "VPRE", "Vsupply", "1V0", "1V8",
              "3V3_FPGA", "VCC_IO_FPGA", "3V3_OPA", "VCC_PLATFORM", "VCC_DUT",
              "VCC_PLATFORM_PERMANENT", "VCC_DUT_PERMANENT", "VBUS_SENSE"}

# Footprints
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"

# LCSC codes of JLC basic passives (checked 2026-11-08, see jlc_check.py)
RES = {"1k": "C21190", "2.2k": "C4190", "2.4k": "C22940", "4.7k": "C23162", "10k": "C25804",
       "12k": "C22790", "15k": "C22809", "22k": "C31850", "24k": "C23352", "30k": "C22984",
       "47k": "C25819", "51k": "C23196", "100k": "C25803", "200k": "C25811"}
CAP = {"100nF/50V": (C0603, "C14663"), "1uF/50V": (C0603, "C15849"), "10nF/50V": (C0603, "C57112"),
       "10uF/50V": (C1206, "C13585"), "22uF/25V": (C0805, "C45783"), "10uF/25V": (C0805, "C15850")}

sym_R = LibSymbol.from_kicad_lib("Device", "R")
sym_C = LibSymbol.from_kicad_lib("Device", "C")
sym_L = LibSymbol.from_kicad_lib("Device", "L")
sym_LED = LibSymbol.from_kicad_lib("Device", "LED")
sym_Z = LibSymbol.from_kicad_lib("Device", "D_Zener")
sym_buck = LibSymbol.from_kicad_lib("Regulator_Switching", "TPS62933P")
sym_usbc = LibSymbol.from_kicad_lib("Connector", "USB_C_Receptacle_USB2.0_16P")

# CH224A: same pinout as the CH224K symbol (ESSOP-10), pin names differ.
sym_ch224 = LibSymbol.from_kicad_lib("Interface_USB", "CH224K", rename="CH224A")
sym_ch224.block = (sym_ch224.block.replace('(name "VDD"', '(name "VHV"')
                   .replace('(name "CFG2"', '(name "CFG2/SCL"')
                   .replace('(name "CFG3"', '(name "CFG3/SDA"'))
sym_ch224.lib_id = "Scaffold_Rev2:CH224A"

sym_mux = kisch.box_symbol(
    "Scaffold_Rev2:TPS2121",
    left=[("7", "IN1", "power_in"), ("2", "IN2", "power_in"), None, ("6", "PR1", "input"),
          ("3", "CP2", "input"), ("5", "~{OV1}", "input"), ("4", "~{OV2}", "input")],
    right=[("1", "OUT", "power_out"), ("8", "OUT", "passive"), None, ("9", "ST", "passive"),  # open drain, tied to GND per datasheet
           ("10", "ILM", "passive"), ("11", "SS", "passive")],
    bottom=[None, None, ("12", "GND", "power_in")],
    footprint="Package_DFN_QFN:Texas_VQFN-HR-12_2x2.5mm_P0.5mm")

sheet = kisch.Sheet("Power", INSTANCE, power_nets=POWER_NETS, sheet_uuid=SHEET_UUID)
base = kisch.Baseline("Power.kicad_sch")


def R(g, ref, value, a, b, **kw):
    g.add(ref, sym_R, {"1": a, "2": b}, value=value, footprint=R0603,
          fields={"LCSC": RES[value]}, label_room=12.7, **kw)


def C(g, ref, kind, a, b="GND"):
    fp, lcsc = CAP[kind]
    g.add(ref, sym_C, {"1": a, "2": b}, value=kind.replace("/", " "), footprint=fp,
          fields={"LCSC": lcsc}, label_room=12.7)


# --- USB-C input and USB-PD ------------------------------------------------
g = Grid(sheet, 25, 40, 270, "USB-C input, USB-PD sink (requests 12 V). CH224A DP/DM must stay unconnected.")
usb_nets = {"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "SH": "GND",
            "A4": "VBUS_C", "A9": "VBUS_C", "B4": "VBUS_C", "B9": "VBUS_C",
            "A5": "CC1", "B5": "CC2", "A6": "/USBDP", "B6": "/USBDP",
            "A7": "/USBDM", "B7": "/USBDM", "A8": None, "B8": None}
g.add("J200", sym_usbc, usb_nets, value="USB4105-GF-A",
      footprint="Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
      fields={"LCSC": "C3020560", "MANUFACTURER PN": "USB4105-GF-A", "MANUFACTURER": "GCT"})
base.place(g, "D203", {"A": "GND", "C": "/USBDM"})
base.place(g, "D204", {"A": "GND", "C": "/USBDP"})
g.add("D207", sym_Z, {"1": "VBUS_C", "2": "GND"}, value="SMAJ20A", footprint="Diode_SMD:D_SMA",
      fields={"LCSC": "C115250"}, label_room=12.7)
g.add("U209", sym_ch224, {"1": "VBUS_C", "8": "VBUS_C", "2": "@PD_SCL", "3": "@PD_SDA",
                          "4": None, "5": None, "6": "CC2", "7": "CC1", "9": "PD_CFG1",
                          "10": "PD_PG_N", "11": "GND"},
      value="CH224A", footprint="Package_SO:SSOP-10-1EP_3.9x4.9mm_P1mm_EP2.1x3.3mm",
      fields={"LCSC": "C42459160"})
C(g, "C221", "1uF/50V", "VBUS_C")
R(g, "R218", "24k", "PD_CFG1", "GND")
R(g, "R219", "2.2k", "VBUS_C", "PD_LED_A")
g.add("D208", sym_LED, {"2": "PD_LED_A", "1": "PD_PG_N"}, value="PD 12V OK (red)",
      footprint="LED_SMD:LED_0603_1608Metric", fields={"LCSC": "C2286"}, label_room=12.7)
R(g, "R220", "10k", "@PD_SCL", "3V3_FPGA")
R(g, "R221", "10k", "@PD_SDA", "3V3_FPGA")
# FT232RL USB presence detection, clamped for 5-20 V VBUS (R603/R605 on the
# RS232 sheet divide VBUS_SENSE down to RESET#).
R(g, "R222", "4.7k", "VBUS_C", "VBUS_SENSE")
g.add("D209", sym_Z, {"1": "VBUS_SENSE", "2": "GND"}, value="BZT52C4V7",
      footprint="Diode_SMD:D_SOD-123", fields={"LCSC": "C2116"}, label_room=12.7)

# --- External input and input mux ------------------------------------------
g = Grid(sheet, 25, g.bottom() + 30, 270,
         "External input 7-20 V (priority over USB-C above 6.5 V), input mux, power switch")
base.place(g, "CN202", {"1": "VEXT", "2": "GND"})
g.add("D210", sym_Z, {"1": "VEXT", "2": "GND"}, value="SMAJ20A", footprint="Diode_SMD:D_SMA",
      fields={"LCSC": "C115250"}, label_room=12.7)
C(g, "C222", "1uF/50V", "VEXT")
g.add("U210", sym_mux, {"7": "VEXT", "2": "VBUS_C", "6": "MUX_PR1", "3": "GND", "5": "MUX_OV1",
                        "4": "MUX_OV2", "1": "VIN_MUX", "8": "VIN_MUX", "9": "GND", "10": "MUX_ILM",
                        "11": "MUX_SS", "12": "GND"},
      value="TPS2121RUXR", footprint="Package_DFN_QFN:Texas_VQFN-HR-12_2x2.5mm_P0.5mm",
      fields={"LCSC": "C485916"})
R(g, "R223", "51k", "VEXT", "MUX_PR1")      # switchover to VEXT above 6.5 V
R(g, "R224", "10k", "MUX_PR1", "GND")
R(g, "R225", "200k", "VEXT", "MUX_OV1")     # VEXT overvoltage cut-off 22 V
R(g, "R226", "10k", "MUX_OV1", "GND")
R(g, "R227", "200k", "VBUS_C", "MUX_OV2")   # VBUS overvoltage cut-off 22 V
R(g, "R228", "10k", "MUX_OV2", "GND")
R(g, "R229", "22k", "MUX_ILM", "GND")       # current limit ~4.5 A
C(g, "C223", "10nF/50V", "MUX_SS")
C(g, "C224", "10uF/50V", "VIN_MUX")
base.place(g, "S200", {"1": None, "2": "VIN", "3": "VIN_MUX"})
base.place(g, "TP202", {"1": "VIN"})

# --- Switching regulators ----------------------------------------------------
# All TPS62933P at 500 kHz (RT floating). EN has an internal pull-up: the
# previous rail's open-drain PG holds it low, giving VCCINT -> VCCAUX -> VCCO.
BUCKS = [
    # ref, out net, L ref, L value, L footprint, L LCSC, Rtop, Rbot, EN net, PG net, caps
    ("U211", "VPRE", "L201", "10uH", "Scaffold_Rev2:L_CJiang_FXL1040", "C475915", "30k", "4.7k", None, None, 3),
    ("U213", "1V0", "L202", "3.3uH", "Inductor_SMD:L_Changjiang_FNR6045S", "C168063", "2.4k", "10k", None, "PG_1V0", 3),
    ("U214", "1V8", "L203", "4.7uH", "Inductor_SMD:L_Changjiang_FNR6045S", "C168067", "15k", "12k", "PG_1V0", "PG_1V8", 2),
    ("U215", "3V3_FPGA", "L204", "10uH", "Inductor_SMD:L_Changjiang_FNR6045S", "C168076", "47k", "15k", "PG_1V8", "PG_3V3", 2),
]
rnum, cnum = 230, 225
for ref, out, lref, lval, lfp, llcsc, rtop, rbot, en, pg, ncap in BUCKS:
    g = Grid(sheet, 25, g.bottom() + 30, 270, "%s buck: %s" % (out, ref))
    sw, bst, fb = "SW_" + out, "BST_" + out, "FB_" + out
    g.add(ref, sym_buck, {"1": None, "2": en, "3": "VIN", "4": "GND", "5": sw, "6": bst, "7": pg, "8": fb},
          value="TPS62933PDRLR", footprint="Package_TO_SOT_SMD:SOT-583-8", fields={"LCSC": "C5219254"})
    g.add(lref, sym_L, {"1": sw, "2": out}, value=lval, footprint=lfp, fields={"LCSC": llcsc}, label_room=12.7)
    C(g, "C%d" % cnum, "10uF/50V", "VIN"); cnum += 1
    C(g, "C%d" % cnum, "100nF/50V", "VIN"); cnum += 1
    C(g, "C%d" % cnum, "100nF/50V", bst, sw); cnum += 1
    for _ in range(ncap):
        C(g, "C%d" % cnum, "22uF/25V", out); cnum += 1
    R(g, "R%d" % rnum, rtop, out, fb); rnum += 1
    R(g, "R%d" % rnum, rbot, fb, "GND"); rnum += 1

# Rail test points (refs reused from Rev 1.1)
g = Grid(sheet, 25, g.bottom() + 30, 270, "Rail test points")
base.place(g, "TP208", {"1": "VPRE"})
base.place(g, "TP209", {"1": "1V0"})
base.place(g, "TP210", {"1": "1V8"})
base.place(g, "TP211", {"1": "3V3_FPGA"})

# --- Linear regulators from VPRE ---------------------------------------------
X2 = 320
g = Grid(sheet, X2, 40, 250, "Vsupply 5.0 V (FT232RL, level shifters, 5 V pulse outputs)")
sym_ldo = base.symbol("U200")
props_ldo = {k: v for k, v in base.parts["U200"]["props"].items() if k not in base.SKIP_PROPS}
g.add("U212", sym_ldo, {"1": "VPRE", "2": "VPRE", "3": "GND", "4": "Vsupply", "5": "VSUP_ADJ", "6": "GND"},
      value="TL1963A", footprint=base.parts["U200"]["props"]["Footprint"], fields=dict(props_ldo, LCSC="C86720"))
R(g, "R%d" % rnum, "47k", "Vsupply", "VSUP_ADJ"); rnum += 1
R(g, "R%d" % rnum, "15k", "VSUP_ADJ", "GND"); rnum += 1
C(g, "C%d" % cnum, "10uF/25V", "VPRE"); cnum += 1
C(g, "C%d" % cnum, "10uF/25V", "Vsupply"); cnum += 1

g = Grid(sheet, X2, g.bottom() + 30, 250,
         "VCC_IO_FPGA 1.21-3.37 V (banks 34/35), enabled after 3V3_FPGA is good")
base.place(g, "U205", {"1": "PG_3V3", "2": "VPRE", "3": "GND", "4": "VCC_IO_FPGA", "5": "VCCIO_ADJ", "6": "GND"},
           fields={"LCSC": "C86720"})
R(g, "R%d" % rnum, "100k", "Vsupply", "PG_3V3"); rnum += 1
base.place(g, "R216", {"1": "VCC_IO_FPGA", "2": "VCCIO_ADJ", "3": "VCCIO_ADJ"})
base.place(g, "R217", {"1": "GND", "2": "VCCIO_ADJ"})
base.place(g, "C217", {"1": "GND", "2": "VPRE"})
base.place(g, "C218", {"1": "GND", "2": "VCC_IO_FPGA"})
base.place(g, "THP203", {"1": "VCC_IO_FPGA"})

# Platform and DUT supplies: Rev 1.1 circuit unchanged, input now VPRE.
for title, ldo, pot, rb, cin, cout, cn_ext, f_ext, cn_sel, cperm, q_p, q_n1, q_n2, d1, d2, r_g, r_a, r_b, r_en, \
        tp_ldo, tp_out, tp_en, thp, en, ldo_out, adj, ext, perm, out in [
        ("Platform supply 1.21 V-5.2 V, 1.5 A", "U200", "R200", "R202", "C200", "C201", "CN200", "F202", "CN201",
         "C202", "Q200", "Q201", "Q202", "D200", "D201", "R201", "R203", "R204", "R205", "TP200", "TP201", "TP203",
         "THP204", "/EN_VCC_PLATFORM", "PLAT_LDO_OUT", "PLAT_ADJ", "PLAT_EXT", "VCC_PLATFORM_PERMANENT", "VCC_PLATFORM"),
        ("DUT supply 1.21 V-5.2 V, 1.5 A", "U202", "R207", "R211", "C208", "C209", "CN204", "F203", "CN206",
         "C210", "Q203", "Q204", "Q205", "D205", "D206", "R209", "R212", "R213", "R215", "TP205", "TP206", "TP207",
         "THP205", "/EN_VCC_DUT", "DUT_LDO_OUT", "DUT_ADJ", "DUT_EXT", "VCC_DUT_PERMANENT", "VCC_DUT")]:
    g = Grid(sheet, X2, g.bottom() + 30, 250, title)
    gate, gate_drv, src = out + "_GATE", out + "_GATE_DRV", out + "_DISCH_GATE"
    base.place(g, ldo, {"1": "VPRE", "2": "VPRE", "3": "GND", "4": ldo_out, "5": adj, "6": "GND"},
               fields={"LCSC": "C86720"})
    base.place(g, pot, {"1": ldo_out, "2": adj, "3": adj})
    base.place(g, rb, {"1": "GND", "2": adj})
    base.place(g, cin, {"1": "GND", "2": "VPRE"})
    base.place(g, cout, {"1": "GND", "2": ldo_out})
    base.place(g, cn_ext, {"1": ext + "_IN", "2": "GND"})
    base.place(g, f_ext, {"1": ext + "_IN", "2": ext})
    base.place(g, cn_sel, {"1": ext, "2": perm, "3": ldo_out})
    base.place(g, cperm, {"1": "GND", "2": perm})
    # Rev 1.1 switch: PMOS q_p (gate pulled up by r_g, pulled down by q_n2),
    # NMOS q_n1 discharges the output when off.
    base.place(g, q_p, {"1": gate, "2": perm, "3": out})
    base.place(g, q_n1, {"1": out, "2": out, "5": out, "6": out, "3": src, "4": "GND"})
    base.place(g, q_n2, {"1": gate_drv, "2": gate_drv, "5": gate_drv, "6": gate_drv, "3": en, "4": "GND"})
    base.place(g, d1, {"1": gate_drv, "2": gate})
    base.place(g, d2, {"1": src, "2": gate_drv})
    base.place(g, r_g, {"1": gate_drv, "2": perm})
    base.place(g, r_a, {"1": gate_drv, "2": gate})
    base.place(g, r_b, {"1": gate_drv, "2": src})
    base.place(g, r_en, {"1": "GND", "2": en})
    base.place(g, tp_ldo, {"1": ldo_out})
    base.place(g, tp_out, {"1": out})
    base.place(g, tp_en, {"1": en})
    base.place(g, thp, {"1": ldo_out})

# Current measurement: Rev 1.1 circuit unchanged.
g = Grid(sheet, X2, g.bottom() + 30, 250, "Current measurement (gain 11, 50 ohm output)")
base.place(g, "U201", {"1": "Vsupply", "2": "GND", "3": "Vsupply", "4": None, "5": "3V3_OPA"})
base.place(g, "C206", {"1": "GND", "2": "Vsupply"})
base.place(g, "C207", {"1": "GND", "2": "3V3_OPA"})
base.place(g, "C204", {"1": "3V3_OPA", "2": "GND"})
base.place(g, "C205", {"1": "3V3_OPA", "2": "GND"})
base.place(g, "U203", {"1": "OPA_OUT", "2": "GND", "3": "/DUT_GND", "4": "OPA_INN", "5": "3V3_OPA", "6": "3V3_OPA"})
base.place(g, "R206", {"1": "OPA_OUT", "2": "SHUNT_OUT"})
base.place(g, "R208", {"1": "GND", "2": "OPA_INN"})
base.place(g, "R214", {"1": "OPA_INN", "2": "OPA_OUT"})
base.place(g, "R210", {"1": "/DUT_GND", "2": "GND", "3": "GND"})
base.place(g, "CN205", {"1": "SHUNT_OUT", "2": "GND", "3": "GND"})
base.place(g, "CN207", {"1": "/DUT_GND", "2": "GND"})
base.place(g, "THP200", {"1": "SHUNT_OUT"})
base.place(g, "THP201", {"1": "/DUT_GND"})
base.place(g, "TP204", {"1": "3V3_OPA"})
for thp in ("THP202", "THP206", "THP207", "THP208", "THP209", "THP210"):
    base.place(g, thp, {"1": "GND"})
for logo in ("Logo200", "Logo201", "Logo202", "Logo203"):
    base.place(g, logo, {})

# ERC: rails driven through inductors, switches or connectors.
sheet.power_flags(["VBUS_C", "VEXT", "VIN", "VPRE", "1V0", "1V8", "3V3_FPGA", "3V3_OPA", "VCC_IO_FPGA", "GND"], 25, 20)

sheet.write(OUT)
print("wrote", OUT, "-", len(sheet.parts), "parts")
