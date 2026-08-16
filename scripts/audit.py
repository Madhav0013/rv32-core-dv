#!/usr/bin/env python3
"""
Claim audit -- checks that every claim in the README is backed by evidence.

The premise of this repository is that a stranger can verify every correctness
claim it makes. This script is what makes that premise checkable instead of
aspirational. It reads the README, finds the claims, hunts for the artifact that
would substantiate each one, and reports which claims are actually backed.

It is deliberately LAYOUT-AGNOSTIC: it discovers files by pattern rather than by
hardcoded path, so it keeps working when modules get renamed or directories get
reorganised during the build.

Verdicts
--------
  PASS     claim found, evidence found, and they agree
  FAIL     claim found but the evidence contradicts it, or is absent
           -> this is the dangerous case: an unbacked number in the README
  MISSING  no claim and no evidence (a phase that has not run yet) -- fine
  WARN     something worth a look, not necessarily wrong
  INFO     context, no judgement

Usage
-----
    python3 scripts/audit.py              # inspect artifacts only (fast)
    python3 scripts/audit.py --full       # also run make lint / make unit
    python3 scripts/audit.py --json       # machine-readable output

Exit code is non-zero if any check FAILs, so this can gate CI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


VERDICT_STYLE = {
    "PASS":    ("32;1", "PASS   "),
    "FAIL":    ("31;1", "FAIL   "),
    "WARN":    ("33;1", "WARN   "),
    "MISSING": ("90",   "MISSING"),
    "INFO":    ("36",   "INFO   "),
}


@dataclass
class Result:
    verdict: str
    check: str
    detail: str
    evidence: str = ""


@dataclass
class Audit:
    root: Path
    results: list[Result] = field(default_factory=list)

    def add(self, verdict: str, check: str, detail: str, evidence: str = "") -> None:
        self.results.append(Result(verdict, check, detail, evidence))

    # -- discovery helpers ---------------------------------------------------
    def find(self, *patterns: str, limit: int = 200) -> list[Path]:
        """Glob several patterns, skipping .git and build noise."""
        out: list[Path] = []
        for pat in patterns:
            for p in self.root.glob(pat):
                sp = str(p)
                if "/.git/" in sp or "/third_party/" in sp:
                    continue
                if p.is_file() or p.is_dir():
                    out.append(p)
                if len(out) >= limit:
                    return out
        return out

    def read(self, path: Path) -> str:
        try:
            return path.read_text(errors="replace")
        except OSError:
            return ""

    def run(self, cmd: list[str], timeout: int = 900) -> tuple[int, str]:
        try:
            r = subprocess.run(
                cmd, cwd=self.root, capture_output=True, text=True, timeout=timeout
            )
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            return 127, str(e)


# ---------------------------------------------------------------------------
# README parsing
# ---------------------------------------------------------------------------
NUMERIC = re.compile(r"\d")
EMPTY_CELL = {"", "—", "-", "--", "n/a", "na", "tbd", "todo", "pending", "not run"}


def parse_tables(md: str) -> list[list[str]]:
    """Return every markdown table row as a list of stripped cells."""
    rows = []
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("|") and s.count("|") >= 2:
            cells = [x.strip() for x in s.strip("|").split("|")]
            if all(set(x) <= set("-: ") for x in cells):
                continue  # separator row
            rows.append(cells)
    return rows


def claim_for(md: str, *keywords: str) -> str | None:
    """
    Find the value cell of a README table row whose first cell mentions all
    keywords. Returns None if the row is absent or the value is a placeholder.
    """
    for cells in parse_tables(md):
        if len(cells) < 2:
            continue
        label = cells[0].lower()
        if all(k.lower() in label for k in keywords):
            val = cells[1].strip()
            if val.lower().strip("* `") in EMPTY_CELL:
                return None
            return val
    return None


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_git(a: Audit) -> None:
    if not (a.root / ".git").exists():
        a.add("WARN", "git/repo", "no .git directory found")
        return

    rc, out = a.run(["git", "fsck", "--no-progress"], timeout=300)
    if rc == 0 and "error" not in out.lower() and "missing" not in out.lower():
        a.add("PASS", "git/integrity", "object database intact")
    else:
        a.add("FAIL", "git/integrity",
              "git fsck reported problems -- possible filesystem damage",
              out.strip()[:400])

    _, count = a.run(["git", "rev-list", "--count", "HEAD"])
    n = count.strip()
    if n.isdigit():
        k = int(n)
        # Commit count is a smell, not a claim -- never fail the audit on it.
        if k >= 40:
            a.add("PASS", "git/commits", f"{k} commits on HEAD")
        else:
            a.add("WARN", "git/commits",
                  f"only {k} commits on HEAD -- a completed build of this scope "
                  f"should show far more; few large commits read as bulk-generated")

    _, authors = a.run(["git", "log", "--format=%an <%ae>"])
    uniq = sorted(set(x for x in authors.splitlines() if x.strip()))
    if uniq:
        a.add("INFO", "git/authors", "; ".join(uniq[:5]))

    _, bodies = a.run(["git", "log", "--format=%B"])
    trailers = re.findall(r"(?im)^\s*(co-authored-by|generated with|assisted-by).*$",
                          bodies)
    if trailers:
        a.add("WARN", "git/attribution",
              f"{len(trailers)} tool-attribution trailer(s) in commit messages")
    else:
        a.add("PASS", "git/attribution", "no tool-attribution trailers")

    _, status = a.run(["git", "status", "--porcelain"])
    dirty = [l for l in status.splitlines() if l.strip()]
    if dirty:
        a.add("WARN", "git/clean",
              f"{len(dirty)} uncommitted change(s) -- audit reflects the working "
              f"tree, not HEAD")


def check_lint(a: Audit, full: bool) -> None:
    md = a.readme
    claim = claim_for(md, "lint")
    if not full:
        if claim is not None:
            a.add("INFO", "lint", f"README claims '{claim}' -- rerun with --full to verify")
        return

    rc, out = a.run(["make", "lint"], timeout=600)
    warns = len(re.findall(r"%Warning", out))
    errs = len(re.findall(r"%Error", out))
    if rc == 0 and warns == 0 and errs == 0:
        a.add("PASS", "lint", "make lint clean (0 warnings, 0 errors)")
    else:
        a.add("FAIL", "lint",
              f"make lint: {warns} warning(s), {errs} error(s), exit {rc}",
              out.strip()[-600:])

    if claim is not None and NUMERIC.search(claim):
        claimed = int(re.search(r"\d+", claim).group())
        if claimed != warns:
            a.add("FAIL", "lint/claim",
                  f"README claims {claimed} lint warnings, measured {warns}")


def check_unit(a: Audit, full: bool) -> None:
    if not full:
        return
    rc, out = a.run(["make", "unit"], timeout=1800)
    tallies = re.findall(r"TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)\s+SKIP=(\d+)", out)
    if not tallies:
        a.add("WARN" if rc == 0 else "FAIL", "unit",
              f"make unit exit {rc}, no cocotb tally parsed", out.strip()[-400:])
        return
    tot = sum(int(t[0]) for t in tallies)
    passed = sum(int(t[1]) for t in tallies)
    failed = sum(int(t[2]) for t in tallies)
    skipped = sum(int(t[3]) for t in tallies)
    if failed == 0 and rc == 0:
        a.add("PASS", "unit", f"{passed}/{tot} cocotb tests passing")
    else:
        a.add("FAIL", "unit", f"{failed} failing of {tot} cocotb tests")
    if skipped:
        a.add("FAIL", "unit/skips",
              f"{skipped} skipped test(s) -- skipping is how a regression goes "
              f"green without being correct")


def check_arch(a: Audit) -> None:
    """RISCOF architectural compliance."""
    md = a.readme
    claim_i = claim_for(md, "rv32i", "architectural") or claim_for(md, "architectural")
    reports = a.find("**/report.html", "riscof_work*/report.html", "**/riscof_work/report.html")

    if not reports:
        if claim_i:
            a.add("FAIL", "arch/evidence",
                  f"README claims '{claim_i}' but no RISCOF report.html found",
                  "expected riscof_work/report.html")
        else:
            a.add("MISSING", "arch", "no RISCOF report and no README claim")
        return

    rep = a.read(reports[0])
    passed = len(re.findall(r">\s*Passed\s*<", rep, re.I))
    failed = len(re.findall(r">\s*Failed\s*<", rep, re.I))
    total = passed + failed

    if total == 0:
        a.add("WARN", "arch", f"report found but no results parsed: {reports[0]}")
        return

    if failed == 0:
        a.add("PASS", "arch", f"{passed}/{total} architectural tests passing",
              str(reports[0].relative_to(a.root)))
    else:
        a.add("FAIL", "arch", f"{failed} architectural test(s) FAILING ({passed}/{total})",
              str(reports[0].relative_to(a.root)))

    if claim_i and NUMERIC.search(claim_i):
        nums = [int(x) for x in re.findall(r"\d+", claim_i)]
        if nums and nums[0] != passed:
            a.add("FAIL", "arch/claim",
                  f"README claims '{claim_i}' but report shows {passed} passing")


def check_isa_consistency(a: Audit) -> None:
    """The single easiest claim for an interviewer to falsify."""
    md = a.readme
    claims_m = bool(re.search(r"RV32I?M|RV32IM", md))
    claims_rv32im = "rv32im" in md.lower()

    yamls = a.find("**/*isa*.yaml", "**/*isa*.yml", "tests/**/*.yaml")
    declared = set()
    for y in yamls:
        txt = a.read(y)
        for m in re.findall(r"ISA\s*:\s*([A-Za-z0-9_]+)", txt):
            declared.add(m.upper())

    m_tests = a.find("**/riscof_work*/**/mul*", "**/riscof_work*/**/div*",
                     "**/riscof_work*/**/rem*")

    if claims_rv32im:
        if not declared:
            a.add("WARN", "isa/consistency",
                  "README says RV32IM but no RISCOF ISA yaml found to confirm "
                  "the M extension was actually tested")
        elif not any("M" in d.replace("RV32I", "") for d in declared):
            a.add("FAIL", "isa/consistency",
                  f"README claims RV32IM but RISCOF ISA declares {sorted(declared)} "
                  f"-- the M extension was not exercised by the compliance suite")
        elif not m_tests:
            a.add("WARN", "isa/consistency",
                  f"ISA declares {sorted(declared)} but no mul/div/rem test "
                  f"artifacts found in riscof_work")
        else:
            a.add("PASS", "isa/consistency",
                  f"RV32IM claim backed by declared ISA {sorted(declared)} and M tests")
    elif declared:
        a.add("INFO", "isa/consistency", f"RISCOF ISA declared: {sorted(declared)}")


def check_random(a: Audit) -> None:
    md = a.readme
    claim_progs = claim_for(md, "random", "program") or claim_for(md, "programs")
    claim_instr = claim_for(md, "instruction") or claim_for(md, "co-simulated")

    logs = a.find("**/*.rtl.log", "build/**/*.log", "out_*/**/*.S", "**/asm_test/*.S")
    if not logs:
        if claim_progs or claim_instr:
            a.add("FAIL", "random/evidence",
                  f"README claims random-regression numbers "
                  f"({claim_progs or claim_instr}) but no generated programs or "
                  f"RTL logs found on disk")
        else:
            a.add("MISSING", "random", "no random-regression artifacts, no claim")
        return
    a.add("INFO", "random", f"{len(logs)} random-regression artifact(s) on disk")
    if claim_progs:
        a.add("WARN", "random/claim",
              f"README claims '{claim_progs}' -- confirm this came from a log, "
              f"not from the intended iteration count")


def check_coverage(a: Audit) -> None:
    md = a.readme
    claim = claim_for(md, "coverage")
    reports = a.find("**/coverage*.dat", "**/coverage*.json", "**/coverage*.txt",
                     "**/coverage*.xml", "**/*coverage*report*", "**/annotated/**")

    if claim is None:
        a.add("MISSING" if not reports else "INFO", "coverage",
              "no coverage claim in README" +
              (f" ({len(reports)} artifact(s) present)" if reports else ""))
        return

    if not reports:
        a.add("FAIL", "coverage",
              f"README claims coverage '{claim}' but NO coverage report exists "
              f"on disk -- this number is unbacked")
    else:
        a.add("WARN", "coverage",
              f"README claims '{claim}'; artifact(s) found -- verify the number "
              f"matches", str(reports[0].relative_to(a.root)))


def check_formal(a: Audit) -> None:
    md = a.readme
    claim = claim_for(md, "formal")
    passes = a.find("formal/**/PASS", "**/checks/**/PASS")
    fails = a.find("formal/**/FAIL", "**/checks/**/FAIL")
    sby = a.find("formal/**/*.sby", "**/checks/**/*.sby")

    if claim is None:
        if passes:
            a.add("INFO", "formal", f"{len(passes)} passing check(s) but no README claim")
        else:
            a.add("MISSING", "formal",
                  "no formal results and no README claim" +
                  (f" ({len(sby)} .sby task(s) wired but not run)" if sby else ""))
        return

    if not passes:
        a.add("FAIL", "formal",
              f"README claims formal results ('{claim}') but no passing SymbiYosys "
              f"task found -- instrumentation is not verification")
    elif fails:
        a.add("FAIL", "formal", f"{len(fails)} formal check(s) FAILING")
    else:
        a.add("PASS", "formal", f"{len(passes)} formal check(s) passing")

    if claim and not re.search(r"(depth|bound|k\s*=|\bBMC\b)", md, re.I):
        a.add("WARN", "formal/bound",
              "formal results claimed without stating the bound depth -- an "
              "unbounded reading of a bounded proof is the first thing a formal "
              "engineer will question")


def check_doc_drift(a: Audit) -> None:
    """Design document vs RTL: memory sizes are the usual drift point."""
    docs = a.find("docs/microarchitecture.md", "**/microarchitecture.md")
    if not docs:
        a.add("WARN", "docs/drift", "no microarchitecture.md found")
        return
    doc = a.read(docs[0])
    doc_sizes = set(m.upper().replace(" ", "")
                    for m in re.findall(r"(\d+\s*[KMG]B)", doc, re.I))

    rtl_text = ""
    for f in a.find("rtl/**/*.sv", "rtl/**/*.v"):
        rtl_text += a.read(f)
    rtl_sizes = set()
    for m in re.findall(r"(?:MEM_|RAM_)?(?:SIZE|BYTES|DEPTH)\s*=\s*(\d+)", rtl_text, re.I):
        n = int(m)
        if n >= 1024:
            rtl_sizes.add(f"{n // 1024}KB" if n < 1024 * 1024 else f"{n // (1024*1024)}MB")
    for m in re.findall(r"\[\s*(\d+)\s*:\s*0\s*\]\s*mem", rtl_text, re.I):
        pass

    if doc_sizes and rtl_sizes and not (doc_sizes & rtl_sizes):
        a.add("FAIL", "docs/drift",
              f"microarchitecture.md mentions memory size(s) {sorted(doc_sizes)} "
              f"but RTL parameters imply {sorted(rtl_sizes)} -- the design "
              f"document describes a different core than the repo contains")
    elif doc_sizes:
        a.add("INFO", "docs/drift", f"documented memory size(s): {sorted(doc_sizes)}")


def check_fabrication_markers(a: Audit) -> None:
    """The rules from AGENT_BRIEF §2.1, mechanically."""
    skips = []
    for f in a.find("tb/**/*.py", "tests/**/*.py", "**/test_*.py"):
        txt = a.read(f)
        for m in re.finditer(r"(?m)^.*(@\w*\.?skip|pytest\.mark\.skip|xfail|"
                             r"\.skip\s*=\s*True|SKIP\s*=\s*True).*$", txt):
            skips.append(f"{f.relative_to(a.root)}: {m.group().strip()[:90]}")
    if skips:
        a.add("FAIL", "integrity/skipped-tests",
              f"{len(skips)} skip/xfail marker(s) found", "\n".join(skips[:8]))
    else:
        a.add("PASS", "integrity/skipped-tests", "no skip or xfail markers")

    waivers = []
    for f in a.find("Makefile", "**/Makefile", "**/*.mk", "**/*.vlt"):
        for m in re.finditer(r"-Wno-(\w+)", a.read(f)):
            if m.group(1) != "fatal":
                waivers.append(f"{f.relative_to(a.root)}: -Wno-{m.group(1)}")
    inline = []
    for f in a.find("rtl/**/*.sv", "rtl/**/*.v"):
        for m in re.finditer(r"lint_off\s+(\w+)", a.read(f)):
            inline.append(f"{f.relative_to(a.root)}: lint_off {m.group(1)}")

    allowed = {"MULTITOP", "UNUSEDSIGNAL"}
    bad = [w for w in waivers + inline
           if not any(x in w for x in allowed)]
    if bad:
        a.add("WARN", "integrity/lint-waivers",
              f"{len(bad)} lint waiver(s) beyond the permitted MULTITOP",
              "\n".join(bad[:8]))
    else:
        a.add("PASS", "integrity/lint-waivers", "no unauthorised lint waivers")


OVERCLAIMS = [
    (r"zero\s+bubbles?",
     "false in any 5-stage design: load-use costs one cycle by construction"),
    (r"mathematically\s+prov(ed|en)",
     "fault injection is empirical validation, not proof"),
    (r"formally\s+verified(?!.{0,80}(depth|bound))",
     "state the bound depth, or this reads as an unbounded claim"),
    (r"fully\s+verified|completely\s+verified|100%\s+verified",
     "no processor is fully verified; name what is not covered instead"),
    (r"bug[- ]free|no\s+known\s+bugs",
     "unfalsifiable, and invites exactly the question you don't want"),
    (r"production[- ]ready|industry[- ]grade",
     "unearned for a student project and easy to challenge"),
]


def check_overclaims(a: Audit) -> None:
    md = a.readme
    hits = []
    for pat, why in OVERCLAIMS:
        for m in re.finditer(pat, md, re.I):
            line = md[:m.start()].count("\n") + 1
            hits.append(f"README:{line}  '{m.group()[:40]}'  -- {why}")
    if hits:
        a.add("FAIL", "claims/overstated",
              f"{len(hits)} overstated claim(s) in README", "\n".join(hits))
    else:
        a.add("PASS", "claims/overstated", "no overstated language detected")


def check_unbacked_numbers(a: Audit) -> None:
    """Any populated cell in the results table needs a named producer."""
    rows = parse_tables(a.readme)
    populated, placeholder = [], []
    for cells in rows:
        if len(cells) < 2:
            continue
        label, val = cells[0], cells[1]
        if not label or label.lower() in ("metric", "item", "document", "group"):
            continue
        if val.lower().strip("* `") in EMPTY_CELL:
            placeholder.append(label)
        elif NUMERIC.search(val):
            producer = cells[2] if len(cells) > 2 else ""
            populated.append((label, val, producer))

    for label, val, producer in populated:
        if not producer.strip():
            a.add("WARN", "claims/traceability",
                  f"'{label}' = {val} has no named producing command")
    if populated:
        a.add("INFO", "claims/populated",
              f"{len(populated)} populated metric(s); {len(placeholder)} left as "
              f"placeholder")


def check_debug_log(a: Audit) -> None:
    logs = a.find("docs/debug_log.md", "**/debug_log.md")
    if not logs:
        a.add("WARN", "docs/debug-log", "no debug_log.md found")
        return
    txt = a.read(logs[0])
    entries = re.findall(r"(?m)^###\s+(?!Template|YYYY)(.+)$", txt)
    todos = len(re.findall(r"\bTODO\b", txt))
    real = [e for e in entries if "TODO" not in e.upper()]

    # If the README advertises a bug count, that IS a claim and must match.
    m = re.search(r"(\d+)\s+(?:detailed\s+)?(?:bug|debug)\s+(?:log\s+)?entr",
                  a.readme, re.I)
    claimed = int(m.group(1)) if m else None

    if claimed is not None and len(real) < claimed:
        a.add("FAIL", "docs/debug-log",
              f"README claims {claimed} debug entries, found {len(real)} "
              f"complete ({todos} TODO marker(s) remain)")
    elif len(real) >= 5 and todos == 0:
        a.add("PASS", "docs/debug-log", f"{len(real)} completed entries")
    elif real:
        a.add("WARN", "docs/debug-log",
              f"{len(real)} entry heading(s), {todos} TODO marker(s) remaining")
    else:
        a.add("WARN", "docs/debug-log",
              "no completed entries yet (template only)")


def check_reproducibility(a: Audit) -> None:
    mk = a.find("Makefile")
    if not mk:
        a.add("WARN", "repro/makefile", "no top-level Makefile")
        return
    txt = a.read(mk[0])
    targets = set(re.findall(r"(?m)^([a-zA-Z][\w-]*)\s*:", txt))
    expected = {"lint", "unit", "arch", "random", "formal", "regress"}
    missing = expected - targets
    if missing:
        a.add("WARN", "repro/targets",
              f"README-referenced target(s) absent from Makefile: {sorted(missing)}")
    else:
        a.add("PASS", "repro/targets", "all documented make targets exist")


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help="repo root (default: auto-detect)")
    ap.add_argument("--full", action="store_true",
                    help="also run make lint / make unit (slower)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    a = Audit(root=root)

    readme = None
    for cand in ("README.md", "readme.md", "Readme.md"):
        if (root / cand).exists():
            readme = root / cand
            break
    a.readme = a.read(readme) if readme else ""
    if not readme:
        a.add("WARN", "readme", "no README.md found -- claim checks will be empty")

    check_git(a)
    check_lint(a, args.full)
    check_unit(a, args.full)
    check_arch(a)
    check_isa_consistency(a)
    check_random(a)
    check_coverage(a)
    check_formal(a)
    check_doc_drift(a)
    check_fabrication_markers(a)
    check_overclaims(a)
    check_unbacked_numbers(a)
    check_debug_log(a)
    check_reproducibility(a)

    if args.json:
        print(json.dumps([r.__dict__ for r in a.results], indent=2))
    else:
        print()
        print(c("  CLAIM AUDIT", "1"), f" {root}")
        print("  " + "-" * 74)
        for r in a.results:
            style, label = VERDICT_STYLE[r.verdict]
            print(f"  {c(label, style)}  {c(r.check, '1')}")
            for line in r.detail.split("\n"):
                print(f"           {line}")
            if r.evidence:
                for line in r.evidence.split("\n")[:8]:
                    print(f"           {c('| ' + line, '90')}")
        print("  " + "-" * 74)

    counts = {k: sum(1 for r in a.results if r.verdict == k) for k in VERDICT_STYLE}
    if not args.json:
        summary = "  ".join(
            f"{c(k, VERDICT_STYLE[k][0])} {v}" for k, v in counts.items() if v
        )
        print(f"  {summary}")
        if counts["FAIL"]:
            print()
            print(c("  Every FAIL is a claim your repository cannot currently "
                    "substantiate.", "31;1"))
            print("  Fix the claim or produce the evidence -- do not leave it as is.")
        print()

    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
