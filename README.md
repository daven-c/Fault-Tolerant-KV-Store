# Fault-Tolerant Distributed Key-Value Store

This project is a from-scratch implementation of a fault-tolerant, distributed key-value store in C++. It is designed to be highly available and resilient to node failures, achieving data consistency across a replicated cluster via the Raft consensus algorithm. It is conceptually similar to core infrastructure components like Redis or etcd.

---

## 🚀 Features

-   **Distributed Consensus**: Uses the Raft algorithm for leader election and replicated log management to ensure data consistency.
-   **Fault Tolerance**: The cluster can tolerate failures of minority nodes and continue to serve requests.
-   **Automated Cluster Launching**: Includes a powerful script to build, clean, and launch a multi-node cluster in separate, customizable terminal windows.
-   **Persistence**: Each node persists its command log to an Append-Only File (AOF), allowing for state recovery after a crash.
-   **Concurrent & Asynchronous Networking**: Built on a multi-threaded, event-driven server architecture using Boost.Asio to handle many simultaneous client connections efficiently.
-   **Modern C++**: Utilizes C++20 features, including concurrency primitives and coroutines for clean, modern asynchronous code.

---

## 🏗 Architecture Overview

The system is built as a cluster of identical server nodes. At any given time, one node is elected as the **Leader**, and all others are **Followers**.

-   **Client Interaction**: All client write requests (`SET`, `DEL`) are directed to the Leader. If a client contacts a Follower, the Follower will redirect the client to the current Leader.
-   **Log Replication**: The Leader appends the command to its own log, then replicates this log entry to its Followers.
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

---

## 🐛 Troubleshooting

-   **CMake Error: "Could not find toolchain file"**
    The path provided to `-DCMAKE_TOOLCHAIN_FILE` is incorrect. Double-check the absolute path to your Vcpkg installation.

-   **Build fails with C++20 errors**
    Ensure you have a modern C++ compiler and that CMake is correctly configured to use it. The included `CMakeLists.txt` file requests C++20 automatically.
