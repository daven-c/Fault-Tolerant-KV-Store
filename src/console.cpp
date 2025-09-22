#include "kv_store.h"
#include <iostream>
#include <string>

int main() {
    // The KeyValueStore now requires a path for its Append-Only File.
    // This gives our console a persistent state between runs.
    KeyValueStore kv_store("console_store.aof");
    std::string line;

    std::cout << "C++ Key-Value Store CLI" << std::endl;
    std::cout << "Commands: SET key value, GET key, DEL key, EXIT" << std::endl;

    while (std::cout << "> " && std::getline(std::cin, line) && line != "EXIT") {
        if (!line.empty()) {
            // We now use the process_client_command method, which handles
            // both logging the command to the AOF and applying it to the store.
            std::cout << kv_store.apply_command(line);
        }
    }
        
    return 0;
}
