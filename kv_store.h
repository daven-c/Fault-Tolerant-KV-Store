#ifndef KV_STORE_H
#define KV_STORE_H

#include <string>
#include <unordered_map>

using namespace std;

class KeyValueStore {
private: 
    unordered_map<string, string> store;

public:
    void set(const string& key, const string& value);
    void get(const string& key);
    void del(const string& key);
};

#endif
