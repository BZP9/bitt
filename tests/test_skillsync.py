"""Release and dev skills (owner 11-06): a release install syncs its own packaged SKILL.md on every command; a dev tree never syncs
on its own (it would overwrite the release's skills with work in progress)."""
import tomllib
from pathlib import Path

from bitt import skills

ROOT = Path(__file__).resolve().parents[1]


def test_a_dev_tree_does_not_sync_and_a_release_does(tmp_path, monkeypatch):
    monkeypatch.delenv("BITT_NO_SKILL_SYNC", raising=False)
    monkeypatch.setenv("BITT_SKILLS_DEST", str(tmp_path / "skills"))
    monkeypatch.setattr(skills, "RELEASE", tmp_path / "pkg" / "SKILL.md")         # a dev tree: no SKILL.md in the package
    assert skills.auto_sync() == [] and not (tmp_path / "skills").exists()
    (tmp_path / "pkg").mkdir()
    skills.RELEASE.write_text("## skill: bitt\n**Trigger**: release text\n")
    assert skills.auto_sync() == ["bitt"]
    assert "release text" in (tmp_path / "skills" / "bitt" / "SKILL.md").read_text()


def test_the_wheel_carries_skill_md_and_the_store_format():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert cfg["force-include"]["SKILL.md"] == "bitt/SKILL.md"
    assert (ROOT / "src/bitt/sql/format.json").exists() and (ROOT / "src/bitt/sql/migrations").is_dir()
