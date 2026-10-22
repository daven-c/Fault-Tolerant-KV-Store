#include "raft.h"
#include <algorithm>
#include <boost/asio/co_spawn.hpp>
#include <boost/asio/detached.hpp>
#include <boost/asio/post.hpp>
#include <boost/asio/use_awaitable.hpp>
#include <fstream>
#include <iostream>
#include <random>
#include <sstream>
#include <thread>
#include <unistd.h>

using boost::asio::ip::tcp;

RaftNode::RaftNode(int id, const std::vector<std::string>& peer_addresses,
                   KeyValueStore& store, boost::asio::io_context& io_context,
                   const std::string& state_path)
    : id_(id),
      kv_store_(store),
      state_path_(state_path),
      peer_addresses_(peer_addresses),
      io_context_(io_context),
      election_timer_(io_context),
      heartbeat_timer_(io_context) {
    log_.push_back({0, ""}); // Sentinel entry
    load_state();
    state_file_ = std::fopen(state_path_.c_str(), "a");
    if (!state_file_) {
        throw std::runtime_error("cannot open Raft state file " + state_path_);
    }
}

RaftNode::~RaftNode() {
    if (state_file_) std::fclose(state_file_);
}

// --- Durable state ---
//
// Records, one per line, replayed in order on startup:
//   T <term> <voted_for>        current term and vote
//   E <index> <term> <command>  log entry; an index at or below the current length truncates first
//   A <index>                   last applied index (the KV store's AOF already holds that state)

void RaftNode::load_state() {
    std::ifstream in(state_path_);
    if (!in.is_open()) return;

    int applied = 0;
    std::string line;
    while (std::getline(in, line)) {
        if (in.eof()) break; // torn final record from a crash mid-write
        std::stringstream ss(line);
        char kind;
        ss >> kind;
        if (kind == 'T') {
            ss >> current_term_ >> voted_for_;
        } else if (kind == 'E') {
            size_t index;
            int term;
            ss >> index >> term >> std::ws;
            std::string command;
            std::getline(ss, command);
            if (index == 0 || index > log_.size()) continue;
            log_.resize(index);
            log_.push_back({term, command});
        } else if (kind == 'A') {
            ss >> applied;
        }
    }
    // Applied entries were committed, and their effects are already in the AOF.
    last_applied_ = commit_index_ = std::min(applied, (int)log_.size() - 1);
    std::cout << "[Node " << id_ << "] Restored term " << current_term_ << ", vote " << voted_for_
              << ", " << log_.size() - 1 << " log entries, applied through " << last_applied_ << "." << std::endl;
}

void RaftNode::append_state(const std::string& records, bool durable) {
    std::fwrite(records.data(), 1, records.size(), state_file_);
    std::fflush(state_file_);
    if (durable) ::fsync(fileno(state_file_));
}

void RaftNode::persist_term_and_vote() {
    // Must be durable before any vote or RPC reply in this term leaves the node.
    append_state("T " + std::to_string(current_term_) + " " + std::to_string(voted_for_) + "\n", true);
}

void RaftNode::persist_entries(size_t from_index) {
    // Must be durable before the entries are acknowledged to the leader (or counted by it).
    std::string records;
    for (size_t i = from_index; i < log_.size(); ++i) {
        records += "E " + std::to_string(i) + " " + std::to_string(log_[i].term) + " " + log_[i].command + "\n";
    }
    if (!records.empty()) append_state(records, true);
}

void RaftNode::persist_applied() {
    // Not fsynced: losing it only means re-applying a suffix of SET/DEL commands on top of a state
    // that already contains them, which leaves the same final state.
    append_state("A " + std::to_string(last_applied_) + "\n", false);
}

void RaftNode::start() {
    std::cout << "[Node " << id_ << "] Starting." << std::endl;
    reset_election_timer();
}

void RaftNode::stop() {
    election_timer_.cancel();
    heartbeat_timer_.cancel();
    std::cout << "[Node " << id_ << "] Stopped." << std::endl;
}

