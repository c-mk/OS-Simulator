# OS Simulator — CSC301 Team Project

Deterministic discrete-event operating-system simulator with process, memory, file, security, device and network
managers, a parallel-computing component, and a local web dashboard. **Simulation only:** it never runs host commands,
touches real user files, or sends network traffic.

**Status:** Milestone 3 (Working modules and dashboard views, metrics, visuals, tests, comparison results, integration contract/FIFO/LRU, trace import, frame state; file tree, commands, path/error handling.)

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

## Milestone 3 demo: Memory, File and Integration

Start the dashboard (`python -m ossim.ui`) and check the green "Engine connected" banner on each page. The Process page
(Milestone 2) is unchanged; its walk-through is in `docs/process_manager_report.md`.

**Memory page (about 2 minutes).**
1. Pick **LRU**, 3 frames, 4096-byte pages. Press **Baseline trace**, then **Run selected policy**. Read the hit/fault timeline, the frame
   occupancy chart (and its text table), the page table and the metrics: 7 faults, 4 evictions.
2. Press **Compare FIFO vs LRU**: FIFO 8 faults, LRU 7 faults on the same trace. Press **Locality trace** and compare again: FIFO 12, LRU 8.
3. Export CSV or JSON from the buttons under the results.

**File page (about 2 minutes).**
1. Press **Baseline script (12)** then **Run script**. Results: 9 ok, 3 safe errors. Press **Sample script (20)** to see all eight commands, five expected errors and the file tree with metadata.
2. Press **Reset**, then **Step one command** to run one command at a time; the tree and operation log update after each.
3. Set the user to `guest` (or change the root permission) and run again: commands are refused as `denied` and the tree is unchanged.
4. Export the operation log as CSV. Rules and limits: `docs/file_manager.md`.

**Integration page (about 2 minutes).** Use the default workload and requests, press **Run integration**. The lanes show each process on the CPU,
blocked on a page fault, and blocked on a file request, then ready again. The correlated log can be filtered by source.
A request from a user without permission shows as `denied`. What is and is not modeled: `docs/adr/0004-integration.md`.

**Testing center** (**Run engine checks**) runs the process, memory, file and integration checks against the engine (19 of 19 pass). **Comparison center**
now includes the FIFO vs LRU results; **Export** downloads each run. Results tables and the figure: `docs/m3_results.md`.

Input files: `inputs/trace_baseline.txt`, `inputs/trace_locality.txt`, `inputs/fs_baseline.txt` (12 commands), `inputs/fs_script.txt` (20 commands),
plus the process workloads from Milestone 2.

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
Milestone 3 adds `test_memory_manager.py`, `test_memory_api.py`, `test_memory_locality.py` (hand-worked FIFO/LRU traces), `test_file_manager.py`
(every command, errors, limits, permissions, process requests), `test_file_api.py`, `test_integration.py` (hand-worked process + memory + file case)
and `tests/integration/test_ui_api_m3.py` (HTTP routes). Regenerate the results and figure with `PYTHONPATH=. python experiments/m3_results.py`.

## Repository layout

```
ossim/
  core/        events.py (shared Event record), clock.py (ticks), controller.py (clock, queue, router)
  model/       shared entities (Process, Task, Page/Frame, FsNode, User, Device, Packet, ...)
  managers/    base.py (Appendix A interface) + process/ memory/ file/ security/ device/ network/
  parallel/    cores, distribution policies, sync primitives, deadlock detection
  io/          loaders.py (validated CSV/JSON/text import), export
  ui/          dashboard (prototype/index.html) and the localhost server with the /api/process, /api/memory, /api/file and /api/integration endpoints
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
Student modification: The team generated the first draft of the process manager, controller, tests, dashboard and docs in one session. The team reviewed the output, ran pytest and ruff locally on Python 3.12, and tested the dashboard in a browser. Rasheed removed an outdated test file (test_process_manager.py) that conflicted with the new manager. Christian fixed whitespace lint in scheduler.py, wired the changes into branches and pull requests, and filled in this entry.. Verification: pytest and ruff run ; baseline values compared with `expected_results/process_baseline.json`; re-derived the hand-worked cases in `test_process_scenarios.py` independently and found no differences. Affected files/sections: those
listed under Use.


**Sourced Tools — GenAI Entry (Milestone 3).** Tool/model: Claude (Anthropic), Claude Sonnet 5.5, in Claude Code / the Claude desktop app.
Access date: November 6, 2026. Instructor-authorized purpose: helping plan and draft the Milestone 3 work (File Manager, process/memory/file
integration, dashboard views, tests and results), with the team checking and approving everything it produced. Use: drafted the File Manager
(`ossim/managers/file/`), the process/memory/file integration (`ossim/integration.py`), the file and integration server routes
(`ossim/ui/file_api.py`, `integration_api.py`, `process_api.py`, `__main__.py`), the Memory, File and Integration dashboard pages
(`ossim/ui/prototype/index.html`), `inputs/fs_script.txt`, the file, integration, locality and HTTP tests, `docs/file_manager.md`,
`docs/m3_results.md`, `experiments/m3_results.py`, ADR-0004 and the architecture update, and this README section.
Student modification: Christian reviewed the generated code, ran pytest and ruff locally on Python 3.12, tried the dashboard pages in a
browser, and wired the changes into the feature branch and pull request. Copernic's memory manager and memory API were written by the team and
were not changed by the AI. Verification: pytest (240 tests pass) and ruff run locally; the FIFO/LRU, file-system and integration tests use
hand-worked expected values (listed in the test files), and the engine output was compared with them and with `expected_results/*.json`;
dashboard flows (run, step, reset, compare, exports) checked in a browser. Affected files/sections: those listed under Use.
