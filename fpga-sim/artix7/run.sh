#!/bin/sh
# Simulates the vendor-neutral modules of the Artix-7 (Rev 2) build with nvc.
set -e
cd "$(dirname "$0")"
A=../../fpga-arch/artix7
nvc -a $A/fifo512.vhd $A/lpm_down_counter_24.vhd $A/lpm_down_counter_27.vhd \
    $A/lpm_down_counter_32.vhd $A/tlc5952_driver.vhd tb_portable.vhd tb_leds.vhd
for tb in tb_portable tb_leds; do
    nvc -e $tb -r 2>&1 | grep -v "metavalue detected\|numeric_std-body\|fifo512.vhd" || true
done
