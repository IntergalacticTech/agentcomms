# OpenClaw Plugin for FreeMail

This directory contains the ClawHub skill definition for FreeMail, making it available as a skill in OpenClaw agents.

## Contents

- `SKILL.md` - The main skill file with YAML frontmatter and markdown instructions
- `_meta.json` - Package metadata (owner, slug, version)
- `README.md` - This file

## Publishing

To publish this skill to ClawHub:

```bash
clawhub skill publish openclaw/
```

## Local Testing

To test the skill locally, copy `SKILL.md` to your local OpenClaw skills directory:

```bash
mkdir -p ~/.openclaw/skills/freemail
cp openclaw/SKILL.md ~/.openclaw/skills/freemail/SKILL.md
```

Then restart your OpenClaw agent to pick up the new skill.
