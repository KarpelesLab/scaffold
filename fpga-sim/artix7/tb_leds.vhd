-- Self-checking testbench for the Rev 2 74HC595 LED driver. Models three
-- daisy-chained 74HC595 and checks the latched outputs and the PWM duty.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_leds is
end;

architecture sim of tb_leds is
    signal clock: std_logic := '0';
    signal reset_n: std_logic := '0';
    signal leds, control: std_logic_vector(23 downto 0) := (others => '0');
    signal sin, sclk, lat, blank: std_logic;
    -- 74HC595 chain model: sr(0) is QA of U400, sr(23) is QH of U402.
    -- Outputs are active low (LED lit when the output is '0'), lit is the
    -- resulting LED state.
    signal sr, outputs, lit: std_logic_vector(23 downto 0) := (others => 'U');
    signal done: boolean := false;
begin
    clock <= not clock after 5 ns when not done;

    dut: entity work.tlc5952_driver
    generic map (divisor => 16, pwm_divisor => 4)
    port map (clock => clock, reset_n => reset_n, leds => leds,
        control => control, sin => sin, sclk => sclk, lat => lat,
        blank => blank);

    sr <= sr(22 downto 0) & sin when rising_edge(sclk);
    outputs <= sr when rising_edge(lat);
    lit <= not outputs;

    process
        variable on_count: natural;
        procedure wait_update is begin
            wait until falling_edge(lat); wait for 100 ns;
        end;
        procedure check_pwm(b: natural) is begin
            control <= std_logic_vector(to_unsigned(b, 24));
            wait for 128 * 4 * 10 ns;  -- one full period to settle
            wait until rising_edge(clock);
            on_count := 0;
            for i in 1 to 128 * 4 loop
                wait until rising_edge(clock);
                if blank = '0' then on_count := on_count + 1; end if;
            end loop;
            assert on_count = (b + 1) * 4
                report "PWM brightness " & integer'image(b) & ": on "
                & integer'image(on_count) severity failure;
        end;
    begin
        wait for 20 ns; reset_n <= '1';
        -- Startup update to all off.
        wait_update;
        assert lit = x"000000" report "startup" severity failure;
        leds <= x"A5C301"; wait_update;
        assert lit = x"A5C301" report "pattern 1" severity failure;
        leds <= x"800001"; wait_update;
        assert lit = x"800001" report "pattern 2 (bit order)" severity failure;
        check_pwm(0); check_pwm(63); check_pwm(127);
        report "PASS" severity note;
        done <= true; wait;
    end process;
end;
