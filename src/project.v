/*
 * Copyright (c) 2026 Jamie Gilbert
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// Top level: input synchronizer, SPI host port, per-engine config, divider,
// program memory and FIFOs, the engine(s) and the shared pin register file.
// Spec: docs/isa-v0.md. The engine itself is src/engine.v.
module tt_um_ja_gilbert_mockingbird #(
    parameter NENGINES = 1
) (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

    // ---- input synchronizer: in_s2 is the input space the engines see
    reg [15:0] in_s1, in_s2;
    always @(posedge clk) begin
        if (!rst_n) begin
            in_s1 <= 16'd0;
            in_s2 <= 16'd0;
        end else begin
            in_s1 <= {uio_in, ui_in};
            in_s2 <= in_s1;
        end
    end

    // ---- host port
    wire        cmd_valid, accept_push, accept_pop, miso;
    wire [2:0]  cmd, reg_addr;
    wire [1:0]  eng;
    wire [15:0] data;
    reg  [7:0]  status_sel, rx_head_sel;

    host_port host (
        .clk(clk), .rst_n(rst_n),
        .cs_n(in_s2[5]), .sck(in_s2[6]), .mosi(in_s2[7]), .miso(miso),
        .eng(eng), .status(status_sel), .rx_head(rx_head_sel),
        .cmd_valid(cmd_valid), .cmd(cmd), .reg_addr(reg_addr), .data(data),
        .accept_push(accept_push), .accept_pop(accept_pop)
    );

    wire host_eng_ok = ({30'd0, eng} < NENGINES);
    localparam EB = (NENGINES > 2) ? 2 : 1;       // index width for the arrays below
    wire [EB-1:0] eidx = eng[EB-1:0];              // only used when host_eng_ok

    // ---- per-engine registers (written only by the host block below)
    reg [15:0] clkdiv [0:NENGINES-1];
    reg        run    [0:NENGINES-1];
    reg        clr    [0:NENGINES-1];   // one-clock pulse
    reg [4:0]  start  [0:NENGINES-1];
    reg [1:0]  shift  [0:NENGINES-1];
    reg [3:0]  jmppin [0:NENGINES-1];
    reg [4:0]  ptr    [0:NENGINES-1];
    reg        rx_ovf [0:NENGINES-1];

    wire [NENGINES-1:0]    tick, tx_empty, tx_full, rx_empty, rx_full;
    wire [NENGINES-1:0]    tx_pop, rx_push, rx_drop, stalled;
    wire [8*NENGINES-1:0]  tx_rdata, rx_rdata, rx_wdata, status;
    wire [5*NENGINES-1:0]  pc;
    wire [16*NENGINES-1:0] instr, out_we, out_wdata, oe_we, oe_wdata;

    genvar e;
    generate
        for (e = 0; e < NENGINES; e = e + 1) begin : g
            wire sel = cmd_valid && host_eng_ok && ({30'd0, eng} == e);

            // divider: a tick every CLKDIV clocks while running; 0 and 1 mean every clock
            reg  [15:0] divcnt;
            wire [15:0] last = (clkdiv[e] <= 16'd1) ? 16'd0 : clkdiv[e] - 16'd1;
            assign tick[e] = run[e] && (divcnt == last);
            always @(posedge clk) begin
                if (!rst_n || clr[e] || !run[e])      // held at zero while stopped
                    divcnt <= 16'd0;
                else
                    divcnt <= tick[e] ? 16'd0 : divcnt + 16'd1;
            end

            // private program memory, written by host PROG at this engine's PTR
            // while the engine is stopped
            reg [15:0] mem [0:31];
            always @(posedge clk)
                if (sel && cmd == 3'd1 && !run[e])
                    mem[ptr[e]] <= data;
            assign instr[16*e +: 16] = mem[pc[5*e +: 5]];

            fifo8 txf (
                .clk(clk), .rst_n(rst_n), .flush(clr[e]),
                .push(sel && cmd == 3'd3 && accept_push), .wdata(data[7:0]),
                .pop(tx_pop[e]), .rdata(tx_rdata[8*e +: 8]),
                .empty(tx_empty[e]), .full(tx_full[e])
            );
            fifo8 rxf (
                .clk(clk), .rst_n(rst_n), .flush(clr[e]),
                .push(rx_push[e]), .wdata(rx_wdata[8*e +: 8]),
                .pop(sel && cmd == 3'd4 && accept_pop), .rdata(rx_rdata[8*e +: 8]),
                .empty(rx_empty[e]), .full(rx_full[e])
            );
            engine core (
                .clk(clk), .rst_n(rst_n), .tick(tick[e]), .clr(clr[e]),
                .start_pc(start[e]), .out_right(shift[e][0]), .in_right(shift[e][1]),
                .jmppin(jmppin[e]), .pc(pc[5*e +: 5]), .instr(instr[16*e +: 16]),
                .in_pins(in_s2),
                .out_we(out_we[16*e +: 16]), .out_wdata(out_wdata[16*e +: 16]),
                .oe_we(oe_we[16*e +: 16]), .oe_wdata(oe_wdata[16*e +: 16]),
                .tx_empty(tx_empty[e]), .tx_rdata(tx_rdata[8*e +: 8]), .tx_pop(tx_pop[e]),
                .rx_full(rx_full[e]), .rx_push(rx_push[e]), .rx_wdata(rx_wdata[8*e +: 8]),
                .rx_drop(rx_drop[e]), .stalled(stalled[e])
            );
            assign status[8*e +: 8] = {1'b0, rx_ovf[e], rx_full[e], tx_empty[e],
                                       stalled[e], run[e], tx_full[e], !rx_empty[e]};
        end
    endgenerate

    // ---- host command execution and config registers
    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (i = 0; i < NENGINES; i = i + 1) begin
                clkdiv[i] <= 16'd0;
                run[i]    <= 1'b0;
                clr[i]    <= 1'b0;
                start[i]  <= 5'd0;
                shift[i]  <= 2'd0;
                jmppin[i] <= 4'd0;
                ptr[i]    <= 5'd0;
                rx_ovf[i] <= 1'b0;
            end
        end else begin
            for (i = 0; i < NENGINES; i = i + 1) begin
                clr[i] <= 1'b0;
                if (rx_drop[i]) rx_ovf[i] <= 1'b1;
                if (clr[i])     rx_ovf[i] <= 1'b0;
            end
            if (cmd_valid && host_eng_ok) begin
                case (cmd)
                    3'd1: if (!run[eidx])                        // PROG: word written in g[eidx]
                              ptr[eidx] <= ptr[eidx] + 5'd1;
                    3'd2: case (reg_addr)                        // CFG
                        3'd0: clkdiv[eidx] <= data;
                        3'd1: begin run[eidx] <= data[0]; clr[eidx] <= data[1]; end
                        3'd2: start[eidx]  <= data[4:0];
                        3'd3: shift[eidx]  <= data[1:0];
                        3'd4: jmppin[eidx] <= data[3:0];
                        3'd5: ptr[eidx]    <= data[4:0];
                        default: ;
                    endcase
                    default: ;                                   // STATUS, PUSH, POP: FIFOs above
                endcase
            end
        end
    end

    // status and RX head of the addressed engine, for the host port's latch
    always @(*) begin
        status_sel  = 8'd0;
        rx_head_sel = 8'd0;
        if (host_eng_ok) begin
            status_sel  = status[8*eidx +: 8];
            if (!rx_empty[eidx])                   // an empty FIFO's head reads 0, never X
                rx_head_sel = rx_rdata[8*eidx +: 8];
        end
    end

    // ---- shared pin register file: later (higher) engines win a same-cycle write
    reg [15:0] out_r;
    reg [7:0]  oe_r;
    integer k, b;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_r <= 16'd0;
            oe_r  <= 8'd0;
        end else begin
            for (k = 0; k < NENGINES; k = k + 1) begin
                for (b = 0; b < 16; b = b + 1)
                    if (out_we[16*k + b]) out_r[b] <= out_wdata[16*k + b];
                for (b = 8; b < 16; b = b + 1)
                    if (oe_we[16*k + b]) oe_r[b-8] <= oe_wdata[16*k + b];
            end
        end
    end

    assign uo_out  = {miso, out_r[6:0]};   // output 7 is the host port's MISO
    assign uio_out = out_r[15:8];
    assign uio_oe  = oe_r;

    wire _unused = &{ena, out_r[7], 1'b0};

endmodule
