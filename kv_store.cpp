#include "kv_store.h"
#include <iostream>

using namespace std;

void KeyValueStore::set(const string& key, const string& value) {
    store[key] = value;
    cout << "OK" << endl;
}

void KeyValueStore::get(const string& key) {
    if (store.count(key)) {
        cout << "\"" << store[key] << "\"" << endl;
    } else {
        cout << "(nil)" << endl;
    }
}

void KeyValueStore::del(const string& key) {
    if (store.erase(key)) {
        cout << "1" << endl;
    } else {
        cout << "0" << endl;
    }
}
