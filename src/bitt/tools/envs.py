"""Where jobs run (Exec): named environments, each with an adapter that knows how to get a job running there.

The config lives outside the repo: $BITT_ENVS or ~/.config/bitt/envs.yaml. A missing file means one env, `local`.

  local:                       # this machine
    type: local
    max_sensitivity: company   # the most sensitive data that may be sent here (public < internal < company < personal)
    python: python3            # how to run Python there (e.g. "uv run --with torch python")
  gpubox:
    type: ssh
    host: <ssh destination>    # anything `ssh` accepts (an alias from ~/.ssh/config, user@host)
    workdir: /path/on/host/bitt-jobs
    python: python3
    tasks: ~/bitt-tasks        # where task folders live on the host (a model is written there; default ~/bitt-tasks)
    gpus: "1"                  # CUDA_VISIBLE_DEVICES for the job (optional)
    mps_guard: true            # refuse to launch while a shared CUDA MPS server runs on the host
    max_sensitivity: company

Every env runs the same job directory (the job protocol, src/bitt/tools/bitt_run.py; written by write_module_job):
  job.json         what to do: {kind, scope, params}
  module.py        the module's script (from the blob store, hash-checked)
  bitt_run.py      the shim that feeds module.py its input and writes what it returns (tools/bitt_run.py)
  input/rows.jsonl the rows it reads
  run.sh           written by bitt: fingerprint → shim → `status` (running / done / failed <code>), output in log.txt
  fingerprint.json what the job really ran on (GPU, driver, CUDA, Python, packages), written before the script starts
  output/          what the module returns (rows.jsonl, or variables.json for a table check)

A model is never in the job folder or bitt's store: a full train writes it into the folder bitt assigns in the env's task folders
(`<tasks>/<task>/artifacts/<cycle>/<line>/<run>/`, job.json `model_dir`); the shim hashes its files there (output/manifest.json), and
only that list comes back. The local env's task folders: $BITT_TASKS, default ~/bitt-tasks.
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from ..errors import Refused

SENSITIVITY = ["public", "internal", "company", "personal"]

FINGERPRINT = r'''import json, platform, subprocess, sys
out = {"python": sys.version.split()[0], "platform": platform.platform()}
for m in ("torch", "transformers", "peft", "trl", "accelerate", "datasets"):
    try:
        mod = __import__(m)
        out[m] = getattr(mod, "__version__", "?")
        if m == "torch":
            out["cuda"] = getattr(mod.version, "cuda", None)
            out["cuda_available"] = mod.cuda.is_available()
    except Exception:
        pass
try:
    q = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_mode", "--format=csv,noheader"],
                       capture_output=True, text=True, timeout=20)
    out["gpus"] = [dict(zip(["name", "memory", "driver", "compute_mode"], [x.strip() for x in line.split(",")]))
                   for line in q.stdout.splitlines() if line.strip()]
except Exception:
    out["gpus"] = []
print(json.dumps(out))
'''

MANIFEST = r'''import hashlib, json, os, sys
root = os.path.expanduser(sys.argv[1])
out = []
for d, _, fs in sorted(os.walk(root)):
    for f in sorted(fs):
        p = os.path.join(d, f)
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        out.append({"path": os.path.relpath(p, root), "size": os.path.getsize(p), "sha256": h.hexdigest()})
print(json.dumps(sorted(out, key=lambda x: x["path"])))
'''


def manifest_of(root):
    """[{path, size, sha256}] of every file under root (the same as MANIFEST, which runs on a host)."""
    import hashlib
    out = []
    for p in sorted(x for x in Path(root).rglob("*") if x.is_file()):
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        out.append({"path": str(p.relative_to(root)), "size": p.stat().st_size, "sha256": h.hexdigest()})
    return sorted(out, key=lambda x: x["path"])


RUN_SH = """#!/usr/bin/env bash
cd "$(dirname "$0")"
echo running > status
{env}{python} fingerprint.py > fingerprint.json 2>> log.txt
{env}{python} {script} job.json >> log.txt 2>&1
code=$?
if [ $code -eq 0 ]; then echo done > status; else echo "failed $code" > status; fi
"""


def config():
    path = Path(os.environ.get("BITT_ENVS") or Path.home() / ".config" / "bitt" / "envs.yaml")
    envs = (yaml.safe_load(path.read_text()) if path.exists() else None) or {}
    envs.setdefault("local", {"type": "local", "max_sensitivity": "company", "python": sys.executable})   # this machine, bitt's Python
    return envs, path


def get(name):
    envs, path = config()
    if name not in envs:
        raise Refused(f"no env {name!r} (envs: {sorted(envs)}); add it to {path}")
    c = {**envs[name], "name": name}
    if c.get("type") == "local":
        return LocalEnv(c)
    if c.get("type") == "ssh":
        return SSHEnv(c)
    raise Refused(f"env {name!r}: type {c.get('type')!r} is not local or ssh")


def check_sensitivity(env, sensitivity):
    top = env.c.get("max_sensitivity", "internal")
    if SENSITIVITY.index(sensitivity) > SENSITIVITY.index(top):
        raise Refused(f"env {env.name!r} takes data up to {top!r}; this dataset is {sensitivity!r} (set max_sensitivity in the env config "
                      "only if that data may really go there)")


def write_runner(job_dir, script, python, gpus):
    (job_dir / "fingerprint.py").write_text(FINGERPRINT)
    env = f"CUDA_VISIBLE_DEVICES={shlex.quote(str(gpus))} " if gpus is not None else ""
    (job_dir / "run.sh").write_text(RUN_SH.format(env=env, python=python, script=script))


def write_module_job(job_dir, job, script, rows, python, gpus=None):
    """A module's job directory (src/bitt/tools/bitt_run.py): job.json, module.py, bitt_run.py (the shim), input/rows.jsonl, output/."""
    (job_dir / "input").mkdir(parents=True, exist_ok=True)
    (job_dir / "output").mkdir(exist_ok=True)
    (job_dir / "job.json").write_text(json.dumps(job, indent=1, ensure_ascii=False))
    (job_dir / "module.py").write_bytes(script)
    (job_dir / "bitt_run.py").write_bytes((Path(__file__).parent / "bitt_run.py").read_bytes())
    (job_dir / "input" / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows))
    write_runner(job_dir, "bitt_run.py", python, gpus)