void RaftNode::reset_election_timer() {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> distrib(300, 500);
    const auto timeout = std::chrono::milliseconds(distrib(gen));
    election_deadline_ = std::chrono::steady_clock::now() + timeout;
    election_timer_.expires_after(timeout);
    election_timer_.async_wait([this, self = shared_from_this()](const boost::system::error_code& ec) {
        if (!ec) {
            std::lock_guard<std::mutex> lock(mutex_);
            // The timer can fire and queue this handler while another thread holds the mutex
            // (e.g. handling an AppendEntries); resetting the timer then doesn't cancel it. Only
            // campaign if no reset has pushed the deadline past now.
            if (state_ != RaftState::Leader && std::chrono::steady_clock::now() >= election_deadline_) {
                start_election();
            }
        }
    });
}

void RaftNode::start_election() {
    // This function is called WITH THE MUTEX HELD.
    state_ = RaftState::Candidate;
    current_term_++;
    voted_for_ = id_;
    persist_term_and_vote();
    votes_received_ = 1;
    current_leader_id_ = -1;

    std::cout << "[Node " << id_ << "] Timed out, starting election for term " << current_term_ << "." << std::endl;

    for (size_t i = 0; i < peer_addresses_.size(); ++i) {
        if (i == (size_t)id_) continue;
        
        std::stringstream rpc;
        rpc << "RequestVote " << current_term_ << " " << id_ << " " << (log_.size() - 1) << " " << log_.back().term << "\n";
        
        send_rpc(peer_addresses_[i], rpc.str(), [this, self = shared_from_this(), election_term = current_term_](const std::string& res) {
            std::lock_guard<std::mutex> lock(mutex_);
            if (state_ != RaftState::Candidate) return;

            if (res == "RPC_FAILED\n") return;

            std::stringstream ss(res);
            std::string result;
            int term;
            ss >> result >> term;

            if (term > current_term_) {
                step_down(term);
                return;
            }

            // A late reply from an earlier election must not count towards this one.
            if (current_term_ != election_term || term != election_term) return;

            if (result == "VoteGranted") {
                votes_received_++;
                if (votes_received_ > peer_addresses_.size() / 2) {
                    become_leader();
                }
            }
        });
    }
    reset_election_timer();
}

void RaftNode::become_leader() {
    // This function is called WITH THE MUTEX HELD.
    if (state_ != RaftState::Candidate) return;

    state_ = RaftState::Leader;
    current_leader_id_ = id_;
    std::cout << "[Node " << id_ << "] Became LEADER for term " << current_term_ << "!" << std::endl;
    election_timer_.cancel();

    // A leader may only commit entries from earlier terms indirectly, by committing one from its
    // own term (Raft §5.4.2). Append a no-op so they commit now, not on the next client write.
    log_.push_back({current_term_, ""});
    persist_entries(log_.size() - 1);

    next_index_.assign(peer_addresses_.size(), log_.size() - 1);
    match_index_.assign(peer_addresses_.size(), 0);
    append_in_flight_.assign(peer_addresses_.size(), false);
    append_sent_at_.assign(peer_addresses_.size(), std::chrono::steady_clock::time_point{});

    broadcast_append_entries();
}

void RaftNode::broadcast_append_entries() {
    // This function is called WITH THE MUTEX HELD.
    if (state_ != RaftState::Leader) return;

    for (size_t i = 0; i < peer_addresses_.size(); ++i) {
        if (i != (size_t)id_) {
            replicate_to(i);
        }
    }

    heartbeat_timer_.expires_after(std::chrono::milliseconds(150));
    heartbeat_timer_.async_wait([this, self = shared_from_this()](const boost::system::error_code& ec) {
        if (!ec) {
            std::lock_guard<std::mutex> lock(mutex_);
            if (state_ == RaftState::Leader) {
                broadcast_append_entries();
            }
        }
    });
}

void RaftNode::replicate_to(int peer_index) {
    // This function is called WITH THE MUTEX HELD.
    // Keep at most one AppendEntries in flight per follower: entries that arrive meanwhile are
    // batched into the next RPC, sent as soon as the response comes back. A request that has
    // been outstanding too long is presumed lost and superseded.
    if (append_in_flight_[peer_index] &&
        std::chrono::steady_clock::now() - append_sent_at_[peer_index] < std::chrono::milliseconds(300)) {
        return;
    }
    send_append_entries(peer_index);
}

