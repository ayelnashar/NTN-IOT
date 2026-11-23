"""Recompute every result of the paper (about 2 hours, about 3 GB of memory).

Run from the repository root:
    python3 scripts/run_batch.py
Stages are checkpointed in out/ckpt, so an interrupted run resumes.
Results go to out/ (results.json, CSV tables, figures); the frozen paper
results are in frozen/ for comparison.
"""
import os
import sys
import time

sys.path.insert(0, os.getcwd())
from ntnsim import figures, report  # noqa: E402

report.CKPT_DIR = "out/ckpt"
t0 = time.time()
report.run_all(out_dir="out", cache_dir="out/cache", n_mc=3000,
               log=lambda *a: print(*a, "%.0f s" % (time.time() - t0), flush=True))
print(figures.make_all("out/results.json", "out/figs"))
print("done in %.0f s" % (time.time() - t0))
