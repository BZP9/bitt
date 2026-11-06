"""Write this dev tree's skills (SKILL.md) to ~/.claude/skills now: a release's own `bitt` puts its skills back on its next command
(`bitt --help` will do). Run: uv run python scripts/sync_skills.py"""
from bitt import skills

if __name__ == "__main__":
    names = skills.sync(source=skills.SOURCE, quiet=False)
    print(f"[sync_skills] {len(names)} changed" + (f": {', '.join(names)}" if names else " (all up to date)"))
