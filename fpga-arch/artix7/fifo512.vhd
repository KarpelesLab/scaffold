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
-- Vendor-neutral replacement for the Altera scfifo-based fifo512.
--
-- Behaviour matches the scfifo configuration used in Rev 1.x
-- (lpm_showahead = OFF, overflow/underflow checking = ON):
-- - q is updated on the clock edge following a rdreq (1 cycle latency),
-- - wrreq is ignored when full, rdreq is ignored when empty,
-- - empty, full and usedw are registered and reflect the operations
--   performed at the previous clock edge,
-- - when the FIFO is full, usedw wraps to 0 (as scfifo does with a 9-bit
--   usedw for 512 words), full must be used to detect this case.
-- The memory is written to infer a simple dual port block RAM.
--


library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;


entity fifo512 is
port (
    clock: in std_logic;
    aclr: in std_logic;
    data: in std_logic_vector(7 downto 0);
    rdreq: in std_logic;
    sclr: in std_logic;
    wrreq: in std_logic;
    empty: out std_logic;
    full: out std_logic;
    q: out std_logic_vector(7 downto 0);
    usedw: out std_logic_vector(8 downto 0) );
end;


architecture behavior of fifo512 is
    type mem_t is array (0 to 511) of std_logic_vector(7 downto 0);
    signal mem: mem_t;
    signal wr_ptr: unsigned(8 downto 0);
    signal rd_ptr: unsigned(8 downto 0);
    -- Number of stored words, from 0 to 512.
    signal count: unsigned(9 downto 0);
    signal do_write: std_logic;
    signal do_read: std_logic;
    signal q_reg: std_logic_vector(7 downto 0);
begin
    do_write <= wrreq when count /= 512 else '0';
    do_read <= rdreq when count /= 0 else '0';

    -- Block RAM: synchronous write port and registered read port. No reset
    -- on the memory or the read register, so it maps on BRAM primitives.
    p_mem: process (clock)
    begin
        if rising_edge(clock) then
            if do_write = '1' then
                mem(to_integer(wr_ptr)) <= data;
            end if;
            if do_read = '1' then
                q_reg <= mem(to_integer(rd_ptr));
            end if;
        end if;
    end process;

    p_ctrl: process (clock, aclr)
    begin
        if aclr = '1' then
            wr_ptr <= (others => '0');
            rd_ptr <= (others => '0');
            count <= (others => '0');
        elsif rising_edge(clock) then
            if sclr = '1' then
                wr_ptr <= (others => '0');
                rd_ptr <= (others => '0');
                count <= (others => '0');
            else
                if do_write = '1' then
                    wr_ptr <= wr_ptr + 1;
                end if;
                if do_read = '1' then
                    rd_ptr <= rd_ptr + 1;
                end if;
                if (do_write = '1') and (do_read = '0') then
                    count <= count + 1;
                elsif (do_write = '0') and (do_read = '1') then
                    count <= count - 1;
                end if;
            end if;
        end if;
    end process;

    q <= q_reg;
    empty <= '1' when count = 0 else '0';
    full <= '1' when count = 512 else '0';
    usedw <= std_logic_vector(count(8 downto 0));
end;
