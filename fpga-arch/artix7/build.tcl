# Vivado non-project build of the Scaffold FPGA architecture for the Rev 2
# board (Artix-7, CSG324 package).
#
# Usage (from this directory):
#   vivado -mode batch -source build.tcl
#   vivado -mode batch -source build.tcl -tclargs xc7a100tcsg324-1
#
# Outputs, in ./build:
#   scaffold.bit  - SRAM bitstream (load over JTAG)
#   scaffold.bin  - image to program in the configuration SPI flash
#   reports       - utilization and timing summaries

set part xc7a35tcsg324-1
if {$argc > 0} { set part [lindex $argv 0] }

set here [file dirname [file normalize [info script]]]
set common [file normalize "$here/.."]
set out "$here/build"
file mkdir $out

# Sources shared with the Rev 1.x Quartus project. Vendor specific entities
# (fifo512, lpm_down_counter_*, pll) and board specific ones (tlc5952_driver,
# which drives 74HC595 shift registers on Rev 2) are replaced by the ones from
# this directory.
set replaced {fifo512.vhd lpm_down_counter_24.vhd lpm_down_counter_27.vhd
    lpm_down_counter_32.vhd pll.vhd tlc5952_driver.vhd}
set qsf [open "$common/scaffold.qsf"]
while {[gets $qsf line] >= 0} {
    if {[regexp {VHDL_FILE\s+(\S+)} $line -> f] && [lsearch $replaced $f] < 0} {
        read_vhdl "$common/$f"
    }
}
close $qsf
foreach f $replaced { read_vhdl "$here/$f" }
read_xdc "$here/scaffold.xdc"

synth_design -top scaffold -part $part
opt_design
place_design
phys_opt_design
route_design

report_utilization -file "$out/utilization.rpt"
report_timing_summary -file "$out/timing.rpt"
if {[get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]] < 0} {
    puts "ERROR: timing constraints not met, see $out/timing.rpt"
    exit 1
}

write_bitstream -force "$out/scaffold.bit"
write_cfgmem -force -format bin -interface SPIx4 -size 16 \
    -loadbit "up 0x0 $out/scaffold.bit" -file "$out/scaffold.bin"
