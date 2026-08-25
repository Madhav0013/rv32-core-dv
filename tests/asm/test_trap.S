.section .text.init
.global main
main:
  ecall
  ebreak
  li a0, 0
  ret
