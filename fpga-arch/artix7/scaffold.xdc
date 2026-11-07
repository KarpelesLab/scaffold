# Constraints for the Scaffold Rev 2 board (Artix-7 XC7A35T/XC7A100T, CSG324).
#
# PACKAGE_PIN assignments are filled in from the Rev 2 PCB once the FPGA
# fanout is fixed (see hw/kicad). Bank voltages:
#   - banks 14/15: 3V3_FPGA (UART, LEDs driver, configuration, misc)
#   - banks 34/35: VCC_IO_FPGA, adjustable 1.2 V to 3.3 V (DUT/platform IOs)

# 25 MHz board oscillator.
create_clock -name clock -period 40.000 [get_ports clock]

# Configuration: 3.3 V bank 0, quad SPI flash, compressed bitstream.
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4 [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 33 [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]

# Asynchronous inputs and outputs: no timing relationship with the system
# clock is required (the architecture synchronizes inputs internally).
set_false_path -from [get_ports {reset_n rx teardown io[*]}]
set_false_path -to [get_ports {tx leds_* io[*] io_dir[*] pull_d* power_*}]

# I/O standards. VCC_IO_FPGA is adjustable: LVCMOS33 is declared for the
# DUT/platform banks, the actual levels follow the bank supply.
set_property IOSTANDARD LVCMOS33 [get_ports *]
set_property PULLUP TRUE [get_ports reset_n]

# --- Pin assignments (TODO: from Rev 2 PCB) ---
# set_property PACKAGE_PIN <pin> [get_ports clock]
