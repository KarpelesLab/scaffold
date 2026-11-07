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
-- Vendor-neutral replacement for the Altera lpm_counter based
-- lpm_down_counter_24 (down counter, synchronous load, count enable,
-- asynchronous clear).
--


library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;


entity lpm_down_counter_24 is
port (
    aclr: in std_logic;
    clock: in std_logic;
    cnt_en: in std_logic;
    data: in std_logic_vector(23 downto 0);
    sload: in std_logic;
    q: out std_logic_vector(23 downto 0) );
end;


architecture behavior of lpm_down_counter_24 is
    signal value: unsigned(23 downto 0);
begin
    process (clock, aclr)
    begin
        if aclr = '1' then
            value <= (others => '0');
        elsif rising_edge(clock) then
            -- As with lpm_counter, sload has priority over and does not
            -- depend on cnt_en.
            if sload = '1' then
                value <= unsigned(data);
            elsif cnt_en = '1' then
                value <= value - 1;
            end if;
        end if;
    end process;
    q <= std_logic_vector(value);
end;
