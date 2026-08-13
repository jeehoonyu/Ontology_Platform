#!/bin/sh
# Reproduce a Tier B measurement from a clean environment.
#
# Condition D5 of GOAL_REPRODUCIBILITY_2026-08-13. This is the path a reader who
# did not author the evidence can follow to check it, and it is the same path D4
# used to reproduce the pipeline-scale gate on 2026-08-13.
#
# It defaults to `pipeline_scale` because that is the only Tier B gate needing no
# external infrastructure: it drives DuckDB over a throwaway SQLite database. The
# others need PostgreSQL, a broker, an object store or an OCI sandbox, and are
# declared with what they need in oms/check_registry.py.
#
#   ./scripts/reproduce-measurement.sh [workdir]
#
# What it does, and why each step is there:
#
#   1. clone       a fresh clone, so nothing in your working tree can leak in
#   2. venv        an isolated interpreter, because this project's own evidence
#                  was produced in a shared global one carrying 101 packages
#   3. lock        install from requirements.lock, not requirements.txt: pinning
#                  the 17 declarations still let 11 of 42 transitive packages
#                  resolve differently, and the result could not import the suite
#   4. digest      confirm the rebuilt closure matches what the lock describes
#   5. run         emit the gate inside the clone
#   6. changed?    confirm the evidence file was actually rewritten -- a run that
#                  crashes leaves the committed file untouched, and comparing it
#                  to itself agrees perfectly. That mistake was made on 2026-08-13
#                  and reported as a success before it was caught.
#   7. compare     structural measurements should match exactly; timings will not

set -e
source_repo=$(cd "$(dirname "$0")/.." && pwd)
work=${1:-$(mktemp -d)}
clone="$work/clone"
venv="$work/venv"
gate=docs/tier-b-pipeline-scale-evidence.json

echo "source     $source_repo"
echo "workdir    $work"
echo

echo "[1/7] cloning"
rm -rf "$clone"
git clone --quiet "$source_repo" "$clone"
( cd "$clone" && git log --oneline -1 )

echo "[2/7] creating an isolated interpreter"
rm -rf "$venv"
python -m venv "$venv"
if [ -x "$venv/bin/python" ]; then py="$venv/bin/python"; else py="$venv/Scripts/python.exe"; fi

echo "[3/7] installing from the lock"
"$py" -m pip install --quiet --upgrade pip
"$py" -m pip install --quiet -r "$clone/oms/requirements.lock"

echo "[4/7] closure digest"
"$py" "$clone/oms/dependency_provenance.py" | grep -E "closure|digest"

echo "[5/7] running the gate"
( cd "$clone" && PIPELINE_SCALE_PROFILE=reference "$py" oms/benchmark_pipeline_scale.py >"$work/run.log" 2>&1 ) || {
    echo "  the gate did not complete; last lines:"; tail -20 "$work/run.log"; exit 1; }
tail -1 "$work/run.log"

echo "[6/7] did the evidence file actually change?"
if ( cd "$clone" && git diff --quiet -- "$gate" ); then
    echo "  NO. The gate did not rewrite $gate, so there is nothing to compare."
    echo "  Comparing the committed file to itself would agree perfectly and mean nothing."
    exit 1
fi
echo "  yes, it was rewritten"

echo "[7/7] recorded against reproduced"
"$py" - "$source_repo/$gate" "$clone/$gate" <<'PY'
import json, sys
recorded = json.load(open(sys.argv[1], encoding="utf-8"))
reproduced = json.load(open(sys.argv[2], encoding="utf-8"))
print(f"  verdict  recorded {recorded['status']}  reproduced {reproduced['status']}")
exact = drifted = 0
for key in sorted(recorded["measurements"]):
    was, now = recorded["measurements"][key], reproduced["measurements"].get(key)
    if isinstance(was, bool) or not isinstance(was, (int, float)):
        same = was == now
        exact += same
        drifted += not same
        continue
    if was == now:
        exact += 1
        continue
    drifted += 1
    change = f"{(now - was) / was * 100:+.1f}%" if was else "n/a"
    print(f"  {key:<34}{was:>13}{now:>13}   {change}")
print(f"\n  {exact} measurements reproduced exactly, {drifted} drifted.")
print("  Structure is expected to match to the digit; timings are not -- deliver_ms")
print("  moved 33% on the same machine with a byte-identical closure on 2026-08-13.")
if recorded["status"] != reproduced["status"]:
    print("\n  VERDICTS DISAGREE. That is a finding, not noise.")
    raise SystemExit(1)
PY
echo
echo "done. workdir kept at $work"