class LocalEnv:
    """Runs a job on this machine, in its own process group, under $BITT_JOBS (default ~/.cache/bitt/jobs)."""

    def __init__(self, c):
        self.c, self.name = c, c["name"]
        self.root = Path(os.environ.get("BITT_JOBS") or Path.home() / ".cache" / "bitt" / "jobs")

    def local_dir(self, job):
        return self.root / job

    def python(self):
        return self.c.get("python", "python3")

    def guard(self):
        return None

    def launch(self, job):
        subprocess.Popen(["bash", "run.sh"], cwd=self.local_dir(job), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)

    def status(self, job):
        p = self.local_dir(job) / "status"
        return p.read_text().strip() if p.exists() else "staged"

    def fetch(self, job):
        return self.local_dir(job)

    def drop_job(self, job):
        """Delete a job's folder here (scratch once the job is landed: the record holds what it made; models live elsewhere)."""
        import shutil
        shutil.rmtree(self.local_dir(job), ignore_errors=True)

    # ---- the env's task folders (where models live): paths are as the env sees them, `~/` meaning the home there
    def tasks_root(self):
        """`tasks:` in the env's config ($VARS expanded), else $BITT_TASKS, else ~/bitt-tasks."""
        if self.c.get("tasks"):
            return str(Path(os.path.expandvars(self.c["tasks"])).expanduser())
        return str(Path(os.environ.get("BITT_TASKS") or Path.home() / "bitt-tasks").expanduser())

    def has(self, path):
        """Is there a folder at path in this env?"""
        return Path(path).expanduser().is_dir()

    def manifest(self, path):
        """[{path, size, sha256}] of every file under path, hashed where it sits."""
        return manifest_of(Path(path).expanduser())

    def remove(self, path):
        import shutil
        shutil.rmtree(Path(path).expanduser())

    def receive(self, src, path):
        """Copy a local folder src into this env at path (bringing a model here)."""
        import shutil
        dest = Path(path).expanduser()
        if dest.exists():
            raise Refused(f"env {self.name!r}: {path} already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, symlinks=False)

    def send(self, path, dest):
        """Copy this env's folder at path to a local folder dest."""
        import shutil
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(Path(path).expanduser(), dest)


class SSHEnv(LocalEnv):
    """Runs a job on another machine over ssh: rsync the job directory there, start run.sh with nohup, poll `status`, rsync it back.
    `host: ""` runs the same commands on this machine (tests use it); the job then lives in `workdir`."""

    def __init__(self, c):
        super().__init__(c)
        if "workdir" not in c:
            raise Refused(f"env {self.name!r}: an ssh env needs `workdir` (where jobs live on the host)")
        self.host = c.get("host", "")

    def sh(self, cmd, timeout=60):
        argv = ["ssh", "-o", "BatchMode=yes", self.host, cmd] if self.host else ["bash", "-c", cmd]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr

    def remote(self, job):
        return f"{self.c['workdir'].rstrip('/')}/{job}"

    def at(self, p):
        return f"{self.host}:{p}" if self.host else p

    def guard(self):
        """The host-side checks that must pass before a launch (quirks that can harm other users of the machine)."""
        if self.c.get("mps_guard"):
            code, out, _ = self.sh("echo get_server_list | nvidia-cuda-mps-control 2>/dev/null")
            if code == 0 and out.strip():
                return (f"env {self.name!r}: a shared CUDA MPS server is running on the host (servers: {out.split()[:3]}); a crashing "
                        "job can fault it for every user. Use GPUs outside MPS (`gpus:`) and turn mps_guard off only for those")
        return None

    def launch(self, job):
        code, _, err = self.sh(f"mkdir -p {shlex.quote(self.remote(job))}")
        if code:
            raise Refused(f"env {self.name!r}: cannot reach the host ({err.strip()[:200]})")
        r = subprocess.run(["rsync", "-a", f"{self.local_dir(job)}/", self.at(self.remote(job)) + "/"], capture_output=True, text=True)
        if r.returncode:
            raise Refused(f"env {self.name!r}: copying the job failed ({r.stderr.strip()[:200]})")
        detach = "S=$(command -v setsid || true); "            # setsid where it exists (Linux), plain nohup elsewhere
        self.sh(f"cd {shlex.quote(self.remote(job))} && {detach}(nohup $S bash run.sh < /dev/null > /dev/null 2>&1 &)")

    def status(self, job):
        code, out, _ = self.sh(f"cat {shlex.quote(self.remote(job))}/status 2>/dev/null || echo staged")
        return out.strip() if code == 0 else "unreachable"

    def fetch(self, job):
        subprocess.run(["rsync", "-a", self.at(self.remote(job)) + "/", f"{self.local_dir(job)}/"], capture_output=True, text=True)
        return self.local_dir(job)

    def job_dirs(self):
        """The job folders on the host (names under workdir)."""
        code, out, _ = self.sh(f"ls -1 {shlex.quote(self.c['workdir'])} 2>/dev/null || true")
        if code:
            raise Refused(f"env {self.name!r}: cannot reach the host")
        return set(out.split())

    def drop_job(self, job):
        code, _, err = self.sh(f"rm -rf {shlex.quote(self.remote(job))}")
        if code:
            raise Refused(f"env {self.name!r}: removing job {job[:12]} on the host failed ({err.strip()[:200]})")
        super().drop_job(job)

    def tasks_root(self):
        return self.c.get("tasks") or "~/bitt-tasks"

    def q(self, path):
        """A path for the host's shell: `~/x` → "$HOME"/x (quoted, still expanded there)."""
        return '"$HOME"/' + shlex.quote(path[2:]) if path.startswith("~/") else shlex.quote(path)

    def r(self, path):
        """A path for rsync on the host side (rsync expands a leading ~ itself over ssh; local-shell mode: expand here)."""
        return self.at(path if self.host else str(Path(path).expanduser()))

    def has(self, path):
        code, out, _ = self.sh(f"test -d {self.q(path)} && echo yes || echo no")
        if code:
            raise Refused(f"env {self.name!r}: cannot reach the host")
        return out.strip() == "yes"

    def manifest(self, path):
        code, out, err = self.sh(f"{self.python()} - {self.q(path)} <<'EOF'\n{MANIFEST}\nEOF", timeout=3600)
        if code:
            raise Refused(f"env {self.name!r}: hashing {path} failed ({err.strip()[:200]})")
        return json.loads(out)

    def remove(self, path):
        code, _, err = self.sh(f"rm -rf {self.q(path)}")
        if code:
            raise Refused(f"env {self.name!r}: removing {path} failed ({err.strip()[:200]})")

    def receive(self, src, path):
        if self.has(path):
            raise Refused(f"env {self.name!r}: {path} already exists")
        self.sh(f"mkdir -p {self.q(path)}")
        r = subprocess.run(["rsync", "-a", f"{src}/", self.r(path) + "/"], capture_output=True, text=True)
        if r.returncode:
            raise Refused(f"env {self.name!r}: copying to {path} failed ({r.stderr.strip()[:200]})")

    def send(self, path, dest):
        dest.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["rsync", "-a", self.r(path) + "/", f"{dest}/"], capture_output=True, text=True)
        if r.returncode:
            raise Refused(f"env {self.name!r}: copying {path} back failed ({r.stderr.strip()[:200]})")