void RaftNode::send_append_entries(int peer_index) {
    // This function is called WITH THE MUTEX HELD.
    if (state_ != RaftState::Leader) return;

    int prev_log_index = next_index_[peer_index] - 1;
    int prev_log_term = log_[prev_log_index].term;

    std::stringstream rpc;
    rpc << "AppendEntries " << current_term_ << " " << id_ << " " << prev_log_index << " " << prev_log_term << " " << commit_index_;

    // Cap the batch: a follower far behind (e.g. after a restart) gets a stream of bounded RPCs
    // rather than one huge message that outlasts its election timeout and triggers an election.
    size_t entries_to_send = std::min(log_.size() - next_index_[peer_index], kMaxEntriesPerAppend);
    for (size_t i = 0; i < entries_to_send; ++i) {
        const auto& entry = log_[next_index_[peer_index] + i];
        // We add a separator character (\x01) to properly handle commands with spaces.
        rpc << " " << entry.term << " " << entry.command << "\x01";
    }
    rpc << "\n";
    const std::string rpc_message = rpc.str();
    const int sent_term = current_term_;
    append_in_flight_[peer_index] = true;
    append_sent_at_[peer_index] = std::chrono::steady_clock::now();

    // Release the lock before the async network call
    boost::asio::post(io_context_, [this, self = shared_from_this(), peer_index, prev_log_index, entries_to_send, sent_term, rpc_message]() {
        send_rpc(peer_addresses_[peer_index], rpc_message, [this, self, peer_index, prev_log_index, entries_to_send, sent_term](const std::string& response) {
            std::lock_guard<std::mutex> lock(mutex_);
            // Ignore responses that belong to an earlier leadership term.
            if (state_ != RaftState::Leader || current_term_ != sent_term) return;
            append_in_flight_[peer_index] = false;

            if (response == "RPC_FAILED\n") return; // the heartbeat will retry

            std::stringstream ss(response);
            std::string result;
            int term;
            ss >> result >> term;

            if (term > current_term_) {
                step_down(term);
                return;
            }

            if (result == "Success") {
                // Credit the follower only with the entries this RPC carried; the leader's log may
                // have grown since it was sent. Responses can arrive out of order, so never regress.
                int replicated_up_to = prev_log_index + (int)entries_to_send;
                match_index_[peer_index] = std::max(match_index_[peer_index], replicated_up_to);
                next_index_[peer_index] = match_index_[peer_index] + 1;
                advance_commit_index();
                if (next_index_[peer_index] < (int)log_.size()) {
                    send_append_entries(peer_index);
                }
            } else {
                // The follower reports where its log diverges, so jump there in one step instead
                // of backing off one entry per heartbeat, and retry immediately.
                int conflict_index = next_index_[peer_index] - 1;
                ss >> conflict_index;
                next_index_[peer_index] = std::clamp(conflict_index, 1, std::max(1, next_index_[peer_index] - 1));
                send_append_entries(peer_index);
            }
        });
    });
}


void RaftNode::advance_commit_index() {
    // This function is called WITH THE MUTEX HELD.
    int old_commit_index = commit_index_;
    for (int N = log_.size() - 1; N > commit_index_; --N) {
        if (log_[N].term == current_term_) {
            int count = 1;
            for (size_t i = 0; i < peer_addresses_.size(); ++i) {
                if (i != (size_t)id_ && match_index_[i] >= N) {
                    count++;
                }
            }
            if (count > peer_addresses_.size() / 2) {
                commit_index_ = N;
                break;
            }
        }
    }

    if (commit_index_ > old_commit_index) {
        while (last_applied_ < commit_index_) {
            last_applied_++;
            const auto& entry = log_[last_applied_];
            if (entry.command.empty()) continue; // leader no-op
            std::string result = kv_store_.apply_command(entry.command);

            if (client_callbacks_.count(last_applied_)) {
                auto callback = client_callbacks_[last_applied_];
                boost::asio::post(io_context_, [callback, result]() {
                    callback(result);
                });
                client_callbacks_.erase(last_applied_);
            }
        }
        persist_applied();
    }
}

void RaftNode::step_down(int new_term) {
    // This function is called WITH THE MUTEX HELD.
    state_ = RaftState::Follower;
    current_term_ = new_term;
    voted_for_ = -1;
    persist_term_and_vote();
    current_leader_id_ = -1;
    heartbeat_timer_.cancel();
    reset_election_timer();
}

