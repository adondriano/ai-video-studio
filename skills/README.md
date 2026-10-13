# Skills

External LLM/editing skills are cloned here.

## Required for the AI Final Edit (Live mode)

```bash
cd skills
git clone https://github.com/haidrrrry/claude-remotion-skill.git
```

The Studio checks for `skills/claude-remotion-skill/` (with a `SKILL.md` or
`README.md`) before allowing a Live final edit. In Demo mode the final edit is
simulated locally (EDL + preview render + notes) so you can test the full
pipeline without the skill.
