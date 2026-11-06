"""Sync SKILL.md's blocks to ~/.claude/skills now (every `bitt` command also does it). Run: uv run python scripts/sync_skills.py"""
from bitt import skills

if __name__ == "__main__":
    names = skills.sync(quiet=False)
    print(f"[sync_skills] {len(names)} changed" + (f": {', '.join(names)}" if names else " (all up to date)"))
