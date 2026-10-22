#ifndef KV_STORE_H
#define KV_STORE_H

#include <fstream>
#include <mutex>
#include <string>
#include <unordered_map>

class KeyValueStore {
public:
    explicit KeyValueStore(const std::string& aof_path);
    
    // Applies a command to the in-memory store AND logs it to the AOF.
    // This is the single entry point for changing state. If `aof_records` is given, the AOF lines
    // are appended to it for the caller to write later (with append_to_aof) instead of written now.
    std::string apply_command(const std::string& command, std::string* aof_records = nullptr);
    void append_to_aof(const std::string& records);
    size_t size();

private:
    void load_from_aof();

    std::unordered_map<std::string, std::string> store_;
    std::string aof_path_;
    std::mutex mutex_;
};

#endif // KV_STORE_H

