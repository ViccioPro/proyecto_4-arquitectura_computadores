// Copyright 2026 Universidad de los Andes.
// Licensed under the Solderpad Hardware License, Version 0.51 (the "License");
// you may not use this file except in compliance with the License.
// SPDX-License-Identifier: SHL-0.51
//
// Course: Arquitectura de Computadores (2026)
// 
// Authors:
// - Nicolás Villegas <navillegas@miuandes.cl>

module espino_if_stage #(
  parameter [31:0] BootAddr = 32'h0000_0000,
  // [Proyecto 4] bits del PC; 32 = comportamiento original.
  // Con la RAM de 2 KB bastan 11 bits: ahorra flip-flops y sumadores.
  parameter integer PcWidth = 32
) (
  input  wire        clk_i,
  input  wire        rst_ni,

  input  wire        pc_set_i,
  input  wire [31:0] pc_target_i,
  input  wire        stall_i,

  output wire        instr_req_o,
  output wire [31:0] instr_addr_o,

  output wire [31:0] pc_id_o,
  output wire        instr_valid_id_o
);

  reg  [PcWidth-1:0] pc_q;
  wire [PcWidth-1:0] pc_next;
  reg  [PcWidth-1:0] pc_id_q;
  reg         valid_q;
  wire        valid_d;

  assign pc_next = pc_set_i ? pc_target_i[PcWidth-1:0] : (pc_q + 3'd4);
  assign valid_d = ~pc_set_i;

  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      pc_q    <= BootAddr[PcWidth-1:0];
      pc_id_q <= BootAddr[PcWidth-1:0];
      valid_q <= 1'b0;
    end else if (!stall_i) begin
      pc_q    <= pc_next;
      pc_id_q <= pc_q;
      valid_q <= valid_d;
    end
  end

  assign instr_req_o      = ~stall_i;
  // Asignar un valor angosto a un wire de 32 bits lo extiende con ceros
  assign instr_addr_o     = pc_q;
  assign pc_id_o          = pc_id_q;
  assign instr_valid_id_o = valid_q;

endmodule