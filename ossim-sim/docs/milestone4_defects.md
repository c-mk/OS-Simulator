# Milestone 4 unresolved defect and limitation list

This list records known limitations that remain visible at the end of the current implementation. It distinguishes a modeling limitation from a reproducible software failure; none of the items below should be described as a passing feature test.

| ID | Area | Severity | Status | Description / impact | Next action |
| --- | --- | --- | --- | --- | --- |
| M4-01 | Integration controller | High | Open | The six-manager scenario merges deterministic manager outputs, but it does not yet route device, network or security events through the central controller to block/unblock CPU processes. | Add controller-owned request and completion events; test same-tick ordering and process state transitions. |
| M4-02 | Security integration | High | Open | Security login and authorization are simulated in the Security Manager; the early scenario does not yet enforce a security decision as a gate on every file/device/network operation. | Pass authenticated principal and resource action to each manager before mutation; reject unauthorized requests without changing state. |
| M4-03 | Device realism | Medium | Open | Disk scheduling abstracts seek movement and service time; it does not model rotational latency, DMA, interrupts or physical device drivers. | Keep scope explicit or add optional device-specific latency components. |
| M4-04 | Network realism | Medium | Open | Links are undirected and use deterministic shortest-delay routing; TCP, retransmission, packet bytes, congestion windows and real sockets are out of scope. | Add directed-link and packet-size experiments if required by the rubric. |
| M4-05 | Network queue fidelity | Medium | Open | Priority ordering is deterministic at equal packet-arrival times; the model is not a continuously concurrent router with a full packet-level event queue. | Replace batch forwarding with controller-scheduled enqueue/dequeue/forward events. |
| M4-06 | Security identity | Medium | Open | Demo users have no passwords, MFA, password hashing, session expiry or persistent identity store. | Retain the explicit simulator-only boundary or add a safe mock credential lifecycle. |
| M4-07 | Parallel workspace | Medium | Open | The Parallel navigation item remains a prototype placeholder and is not one of the six manager workspaces in this milestone. | Implement and test as a separate parallel-computing component if it remains in project scope. |
| M4-08 | Dashboard testing | Low | Open | Browser Testing Center covers process, memory, file, security and the combined scenario; device/network still rely on their independent Python/API test suites for some edge cases. | Add browser-side failure and boundary cases for device and network. |
| M4-09 | Integration page wording | Low | Open | The original three-manager integration view remains available beside the six-manager early scenario. | Keep labels clear so users do not confuse the initial process/memory/file integration with the broader event aggregation. |

## Release rule

Re-run `pytest -q` and `ruff check .` after changes. For a release candidate, manually run the six-manager demo, a failed device request, a failed network link, a denied security access, and export checks. Update this list rather than silently removing an unresolved item.
