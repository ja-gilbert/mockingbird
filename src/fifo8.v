`default_nettype none
// 4-deep, 8-bit, first-word-fall-through FIFO: rdata shows the head while
// !empty. Push into a full FIFO and pop from an empty one are ignored.
module fifo8 (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       flush,
    input  wire       push,
    input  wire [7:0] wdata,
    input  wire       pop,
    output wire [7:0] rdata,
    output wire       empty,
    output wire       full
);
    reg [7:0] m0, m1, m2, m3;   // four explicit bytes: plain flops for every tool
    reg [2:0] wp, rp;           // the extra bit tells full from empty

    assign empty = (wp == rp);
    assign full  = (wp[1:0] == rp[1:0]) && (wp[2] != rp[2]);
    assign rdata = (rp[1:0] == 2'd0) ? m0 :
                   (rp[1:0] == 2'd1) ? m1 :
                   (rp[1:0] == 2'd2) ? m2 : m3;

    always @(posedge clk) begin
        if (!rst_n || flush) begin
            wp <= 3'd0;
            rp <= 3'd0;
        end else begin
            if (push && !full)
                wp <= wp + 3'd1;
            if (pop && !empty)
                rp <= rp + 3'd1;
        end
    end

    always @(posedge clk) begin
        if (push && !full) begin
            case (wp[1:0])
                2'd0: m0 <= wdata;
                2'd1: m1 <= wdata;
                2'd2: m2 <= wdata;
                default: m3 <= wdata;
            endcase
        end
    end
endmodule
