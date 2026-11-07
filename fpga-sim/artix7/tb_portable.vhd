-- Self-checking testbench for the vendor-neutral fifo512 and down counters
-- used by the Artix-7 (Rev 2) build. Run with: fpga-sim/artix7/run.sh
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_portable is
end;

architecture sim of tb_portable is
    signal clock: std_logic := '0';
    signal aclr: std_logic := '1';
    signal sclr, rdreq, wrreq: std_logic := '0';
    signal data, q: std_logic_vector(7 downto 0);
    signal empty, full: std_logic;
    signal usedw: std_logic_vector(8 downto 0);
    signal c_en, c_load: std_logic := '0';
    signal c_data, c_q: std_logic_vector(23 downto 0);
    signal done: boolean := false;
begin
    clock <= not clock after 5 ns when not done;

    dut: entity work.fifo512 port map (clock => clock, aclr => aclr,
        data => data, rdreq => rdreq, sclr => sclr, wrreq => wrreq,
        empty => empty, full => full, q => q, usedw => usedw);

    cnt: entity work.lpm_down_counter_24 port map (aclr => aclr,
        clock => clock, cnt_en => c_en, data => c_data, sload => c_load,
        q => c_q);

    process
        procedure tick is begin
            wait until rising_edge(clock); wait for 1 ns;
        end;
    begin
        tick; aclr <= '0'; tick;
        assert empty = '1' and full = '0' and unsigned(usedw) = 0
            report "reset state" severity failure;
        -- Read on empty is ignored.
        rdreq <= '1'; tick; rdreq <= '0';
        assert empty = '1' and unsigned(usedw) = 0 report "underflow" severity failure;
        -- Fill completely.
        wrreq <= '1';
        for i in 0 to 511 loop
            data <= std_logic_vector(to_unsigned(i mod 256, 8)); tick;
        end loop;
        assert full = '1' and empty = '0' report "full flag" severity failure;
        -- Write when full is ignored.
        data <= x"EE"; tick; wrreq <= '0';
        assert full = '1' report "overflow" severity failure;
        -- Read back: q valid one cycle after rdreq.
        for i in 0 to 511 loop
            rdreq <= '1'; tick; rdreq <= '0';
            assert unsigned(q) = to_unsigned(i mod 256, 8)
                report "data mismatch at " & integer'image(i) severity failure;
            assert unsigned(usedw) = to_unsigned((511 - i) mod 512, 9)
                report "usedw mismatch" severity failure;
        end loop;
        assert empty = '1' report "empty after drain" severity failure;
        -- Simultaneous read/write keeps level, then sclr.
        wrreq <= '1'; data <= x"A5"; tick;
        rdreq <= '1'; data <= x"5A"; tick; wrreq <= '0'; rdreq <= '0';
        assert q = x"A5" and unsigned(usedw) = 1 report "rw" severity failure;
        sclr <= '1'; tick; sclr <= '0';
        assert empty = '1' report "sclr" severity failure;
        -- Counter: load, count down, hold, load priority.
        c_data <= x"000005"; c_load <= '1'; tick; c_load <= '0';
        assert unsigned(c_q) = 5 report "load" severity failure;
        c_en <= '1'; tick; tick; c_en <= '0'; tick;
        assert unsigned(c_q) = 3 report "count" severity failure;
        c_en <= '1'; c_load <= '1'; c_data <= x"000010"; tick;
        c_en <= '0'; c_load <= '0';
        assert unsigned(c_q) = 16 report "load priority" severity failure;
        report "PASS" severity note;
        done <= true; wait;
    end process;
end;
