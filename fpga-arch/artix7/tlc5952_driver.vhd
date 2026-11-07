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
-- Rev 2 replacement of the TLC5952 driver: drives the 24 LEDs through three
-- daisy-chained 74HC595 shift registers. The entity keeps the name and ports
-- of tlc5952_driver so that leds_module is unchanged.
--
-- Wiring on the Rev 2 board:
--   sin   -> SER of the first 74HC595 (U400)
--   sclk  -> SRCLK of all 74HC595
--   lat   -> RCLK of all 74HC595
--   blank -> /OE of all 74HC595 (high = all LEDs off)
--   /SRCLR of all 74HC595 tied high.
-- Bits are shifted MSB first: leds(23) ends on QH of the last register
-- (U402), leds(0) on QA of the first register (U400).
-- The LEDs are wired between 3V3 and the 74HC595 outputs (through series
-- resistors), so they are lit when the output is low: the bits are inverted
-- before being shifted.
--
-- Brightness: the TLC5952 had a constant-current brightness control. Here
-- control(6 downto 0) (the same value is repeated three times by
-- leds_module) sets a PWM duty cycle of (brightness + 1) / 128 on blank.
--


library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;


entity tlc5952_driver is
generic (
    -- System clock divisor for the shift clock. Minimum is 2.
    -- Shift clock is (system clock / divisor).
    divisor: positive := 2;
    -- System clock divisor for the brightness PWM step. PWM period is
    -- 128 * pwm_divisor system clock cycles (about 10 kHz at 100 MHz).
    pwm_divisor: positive := 78 );
port (
    -- System clock.
    clock: in std_logic;
    -- System reset, active low.
    reset_n: in std_logic;
    -- LEDs requested state. When a bit is 1, the corresponding LED is lit.
    leds: in std_logic_vector(23 downto 0);
    -- Brightness, in bits 6 downto 0. Other bits are ignored.
    control: in std_logic_vector(23 downto 0);
    -- 74HC595 serial data. Registered.
    sin: out std_logic;
    -- 74HC595 shift clock. Registered.
    sclk: out std_logic;
    -- 74HC595 storage register clock. Registered.
    lat: out std_logic;
    -- 74HC595 output enable, active low. Registered.
    blank: out std_logic );
end;


architecture behavior of tlc5952_driver is
    type state_t is (st_idle, st_start, st_sync, st_transmit, st_latch);
    signal state: state_t;
    -- LEDs state currently latched in the shift registers.
    signal current_leds: std_logic_vector(23 downto 0);
    signal shift: std_logic_vector(23 downto 0);
    -- Shift clock divisor counter.
    signal counter: integer range 0 to divisor-1;
    signal tick: std_logic;
    -- Number of remaining bits to be transmitted (minus 1).
    signal bit_counter: integer range 0 to 23;
    -- Brightness PWM.
    signal pwm_prescaler: integer range 0 to pwm_divisor-1;
    signal pwm_phase: unsigned(6 downto 0);
begin
    assert divisor >= 2 report "Invalid divisor value!";

    p_counter: process (clock, reset_n)
    begin
        if reset_n = '0' then
            counter <= divisor-1;
        elsif rising_edge(clock) then
            if counter = 0 then
                counter <= divisor-1;
            else
                counter <= counter-1;
            end if;
        end if;
    end process;
    tick <= '1' when counter = 0 else '0';

    p_fsm: process (clock, reset_n)
    begin
        if reset_n = '0' then
            state <= st_idle;
            -- Forces an update at startup (default request is all off).
            current_leds <= (others => '1');
            shift <= (others => '0');
            bit_counter <= 23;
        elsif rising_edge(clock) then
            case state is
                when st_idle =>
                    bit_counter <= 23;
                    if current_leds /= leds then
                        state <= st_start;
                    end if;
                when st_start =>
                    current_leds <= leds;
                    -- Active-low outputs.
                    shift <= not leds;
                    state <= st_sync;
                when st_sync =>
                    if tick = '1' then
                        state <= st_transmit;
                    end if;
                -- One bit per tick period. sclk rises in the middle of the
                -- period, when sin is stable.
                when st_transmit =>
                    if tick = '1' then
                        shift <= shift(22 downto 0) & '0';
                        if bit_counter = 0 then
                            state <= st_latch;
                        else
                            bit_counter <= bit_counter - 1;
                        end if;
                    end if;
                when st_latch =>
                    if tick = '1' then
                        state <= st_idle;
                    end if;
            end case;
        end if;
    end process;

    p_pwm: process (clock, reset_n)
    begin
        if reset_n = '0' then
            pwm_prescaler <= 0;
            pwm_phase <= (others => '0');
        elsif rising_edge(clock) then
            if pwm_prescaler = pwm_divisor-1 then
                pwm_prescaler <= 0;
                pwm_phase <= pwm_phase + 1;
            else
                pwm_prescaler <= pwm_prescaler + 1;
            end if;
        end if;
    end process;

    p_signals: process (clock, reset_n)
    begin
        if reset_n = '0' then
            sin <= '0';
            sclk <= '0';
            lat <= '0';
            blank <= '1';
        elsif rising_edge(clock) then
            sin <= shift(23);
            if (state = st_transmit) and (counter < (divisor / 2)) then
                sclk <= '1';
            else
                sclk <= '0';
            end if;
            if state = st_latch then
                lat <= '1';
            else
                lat <= '0';
            end if;
            -- LEDs on during (brightness + 1) phases out of 128.
            if pwm_phase <= unsigned(control(6 downto 0)) then
                blank <= '0';
            else
                blank <= '1';
            end if;
        end if;
    end process;
end;
