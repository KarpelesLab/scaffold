-- This file is part of Scaffold
--
-- Scaffold is free software: you can redistribute it and/or modify
-- it under the terms of the GNU Lesser General Public License as published by
-- the Free Software Foundation, either version 3 of the License, or
-- (at your option) any later version.
--
-- This program is distributed in the hope that it will be useful,
-- but WITHOUT ANY WARRANTY; without even the implied warranty of
-- MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
-- GNU Lesser General Public License for more details.
--
-- You should have received a copy of the GNU Lesser General Public License
-- along with this program.  If not, see <https://www.gnu.org/licenses/>.
--
--
-- Copyright 2026 Scaffold contributors


--
-- Artix-7 replacement for the Altera altpll based pll entity.
-- Generates the 100 MHz system clock from the 25 MHz board oscillator using
-- an MMCM: VCO = 25 MHz * 40 = 1000 MHz (valid for all speed grades),
-- c0 = VCO / 10 = 100 MHz.
--


library ieee;
use ieee.std_logic_1164.all;
library unisim;
use unisim.vcomponents.all;


entity pll is
port (
    areset: in std_logic;
    inclk0: in std_logic;
    c0: out std_logic;
    locked: out std_logic );
end;


architecture behavior of pll is
    signal clkfb: std_logic;
    signal clkout0: std_logic;
begin
    e_mmcm: MMCME2_BASE
    generic map (
        BANDWIDTH => "OPTIMIZED",
        CLKIN1_PERIOD => 40.0,
        DIVCLK_DIVIDE => 1,
        CLKFBOUT_MULT_F => 40.0,
        CLKFBOUT_PHASE => 0.0,
        CLKOUT0_DIVIDE_F => 10.0,
        CLKOUT0_DUTY_CYCLE => 0.5,
        CLKOUT0_PHASE => 0.0,
        STARTUP_WAIT => FALSE )
    port map (
        CLKIN1 => inclk0,
        CLKFBIN => clkfb,
        CLKFBOUT => clkfb,
        CLKFBOUTB => open,
        CLKOUT0 => clkout0,
        CLKOUT0B => open,
        CLKOUT1 => open,
        CLKOUT1B => open,
        CLKOUT2 => open,
        CLKOUT2B => open,
        CLKOUT3 => open,
        CLKOUT3B => open,
        CLKOUT4 => open,
        CLKOUT5 => open,
        CLKOUT6 => open,
        LOCKED => locked,
        PWRDWN => '0',
        RST => areset );

    e_bufg: BUFG port map (I => clkout0, O => c0);
end;
