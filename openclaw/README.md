# OpenClaw Plugin for AgentComms

This directory contains the ClawHub skill definition for AgentComms, making it available as a skill in OpenClaw agents.

## Contents

- `SKILL.md` - The main skill file with YAML frontmatter and markdown instructions
- `_meta.json` - Package metadata
- `README.md` - This file

## Publishing

To publish this skill to ClawHub:

```bash
clawhub skill publish openclaw/
```

## Local Testing

To test the skill locally, copy `SKILL.md` to your local OpenClaw skills directory:

```bash
mkdir -p ~/.openclaw/skills/agentcomms
cp openclaw/SKILL.md ~/.openclaw/skills/agentcomms/SKILL.md
```

Then restart your OpenClaw agent to pick up the new skill.
