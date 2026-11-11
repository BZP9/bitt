"""A task's working folder (scenarios E12, owner 11-10): bitt makes it when the task is made, under the local env's task folders
($BITT_TASKS, default ~/bitt-tasks), and puts its own note for agents in it, so an agent's global rules never need to know bitt.

  <task>/
    AGENTS.md     how to work here (bitt's note; CLAUDE.md imports it)
    modules/      the task's scripts (in git: a module's version is its commit)
    datasets/     files to load, by cycle (datasets/c<N>/); bitt keeps the rows, these files can be pruned
    artifacts/    what runs write, by cycle: a train's model lands in artifacts/c<N>/<line>/<run>/ (bitt assigns it)

A model's folder is bitt's: written once by a train, hashed where it sits, deleted only by `bitt artifact rm` (a person's).
"""
import subprocess
from pathlib import Path

from .tools import envs

NOTE = """# {task}: a bitt task folder

bitt made this folder for the task `{task}` ("{problem}"). Work here; use the bitt skill for every step (`bitt help`).

- `modules/`: your scripts. Commit them: a module's version is its git commit, so never name files v2, v3. Add one with
  `bitt module add modules/<file>.py`.
- `datasets/c<N>/`: files you load in cycle N (`bitt data load <file>`). bitt keeps the rows; these files can be deleted later.
- `artifacts/c<N>/`: what runs write in cycle N. A train script saves its model into `job.output` (the folder bitt hands it) and
  nowhere else; bitt records the files there by hash. Never move, rename or delete anything under `artifacts/`: the record
  points at it. Removing a model is the person's call (`bitt artifact rm`); if the disk is filling, `bitt jobs clean --yes`
  frees finished jobs' folders, and say in your report what else could go.
- Scratch goes in `_output/` (always deletable); pages for the person in `_report/`.
"""

GITIGNORE = "artifacts/\ndatasets/\n_output/\n_report/\n"


def make(task, problem):
    """Make the task's folder (once: an existing folder keeps what it has); returns its path."""
    root = Path(envs.get("local").tasks_root()) / task
    for sub in ("modules", "datasets", "artifacts"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    for name, text in (("AGENTS.md", NOTE.format(task=task, problem=problem)), ("CLAUDE.md", "@AGENTS.md\n"),
                       (".gitignore", GITIGNORE)):
        if not (root / name).exists():
            (root / name).write_text(text)
    inside = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
    if inside.returncode:                                  # not in a repo yet: modules/ is versioned by git, so make one
        subprocess.run(["git", "init", "-q", str(root)], capture_output=True)
    return root
