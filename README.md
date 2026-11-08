# Q-Day Radar

Runs real Shor and Grover circuits on IBM quantum hardware, measures how far
today's machines are from breaking real cryptography, and turns that gap into
a ranked migration plan for a crypto inventory (CBOM).

A personal project, started at Qiskit Fall Fest 2026.

- Plan: [`docs/PLAN.md`](docs/PLAN.md)
- How we build (three coordinated Claude Code sessions): [`docs/WORKFLOW.md`](docs/WORKFLOW.md)
- Where we are right now: `python3 scripts/coord.py status`

## Quick start

```bash
brew install uv
uv sync
uv run pytest
```
