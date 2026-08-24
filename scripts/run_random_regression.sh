#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Constrained-random regression using riscv-dv in PYFLOW mode.
#
# WHY PYFLOW: riscv-dv's headline flow is SystemVerilog + UVM, which needs VCS,
# Xcelium or Questa -- none of which you have. `--simulator pyflow` runs the
# same generator reimplemented in Python on top of PyVSC, so you get real
# constrained-random instruction streams with zero licences. This is the single
# most important flag in this project; without it this phase is inaccessible to
# a student and most student projects quietly skip it.
#
# Usage:
#   ./scripts/run_random_regression.sh                     # default smoke set
#   ./scripts/run_random_regression.sh -n 50               # 50 iterations
#   ./scripts/run_random_regression.sh -t riscv_rand_instr_test -n 200
# -----------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DV_DIR="${RISCV_DV_DIR:-$REPO_ROOT/riscv-dv}"

TEST="riscv_arithmetic_basic_test"
ITERATIONS=20
while getopts "t:n:" opt; do
  case "$opt" in
    t) TEST="$OPTARG" ;;
    n) ITERATIONS="$OPTARG" ;;
    *) echo "usage: $0 [-t test_name] [-n iterations]" >&2; exit 1 ;;
  esac
done

# --- Preconditions ------------------------------------------------------------
: "${RISCV_GCC:?set it via 'source scripts/env.sh'}"
: "${RISCV_OBJCOPY:?set it via 'source scripts/env.sh'}"
: "${SPIKE_PATH:?set it via 'source scripts/env.sh'}"

if [ ! -d "$DV_DIR" ]; then
  echo "==> Cloning riscv-dv into $DV_DIR"
  git clone --depth 1 https://github.com/chipsalliance/riscv-dv.git "$DV_DIR"
  
  # Patch deprecated 'imp' module for Python 3.12 compatibility
  sed -i 's/from imp import reload/from importlib import reload/g' "$DV_DIR/pygen/pygen_src/isa/riscv_instr.py" || true
  
  pip3 install --user -r "$DV_DIR/requirements.txt" || \
    pip3 install --user --break-system-packages -r "$DV_DIR/requirements.txt"
fi

OUT_DIR="$REPO_ROOT/build/riscv_dv_out"
mkdir -p "$OUT_DIR"

# --- Generate + assemble ------------------------------------------------------
echo "==> Generating $ITERATIONS random program(s) for test '$TEST' (pyflow)"
pushd "$DV_DIR" >/dev/null
  python3 run.py \
    --test="$TEST" \
    --simulator=pyflow \
    --iterations="$ITERATIONS" \
    --target=rv32i \
    --output="$OUT_DIR" \
    --steps=gen,gcc_compile \
    --sim_opts="--bare_program_mode=1"
popd >/dev/null

# --- Run each program on RTL and compare against Spike ------------------------
echo "==> Lockstep-comparing each program against Spike"
fail=0
shopt -s nullglob
for elf in "$OUT_DIR"/asm_test/*.o; do
  name="$(basename "$elf" .o)"
  echo "--- $name"
  
  # Run the RTL simulation to generate the rtl_log and cov_log
  TESTCASE_ELF="$(realpath "$elf")" make -C "$REPO_ROOT/tb/cocotb" soc_top PLUSARGS="+rtl_log=$(realpath "$OUT_DIR")/$name.rtl.log" > /dev/null

  if ! python3 "$REPO_ROOT/tb/lockstep/spike_compare.py" \
        --elf "$elf" \
        --rtl-log "$OUT_DIR/$name.rtl.log" \
        --max-instr 200000; then
    echo "    FAILED: $name"
    fail=$((fail + 1))
  fi
done

echo
if [ "$fail" -ne 0 ]; then
  echo "RESULT: $fail program(s) mismatched. Waveforms are in build/."
  exit 1
fi
echo "RESULT: all programs matched Spike."
