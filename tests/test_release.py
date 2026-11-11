"""A release works installed, outside this checkout (v2.0.2 shipped without its cards: `bitt init` failed on spec/cards/module.yaml).
Builds the wheel, installs it in a fresh venv away from the repo, and runs it on a throwaway store."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_the_built_release_runs_outside_the_repo(pg_dsn, tmp_path):
    if not shutil.which("uv"):
        pytest.skip("needs uv")
    subprocess.run(["uv", "build", "-q", "--wheel", "-o", str(tmp_path / "dist")], cwd=ROOT, check=True)
    (wheel,) = (tmp_path / "dist").glob("bitt-*.whl")
    subprocess.run(["uv", "venv", "-q", str(tmp_path / "venv")], cwd=tmp_path, check=True)
    py = tmp_path / "venv" / "bin" / "python"
    subprocess.run(["uv", "pip", "install", "-q", "--python", str(py), str(wheel)], cwd=tmp_path, check=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BITT_", "VIRTUAL_ENV", "PYTHON"))} | {
        "BITT_SKILLS_DEST": str(tmp_path / "skills"), "HOME": str(tmp_path)}
    run = lambda *a: subprocess.run([str(tmp_path / "venv" / "bin" / "bitt"), "--dsn", pg_dsn, *a], cwd=tmp_path, env=env,  # noqa: E731
                                    capture_output=True, text=True)
    r = run("init")
    assert r.returncode == 0 and r.stdout.startswith("ok: 0 nodes"), r.stderr[-800:]
    r = run("tasks")
    assert r.returncode == 0, r.stderr[-800:]
    assert (tmp_path / "skills" / "bitt" / "SKILL.md").exists(), "a release syncs its own skills"
    site = next((tmp_path / "venv" / "lib").glob("python*/site-packages/bitt"))
    assert (site / "cards" / "module.yaml").exists() and (site / "SKILL.md").exists()
