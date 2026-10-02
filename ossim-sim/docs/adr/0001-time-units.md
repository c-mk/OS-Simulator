# ADR-0001: Integer simulation ticks and same-time ordering

Status: Proposed (Milestone 1) · Owner: Rasheed · Reviewers: all

## Decision
- Simulated time is an integer tick count; 1 tick = 0.1 ms. Dashboard shows ms.
- Baseline workloads given in whole units use 1 unit = 1 ms = 10 ticks.
- Events at the same tick run in phase order: completion, service/fault/I-O completion, arrival (arrival time, then
  input order), quantum expiry (requeue after arrivals), preemption check, dispatch, other. Remaining ties: core id,
  then sequence number.
- One master seed per run; each manager uses random.Random(f"{seed}:{manager}").

## Why
The context-switch sweep uses 0.1 ms steps; floats would make results depend on rounding. A fixed phase order makes
every run reproducible (spec 1.2) and matches the hand calculations.

## Consequences
All inputs in ms must be multiples of 0.1 ms (validated by ms_to_ticks). Very long runs are bounded by an event limit.