std::string RaftNode::handle_rpc(const std::string& request) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::stringstream ss(request);
    std::string rpc_type;
    ss >> rpc_type;

    if (rpc_type == "RequestVote") {
        int term, candidate_id, last_log_index, last_log_term;
        ss >> term >> candidate_id >> last_log_index >> last_log_term;
        
        if (term > current_term_) step_down(term);
        
        bool log_ok = (last_log_term > log_.back().term) || (last_log_term == log_.back().term && last_log_index >= (int)(log_.size() - 1));

        if (term == current_term_ && log_ok && (voted_for_ == -1 || voted_for_ == candidate_id)) {
            voted_for_ = candidate_id;
            persist_term_and_vote();
            reset_election_timer();
            return "VoteGranted " + std::to_string(current_term_) + "\n";
        }
        return "VoteDenied " + std::to_string(current_term_) + "\n";
    }

    if (rpc_type == "AppendEntries") {
        int term, leader_id, prev_log_index, prev_log_term, leader_commit;
        ss >> term >> leader_id >> prev_log_index >> prev_log_term >> leader_commit;
        
        if (term > current_term_) step_down(term);
        if (term < current_term_) return "Fail " + std::to_string(current_term_) + "\n";
        
        reset_election_timer();
        if (state_ != RaftState::Follower) {
           state_ = RaftState::Follower;
        }
        current_leader_id_ = leader_id;


        if (log_.size() <= (size_t)prev_log_index) {
            // Log too short: the leader should resume right after our last entry.
            return "Fail " + std::to_string(current_term_) + " " + std::to_string(log_.size()) + "\n";
        }
        if (log_[prev_log_index].term != prev_log_term) {
            // Term conflict: skip back past every entry of the conflicting term at once.
            int conflict_term = log_[prev_log_index].term;
            int conflict_index = prev_log_index;
            while (conflict_index > 1 && log_[conflict_index - 1].term == conflict_term) --conflict_index;
            return "Fail " + std::to_string(current_term_) + " " + std::to_string(conflict_index) + "\n";
        }

        // Correctly parse multiple log entries, even with spaces in commands.
        std::vector<LogEntry> entries;
        std::string entries_payload;
        // Read the rest of the line, which contains the log entries.
        std::getline(ss, entries_payload);

        std::stringstream entries_ss(entries_payload);
        std::string single_entry_str;
        // Split entries by our separator character.
        while (std::getline(entries_ss, single_entry_str, '\x01')) {
            if (single_entry_str.empty() || single_entry_str.find_first_not_of(' ') == std::string::npos) {
                continue;
            }
            std::stringstream entry_ss(single_entry_str);
            int entry_term;
            entry_ss >> entry_term;
            entry_ss >> std::ws; // skip whitespace
            std::string entry_command;
            std::getline(entry_ss, entry_command);
            entries.push_back({entry_term, entry_command});
        }

        // Truncate only at the first entry that conflicts with the leader's (same index, different
        // term). Entries we already hold are kept, so a stale, shorter AppendEntries arriving out
        // of order can never remove entries the leader has counted as replicated.
        size_t first_changed = log_.size();
        for (size_t i = 0; i < entries.size(); ++i) {
            size_t index = prev_log_index + 1 + i;
            if (index < log_.size()) {
                if (log_[index].term == entries[i].term) continue;
                log_.erase(log_.begin() + index, log_.end());
            }
            first_changed = std::min(first_changed, log_.size());
            log_.push_back(entries[i]);
        }
        persist_entries(first_changed);

        // Only entries confirmed by this RPC may be committed; anything beyond may be stale.
        int last_new_index = prev_log_index + (int)entries.size();
        if (leader_commit > commit_index_) {
            commit_index_ = std::max(commit_index_, std::min(leader_commit, last_new_index));
        }

        if (last_applied_ < commit_index_) {
            while (last_applied_ < commit_index_) {
                last_applied_++;
                if (log_[last_applied_].command.empty()) continue; // leader no-op
                kv_store_.apply_command(log_[last_applied_].command);
            }
            persist_applied();
        }

        return "Success " + std::to_string(current_term_) + "\n";
    }
    return "UnknownRPC\n";
}

