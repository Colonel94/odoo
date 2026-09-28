# FleetFlow — Start here

This pack turns FleetFlow from a maintenance workspace into a planned Dubai fleet-operations product. It contains research and build instructions, not newly implemented software.

## Give Claude Code this instruction

> Read `CLAUDE_BUILD_PROMPT.md`, `FLEETFLOW_DUBAI_OPERATIONS_RESEARCH.md`, `SOURCE_REGISTER.json` and `OPS_BACKLOG_AND_ACCEPTANCE.md`. Inspect the latest `Colonel94/odoo` checkout, preserve existing work and implement OPS-1 end to end. Keep the current UI. Build vehicle/driver evidence, explainable readiness, conflict-safe assignment/custody and maintenance holds, with real tests. Do not stop at a plan, invent RTA rules, claim live integrations or deploy to customers. Follow the scope and stop gate in the prompt.

Place these files in Claude Code's working context or a documentation folder in the repository. Include the previous `fleetflow-github-review-and-claude-prompt.md` where available; its foundation corrections are retained.

## Files

- `CLAUDE_BUILD_PROMPT.md` — bounded first build with model guidance, permissions, concurrency and 20 acceptance scenarios.
- `FLEETFLOW_DUBAI_OPERATIONS_RESEARCH.md` — sourced regulatory/platform distinctions, full operating processes and target product behavior.
- `OPS_BACKLOG_AND_ACCEPTANCE.md` — later increments for workshop/handovers, rental/TARS, financial imports, lifecycle and customer hosting.
- `SOURCE_REGISTER.json` — official source URLs, retrieval dates, sections and research limitations.

**First demonstration:** a valid shift can be assigned and checked out; missing approval, an expiring permit, conflict or maintenance hold blocks it with a useful next action.

**Research boundary:** public official pages were reviewed on 21 September 2026. This is not an exhaustive legal assessment or an approved production ruleset. Source date, retrieval date and rule effective date are different. Unknown mandatory requirements remain Needs review. Current branch was checked; no repository changes or new Odoo runtime tests were performed by this research task.
