#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Run the RISC-V architectural compliance suite (RISCOF) against the core.
#
# HOW RISCOF WORKS, in one paragraph, because the docs bury it:
#   RISCOF compiles each test twice -- once for your DUT and once for a
#   reference model (Spike). Each test writes a "signature": a block of memory
#   containing the results it computed. RISCOF then diffs your signature against
#   Spike's. Identical signature => pass. So the entire job of your DUT plugin
#   is (a) build the ELF, (b) run it on your RTL, (c) dump the signature region
#   to a text file in the exact format RISCOF expects. Nothing more.
#
# Exit code is the CI gate: non-zero if any test fails.
# -----------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- Preconditions ------------------------------------------------------------
missing=0
need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "MISSING: $1 -- run ./scripts/setup.sh and 'source scripts/env.sh'" >&2
    missing=1
  fi
}
need riscof
need spike
need "${RISCV_GCC:-riscv-none-elf-gcc}"
[ "$missing" -eq 0 ] || exit 2

# --- Generate config.ini with correct absolute paths for this machine --------
cat > "$REPO_ROOT/tests/riscof/config.ini" <<CONFEOF
[RISCOF]
ReferencePlugin=spike
ReferencePluginPath=$REPO_ROOT/tests/riscof/spike
DUTPlugin=rv32i_core
DUTPluginPath=$REPO_ROOT/tests/riscof/rv32i_core

[rv32i_core]
pluginpath=$REPO_ROOT/tests/riscof/rv32i_core
ispec=$REPO_ROOT/tests/riscof/rv32i_core/rv32i_core_isa.yaml
pspec=$REPO_ROOT/tests/riscof/rv32i_core/rv32i_core_platform.yaml
target_run=1
jobs=4

[spike]
pluginpath=$REPO_ROOT/tests/riscof/spike
CONFEOF
echo "Generated tests/riscof/config.ini for $REPO_ROOT"

if [ ! -d tests/riscof/rv32i_core ]; then
  cat >&2 <<'EOF'
ERROR: the DUT plugin does not exist yet.

  Expected: tests/riscof/rv32i_core/{riscof_rv32i_core.py,rv32i_core_isa.yaml,
                                     rv32i_core_platform.yaml,env/}

  Generate the templates with:
      riscof setup --dutname=rv32i_core --refname=spike
  then move them under tests/riscof/ and fill in the three TODOs in
  riscof_rv32i_core.py (build command, run command, signature dump).

  See IMPLEMENTATION.md Phase 4.
EOF
  exit 2
fi

# --- Run ----------------------------------------------------------------------
if [ ! -d "$REPO_ROOT/riscv-arch-test" ]; then
  echo "==> Fetching riscv-arch-test suite"
  riscof --verbose info arch-test --clone
fi

echo "==> RISCOF: running architectural compliance suite"
riscof run --config=tests/riscof/config.ini \
           --suite=riscv-arch-test/riscv-test-suite/ \
           --env=riscv-arch-test/riscv-test-suite/env \
           --no-browser

# --- Summarise ----------------------------------------------------------------
REPORT="riscof_work/report.html"
if [ -f "$REPORT" ]; then
  total=$(grep -c 'class="details"' "$REPORT" || true)
  echo
  echo "Report: $REPORT"
  echo "Open it in a browser for the per-test pass/fail table."
  echo "Screenshot this for your README -- 'passes the official suite' is a"
  echo "claim reviewers will want to see evidence for."
fi
