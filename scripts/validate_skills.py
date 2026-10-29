# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Validate every SKILL.md in the repository.

Checks frontmatter fields, name format, description length, file length,
and that relative markdown links resolve.

Usage:
    uv run scripts/validate_skills.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
MAX_LINES = 500


def check_skill(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT).as_posix()

    if not text.startswith("---\n"):
        return [f"{rel}: missing YAML frontmatter"]
    try:
        _, front, body = text.split("---\n", 2)
        meta = yaml.safe_load(front) or {}
    except (ValueError, yaml.YAMLError) as exc:
        return [f"{rel}: invalid frontmatter ({exc})"]

    name = meta.get("name")
    desc = meta.get("description")
    expected = "openstack-skills" if path.parent == ROOT else path.parent.name

    if not name:
        errors.append(f"{rel}: 'name' is required")
    elif not NAME_RE.match(name) or len(name) > 64:
        errors.append(f"{rel}: name '{name}' must be lowercase-hyphenated, max 64 chars")
    elif name != expected:
        errors.append(f"{rel}: name '{name}' should match directory '{expected}'")

    if not desc or not str(desc).strip():
        errors.append(f"{rel}: 'description' is required")
    elif len(str(desc)) > 1024:
        errors.append(f"{rel}: description is {len(str(desc))} chars (max 1024)")

    lines = text.count("\n") + 1
    if lines > MAX_LINES:
        errors.append(f"{rel}: {lines} lines (max {MAX_LINES}); move detail into reference files")

    errors.extend(check_links(path, body))
    return errors


def check_links(path: Path, body: str) -> list[str]:
    errors = []
    for target in LINK_RE.findall(body):
        if re.match(r"^[a-z]+://", target) or target.startswith("mailto:"):
            continue
        if not (path.parent / target).exists():
            errors.append(f"{path.relative_to(ROOT).as_posix()}: broken link '{target}'")
    return errors


def main() -> int:
    skills = sorted(ROOT.glob("SKILL.md")) + sorted(ROOT.glob("skills/*/SKILL.md"))
    errors: list[str] = []
    for skill in skills:
        errors.extend(check_skill(skill))
    for md in sorted(ROOT.glob("skills/*/*.md")):
        if md.name != "SKILL.md":
            errors.extend(check_links(md, md.read_text(encoding="utf-8")))

    names = [s.parent.name for s in skills if s.parent != ROOT]
    for d in sorted((ROOT / "skills").iterdir()):
        if d.is_dir() and d.name not in names:
            errors.append(f"skills/{d.name}: directory has no SKILL.md")

    for e in errors:
        print(f"ERROR {e}")
    print(f"Checked {len(skills)} skills: {'OK' if not errors else f'{len(errors)} error(s)'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
