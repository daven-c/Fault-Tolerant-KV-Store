#include "kv_store.h"
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

// --- Helper Functions ---

// Parses a single argument from the string stream.
// If the argument starts with a double quote, it reads until the matching closing quote.
// Otherwise, it reads until the next whitespace character.
std::string parse_argument(std::stringstream& ss) {
    std::string arg;
    ss >> std::ws; // Consume leading whitespace

    if (ss.peek() == '"') {
        ss.get(); // Consume the opening quote
        std::getline(ss, arg, '"'); // Read everything until the closing quote
    } else {
        ss >> arg; // Read until the next whitespace
    }
    return arg;
}

// --- KeyValueStore Implementation ---

KeyValueStore::KeyValueStore(const std::string& aof_path) : aof_path_(aof_path) {
    std::cout << "Initializing KeyValueStore with AOF: " << aof_path_ << std::endl;
    load_from_aof();
}

void KeyValueStore::load_from_aof() {
    std::ifstream aof_file(aof_path_);
    if (!aof_file.is_open()) {
        std::cout << "AOF file not found. Starting with an empty state." << std::endl;
        return;
    }

    std::cout << "Loading commands from " << aof_path_ << "..." << std::endl;
    std::string line;
    int commands_replayed = 0;
    while (std::getline(aof_file, line)) {
        if (line.empty()) continue;
        
        // Apply command to in-memory store, but do not re-write to AOF.
        std::lock_guard<std::mutex> lock(mutex_);
        std::stringstream ss(line);
        std::string command = parse_argument(ss);

        if (command == "SET") {
            std::string key = parse_argument(ss);
            std::string value = parse_argument(ss);
            if (!key.empty()) { // Value can be empty
                store_[key] = value;
            }
        } else if (command == "DEL") {
            std::string key = parse_argument(ss);
            if (!key.empty()) {
                store_.erase(key);
            }
        }
        commands_replayed++;
    }
    std::cout << "Replayed " << commands_replayed << " commands from AOF." << std::endl;
}

std::string KeyValueStore::apply_command(const std::string& command) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    std::stringstream ss(command);
    std::string command_type = parse_argument(ss);

    if (command_type == "SET") {
        std::string key = parse_argument(ss);
        std::string value;

        // Special handling for value to capture everything remaining, even with spaces
        ss >> std::ws;
        if (ss.peek() == '"') {
             ss.get(); // Consume quote
             std::getline(ss, value, '"');
        } else {
             std::getline(ss, value);
        }

        if (key.empty()) {
            return "ERR wrong number of arguments for 'SET' command\n";
        }
        
        // Persist to AOF in a canonical, quoted format before applying to memory
        std::string canonical_command = "SET \"" + key + "\" \"" + value + "\"";
        std::ofstream aof_file(aof_path_, std::ios::app);
        aof_file << canonical_command << std::endl;

        store_[key] = value;
        return "OK\n";

    } else if (command_type == "GET") {
        std::string key = parse_argument(ss);
        if (key.empty()) {
             return "ERR wrong number of arguments for 'GET' command\n";
        }
        if (store_.count(key)) {
            return "\"" + store_.at(key) + "\"\n";
        } else {
            return "(nil)\n";
        }
    } else if (command_type == "DEL") {
        std::string key = parse_argument(ss);
        if (key.empty()) {
             return "ERR wrong number of arguments for 'DEL' command\n";
        }

        // Persist to AOF in a canonical, quoted format before applying to memory
        std::string canonical_command = "DEL \"" + key + "\"";
        std::ofstream aof_file(aof_path_, std::ios::app);
        aof_file << canonical_command << std::endl;

        if (store_.erase(key)) {
            return "1\n";
        } else {
            return "0\n";
        }
    } else if (command_type == "KEYS") {
        if (store_.empty()) {
            return "(empty list or set)\n";
        }
        std::string result;
        int i = 1;
        for (const auto& pair : store_) {
            result += std::to_string(i++) + ") \"" + pair.first + "\"\n";
        }
        return result;
    }
    
    return "ERR unknown command '" + command_type + "'\n";
}

