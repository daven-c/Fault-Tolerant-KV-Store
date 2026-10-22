#ifndef RAFT_H
#define RAFT_H

#include "kv_store.h"
#include <boost/asio.hpp>
#include <chrono>
#include <climits>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
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
    // Replies through `reply` once any state the reply depends on is on disk (possibly later, from
    // the persistence thread), so no thread ever blocks on the disk.
    void handle_rpc(const std::string& request, std::function<void(const std::string&)> reply);
    // One-line JSON snapshot of this node's Raft state, answered locally (not replicated).
    std::string status_json();

private:
    void reset_election_timer();
    void start_election();
    void request_votes();
    void become_leader();
    void broadcast_append_entries();
    void replicate_to(int peer_index);
    void send_append_entries(int peer_index);
    void advance_commit_index();
    uint64_t step_down(int new_term);
    // Durable Raft state (term, vote, log, applied index) in an append-only file. Records are
    // queued under mutex_ and written + fsynced in batches by persist_thread_ without holding it
    // (group commit), so a slow disk never stalls heartbeats or replication. Each persist_* call
    // returns a sequence number to pass to after_durable() when the record must be on disk first.
    void load_state();
    uint64_t persist_term_and_vote();
    uint64_t persist_entries(size_t from_index);
    void persist_applied();
    uint64_t enqueue_state(const std::string& records);
    void after_durable(uint64_t seq, std::function<void()> action);
    void persist_loop();
    void stop_persistence();

    std::shared_ptr<boost::asio::ip::tcp::socket> take_idle_connection(const std::string& peer_address);
    void return_idle_connection(const std::string& peer_address, std::shared_ptr<boost::asio::ip::tcp::socket> socket);
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
    std::string persist_buf_;         // records queued for the next batch
    std::string aof_buf_;             // AOF lines from applied commands, written just before it
    uint64_t queued_seq_{0};          // sequence number of the last queued record
    uint64_t durable_seq_{0};         // ... and of the last one known to be on disk
    int queued_log_end_{0};           // last log index the queued E records describe
    int durable_log_end_{0};          // last log index known to be on disk
    int truncated_since_batch_{INT_MAX};  // lowest truncation queued after the batch in flight was taken
    bool persist_stop_{false};
    std::condition_variable persist_cv_;  // wakes the writer
    std::multimap<uint64_t, std::function<void()>> after_durable_;  // actions waiting on the disk
    std::thread persist_thread_;
    std::vector<std::string> peer_addresses_;
    boost::asio::io_context& io_context_;
    boost::asio::steady_timer election_timer_;
    std::chrono::steady_clock::time_point election_deadline_{};
    boost::asio::steady_timer heartbeat_timer_;
    std::mutex mutex_;

    static constexpr size_t kMaxEntriesPerAppend = 2048;

    // Idle RPC connections per peer, reused instead of reconnecting for every RPC.
    static constexpr size_t kMaxIdleConnectionsPerPeer = 4;
    std::map<std::string, std::vector<std::shared_ptr<boost::asio::ip::tcp::socket>>> idle_connections_;
    std::mutex connections_mutex_;
};

#endif // RAFT_H

