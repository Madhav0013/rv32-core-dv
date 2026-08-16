/* ----------------------------------------------------------------------------
 * Linker script for bare-metal test programs.
 *
 * Memory map is deliberately identical to Spike's default so the same ELF runs
 * on both the RTL and the golden model with no relinking. If you change the
 * base address here you MUST pass a matching -m option to spike, or every
 * lockstep run will diverge on the very first instruction -- which looks like a
 * catastrophic core bug and is actually a linker script mismatch. This has
 * cost people entire afternoons.
 *
 * tohost/fromhost: the standard RISC-V test convention. A program signals
 * "done" by writing to tohost: value 1 means pass, any other odd value encodes
 * a failing test number. The testbench polls this address and stops the sim.
 * -------------------------------------------------------------------------- */

OUTPUT_ARCH("riscv")
ENTRY(_start)

MEMORY
{
  RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 256K
}

SECTIONS
{
  . = 0x80000000;

  .text.init : { *(.text.init) } > RAM
  .text      : { *(.text .text.*) } > RAM

  .rodata    : { *(.rodata .rodata.*) } > RAM

  .data      : { *(.data .data.*) } > RAM
  .sdata     : { *(.sdata .sdata.*) } > RAM

  .bss       : {
                 _bss_start = .;
                 *(.bss .bss.*)
                 *(.sbss .sbss.*)
                 *(COMMON)
                 _bss_end = .;
               } > RAM

  /* Host communication block. Must be 8-byte aligned and must be findable by
     name in the ELF symbol table -- the testbench looks up 'tohost'. */
  .tohost : ALIGN(8) {
    tohost = .;   . += 8;
    fromhost = .; . += 8;
  } > RAM

  . = ALIGN(16);
  _stack_bottom = .;
  . += 4K;
  _stack_top = .;

  _end = .;
}
