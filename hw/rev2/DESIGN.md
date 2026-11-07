# Scaffold Rev 2 — design specification

Status: **draft, in progress**. Nothing here has been built or tested yet.

Rev 2 keeps the Rev 1.1 board's function, form factor (195 x 150 mm), connectors
and register map, and changes three things:

1. Micro-USB is replaced by a USB-C receptacle.
2. The power tree is redesigned around USB Power Delivery (12 V request) with a
   wide-range external input, so the DUT and platform supplies can reach 5 V at
   1.5 A each.
3. The Intel Cyclone IV EP4CE22 (TQFP-144) is replaced by an AMD/Xilinx
   Artix-7 in the CSG324 package (XC7A35T, or XC7A100T on the same footprint).

The design moves from Altium to KiCad (`hw/kicad/`). The Altium files and the
Rev 1.1 fabrication outputs are kept unchanged for reference.

All part numbers are LCSC/JLCPCB codes, checked against JLCPCB's parts API on
2026-11-08. Stock changes daily: re-check before ordering (`hw/rev2/jlc_check.py`).

## 1. USB-C and power input

```
USB-C (J200) --VBUS--+-- CH224A (PD sink, requests 12 V) --> PG, I2C to FPGA
                     |
                     +--> TPS2121 IN2 ---+
CN202 terminal block (7-20 V) --> IN1 ---+--> VIN (5..20 V) --> S200 power switch
```

| Ref | Function | Part | LCSC | Notes |
|---|---|---|---|---|
| J200 | USB-C receptacle | GCT USB4105-GF-A | C3020560 | USB 2.0, 5 A, THT shell pegs for mechanical strength |
| U209 | USB-PD sink controller | WCH CH224A | C42459160 | ESSOP-10. 24 kΩ on CFG1 = 12 V request. Single-resistor mode also enables I²C (addr 0x22/0x23) |
| U210 | Input power mux | TI TPS2121RUXR | C485916 | 2.8–22 V, 4.5 A, priority to the external input |

Rules:

- **CH224A DP/DM pins are left unconnected.** They perform BC1.2/QC
  handshakes, which would corrupt the FT232RL USB data on D+/D-. PD is
  negotiated on CC only.
- VBUS and VHV are tied together (datasheet), 1 µF/50 V on VHV.
- CH224A CFG2/SCL and CFG3/SDA go to FPGA bank 15 (3.3 V) with 4.7 kΩ pull-ups
  to 3V3. The gateware can later read the PD contract (register 0x09 status,
  0x50 maximum current in 50 mA units) and request another voltage (0x0A).
  CH224A PG (open drain, active low) goes to the FPGA and to a "PD OK" LED.
- D+/D- go from J200 (A6/B6, A7/B7 paired) to the FT232RL through the existing
  ESD diodes, 90 Ω differential.
- With a plain 5 V source (no PD), the board still runs but the VPRE buck goes
  into dropout: DUT/platform supplies are then limited to about 4.2 V, as on
  Rev 1.1.

## 2. Power tree

```
VIN (5-20 V)
 |-- U211 TPS62933P  -> VPRE 6.0 V / 3 A ---+-- U200 TL1963A -> VCC_PLATFORM 1.2-5.0 V / 1.5 A
 |                                          +-- U202 TL1963A -> VCC_DUT      1.2-5.0 V / 1.5 A
 |                                          +-- U205 TL1963A -> VCC_IO_FPGA  1.2-3.3 V
 |                                          +-- U212 TL1963A -> Vsupply      5.0 V (FT232, level shifters, LED driver)
 |-- U213 TPS62933P  -> 1V0   (VCCINT, VCCBRAM) -- PG -+
 |-- U214 TPS62933P  -> 1V8   (VCCAUX, VCCADC)  <- EN -+ -- PG -+
 |-- U215 TPS62933P  -> 3V3_FPGA (VCCO 0/14/15, flash, osc) <- EN +
```

| Ref | Function | Part | LCSC |
|---|---|---|---|
| U211, U213–U215 | 3 A synchronous buck, 3.8–30 V in, with PG | TI TPS62933PDRLR | C5219254 |
| U200, U202, U205, U212 | 1.5 A low-noise adjustable LDO | TI TL1963ADCQR (unchanged from Rev 1.1) | C86720 |

- The DUT and platform supplies stay on low-noise LDOs. Switching regulators
  are never in the measured path, which matters for side-channel measurements
  through the shunt amplifier.
- VPRE = 6.0 V leaves 0.66 V headroom over the TL1963A 340 mV dropout at 1.5 A
  for a 5.0 V output. Worst-case LDO dissipation (1.2 V out, 1.5 A) is 7.2 W:
  more than an SOT-223 can sink. The PTC fuses (F202, F203) are raised from
  0.5 A to 1.5 A hold, and the potentiometer ranges keep the existing limits.
  **Open point:** add a thermal pad array or limit to 1 A at low output
  voltages; to be decided at layout.
