module engine (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        tick,        // one-clock pulse per engine tick (divider, mine)
    input  wire        clr,         // one-clock pulse: restart (host CTRL.CLR)
    input  wire [4:0]  start_pc,    // loaded into pc by clr
    input  wire        out_right,   // SHIFT bit 0
    input  wire        in_right,    // SHIFT bit 1
    input  wire [3:0]  jmppin,      // JMPPIN
    output reg [4:0]   pc,          // fetch address; instr = mem[pc] arrives same cycle
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
    // ---- state (docs/isa-v0.md, "Engine state")
    reg [7:0] x, y, isr, osr;
    reg [3:0] delay;

    // ---- decode (docs/isa-v0.md, "Instruction format")
    wire [3:0] op = instr[15:12];
    wire [3:0] dly = instr[11:8];
    wire [7:0] arg = instr[7:0];
    
    // ---- opcodes (docs/isa-v0.md, instruction table; same numbers as isa.py)
    localparam [3:0] JMP = 4'd0, WAIT = 4'd1, IN = 4'd2, OUT = 4'd3, PUSH = 4'd4,
                     PULL = 4'd5, MOV = 4'd6, SET = 4'd7, SETP = 4'd8;
    
    // ---- argument fields . Bit 7 means something different per opcode, 
    //      so it gets one name per meaning, they are all the same wire.
        wire [2:0] cond    = arg[7:5];     // JMP
    wire [4:0] target  = arg[4:0];     // JMP
    wire       pol     = arg[7];       // WAIT: level to wait for
    wire       blk     = arg[7];       // PUSH, PULL: 1 = blocking
    wire       dir     = arg[7];       // OUT, SETP: 1 = write oe instead of out
    wire       in_null = arg[7];       // IN: 1 = shift in zeros
    wire       sreg    = arg[7];       // SET: 0 = X, 1 = Y
    wire [3:0] pidx    = arg[3:0];     // WAIT, SETP: pin index
    wire [3:0] gidx    = arg[6:3];     // IN, OUT: first pin of the group
    wire [3:0] n       = (arg[2:0] == 3'd0) ? 4'd8 : {1'b0, arg[2:0]};  // count, 0 means 8
    wire [2:0] dst     = arg[7:5];     // MOV
    wire [1:0] mop     = arg[4:3];     // MOV
    wire [2:0] src     = arg[2:0];     // MOV
    wire       mov_ok  = (dst <= 3'd3) && (src <= 3'd4) && (mop != 2'd3);  // else NOP
    wire [6:0] imm     = arg[6:0];     // SET
    wire       sval    = arg[6];       // SETP: value to write

    // ---- stall: a pure function of this instruction and the current inputs
    wire stall = (op == WAIT && in_pins[pidx] != pol)
              || (op == PULL && blk && tx_empty)
              || (op == PUSH && blk && rx_full);
    wire exec  = tick && (delay == 4'd0);   // this tick decodes mem[pc]
    wire fire  = exec && !stall && !clr;    // ...and applies it at this edge

    
    // ---- OUT data: the n bits leaving OSR. odata bit k goes to pin gidx + k.
    wire [7:0]  omask = ~(8'hFF << n);                                    // low n bits set
    wire [7:0]  odata = out_right ? (osr & omask) : ((osr >> (4'd8 - n)) & omask);

    // ---- pin writes: OUT writes a group, SETP writes one pin; dir picks out vs oe.
    //      A bit shifted past 15 is dropped, which is the "indices beyond 15" rule.
    wire        pin_wr = fire && (op == OUT || op == SETP);
    wire [15:0] pin_we = (op == OUT) ? ({8'd0, omask} << gidx) : (16'd1 << pidx);
    wire [15:0] pin_wd = (op == OUT) ? ({8'd0, odata} << gidx) : ({15'd0, sval} << pidx);

    assign out_we    = (pin_wr && !dir) ? pin_we : 16'd0;
    assign oe_we     = (pin_wr &&  dir) ? pin_we : 16'd0;
    assign out_wdata = pin_wd;        // only read where a we bit is set
    assign oe_wdata  = pin_wd;

    // ---- FIFO strobes. A blocking PUSH on full or PULL on empty never fires
    //      (it stalls), so rx_drop can only come from a non-blocking PUSH.
    assign tx_pop   = fire && (op == PULL) && !tx_empty;
    assign rx_push  = fire && (op == PUSH) && !rx_full;
    assign rx_drop  = fire && (op == PUSH) &&  rx_full;
    assign rx_wdata = isr;

    
    // ---- IN data: n pins starting at gidx, or zeros. idata bit k came from pin gidx + k.
    wire [15:0] in_sh = in_pins >> gidx;
    wire [7:0]  idata = in_null ? 8'd0 : (in_sh[7:0] & omask);

    // ---- next register values, one wire each. Pass 5 only picks which one to latch.
    wire [7:0]  isr_in  = in_right  ? ((isr >> n) | (idata << (4'd8 - n)))   // LSB first
                                    : ((isr << n) | idata);                  // MSB first
    wire [7:0]  osr_out = out_right ? (osr >> n) : (osr << n);               // sent bits leave
    wire [7:0]  osr_in  = tx_empty  ? x : tx_rdata;                          // PULL; empty => NOBLOCK

    // ---- MOV: pick the source, then apply the op
    wire [7:0]  msrc = (src == 3'd0) ? x   : (src == 3'd1) ? y
                     : (src == 3'd2) ? isr : (src == 3'd3) ? osr : 8'd0;     // 4 = NULL
    wire [7:0]  mrev = {msrc[0], msrc[1], msrc[2], msrc[3], msrc[4], msrc[5], msrc[6], msrc[7]};
    wire [7:0]  mval = (mop == 2'd1) ? ~msrc : (mop == 2'd2) ? mrev : msrc;

    // ---- JMP: the condition table, then the next pc for every instruction
    wire        jpin  = in_pins[jmppin];
    wire        taken = (cond == 3'd0) ? 1'b1
                      : (cond == 3'd1) ? (x == 8'd0)
                      : (cond == 3'd2) ? (x != 8'd0)      // X--: pass 5 does the decrement
                      : (cond == 3'd3) ? (y == 8'd0)
                      : (cond == 3'd4) ? (y != 8'd0)      // Y--
                      : (cond == 3'd5) ? (x != y)
                      : (cond == 3'd6) ? jpin : !jpin;
    wire [4:0]  pc_next = (op == JMP && taken) ? target : pc + 5'd1;        // 5 bits: wraps at 32

    
    // ---- the one clocked block. Priority: reset, then clr, then a tick.
    always @(posedge clk) begin
        if (!rst_n) begin
            pc      <= 5'd0;
            x       <= 8'd0;
            y       <= 8'd0;
            isr     <= 8'd0;
            osr     <= 8'd0;
            delay   <= 4'd0;
            stalled <= 1'b0;
        end else if (clr) begin
            pc      <= start_pc;                // the only difference from reset
            x       <= 8'd0;
            y       <= 8'd0;
            isr     <= 8'd0;
            osr     <= 8'd0;
            delay   <= 4'd0;
            stalled <= 1'b0;
        end else if (tick) begin
            if (delay != 4'd0)
                delay <= delay - 4'd1;          // still paying for the last instruction
            else if (stall)
                stalled <= 1'b1;                // hold everything, try again next tick
            else begin
                stalled <= 1'b0;
                pc      <= pc_next;
                delay   <= dly;
                case (op)
                    JMP:  if (taken && cond == 3'd2)      x <= x - 8'd1;
                          else if (taken && cond == 3'd4) y <= y - 8'd1;
                    IN:   isr <= isr_in;
                    OUT:  osr <= osr_out;
                    PUSH: isr <= 8'd0;          // pushed or dropped, ISR clears either way
                    PULL: osr <= osr_in;
                    MOV:  if (mov_ok)
                              case (dst)
                                  3'd0: x   <= mval;
                                  3'd1: y   <= mval;
                                  3'd2: isr <= mval;
                                  3'd3: osr <= mval;
                                  default: ;    // unreachable: mov_ok means dst <= 3
                              endcase
                    SET:  if (sreg) y <= {1'b0, imm};
                          else      x <= {1'b0, imm};
                    default: ;                  // WAIT, SETP, reserved: no register changes
                endcase
            end
        end
    end

    // in_sh is 16 bits wide only so the shift is; IN never reads past 8 pins
    wire _unused = &{in_sh[15:8], 1'b0};
endmodule
