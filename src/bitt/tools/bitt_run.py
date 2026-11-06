"""bitt's runner shim: copied into every module job folder and run there as `python bitt_run.py job.json`.

Standalone (standard library only): it loads the module (module.py), calls its function on the job's input and writes what it returns
to output/. It checks nothing: bitt checks the output against the module's contract after the job.

  a row module            fn(*the row's values by role, **params) per input row → a value (one column) or a dict (its fields):
                          output/rows.jsonl, each with bitt_in (the input's index) and bitt_part; a row that raises is
                          {bitt_in, bitt_error} (the others run)
  a connector (generate)  fn(row["messages"], **params) per row → the reply's text: output/rows.jsonl {bitt_in, raw_text}
  a table derive          fn(rows, **params) → rows (output/rows.jsonl), or a select → [(index, split)] (output/select.json);
                          named inputs: fn(rows, <role rows>…, **params), each role's rows in input/<role>.jsonl
  an aggregate            fn(rows, **params) → one row (a dict): output/rows.jsonl
  a train                 fn(job, **params): job.input {split: [rows]}, job.output (the model folder), job.report(**values)
  a load                  fn(data, **params) with the file's bytes → rows: output/rows.jsonl
"""
import importlib.util
import json
import sys
import traceback
from pathlib import Path


def main(job_path):
    job = json.loads(Path(job_path).read_text())
    spec = importlib.util.spec_from_file_location("module", "module.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    fn, params = getattr(m, job["fn"]), job.get("params") or {}
    src = Path("input") / "rows.jsonl"
    rows = [json.loads(x) for x in src.read_text().splitlines() if x.strip()] if src.exists() else []
    out = Path("output")
    out.mkdir(exist_ok=True)
    kind, scope = job["kind"], job["scope"]
    if kind == "train":
        fn(TrainJob(job, rows), **params)
        return
    if kind == "load":
        write_rows(out, fn((Path("input") / "file").read_bytes(), **params))
        return
    if scope == "table":
        others = [[json.loads(x) for x in (Path("input") / f"{role}.jsonl").read_text().splitlines() if x.strip()]
                  for role in job.get("inputs") or []]                 # named inputs (docs/v2/inputs.md J3), in the signature's order
        got = fn(rows, *others, **params)
        if job.get("returns") == "row":                              # an aggregate: exactly one row
            if not isinstance(got, dict):
                raise TypeError(f"an aggregate returns one row (a dict), not {type(got).__name__}")
            write_rows(out, [got])
        elif job.get("writes") == "selection":
            (out / "select.json").write_text(json.dumps([list(p) for p in got]))
        else:
            write_rows(out, got)
        return
    with open(out / "rows.jsonl", "w") as f:
        for i, r in enumerate(rows):
            try:
                if job.get("connector"):
                    res = {"raw_text": fn(r["messages"], **params)}
                else:
                    v = fn(*[r.get(c) for c in job["reads"]], **params)
                    res = v if job.get("returns") == "fields" else {next(iter(job["writes"])): v}
            except Exception as x:                                   # noqa: BLE001 — one row's failure is that row's, not the job's
                f.write(json.dumps({"bitt_in": i, "bitt_error": f"{type(x).__name__}: {x}",
                                    "bitt_trace": traceback.format_exc()[-800:]}) + "\n")
                continue
            for p, o in enumerate(res if isinstance(res, list) else [res]):
                f.write(json.dumps({"bitt_in": i, "bitt_part": p, **o}, ensure_ascii=False, default=str) + "\n")


def write_rows(out, rows):
    with open(out / "rows.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


class TrainJob:
    """What a train module gets: input {split: [rows]}, output (the folder to write the model into), report(**values) (a line of
    reported.jsonl: a loss curve, the script's own scores)."""

    def __init__(self, job, rows):
        self.input = {}
        for r in rows:
            self.input.setdefault(r.pop("bitt_split", None) or "train", []).append(r)
        self.output = Path("output") / "model"
        self.output.mkdir(parents=True, exist_ok=True)

    def report(self, **values):
        with open("reported.jsonl", "a") as f:
            f.write(json.dumps(values, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
