# OS Simulator — CSC301 Team Project

Deterministic discrete-event operating-system simulator with process, memory, file, security, device and network
managers, a parallel-computing component, and a local web dashboard. **Simulation only:** it never runs host commands,
touches real user files, or sends network traffic.

**Status:** Milestone 2 (process manager + simulation core + dashboard demo)

| Member | Role |
| --- | --- |
| Rasheed Rahman | Project lead / integrator, parallel computing |
| Copernic | Process & memory engineer |
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

## Run the dashboard

```bash
python -m ossim.ui          # then open http://127.0.0.1:8000 in Firefox or Chrome
```

The server only listens on localhost. Opening `index.html` as a file still shows the pages, but the Process page then
says "Engine not connected" and can only show the hand-calculated baseline, because the engine runs behind the server.

## Milestone 2 demo: process scheduling

1. Start the dashboard and open **Process** in the left menu. The green banner should say "Engine connected".
2. Pick a policy. Set **q** for Round-Robin, **context switch** (ms) for dispatcher overhead, and **aging** (ms, 0 = off)
   for Priority. The workload box takes CSV (`pid,arrival,burst,priority`); the default is the baseline workload.
3. Use the toolbar: **Run** plays the simulation event by event at the chosen speed (1x, 2x, 5x, Max); **Pause** holds it;
   **Step** advances one event; **Reset** clears the run and keeps your inputs. The clock and state at the top right follow along.
4. Read the results: CPU Gantt chart (process bars, `CS` context-switch bars, `IDLE` gaps), per-process and average
   metrics, the process state timeline (with a text version under "Text version of the timeline"), and the event log.
5. **Testing center** runs baseline and bad-input checks against the engine. **Event explorer** shows the same events with search and filter. **Comparison center** still shows the hand-calculated
   baseline for all six policies side by side.

Bad input never changes anything: **Validate workload** and **Run** report the line and the problem (for example
`Line 3: duplicate pid P1`, `Quantum must be at least 1 ms`).

Suggested walk-through for the demo (about 2 minutes):
1. FCFS on the baseline: Gantt P1 0-8, P2 8-12, P3 12-21, P4 21-26; averages 15.25 turnaround, 8.75 waiting.
2. SRTF: P1 is preempted at 1 ms; average waiting drops to 6.5.
3. Round-Robin q = 4, then set context switch to 1: `CS` bars appear and makespan grows from 26 to 33 ms.
4. Paste `inputs/starvation.csv`, choose Priority, run with aging 0 and then aging 2: process L finishes at 10 ms, then at 4 ms.
5. Type a bad workload (duplicate pid or burst 0) to show the error messages; press Reset.
6. Open **Testing center** and press **Run process checks**: the six baseline policies and three bad inputs run through the engine and show pass/fail with expected and actual values.
7. Optional: pick **Stop: t = 10 ms** in the toolbar and Run to show a stop condition; the page says the run was stopped early.

Input files: `inputs/process_baseline.csv` (4 processes), `inputs/processes.csv` (7 processes with an idle gap),
`inputs/starvation.csv` (aging demo). Rules and tie-breakers: `docs/tie_breakers.md`.

## Run the tests

```bash
pytest -q        # baseline and hand-worked scheduler cases, controller, error/boundary cases, dashboard API
ruff check .     # style
```

CI (`.github/workflows/ci.yml`) runs both on every pull request and on `main`. Test files for this milestone:
`test_process_baseline.py` (all six policies against `expected_results/process_baseline.json`),
`test_process_scenarios.py` (hand-worked context-switch, aging, tie-breaker, idle and boundary cases),
`test_process_errors.py` (rejected configuration and workloads, state machine), `test_process_inputs.py`,
`test_controller.py` (clock, event order, run/pause/step/reset, seed replay, event limit) and
`tests/integration/test_ui_api.py` (the dashboard server running the real engine).

## Repository layout

```
ossim/
  core/        events.py (shared Event record), clock.py (ticks), controller.py (clock, queue, router)
  model/       shared entities (Process, Task, Page/Frame, FsNode, User, Device, Packet, ...)
  managers/    base.py (Appendix A interface) + process/ memory/ file/ security/ device/ network/
  parallel/    cores, distribution policies, sync primitives, deadlock detection
  io/          loaders.py (validated CSV/JSON/text import), export
  ui/          dashboard (prototype/index.html) and the localhost server with the /api/process endpoints
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
The full rules (aging, context switches, metric definitions) are in `docs/tie_breakers.md`.

## Sourced Tools

Required every milestone (spec 12.4). The team completes the bracketed fields.

**Sourced Tools — GenAI Entry (Milestone 1).** Tool/model: Claude (Anthropic), claude-opus-5-5, via the Claude desktop app.
Access date: October 2, 2026. Instructor-authorized purpose: outlining our milestone objectives. Use: drafted the Milestone 1 report (charter/RACI wording, traceability
matrix, architecture diagram, data model, event schema, API tables, risk register, sprint backlog), generated this
repository skeleton (interface stubs, loaders, CI, tests), the dashboard prototype, and candidate expected results for the
baseline cases. Student modification: . Verification: hand calculations of
the expected results by Copernic and Liberty; pytest/ruff run in the team VM; RTM reviewed against the spec by Derrick.
Affected files/sections: Milestone 1 report; README.md, CONTRIBUTING.md, docs/adr/*, ossim/core/*, ossim/managers/base.py,
ossim/io/loaders.py, ossim/ui/*, tests/*, inputs/*, expected_results/*.

**Sourced Tools — GenAI Entry (Milestone 2).** Tool/model: Claude (Anthropic), Claude Sonnet 5.5, in Claude Code / the
Claude desktop app. Access date: October 27, 2026. Instructor-authorized purpose: Helping develop an outline and plan towards completion of this milestone. Use: produced outlines for the Process Manager (`ossim/managers/process/`), the
process model and state machine (`ossim/model/process.py`), the simulation controller (`ossim/core/controller.py`), the
dashboard server API (`ossim/ui/__main__.py`), the Milestone 2 dashboard (`ossim/ui/prototype/index.html`), the process
tests, `inputs/processes.csv`, `inputs/starvation.csv`, `docs/tie_breakers.md`, this README section and the Milestone 2
progress report. 
Student modification: [what the team changed, rejected or rewrote]. Verification: pytest and ruff run ; baseline values compared with `expected_results/process_baseline.json`; re-derived the hand-worked cases in `test_process_scenarios.py` independently and found no differences. Affected files/sections: those
listed under Use.

**Other tools:** Python 3 standard library; pytest and ruff (testing/linting only); GitHub and GitHub Actions; Firefox.
No third-party code implements any simulator algorithm.
