#include <iostream>
#include <string>
#include <sstream>
#include <vector>
#include "kv_store.h"

using namespace std;

int main() {
    KeyValueStore kv;
    string line;

    cout << "C++ Key-Value Store CLI" << endl;
    cout << "Commands: SET key value, GET key, DEL key, EXIT" << endl;

    while (true) {
        cout << "> ";
        getline(cin, line);
        
        stringstream ss(line);

        string command;
        ss >> command;

        if (command == "SET") {
            string key, value;
            ss >> key >> value;
            if (key.empty() || value.empty()) {
                cout << "Error: SET command requires a key and a value." << endl;
                continue;
            }
            kv.set(key, value);
        } else if (command == "GET") {
            string key;
            ss >> key;
            kv.get(key);
        } else if (command == "DEL") {
            string key;
            ss >> key;
            kv.del(key);
        } else if (command == "EXIT") {
            cout << "Exiting..." << endl;
            break;
        } else {
            cout << "Uknown command: " << command << endl;
        }
    }

    return 0;
}