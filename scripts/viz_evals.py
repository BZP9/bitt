"""The panel (bitt.panel) of every agent eval's store, as files: _report/viz/evals/<folder>/index.html (home → task →
cycle), then the hub. Read only.

  uv run python scripts/viz_evals.py [<eval folder> …]      (default: every folder under ~/.bitt/evals that has a dsn.txt)

Read only: a store is the one the eval judged, on the throwaway cluster only (the live work DSN is refused). A store whose database
was dropped, or that an older bitt made, is skipped and said so. evals/run_agent_eval.py runs this on each run's folder.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_report" / "viz" / "evals"


def one(d):
    sys.path.insert(0, str(ROOT / "conformance"))
    sys.path.insert(0, str(ROOT / "scripts"))
    from backend import throwaway_problem
    sys.path.insert(0, str(ROOT / "src"))
    from bitt.panel import data as panel_data
    from bitt.panel import view as panel_view
    from bitt.panel.serve import read_only
    dsn = (d / "dsn.txt").read_text().strip()
    if why := throwaway_problem(dsn):
        return f"refused {dsn}: {why}"
    from bitt.kernel import Kernel
    from bitt.record.postgres import PostgresRecord
    from bitt.tools import packages
    os.environ.update({"BITT_BLOBS": str(d / "blobs"), "BITT_JOBS": str(d / "jobs")})   # the eval's own, for blob reads
    try:
        k = Kernel(PostgresRecord(read_only(dsn), init=False), packages=packages())
        S = panel_data.model(k)
    except Exception as e:                                       # the database is gone, or an older bitt made it
        return f"skipped: {type(e).__name__}: {str(e).splitlines()[0][:160]}"
    panel_view.L = panel_view.Links()
    return str(panel_view.write_static(S, OUT / d.name).relative_to(ROOT))


def main():
    dirs = [Path(x).resolve() for x in sys.argv[1:]] or sorted(p.parent for p in (Path.home() / ".bitt" / "evals").glob("*/dsn.txt"))
    for d in dirs:
        # each store in its own process: a kernel holds its record's connection and specs
        r = subprocess.run([sys.executable, __file__, "--one", str(d)], capture_output=True, text=True, cwd=ROOT)
        print(f"{d.name}: {(r.stdout.strip() or r.stderr.strip().splitlines()[-1] if (r.stdout or r.stderr) else 'no output')}")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_reports.py")], check=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--one"]:
        print(one(Path(sys.argv[2])))
    else:
        main()