std::string RaftNode::status_json() {
    std::lock_guard<std::mutex> lock(mutex_);
    const char* state = state_ == RaftState::Leader ? "leader"
                      : state_ == RaftState::Candidate ? "candidate" : "follower";
    std::stringstream out;
    out << "{\"id\":" << id_ << ",\"state\":\"" << state << "\",\"term\":" << current_term_
        << ",\"voted_for\":" << voted_for_ << ",\"leader\":" << current_leader_id_
        << ",\"log\":" << log_.size() - 1 << ",\"last_log_term\":" << log_.back().term
        << ",\"commit\":" << commit_index_ << ",\"applied\":" << last_applied_
        << ",\"keys\":" << kv_store_.size() << ",\"match\":[";
    if (state_ == RaftState::Leader) {
        for (size_t i = 0; i < match_index_.size(); ++i) {
            if (i) out << ",";
            out << (i == (size_t)id_ ? (int)log_.size() - 1 : match_index_[i]);
        }
    }
    out << "]}\n";
    return out.str();
}

void RaftNode::submit_command(const std::string& command, std::function<void(const std::string&)> callback) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (state_ != RaftState::Leader) {
        std::string response = "NOT_LEADER";
        if (current_leader_id_ != -1 && current_leader_id_ < (int)peer_addresses_.size()) {
            response += " " + peer_addresses_[current_leader_id_];
        }
        response += "\n";

        boost::asio::post(io_context_, [callback, response]() { callback(response); });
        return;
    }

    log_.push_back({current_term_, command});
    int new_log_index = log_.size() - 1;
    persist_entries(new_log_index);
    client_callbacks_[new_log_index] = callback;

    // Replicate now rather than waiting for the next heartbeat.
    for (size_t i = 0; i < peer_addresses_.size(); ++i) {
        if (i != (size_t)id_) {
            replicate_to(i);
        }
    }
    if (peer_addresses_.size() == 1) advance_commit_index();

    std::cout << "[Node " << id_ << "] Leader received command: '" << command << "'. Appending at index " << new_log_index << "." << std::endl;
}

std::shared_ptr<tcp::socket> RaftNode::take_idle_connection(const std::string& peer_address) {
    std::lock_guard<std::mutex> lock(connections_mutex_);
    auto& idle = idle_connections_[peer_address];
    if (idle.empty()) return nullptr;
    auto socket = idle.back();
    idle.pop_back();
    return socket;
}

void RaftNode::return_idle_connection(const std::string& peer_address, std::shared_ptr<tcp::socket> socket) {
    std::lock_guard<std::mutex> lock(connections_mutex_);
    auto& idle = idle_connections_[peer_address];
    if (idle.size() < kMaxIdleConnectionsPerPeer) idle.push_back(std::move(socket));
}

void RaftNode::send_rpc(const std::string& peer_address, const std::string& rpc_message, std::function<void(const std::string&)> callback) {
    auto self = shared_from_this();
    boost::asio::co_spawn(io_context_, [this, self, peer_address, rpc_message, callback]() -> boost::asio::awaitable<void> {
        // Reuse an idle connection to the peer when there is one. If a reused connection turns out
        // to be dead (e.g. the peer restarted), retry once on a fresh one; Raft RPCs are idempotent.
        for (int attempt = 0; attempt < 2; ++attempt) {
            std::shared_ptr<tcp::socket> socket = take_idle_connection(peer_address);
            const bool reused = socket != nullptr;
            try {
                if (!reused) {
                    tcp::resolver resolver(io_context_);
                    size_t colon_pos = peer_address.find(':');
                    std::string host = peer_address.substr(0, colon_pos);
                    std::string port = peer_address.substr(colon_pos + 1);

                    auto endpoints = co_await resolver.async_resolve(host, port, boost::asio::use_awaitable);
                    socket = std::make_shared<tcp::socket>(io_context_);
                    co_await boost::asio::async_connect(*socket, endpoints, boost::asio::use_awaitable);
                    socket->set_option(tcp::no_delay(true));
                }
                co_await boost::asio::async_write(*socket, boost::asio::buffer(rpc_message), boost::asio::use_awaitable);

                boost::asio::streambuf response_buffer;
                co_await boost::asio::async_read_until(*socket, response_buffer, "\n", boost::asio::use_awaitable);

                std::istream is(&response_buffer);
                std::string response;
                std::getline(is, response);
                response += "\n";

                return_idle_connection(peer_address, socket);
                boost::asio::post(io_context_, [callback, response](){ callback(response); });
                co_return;
            } catch (std::exception& e) {
                if (!reused) break;
            }
        }
        boost::asio::post(io_context_, [callback](){ callback("RPC_FAILED\n"); });
    }, boost::asio::detached);
}
