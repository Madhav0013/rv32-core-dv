.section .text.init
.global main
main:
  // Initialize registers to 0 to avoid spurious differences with Spike
  li t3, 0
  li t4, 0
  li t5, 0
  li t6, 0
  li t2, 0
  li t1, 0

  # RAW at distance 1 -- requires EX->EX forwarding
  addi t3, x0, 5
  addi t4, t3, 3          # t4 must be 8
  li t6, 8
  bne t4, t6, fail_1

  # RAW at distance 2 -- requires MEM->EX forwarding
  addi t3, x0, 5
  nop
  addi t4, t3, 3          # t4 must be 8
  li t6, 8
  bne t4, t6, fail_2

  # Double write within 3 instructions -- tests forwarding PRIORITY
  addi t3, x0, 1
  addi t3, x0, 2
  addi t4, t3, 0          # t4 must be 2, not 1
  li t6, 2
  bne t4, t6, fail_3

  # Load-use -- requires a stall; forwarding cannot help
  la t5, test_data
  lw t3, 0(t5)            # t3 gets 42
  addi t4, t3, 1          # t4 must be 43
  li t6, 43
  bne t4, t6, fail_4

  # Taken branch -- requires a flush
  beq x0, x0, 1f
  li t2, 0xDEAD           # must NOT execute
1:
  li t6, 0xDEAD
  beq t2, t6, fail_5

  # x0 forwarding -- a write to x0 must not be forwarded
  addi x0, x0, 42
  add t1, x0, x0          # t1 must be 0
  bne t1, x0, fail_6

pass:
  li a0, 0
  ret

fail_1: li a0, 1; ret
fail_2: li a0, 2; ret
fail_3: li a0, 3; ret
fail_4: li a0, 4; ret
fail_5: li a0, 5; ret
fail_6: li a0, 6; ret

.section .data
.align 2
test_data:
  .word 42
