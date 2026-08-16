  .section .text
  .globl main
.macro CHECK num, expected
  li   t1, \expected
  li   a0, \num
  bne  t0, t1, fail
.endm
main:
  lui t0, 0x12345
  CHECK 1, 0x12345000
  li a0, 0
  ret
fail:
  ret
