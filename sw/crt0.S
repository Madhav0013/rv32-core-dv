# ------------------------------------------------------------------------------
# crt0.S -- minimal startup for bare-metal test programs.
#
# Responsibilities, in order:
#   1. Put every architectural register in a KNOWN state. This matters more than
#      it looks: if you skip it, your RTL starts with x1..x31 = 0 (from reset)
#      while Spike may start them as X/unknown, and a bug that reads an
#      uninitialised register will pass in one and fail in the other for
#      reasons that have nothing to do with the bug.
#   2. Set up the stack pointer.
#   3. Zero .bss.
#   4. Call main().
#   5. Write main()'s return value to tohost to end the simulation.
# ------------------------------------------------------------------------------

  .section .text.init, "ax"
  .globl _start

_start:
  # 1. Deterministic register state.
  li  x1,  0
  li  x2,  0
  li  x3,  0
  li  x4,  0
  li  x5,  0
  li  x6,  0
  li  x7,  0
  li  x8,  0
  li  x9,  0
  li  x10, 0
  li  x11, 0
  li  x12, 0
  li  x13, 0
  li  x14, 0
  li  x15, 0
  li  x16, 0
  li  x17, 0
  li  x18, 0
  li  x19, 0
  li  x20, 0
  li  x21, 0
  li  x22, 0
  li  x23, 0
  li  x24, 0
  li  x25, 0
  li  x26, 0
  li  x27, 0
  li  x28, 0
  li  x29, 0
  li  x30, 0
  li  x31, 0

  # 2. Stack.
  la  sp, _stack_top

  # 3. Zero .bss.
  la  t0, _bss_start
  la  t1, _bss_end
1:
  bge t0, t1, 2f
  sw  x0, 0(t0)
  addi t0, t0, 4
  j   1b
2:

  # 4. main()
  call main

  # 5. Encode the exit code the way the RISC-V test convention expects:
  #    tohost = (code << 1) | 1.  So 0 -> 1 (pass), n -> 2n+1 (fail n).
  slli a0, a0, 1
  ori  a0, a0, 1
  la   t0, tohost
  sw   a0, 0(t0)

_halt:
  j _halt

# Default main, overridden by any test that defines its own.
  .weak main
main:
  li a0, 0
  ret
