#include "kv_store.h"
#include <fstream>
#include <iostream>
#include <sstream>

KeyValueStore::KeyValueStore(const std::string& aof_path) : aof_path_(aof_path) {
    std::cout << "Initializing KeyValueStore with AOF: " << aof_path_ << std::endl;
    load_from_aof();
}

void KeyValueStore::load_from_aof() {
    std::ifstream aof_file(aof_path_);
    if (!aof_file.is_open()) {
        std::cerr << "AOF file not found. Starting with an empty state." << std::endl;
        return;
    }
    
    std::cout << "Loading commands from " << aof_path_ << "..." << std::endl;
    std::string line;
    int commands_replayed = 0;
    while (std::getline(aof_file, line)) {
        if (!line.empty()) {
            // Apply command to in-memory store, but do not re-write to AOF.
             std::lock_guard<std::mutex> lock(mutex_);
            std::stringstream ss(line);
            std::string command;
            ss >> command;
            if (command == "SET") {
                std::string key, value;
                ss >> key;
                std::getline(ss, value);
                if (!value.empty() && value[0] == ' ') value = value.substr(1);
                store_[key] = value;
            } else if (command == "DEL") {
                std::string key;
                ss >> key;
                store_.erase(key);
            }
            commands_replayed++;
        }
    }
    std::cout << "Replayed " << commands_replayed << " commands from AOF." << std::endl;
}

std::string KeyValueStore::apply_command(const std::string& command) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    std::stringstream ss(command);
    std::string command_type, key, value;
    ss >> command_type;

    if (command_type == "SET") {
        if (!(ss >> key)) { // Check if we can extract a key
            return "ERROR: SET command requires a key.\n";
        }
        
        std::getline(ss, value); // Read the rest of the line as the value
        if (!value.empty() && value[0] == ' ') {
             value = value.substr(1);
        }

        if (value.empty()) { // Check that a value was actually provided
            return "ERROR: SET command requires a value.\n";
        }
        
        // Persist to AOF only after validation
        std::ofstream aof_file(aof_path_, std::ios::app);
        aof_file << command << std::endl;

        store_[key] = value;
        return "OK\n";

    } else if (command_type == "GET") {
        ss >> key;
        if (store_.count(key)) {
            return "\"" + store_.at(key) + "\"\n";
        } else {
            return "(nil)\n";
        }
    } else if (command_type == "DEL") {
        if (!(ss >> key)) { // Check if we can extract a key
            return "ERROR: DEL command requires a key.\n";
        }

        // Persist to AOF before applying to memory
        std::ofstream aof_file(aof_path_, std::ios::app);
        aof_file << command << std::endl;

        if (store_.erase(key)) {
            return "1\n";
        } else {
            return "0\n";
        }
    } else if (command_type == "KEYS") {
        if (store_.empty()) {
            return "(empty list)\n";
        }
        std::string result;
        int i = 1;
        for (const auto& pair : store_) {
            result += std::to_string(i++) + ") \"" + pair.first + "\"\n";
        }
        return result;
    }
    
    if (command.empty() || command_type.empty()) {
        return "ERROR: Empty command.\n";
    }

    return "Unknown command\n";
}

