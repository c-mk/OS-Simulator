# Milestone 4 demonstration script

Estimated duration: 7–9 minutes. Start the dashboard with `python -m ossim.ui` and open `http://127.0.0.1:8000`.

1. **Overview (30 sec):** show the six manager workspaces and the engine-connected state.
2. **Security (90 sec):** load the baseline security operations and run them. Point out the active-session requirement, role permissions, a granted file read, a denied delete, the failed-login alert, and the append-only audit view. Export the CSV.
3. **Device (60 sec):** run the disk/printer/keyboard baseline. Compare FCFS and Priority; change the disk policy to SSTF or SCAN. Mark one request `"failed": true` and show the failure event and metrics.
4. **Network (90 sec):** run the A–B–C–D baseline. Show the shortest-delay route and packet metrics. Mark a link `"failed": true` and show alternate routing or a no-route drop.
5. **Six-manager integration (2 min):** open Integration demo and choose **Run all six managers**. Show that Process, Memory, File, Security, Device and Network all appear in the combined event timeline and metrics cards.
6. **Testing Center (60 sec):** run browser checks, then report the independent Python suite result from `pytest -q` and style result from `ruff check .`.
7. **Close (30 sec):** review the final-month experiment plan and unresolved-defect list. Explicitly state that the integrated run aggregates manager outputs; full controller feedback for device/network/security is still open work.

Do not claim that demo users are real authenticated accounts, that the simulator controls host devices, or that packets are sent over a real network.
