# Device and Network Managers

Both managers are deterministic simulations. They do not access host devices or send real network traffic. Time is measured in integer ticks (one tick is 0.1 ms).

## Device manager

`DeviceManager` supports three device types: `disk`, `printer`, and `keyboard`. The general device queue policy is `fcfs` or `priority`. Disk requests additionally support `fcfs`, `sstf` (shortest seek time first), and `scan`; disk head position, cylinder count, scan direction, and per-device service costs are configurable. A request can set `failed: true` to inject a device failure. The event timeline records request start, completion or failure, and service cost. Metrics include request/completion/failure counts, average service time, and disk head movement.

Run through `POST /api/device/run`:

```json
{
  "queue_policy": "fcfs",
  "disk_policy": "sstf",
  "disk_head": 50,
  "requests": [
    {"id":"d1", "pid":"P1", "device":"disk", "cylinder":90},
    {"id":"p1", "pid":"P2", "device":"printer"},
    {"id":"k1", "pid":"P3", "device":"keyboard", "failed":true}
  ]
}
```

## Network manager

`NetworkManager` accepts named nodes, weighted links, and packets with source, destination, arrival tick, and optional priority. It computes a shortest-delay route while avoiding failed links. Queue policies are `fifo` and `priority`; per-link buffer capacity controls congestion drops, and link delay plus packet service time determine forwarding delay. Mark a link `failed: true` to run a failure experiment. Events record enqueue, forwarding, delivery, and drops. Metrics include delivered/dropped packets, delivery rate, average end-to-end delay, and hop count.

Run through `POST /api/network/run`:

```json
{
  "queue_policy":"priority",
  "buffer_capacity":2,
  "nodes":["A","B","C"],
  "links":[{"from":"A","to":"B","delay":4},{"from":"B","to":"C","delay":3}],
  "packets":[{"id":"p1","source":"A","destination":"C","at":0,"priority":2}]
}
```

Both endpoints return `events`, `snapshot`, `metrics`, `warnings`, and a CSV export. They accept an optional `stop` object with positive integer `max_time` and/or `max_events`. Sample inputs are `inputs/device_baseline.json` and `inputs/network_baseline.json`.

## Known modeling limits

- Device models are abstract service queues, not host hardware drivers; keyboard, printer, and disk are representative device classes.
- SCAN and SSTF are simplified deterministic disk-head policies; they do not model rotational latency.
- Network links are undirected and use shortest total configured delay. Packet priority is applied to packets sharing an arrival time; TCP, retransmission, and real socket behavior are outside scope.
- Buffer overflow is modeled from queued work on a link; this is not a packet-level byte buffer.
