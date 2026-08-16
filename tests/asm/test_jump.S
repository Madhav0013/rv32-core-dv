  .section .text
  .globl main
.macro CHECK num, expected
  li   t1, \expected
  li   a0, \num
  bne  t0, t1, fail
.endm
main:
  jal t0, 1f
  li a0, 1
  ret
1:
  li t2, 1
  li t0, 1
  CHECK 1, 1
  li a0, 0
  ret
fail:
  ret
