#ifndef RAFT_H
#define RAFT_H

#include "kv_store.h"
#include <boost/asio.hpp>
#include <chrono>
#include <cstdio>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

enum class RaftState { Follower, Candidate, Leader };

struct LogEntry {
    int term;
    std::string command;
};

class RaftNode : public std::enable_shared_from_this<RaftNode> {
public:
    RaftNode(int id, const std::vector<std::string>& peer_addresses,
             KeyValueStore& store, boost::asio::io_context& io_context,
             const std::string& state_path);
    ~RaftNode();

    void start();
    void stop();
    void submit_command(const std::string& command, std::function<void(const std::string&)> callback);
    std::string handle_rpc(const std::string& request);

private:
    void reset_election_timer();
    void start_election();
    void become_leader();
    void broadcast_append_entries();
    void replicate_to(int peer_index);
    void send_append_entries(int peer_index);
    void advance_commit_index();
    void step_down(int new_term);
    // Durable Raft state (term, vote, log, applied index) in an append-only file.
    void load_state();
    void persist_term_and_vote();
    void persist_entries(size_t from_index);
    void persist_applied();
    void append_state(const std::string& records, bool durable);

    void send_rpc(const std::string& peer_address, const std::string& rpc_message, std::function<void(const std::string&)> callback);

    int id_;
    int current_term_{0};
    int voted_for_{-1};
    int current_leader_id_{-1};
    std::vector<LogEntry> log_;
    RaftState state_{RaftState::Follower};

    int commit_index_{0};
    int last_applied_{0};

    std::vector<int> next_index_;
    std::vector<int> match_index_;
    std::vector<bool> append_in_flight_;
    std::vector<std::chrono::steady_clock::time_point> append_sent_at_;
    int votes_received_{0};
    
    std::map<int, std::function<void(const std::string&)>> client_callbacks_;
    
    KeyValueStore& kv_store_;
    std::string state_path_;
    std::FILE* state_file_{nullptr};
    std::vector<std::string> peer_addresses_;
    boost::asio::io_context& io_context_;
    boost::asio::steady_timer election_timer_;
    boost::asio::steady_timer heartbeat_timer_;
    std::mutex mutex_;
};

#endif // RAFT_H