- Artix-7 sequencing per DS181: VCCINT → VCCAUX → VCCO. The 1V0 buck starts
  first; its PG (pulled up to Vsupply 5 V, within the 5.5 V EN/PG limit)
  enables 1V8, whose PG enables 3V3_FPGA. VCC_IO_FPGA's TL1963A enable is
  driven by the 3V3 PG.
- TPS62933P switching frequency: 500 kHz (RT floating) on VPRE, 1.2 MHz on the
  FPGA rails (smaller inductors). Inductors and capacitors from the JLC basic
  library where possible; values set at schematic capture from the datasheet
  design equations.
- Power budget at 12 V / 3 A (36 W): DUT 7.5 W + platform 7.5 W + VCC_IO 2 W +
  FPGA (35T, worst case) ~2 W + logic 1 W ≈ 20 W input with conversion losses.

## 3. FPGA

| Ref | Function | Part | LCSC |
|---|---|---|---|
| U100 | FPGA | XC7A35T-1CSG324I (default) / XC7A100T-1CSG324C (same footprint) | C1521726 / C1521768 |
| U105 | Configuration flash, 128 Mbit quad SPI | Winbond W25Q128JVSIQ (JLC basic part) | C97521 |
| P100 | JTAG | 2x7 2.0 mm Xilinx header, or 6-pin 2.54 mm (Digilent HS2 pinout) | — |
| Y100 | 25 MHz oscillator | unchanged | — |

- Configuration mode: Master SPI x4 (M[2:0] = 001), CFGBVS = VCCO (bank 0 at 3.3 V).
- The 25 MHz oscillator goes to an MRCC pin in bank 14 or 15. The MMCM
  generates the 100 MHz system clock (VCO 1000 MHz).
- Banks 14 and 15 are on 3V3_FPGA (UART, LED driver, PD controller, flash,
  power enables). Banks 34 and 35 (HR banks) are on the adjustable
  VCC_IO_FPGA and carry the DUT/platform I/Os (A0–A3, D0–D15, P0–P15).
- The design needs about 60 pins out of 210, so only the two outer ball rows
  need breaking out. Unused balls stay unconnected.
- Programming: JTAG through Vivado, or `openFPGALoader`, which also programs
  the W25Q128 flash. The Vivado flash programmer does not list every
  Winbond part, so check before relying on it.

Gateware: `fpga-arch/artix7/` (Vivado build script `build.tcl`, constraints
`scaffold.xdc`). The vendor-specific Rev 1.x modules are replaced by
vendor-neutral ones; the Rev 1.x Quartus project is unchanged.

## 4. Other changes forced by availability

- **LED driver** (decided): the TLC5952DAP (U400) is out of stock at JLCPCB
  (0–2 pcs). It is replaced by 3 x 74HC595D (Nexperia 74HC595D,118, LCSC
  C5947, JLC basic part) U400–U402, powered from 3V3_FPGA, so the FPGA drives
  them directly. Each output drives a LED through a series resistor: the
  2 mA Kingbright LEDs get about 680 Ω, and values are set per LED colour at
  schematic capture. Wiring: FPGA `leds_sin` → SER of U400; QH' of U400 → SER of
  U401, and so on; `leds_sclk` → SRCLK, `leds_lat` → RCLK, `leds_blank` → /OE
  of all three; /SRCLR tied to 3V3. Bit `leds(23)` lands on QH of U402 and
  `leds(0)` on QA of U400.
  Gateware: `fpga-arch/artix7/tlc5952_driver.vhd` keeps the entity name and
  ports, so `leds_module` is unchanged. Brightness becomes a ~10 kHz PWM on
  /OE with duty (brightness + 1)/128. Tested in `fpga-sim/artix7/tb_leds.vhd`.
- **EPCS16** (Intel-only configuration device) → W25Q128JVSIQ, see above.
- **ADA4895-1ARJZ** (current measurement amplifier) is in low stock (33 pcs,
  ~$10). Keep, re-check before ordering.

## 5. PCB

- Stackup (decided): **6 layers**, JLC 1.6 mm, via-in-pad filling included.
  Layers: L1 signal, L2 GND, L3 signal, L4 power, L5 GND, L6 signal. The
  CSG324 is a 0.8 mm-pitch BGA; 6 layers keep two solid ground planes,
  including the one under the analog measurement path.
- BGA fanout: 0.2 mm drill / 0.4 mm via, 0.1 mm tracks under the BGA
  (JLC multilayer minimum: 0.09 mm track/space, 0.15 mm drill).
- Board outline, mounting holes, connector, LED and SMA positions unchanged.

## 6. JLCPCB outputs

Generated by `hw/rev2/make_jlc.sh` from the KiCad project (to be written once
the KiCad project exists):

- `gerbers/` and Excellon drill files, zipped (`scaffold-rev2-gerbers.zip`)
- `bom-jlc.csv`: Comment, Designator, Footprint, LCSC
- `cpl-jlc.csv`: Designator, Mid X, Mid Y, Layer, Rotation (with JLC rotation
  corrections)
- DRC report against the JLC 6-layer rule set

Every footprint carries an `LCSC` field; parts without one (THT test pins,
headers that you populate by hand) are marked `DNP_JLC` and excluded from the
assembly BOM.
