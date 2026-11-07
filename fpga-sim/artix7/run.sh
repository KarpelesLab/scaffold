#!/bin/sh
# Simulates the vendor-neutral modules of the Artix-7 build with nvc.
set -e
cd "$(dirname "$0")"
A=../../fpga-arch/artix7
nvc -a $A/fifo512.vhd $A/lpm_down_counter_24.vhd $A/lpm_down_counter_27.vhd \
    $A/lpm_down_counter_32.vhd tb_portable.vhd
nvc -e tb_portable -r
