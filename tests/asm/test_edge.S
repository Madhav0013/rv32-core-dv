  .section .text
  .globl main
.macro CHECK num, expected
  li   t1, \expected
  li   a0, \num
  bne  t0, t1, fail
.endm
main:
  li t0, 0
  CHECK 1, 0
  li a0, 0
  ret
fail:
  ret
