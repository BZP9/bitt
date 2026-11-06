"""Skills live in this repo (SKILL.md, one `## skill: <name>` block each), written to ~/.claude/skills/<name>/SKILL.md (and
~/.config/opencode/skills/<name>/SKILL.md when opencode is installed). Never edit the installed copies.

Release and dev (owner 11-06): a release install (`uv tool install git+…/bitt@<tag>`) carries its SKILL.md inside the package, and
every `bitt` command of it syncs that copy (`auto_sync`), so the installed skills are the release's. A dev tree (`uv run bitt` in
this repo) never syncs on its own: `uv run python scripts/sync_skills.py` writes the dev skills on purpose, and the eval runner
does it for an eval, then puts the release's back.
BITT_NO_SKILL_SYNC=1 turns syncing off (the test suite sets it); BITT_SKILLS_DEST names the one destination instead."""
import os
import re
from pathlib import Path

RELEASE = Path(__file__).resolve().parent / "SKILL.md"          # in the wheel only (pyproject force-include)
SOURCE = Path(__file__).resolve().parents[2] / "SKILL.md"       # the repo's, in a dev tree


def auto_sync():
    """What every `bitt` command does: sync the release's skills; nothing from a dev tree."""
    return sync(source=RELEASE) if RELEASE.exists() else []


def blocks(text):
    for block in re.split(r"^(?=## )", text, flags=re.MULTILINE):
        m = re.match(r"^## skill: (.+)", block)
        if m:
            name = m.group(1).strip()
            trigger = re.search(r"^\*\*Trigger\*\*: (.+)", block, re.MULTILINE)
            yield name, f"---\nname: {name}\ndescription: {trigger.group(1).strip() if trigger else name}\n---\n\n{block.rstrip()}\n"


def sync(source=SOURCE, dest=None, quiet=True):
    """Write every skill block whose installed copy differs, and remove an installed bitt skill whose block is gone (only one this sync
    wrote: its file is exactly a generated block, nothing else in its folder). Returns the names written, and `-<name>` per removal.
    A checkout without SKILL.md does nothing."""
    if os.environ.get("BITT_NO_SKILL_SYNC") or not source.exists():
        return []
    dests = [Path(dest or os.environ.get("BITT_SKILLS_DEST"))] if (dest or os.environ.get("BITT_SKILLS_DEST")) else default_dests()
    written = []
    have = dict(blocks(source.read_text()))
    for d in dests:
        for name, text in have.items():
            out = d / name / "SKILL.md"
            if not out.exists() or out.read_text() != text:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text)
                written.append(name)
        for old in sorted(d.glob("bitt*/SKILL.md")) if d.is_dir() else []:
            name = old.parent.name
            if name not in have and generated(old, name) and [x.name for x in old.parent.iterdir()] == ["SKILL.md"]:
                old.unlink()
                old.parent.rmdir()
                written.append(f"-{name}")
        if written and not quiet:
            print(f"bitt: synced skills {', '.join(sorted(set(written)))} → {d}")
    return sorted(set(written))


def generated(path, name):
    """A file this sync wrote: the front matter and heading `blocks` gives every block."""
    text = path.read_text()
    return text.startswith(f"---\nname: {name}\ndescription: ") and f"\n## skill: {name}\n" in text


def default_dests():
    """Claude Code's skills; opencode's too when it is installed (its config directory exists)."""
    home = Path.home()
    return [home / ".claude" / "skills"] + ([home / ".config" / "opencode" / "skills"] if (home / ".config" / "opencode").is_dir() else [])
