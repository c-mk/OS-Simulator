# OS Simulator — CSC301 Team Project

Deterministic discrete-event operating-system simulator with process, memory, file, security, device and network
managers, a parallel-computing component, and a local web dashboard. **Simulation only:** it never runs host commands,
touches real user files, or sends network traffic.

**Status:** Milestone 1 (architecture + interactive prototype), tag `m1`.

| Member | Role |
| --- | --- |
| Rasheed Rahman | Project lead / integrator, parallel computing |
| Copernick | Process & memory engineer |
| Liberty | File & security engineer |
| Arian | Device & network engineer |
| Christian | Dashboard / visualization engineer |
| Derrick | Quality & documentation engineer |

## Setup (Ubuntu VM, Python 3.10+)

```bash
git clone <repo-url> ossim-sim && cd ossim-sim
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Run the dashboard prototype

```bash
python -m ossim.ui          # then open http://127.0.0.1:8000
# or open ossim/ui/prototype/index.html directly in Firefox
```

The Milestone 1 prototype shows navigation, every manager tab, the scenario builder, testing center, comparison center,
event explorer and export layout. Process, memory and file pages display the hand-calculated baseline results from
`expected_results/`; they are labeled as prototype data, not simulator output.

## Run the tests

```bash
pytest -q        # baseline-asset consistency, interface/event contracts, invalid input, host-safety check
ruff check .     # style
```

CI (`.github/workflows/ci.yml`) runs both on every pull request and on `main`.

## Repository layout

```
ossim/
  core/        events.py (shared Event record), clock.py (ticks), controller.py (clock, queue, router)
  model/       shared entities (Process, Task, Page/Frame, FsNode, User, Device, Packet, ...)
  managers/    base.py (Appendix A interface) + process/ memory/ file/ security/ device/ network/
  parallel/    cores, distribution policies, sync primitives, deadlock detection
  io/          loaders.py (validated CSV/JSON/text import), export
  ui/          dashboard (prototype/ for Milestone 1)
inputs/            baseline + team scenarios (instructor examples are never edited)
expected_results/  hand-calculated expected outputs for small deterministic cases
tests/             unit/, integration/, regression/, invalid/, stress/
docs/              adr/ (architecture decisions), contribution_log.md
experiments/       experiment configs and exported results (Weeks 9-10)
```

## Time units and tie-breakers

Integer ticks, 1 tick = 0.1 ms (see `docs/adr/0001-time-units.md`). Baseline workloads in whole units use 1 unit = 1 ms.
Ties: earlier arrival, then input order. RR requeues an expired process after same-time arrivals. Preemption only when
strictly better. Lower priority number = higher priority. Baseline Priority runs are preemptive with aging off.

## Sourced Tools

Required every milestone (spec 12.4). The team completes the bracketed fields.

**Sourced Tools — GenAI Entry (Milestone 1).** Tool/model: Claude (Anthropic), claude-opus-5-5, via the Claude desktop app.
Access date: October 2, 2026. Instructor-authorized purpose: [quote the instructor's authorization, or remove the
GenAI-drafted material if none was given]. Use: drafted the Milestone 1 report (charter/RACI wording, traceability
matrix, architecture diagram, data model, event schema, API tables, risk register, sprint backlog), generated this
repository skeleton (interface stubs, loaders, CI, tests), the dashboard prototype, and candidate expected results for the
baseline cases. Student modification: [what the team changed, rejected or rewrote]. Verification: [hand calculations of
the expected results by Copernick and Liberty; pytest/ruff run in the team VM; RTM reviewed against the spec by Derrick].
Affected files/sections: Milestone 1 report; README.md, CONTRIBUTING.md, docs/adr/*, ossim/core/*, ossim/managers/base.py,
ossim/io/loaders.py, ossim/ui/*, tests/*, inputs/*, expected_results/*.

**Other tools:** Python 3 standard library; pytest and ruff (testing/linting only); GitHub and GitHub Actions; Firefox.
No third-party code implements any simulator algorithm.
