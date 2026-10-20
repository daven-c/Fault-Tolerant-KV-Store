# Fault-Tolerant Distributed Key-Value Store

This project is a from-scratch implementation of a fault-tolerant, distributed key-value store in C++. It is designed to be highly available and resilient to node failures, achieving data consistency across a replicated cluster via the Raft consensus algorithm. It is conceptually similar to core infrastructure components like Redis or etcd.

![Live demo: leader election, a leader crash under load with zero lost writes, quorum loss, and recovery on a 5-node cluster](docs/demo.gif)

<sub>A real, unedited run of [`bench/demo.py`](bench/demo.py) on a 5-node cluster ([MP4](docs/demo.mp4) · [asciinema recording](docs/demo.cast)).</sub>

---

## 🚀 Features

-   **Distributed Consensus**: Uses the Raft algorithm for leader election and replicated log management to ensure data consistency.
-   **Fault Tolerance**: The cluster can tolerate failures of minority nodes and continue to serve requests.
-   **Automated Cluster Launching**: Includes a powerful script to build, clean, and launch a multi-node cluster in separate, customizable terminal windows.
-   **Persistence**: Each node keeps its key/value state in an Append-Only File (AOF) and its Raft term, vote and log in a separate fsync'd state file (`AOFs/node_<id>.raft`), so a restarted node keeps its promises (at most one vote per term) and only re-fetches entries it is missing. On macOS `fsync` does not flush the drive's own cache, so this protects against process crashes but not necessarily power loss.
-   **Concurrent & Asynchronous Networking**: Built on a multi-threaded, event-driven server architecture using Boost.Asio to handle many simultaneous client connections efficiently.
-   **Modern C++**: Utilizes C++20 features, including concurrency primitives and coroutines for clean, modern asynchronous code.
-   **Low-Latency Replication**: New entries are replicated as soon as they arrive (not on the next heartbeat), batched with one in-flight request per follower over reused TCP connections. Median write latency is about 0.3 ms on a local 3-node cluster.
-   **Fast Follower Recovery**: Followers report where their log diverges, so a restarted node catches up on thousands of entries in about a second.
-   **Verified by a Fault-Injection Harness**: A reproducible benchmark suite kills leaders under load and checks durability, replica convergence, and quorum safety on every run (see [Benchmarks](#-benchmarks--fault-injection)).

---

## 🎬 Live Demo

Once the project builds (see [Build Instructions](#️-build-instructions)), one command launches a real
5-node cluster on localhost and walks through it in about a minute:

```bash
python3 bench/demo.py            # add --pace 0 to skip the pauses, --nodes 3 for a smaller cluster
```

| Step | What you see |
|---|---|
| 1. Leader election | Nodes campaign and a leader is elected (~350 ms) |
| 2. Client redirection | A follower answers `NOT_LEADER <addr>`; the client follows it to the leader |
| 3. Replication | A committed write appears in every node's AOF |
| 4. Throughput | Live ops/s bar for 32 concurrent clients, then p50/p99 latency |
| 5. Leader crash under load | Leader `SIGKILL`ed mid-write; new leader in ~350 ms; audit finds zero lost acknowledged writes |
| 6. Minority failure | With 2 of 5 nodes down, writes still commit |
| 7. Losing quorum safely | With 3 of 5 down, the leader refuses to acknowledge writes |
| 8. Recovery | Crashed nodes restart, quorum returns, and all replicas converge to identical state |

The recording at the top of this README is a real run of this script. To regenerate it
(requires `asciinema`, `agg` and `ffmpeg`):

```bash
./docs/record-demo.sh
```

The script refuses to render a run in which any guarantee was violated.

The demo exits non-zero if any guarantee is violated, so it doubles as an end-to-end smoke test.

---

## 🕹 Interactive Dashboard

A local web UI for poking at a real cluster:

```bash
python3 dashboard/server.py        # builds the server and opens http://localhost:8090
```

![Dashboard: a 5-node cluster map with a leader, followers, one node down, the console and the event log](docs/dashboard.png)

-   **Cluster map**: every node is a dot, coloured and labelled by role (leader, follower, candidate, paused, down), with its term, log length and an applied-entries ring. The leader's link to each follower shows how many entries that follower is behind, and moving dots show entries being replicated and votes being requested, derived from each node's real state.
-   **Node controls**: click a node to kill it (`SIGKILL`), restart it, or pause/resume it (`SIGSTOP`/`SIGCONT`, a hung server that keeps its sockets open). Rebuild the cluster with 1–7 nodes.
-   **Console**: send `SET`/`GET`/`DEL`/`KEYS` to the cluster (auto-routed to the leader, with any redirects shown) or to one specific node to see `NOT_LEADER` replies.
-   **Load generator**: up to 64 closed-loop clients with a live throughput chart and p50/p99 latency, so you can watch what a leader crash does to traffic.
-   **Event log**: elections, leader changes, kills, restarts and pauses as they happen.

Nodes report their state through a `STATUS` command that each server answers locally (it is not replicated). Raft's peer list is fixed at startup, so changing the cluster size rebuilds the cluster rather than adding a node to a running one.

---

## 🏗 Architecture Overview

The system is built as a cluster of identical server nodes. At any given time, one node is elected as the **Leader**, and all others are **Followers**.

-   **Client Interaction**: All client write requests (`SET`, `DEL`) are directed to the Leader. If a client contacts a Follower, the Follower will redirect the client to the current Leader.
-   **Log Replication**: The Leader appends the command to its own log and immediately sends it to its Followers. Each Follower has at most one `AppendEntries` in flight; entries that arrive meanwhile are sent together as soon as the previous response returns. Heartbeats (every 150 ms) keep idle Followers from starting elections. RPC connections to each peer are pooled and reused.
-   **Log Repair**: If a Follower's log doesn't match, it replies with the index where it diverges, and the Leader retries from there immediately instead of stepping back one entry at a time. Followers only truncate their log at a genuine conflict, so a delayed, out-of-order RPC can't remove entries.
-   **Commit & Apply**: Once a majority of nodes have acknowledged the entry, the Leader "commits" it. Only then is the command applied to the in-memory key-value store (the "state machine"), and the result is returned to the client.
-   **Leader Failure**: If the Leader crashes, the remaining nodes will time out, start a new election, and elect a new Leader from among themselves, ensuring service continuity.

---

## 🛠 Tech Stack

-   **Language**: C++20
-   **Networking**: Boost.Asio (using C++20 coroutines for asynchronous operations)
-   **Concurrency**: Standard C++ library (`std::thread`, `std::mutex`, `std::condition_variable`)
-   **Build System**: CMake
-   **Dependency Management**: Vcpkg

---

## 🔧 Prerequisites

-   A C++ compiler that supports **C++20** (e.g., modern versions of Clang, GCC, or MSVC).
-   **CMake** (version 3.15 or newer).
-   **Vcpkg**: This project uses the Vcpkg package manager to handle the Boost dependency. See the official Vcpkg guide for installation.
-   A build tool like **Ninja** or **make**. (Ninja is recommended.)

---

## ⚙️ Build Instructions

### Clone the Repository:

```bash
git clone https://github.com/daven-c/Fault-Tolerant-KV-Store.git
cd Fault-Tolerant-KV-Store
```

### Install Dependencies with Vcpkg:

```bash
# Make sure you have bootstrapped vcpkg first!
vcpkg install boost
```

### Configure and Build the Project:

```bash
mkdir build
cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=<path-to-your-vcpkg-dir>/scripts/buildsystems/vcpkg.cmake
cmake --build .
```

This will compile and create the **server** executable inside the `build` directory.

---

## ▶️ Usage

### Running the Distributed Server Cluster

The easiest way to run a cluster is with the included **`launch.sh`** script.
This script automatically handles cleanup, builds the peer list, and launches each server in a separate terminal window for easy monitoring.

#### 1. Make the Script Executable

(This only needs to be done once.)

```bash
chmod +x launch.sh
```

#### 2. Launch the Cluster

To launch a default **3-node cluster**:

```bash
./launch.sh start 3
```

To launch a cluster with a specific number of nodes (e.g., 5):

```bash
./launch.sh start [num]
```

To launch a cluster in the background:

```bash
./launch.sh start-bg [num]
```

#### (Optional). Manually launch the Cluster

To launch clusters manually for 3 clusters:

```bash
./server 0 127.0.0.1:8000 127.0.0.1:8001 127.0.0.1:8002
```

```bash
./server 1 127.0.0.1:8000 127.0.0.1:8001 127.0.0.1:8002
```

```bash
./server 2 127.0.0.1:8000 127.0.0.1:8001 127.0.0.1:8002
```

General Command:

```bash
./server <idx of address (node id)> <list of addresses>
```

After a few seconds, an election will occur, and one node will become the Leader. The other nodes will become Followers and print messages indicating who the Leader is.

Logs for all nodes will be stored in server_logs/ by default

#### 3. Interacting with the Cluster

You can connect to any node in the cluster with a tool like `netcat` to send commands.
If you connect to a follower, it will automatically tell you the address of the current Leader.

```bash
# Connect to any node (e.g., the first one on port 8000)
nc 127.0.0.1 8000

# Send commands
SET name Test
GET name
KEYS
```

You can also restart any node in the cluster with:

```bash
./launch.sh restart <id> <total>
```

_id_ is the id of the node (e.g. 1, 2, 3) and _total_ is the total nodes in the cluster

#### 4. Stopping the Cluster

You can stop the cluster by running the following:

```bash
./launch.sh stop
```

#### 5. Resetting Logs

You can remove all logs from AOFs/ and server_logs/ by running:

```bash
./launch.sh reset
```

---

## 📊 Benchmarks & Fault Injection

`bench/harness.py` builds the server, runs real multi-process clusters, kills leaders and
followers under load, and checks correctness on every run. Results are saved to
`bench/results/` along with the commit and the exact command, so every number can be regenerated.

```bash
python3 bench/harness.py run                     # full run (~3 min)
python3 bench/harness.py run --ref <commit>      # benchmark any older commit
python3 bench/harness.py compare bench/results/baseline-bbaeb26.json bench/results/persistent-conns.json
```

### Results (3-node cluster, localhost, Apple Silicon, 10 CPUs)

Before = original implementation (`bbaeb26`). After = current `main` (replication fixes, immediate
replication, fast log repair, durable Raft state, pooled RPC connections), as a range over two
full runs. Full tables are in [bench/results/COMPARISON.md](bench/results/COMPARISON.md); every
intermediate step has its own result file in `bench/results/`.

| Metric | Before | After |
|---|---:|---:|
| Write latency, single client, p50 | 150.8 ms | 0.3 ms |
| Write latency, single client, p99 | 296.9 ms | 1.0–1.5 ms |
| Peak throughput (64 clients, 50/50 SET/GET) | 410 ops/s | 9,202–13,276 ops/s |
| p99 latency at 64 clients | 158 ms | 12–20 ms |
| Leader-failover outage, median | 474 ms | 376–388 ms |
| Leader-failover outage, worst trial | 5,666 ms | 1,106–1,849 ms |
| Restarted-node catch-up, median | did not finish within 20 s (5 of 5 trials) | 0.46–0.57 s for ~15,000 entries |
| Acknowledged writes lost across leader crashes | 0 | 0 (of 138,000+ verified) |

### Correctness checks (all passing)

-   Every replica's AOF replays to identical state after load.
-   No acknowledged write is lost when the leader is `SIGKILL`ed under 32 concurrent writers.
-   The cluster stays writable with a minority of nodes down.
-   No write is acknowledged once a majority of nodes is down.
-   A restarted node catches up, and liveness returns when quorum is restored.
-   A stale, shorter `AppendEntries` delivered after a longer one never truncates a follower's log.
-   A node never grants two votes in the same term, even across a crash and restart.
-   After a leader change with no further client traffic, every acknowledged write is still applied on all survivors.

Bugs found and fixed with the harness:

-   After a successful `AppendEntries`, the leader credited the follower with its *entire current* log, including entries appended after the request was sent. Under load this caused replica divergence and failover outages of several seconds.
-   Followers truncated their log on every `AppendEntries`, so a delayed RPC could delete entries the leader had counted as replicated ([#2](https://github.com/daven-c/Fault-Tolerant-KV-Store/issues/2)).
-   Raft term, vote and log weren't persisted, so a restarted node could vote twice in one term ([#1](https://github.com/daven-c/Fault-Tolerant-KV-Store/issues/1)).
-   A new leader never appended an entry of its own term, so it couldn't commit entries from earlier terms until the next client write; replicas stayed stale while the cluster was idle. Leaders now start their term with a no-op entry (Raft §8). Found by the live demo.

See [bench/README.md](bench/README.md) for scenarios and options.

### Known limitations

-   No log compaction or snapshots: the Raft state file and AOF grow without bound.
-   On macOS, `fsync` does not flush the drive's write cache, so durability covers process crashes but not necessarily power loss (`F_FULLFSYNC` would, at a large latency cost).
-   Failover usually completes in about 0.4 s, but roughly one trial in five or ten takes 1–2 s.
-   RPCs have no timeout, so a peer that accepts connections but never replies can hold an RPC indefinitely.

---

## 🐛 Troubleshooting

-   **CMake Error: "Could not find toolchain file"**
    The path provided to `-DCMAKE_TOOLCHAIN_FILE` is incorrect. Double-check the absolute path to your Vcpkg installation.

-   **Build fails with C++20 errors**
    Ensure you have a modern C++ compiler and that CMake is correctly configured to use it. The included `CMakeLists.txt` file requests C++20 automatically.
