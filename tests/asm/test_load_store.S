  .section .text
  .globl main
.macro CHECK num, expected
  li   t1, \expected
  li   a0, \num
  bne  t0, t1, fail
.endm
main:
  la t2, my_data
  lw t0, 0(t2)
  CHECK 1, 0x12345678
  li t3, 0x87654321
  sw t3, 4(t2)
  lw t0, 4(t2)
  CHECK 2, 0x87654321
  li a0, 0
  ret
fail:
  ret
  .section .data
my_data:
  .word 0x12345678
  .word 0x0
