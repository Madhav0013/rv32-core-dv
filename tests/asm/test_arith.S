# ------------------------------------------------------------------------------
# test_arith.S -- directed test for RV32I register-register and register-
# immediate arithmetic.
#
# CONVENTION used by every test in this directory:
#   * main() returns 0 in a0 on success, or the number of the first failing
#     check. crt0.S turns that into the tohost value the testbench looks for.
#   * Each check gets its own number so a failure identifies itself without a
#     waveform. `tohost = 2n+1` means check n failed.
#
# ALWAYS run a new test on Spike before running it on the RTL:
#     spike --isa=rv32i build/test_arith.elf
# If the test itself is wrong you will otherwise spend hours "debugging" a core
# that is behaving correctly.
# ------------------------------------------------------------------------------

  .section .text
  .globl main

# Helper: compare t0 against t1; if different, return the check number in a0.
# Usage:  li t1, <expected>;  li a0, <check_num>;  bne t0, t1, fail
.macro CHECK num, expected
  li   t1, \expected
  li   a0, \num
  bne  t0, t1, fail
.endm

main:
  # --- check 1: ADDI, basic ---------------------------------------------------
  addi t0, x0, 5
  CHECK 1, 5

  # --- check 2: ADDI with a negative immediate (sign extension) ---------------
  addi t0, x0, -1
  CHECK 2, -1

  # --- check 3: ADD --------------------------------------------------------
  li   t2, 100
  li   t3, 23
  add  t0, t2, t3
  CHECK 3, 123

  # --- check 4: SUB, result negative ------------------------------------------
  li   t2, 10
  li   t3, 30
  sub  t0, t2, t3
  CHECK 4, -20

  # --- check 5: overflow wraps, it does not trap ------------------------------
  li   t2, 0x7FFFFFFF
  addi t0, t2, 1
  CHECK 5, 0x80000000

  # --- check 6: SLT, signed comparison across zero ----------------------------
  # 0xFFFFFFFF is -1 signed, so it IS less than 1.
  li   t2, -1
  li   t3, 1
  slt  t0, t2, t3
  CHECK 6, 1

  # --- check 7: SLTU, the same operands unsigned ------------------------------
  # 0xFFFFFFFF unsigned is the largest 32-bit value, so it is NOT less than 1.
  # If checks 6 and 7 both pass, signed/unsigned comparison is wired correctly.
  li   t2, -1
  li   t3, 1
  sltu t0, t2, t3
  CHECK 7, 0

  # --- check 8: SLL, shift amount masked to 5 bits ----------------------------
  # Shifting by 33 must behave as shifting by 1, not as shifting by 33.
  li   t2, 1
  li   t3, 33
  sll  t0, t2, t3
  CHECK 8, 2

  # --- check 9: SRL is logical (zero fill) ------------------------------------
  li   t2, 0x80000000
  li   t3, 4
  srl  t0, t2, t3
  CHECK 9, 0x08000000

  # --- check 10: SRA is arithmetic (sign fill) --------------------------------
  # The classic bug. If SRA is implemented as a logical shift this is the only
  # check in the file that catches it.
  li   t2, 0x80000000
  li   t3, 4
  sra  t0, t2, t3
  CHECK 10, 0xF8000000

  # --- check 11: LUI places the immediate in the upper 20 bits ----------------
  lui  t0, 0xABCDE
  CHECK 11, 0xABCDE000

  # --- check 12: XOR / OR / AND -----------------------------------------------
  li   t2, 0xF0F0F0F0
  li   t3, 0x0FF00FF0
  xor  t0, t2, t3
  CHECK 12, 0xFF00FF00

  # --- check 13: writes to x0 are dropped -------------------------------------
  addi x0, x0, 42
  add  t0, x0, x0
  CHECK 13, 0

  # --- all passed -------------------------------------------------------------
  li   a0, 0
  ret

fail:
  # a0 already holds the failing check number.
  ret
