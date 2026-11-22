`default_nettype none
// Fixed SPI-slave host port: mode 0, 24-bit frames, docs/isa-v0.md "Host port".
// cs_n, sck and mosi arrive already synchronized; edges are detected here.
// Frame in : [23:21] cmd | [20:19] eng | [18:16] reg | [15:0] data
// Frame out: [23:16] ID  | [15:8] status | [7:0] rx_head, the low 16 bits
//            latched one clock after the 8th bit, together with the
//            accept flags, so they describe the state before this command.
module host_port (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        cs_n,
    input  wire        sck,
    input  wire        mosi,
    output wire        miso,
    output reg  [1:0]  eng,          // addressed engine, valid from the 8th bit on
    input  wire [7:0]  status,       // of engine `eng`
    input  wire [7:0]  rx_head,
    output reg         cmd_valid,    // one-clock pulse, the clock after the 24th bit
    output wire [2:0]  cmd,
    output wire [2:0]  reg_addr,
    output wire [15:0] data,
    output reg         accept_push,  // !TX_FULL at the latch
    output reg         accept_pop    // RX_VALID at the latch
);
    localparam [7:0] ID = 8'h4D;

    reg        sck_d;
    reg [23:0] sh_in, sh_out;
    reg [4:0]  cnt;
    reg        latch;

    wire rise = sck && !sck_d;
    wire fall = !sck && sck_d;

    assign miso     = sh_out[23];
    assign cmd      = sh_in[23:21];
    assign reg_addr = sh_in[18:16];
    assign data     = sh_in[15:0];

    always @(posedge clk) begin
        if (!rst_n) begin
            sck_d       <= 1'b0;
            sh_in       <= 24'd0;
            sh_out      <= {ID, 16'd0};
            cnt         <= 5'd0;
            eng         <= 2'd0;
            latch       <= 1'b0;
            cmd_valid   <= 1'b0;
            accept_push <= 1'b0;
            accept_pop  <= 1'b0;
        end else begin
            sck_d     <= sck;
            cmd_valid <= 1'b0;
            latch     <= 1'b0;
            if (cs_n) begin
                cnt    <= 5'd0;
                sh_out <= {ID, 16'd0};
            end else begin
                if (rise && cnt != 5'd24) begin
                    sh_in <= {sh_in[22:0], mosi};
                    cnt   <= cnt + 5'd1;
                    if (cnt == 5'd7) begin           // 8th bit: cmd and eng are in
                        eng   <= sh_in[3:2];
                        latch <= 1'b1;
                    end
                    if (cnt == 5'd23)
                        cmd_valid <= 1'b1;
                end
                if (fall)
                    sh_out <= {sh_out[22:0], 1'b0};
                if (latch) begin
                    // Seven falling edges have already shifted sh_out left, so the
                    // 16-bit response lands at [22:7]; the 8th fall brings status[7]
                    // to miso for the host's 9th rising edge.
                    sh_out[22:7] <= {status, rx_head};
                    accept_push  <= !status[1];
                    accept_pop   <= status[0];
                end
            end
        end
    end
endmodule
