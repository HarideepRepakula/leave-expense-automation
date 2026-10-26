# Project rules (read at the start of every session)

Project: Enterprise Leave and Expense Approval Automation System.

Source of truth, in priority order:
1. docs/01_amendments.md (overrides the original where they conflict)
2. docs/00_original_spec.md
3. PROGRESS.md (what is done, what is next)

## Working rules
- Work on ONE phase at a time, as recorded in PROGRESS.md. Do not start the next phase until I write
  "APPROVED PHASE N". Code is allowed only in phases that call for it.
- Before changing anything, inspect the existing files. Never assume a file exists.
- Never claim a command or test was run unless you ran it and saw the output. Paste real results.
- Do not invent business policies. Every assumed value goes in docs/09_assumptions_and_decisions.md with an ID,
  labelled ASSUMPTION (illustrative synthetic).
- No random outcomes for derived values or approval decisions. Randomness only for raw inputs and designated
  stochastic fields (e.g. processing delays), from seeded, independent RNG streams.
- Ground truth lives only in the `ground_truth` schema and data/ground_truth/. Operational code must never
  import or read it. Only src/evaluation/ may read both.
- Keep workflow status, exception class, technical processing status and audit events as separate dimensions.
- Preserve immutable IDs and append-only history. Never overwrite past decisions.
- Use synthetic data only. Keep secrets out of source code (.env, with .env.example committed).
- Do not silently resolve ambiguities: list each one with a proposed default and ask me.

## End of every phase
List files created/changed, key decisions, exact run commands, REAL test output, open issues, and which
acceptance criteria are complete or incomplete. Update PROGRESS.md. Then stop.

## Style
I am learning. Explain simply, give exact commands (Windows PowerShell; note macOS/Linux differences).
When debugging: reproduce, find the root cause, make the smallest fix, rerun regression tests.
