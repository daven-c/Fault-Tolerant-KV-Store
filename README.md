# Fault-Tolerant Distributed Key-Value Store

This project is a from-scratch implementation of a fault-tolerant, distributed key-value store in C++. It is designed to be highly available and resilient to node failures, achieving data consistency across a replicated cluster via the Raft consensus algorithm. It is conceptually similar to core infrastructure components like Redis or etcd.

---

## 🚀 Features

-   **Distributed Consensus**: Uses the Raft algorithm for leader election and replicated log management to ensure data consistency.
-   **Fault Tolerance**: The cluster can tolerate failures of minority nodes and continue to serve requests.
-   **Persistence**: Each node persists its command log to an Append-Only File (AOF), allowing for state recovery after a crash.
-   **Concurrent & Asynchronous Networking**: Built on a multi-threaded, event-driven server architecture using Boost.Asio to handle many simultaneous client connections efficiently.
-   **Modern C++**: Utilizes C++20 features, including concurrency primitives and coroutines for clean, modern asynchronous code.

---

## 🏗 Architecture Overview

The system is built as a cluster of identical server nodes. At any given time, one node is elected as the Leader, and all others are Followers.

1. **Client Interaction**: All client write requests (SET, DEL) are forwarded to the Leader.
2. **Log Replication**: The Leader appends the command to its own log, then replicates this log entry to its Followers.
3. **Commit & Apply**: Once a majority of nodes have acknowledged the entry, the Leader "commits" it. Only then is the command applied to the in-memory key-value store (the "state machine"), and the result is returned to the client.
4. **Leader Failure**: If the Leader crashes, the remaining nodes will time out, start a new election, and elect a new Leader from among themselves, ensuring service continuity.

---

## 🛠 Tech Stack

-   **Language**: C++20
-   **Networking**: Boost.Asio (using C++20 coroutines for asynchronous operations)
-   **Concurrency**: Standard C++ library (`std::thread`, `std::mutex`, `std::condition_variable`)
-   **Build System**: CMake
-   **Dependency Management**: Vcpkg

---

## 🔧 Prerequisites

-   A C++ compiler that supports C++20 (e.g., modern versions of Clang, GCC, or MSVC).
-   CMake (version 3.15 or newer).
-   **Vcpkg**: This project uses the Vcpkg package manager to handle the Boost dependency. See the official Vcpkg guide for installation.
-   A build tool like **Ninja** or `make`. Ninja is recommended and can be installed via `brew install ninja` on macOS.

---

## ⚙️ Build Instructions

### Clone the Repository:

```bash
git clone https://github.com/daven-c/Fault-Tolerant-KV-Store
cd <local_path>/Fault-Tolerant-KV-Store
```

### Install Dependencies with Vcpkg:

```bash
# Make sure you have bootstrapped vcpkg first!
vcpkg install boost
```

### Configure the Project with CMake:

Create a build directory and run CMake. You must provide the path to the Vcpkg toolchain file.

```bash
mkdir build
cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=<path-to-your-vcpkg-dir>/scripts/buildsystems/vcpkg.cmake
```

**Example for macOS:**

```bash
cmake .. -DCMAKE_TOOLCHAIN_FILE=~/vcpkg/scripts/buildsystems/vcpkg.cmake
```

### Build the Project:

Use CMake's build command, which will automatically use either Ninja or Make, depending on your system configuration.

```bash
# This command must be run from inside the 'build' directory
cmake --build .
```

This will compile and create two executables inside the build directory: **server** and **console**.

---

## ▶️ Usage

### Running the Distributed Server

To run a fault-tolerant cluster, you need to start multiple server instances and tell each one about its peers.

**Example: Starting a 3-Node Cluster**

Open three separate terminals.

**Terminal 1 (Node 0):**

```bash
./server 0 127.0.0.1:8000 127.0.0.1:8001 127.0.0.1:8002
```

**Terminal 2 (Node 1):**

```bash
./server 1 127.0.0.1:8000 127.0.0.1:8001 127.0.0.1:8002
```

**Terminal 3 (Node 2):**

```bash
./server 2 127.0.0.1:8000 127.0.0.1:8001 127.0.0.1:8002
```

After a few seconds, an election will occur, and one node will print that it has become the leader. You can connect to any node in the cluster with a tool like `netcat` to send commands:

```bash
# Connect to node 1
nc 127.0.0.1 8001

# Send commands
SET name Test
GET name
```

---

### Running the Console Client Utility

The `console` executable is a simple command-line tool for testing the KeyValueStore and its AOF persistence directly, without any networking.

Navigate to the build directory.

Run the executable:

```bash
./console
```

This will create a file named `console_store.aof` in the build directory to store its data. You can exit and restart the console client, and it will reload its previous state.

---

## 🐛 Troubleshooting

-   **CMake Error: "Could not find toolchain file"**: This means the path provided to `-DCMAKE_TOOLCHAIN_FILE` is incorrect. Double-check the absolute path to your Vcpkg installation.
-   **Build fails with C++20 errors (`jthread`, `stop_token`, etc.)**: Ensure you have a modern C++ compiler and that CMake is correctly configured to use the C++20 standard. The included `CMakeLists.txt` file requests this automatically.
