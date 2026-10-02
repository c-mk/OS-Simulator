# Contributing

## Branching and review workflow

1. `main` is protected: no direct pushes; merges only through pull requests with **1 approving review** and green CI.
2. Branch from `main` per backlog item: `feature/<id>-short-name`, `fix/<id>-short-name`, `docs/<topic>`, `test/<topic>`.
   Example: `feature/S2-03-fcfs-sjf`.
3. Commit messages: imperative, reference the item, e.g. `Add FCFS policy (S2-03, PR-02)`.
4. Open the PR early as a draft. Description lists the RTM rows it satisfies and how it was tested.
5. Reviewer checks: tests added/updated, expected values hand-verified, no host access, docs/RTM updated.
   Owner of a shared file (events.py, base.py, model/) must be a reviewer when it changes.
6. Squash-merge. Delete the branch.
7. Milestone release: Rasheed tags `m1`, `m2`, `m3`, `m4`, `v1.0` on `main` after the team demo check.

Default reviewer pairs: Copernick <-> Rasheed, Liberty <-> Arian, Christian <-> Derrick (Derrick reviews tests on every PR).

## Coding standards (Python)

- Python 3.10+, PEP 8, enforced by `ruff check .` (line length 140). Type hints on public functions.
- Module and public-function docstrings; each module names its owner at the top.
- Managers implement `ossim.managers.base.Manager` and talk to each other only through the controller.
- No floats for simulated time: use integer ticks (`ossim.core.clock.ms_to_ticks`).
- No global mutable state; randomness only from the manager's seeded `random.Random`.
- Never import `subprocess`, `socket`, or call `os.system` in `ossim/` (CI test `tests/test_safety.py`).
- Validation errors name the file, line and field, and never modify existing state.
- Core algorithms are written by the team; libraries only for UI, charts, parsing and tests (spec 1.2).

## Tests

- Every algorithm/command: a normal case and a boundary case, compared to a hand-calculated expected value.
- Test names carry the RTM test ID: `test_T_PR_02_fcfs_baseline`.
- Expected results live in `expected_results/` and are reviewed by a second member before merge.

## Weekly contribution log

Each member adds an entry to `docs/contribution_log.md` by Sunday 11:59 pm: completed, blockers, reviews done, next.
