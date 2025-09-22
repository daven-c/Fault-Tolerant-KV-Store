cmake_minimum_required(VERSION 3.15)
project(DistributedKeyValueStore CXX)

# Require C++20 for std::jthread and coroutines
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find Boost using the modern, config-based approach.
find_package(Boost 1.71.0 REQUIRED COMPONENTS system thread)

# --- EXECUTABLE TARGETS ---

# Add the main server executable
add_executable(server src/server.cpp src/raft.cpp src/kv_store.cpp)

# Add the console client executable
add_executable(console src/console.cpp src/kv_store.cpp)


# --- INCLUDE DIRECTORIES ---
target_include_directories(server PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_include_directories(console PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)


# --- LINK LIBRARIES & DEFINITIONS ---

# Link the server against Boost and enable coroutine support
target_link_libraries(server PRIVATE Boost::system Boost::thread)
target_compile_definitions(server PRIVATE BOOST_ASIO_HAS_CO_AWAIT)

# --- INFORMATIVE MESSAGES ---
message(STATUS "Using Boost version: ${Boost_VERSION_STRING}")

