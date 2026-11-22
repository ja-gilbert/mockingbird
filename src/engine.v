module engine (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        tick,        // one-clock pulse per engine tick (divider, mine)
    input  wire        clr,         // one-clock pulse: restart (host CTRL.CLR)
    input  wire [4:0]  start_pc,    // loaded into pc by clr
    input  wire        out_right,   // SHIFT bit 0
    input  wire        in_right,    // SHIFT bit 1
    input  wire [3:0]  jmppin,      // JMPPIN
    output wire [4:0]  pc,          // fetch address; instr = mem[pc] arrives same cycle
    input  wire [15:0] instr,
    input  wire [15:0] in_pins,     // synchronized input space
    output wire [15:0] out_we,      // per-pin write strobes, only during an executing tick
    output wire [15:0] out_wdata,
    output wire [15:0] oe_we,       // bits 0..7 are ignored by the pin file
    output wire [15:0] oe_wdata,
    input  wire        tx_empty,    // TX FIFO, host -> engine
    input  wire [7:0]  tx_rdata,    // head, valid while !tx_empty
    output wire        tx_pop,      // pulse: FIFO drops its head at this edge
    input  wire        rx_full,     // RX FIFO, engine -> host
    output wire        rx_push,     // pulse: FIFO stores rx_wdata at this edge
    output wire [7:0]  rx_wdata,
    output wire        rx_drop,     // pulse: non-blocking PUSH hit a full FIFO
    output reg         stalled      // status bit 3
);
