  .section .text
  .globl main
.macro CHECK num, expected
  li   t1, \expected
  li   a0, \num
  bne  t0, t1, fail
.endm
main:
  li t2, 1
  slli t0, t2, 2
  CHECK 1, 4
  li a0, 0
  ret
fail:
  ret
