  .section .text
  .globl main
.macro CHECK num, expected
  li   t1, \expected
  li   a0, \num
  bne  t0, t1, fail
.endm
main:
  li t2, 0xF
  li t3, 0xA
  and t0, t2, t3
  CHECK 1, 0xA
  li a0, 0
  ret
fail:
  ret
