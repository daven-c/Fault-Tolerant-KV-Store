#include "raft.h"
#include <boost/asio/co_spawn.hpp>
#include <boost/asio/detached.hpp>
#include <boost/asio/post.hpp>
#include <boost/asio/use_awaitable.hpp>
#include <iostream>
#include <random>
#include <sstream>
#include <thread>

using boost::asio::ip::tcp;

RaftNode::RaftNode(int id, const std::vector<std::string>& peer_addresses,
                   KeyValueStore& store, boost::asio::io_context& io_context)
    : id_(id),
      kv_store_(store),
      peer_addresses_(peer_addresses),
      io_context_(io_context),
      election_timer_(io_context),
      heartbeat_timer_(io_context) {
    log_.push_back({0, ""}); // Sentinel entry
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
    election_timer_.expires_after(std::chrono::milliseconds(distrib(gen)));
    election_timer_.async_wait([this, self = shared_from_this()](const boost::system::error_code& ec) {
        if (!ec) {
            std::lock_guard<std::mutex> lock(mutex_);
            if (state_ != RaftState::Leader) {
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
    votes_received_ = 1;
    current_leader_id_ = -1;

    std::cout << "[Node " << id_ << "] Timed out, starting election for term " << current_term_ << "." << std::endl;

    for (size_t i = 0; i < peer_addresses_.size(); ++i) {
        if (i == (size_t)id_) continue;
        
        std::stringstream rpc;
        rpc << "RequestVote " << current_term_ << " " << id_ << " " << (log_.size() - 1) << " " << log_.back().term << "\n";
        
        send_rpc(peer_addresses_[i], rpc.str(), [this, self = shared_from_this()](const std::string& res) {
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

    next_index_.assign(peer_addresses_.size(), log_.size());
    match_index_.assign(peer_addresses_.size(), 0);

    broadcast_append_entries();
}

void RaftNode::broadcast_append_entries() {
    // This function is called WITH THE MUTEX HELD.
    if (state_ != RaftState::Leader) return;

    for (size_t i = 0; i < peer_addresses_.size(); ++i) {
        if (i != (size_t)id_) {
            send_append_entries(i);
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


void RaftNode::send_append_entries(int peer_index) {
    // This function is called WITH THE MUTEX HELD.
    if (state_ != RaftState::Leader) return;

    int prev_log_index = next_index_[peer_index] - 1;
    int prev_log_term = log_[prev_log_index].term;

    std::stringstream rpc;
    rpc << "AppendEntries " << current_term_ << " " << id_ << " " << prev_log_index << " " << prev_log_term << " " << commit_index_;

    size_t entries_to_send = log_.size() - next_index_[peer_index];
    for (size_t i = 0; i < entries_to_send; ++i) {
        const auto& entry = log_[next_index_[peer_index] + i];
        rpc << " " << entry.term << " " << entry.command;
    }
    rpc << "\n";
    
    auto rpc_message = rpc.str();
    
    boost::asio::post(io_context_, [this, self = shared_from_this(), peer_index, entries_to_send, rpc_message]() {
        send_rpc(peer_addresses_[peer_index], rpc_message, [this, self, peer_index, entries_to_send](const std::string& response) {
            std::lock_guard<std::mutex> lock(mutex_);
            if (state_ != RaftState::Leader) return;

            if (response == "RPC_FAILED\n") return;

            std::stringstream ss(response);
            std::string result;
            int term;
            ss >> result >> term;

            if (term > current_term_) {
                step_down(term);
                return;
            }

            if (result == "Success") {
                next_index_[peer_index] = log_.size();
                match_index_[peer_index] = next_index_[peer_index] - 1;
                advance_commit_index();
            } else {
                next_index_[peer_index] = std::max(1, next_index_[peer_index] - 1);
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
            std::string result = kv_store_.apply_command(entry.command);

            if (client_callbacks_.count(last_applied_)) {
                auto callback = client_callbacks_[last_applied_];
                boost::asio::post(io_context_, [callback, result]() {
                    callback(result);
                });
                client_callbacks_.erase(last_applied_);
            }
        }
    }
}

void RaftNode::step_down(int new_term) {
    // This function is called WITH THE MUTEX HELD.
    state_ = RaftState::Follower;
    current_term_ = new_term;
    voted_for_ = -1;
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
        
        if (current_leader_id_ != leader_id) {
            std::cout << "[Node " << id_ << "] Acknowledging new leader: Node " << leader_id << "." << std::endl;
        }
        current_leader_id_ = leader_id;
        reset_election_timer();
        if (state_ == RaftState::Candidate) {
            state_ = RaftState::Follower;
             std::cout << "[Node " << id_ << "] Candidate stepping down to Follower state." << std::endl;
        }


        if (log_.size() <= (size_t)prev_log_index || log_[prev_log_index].term != prev_log_term) {
            return "Fail " + std::to_string(current_term_) + "\n";
        }

        log_.erase(log_.begin() + prev_log_index + 1, log_.end());

        int entry_term;
        std::string entry_command;
        while(ss >> entry_term >> entry_command) {
            log_.push_back({entry_term, entry_command});
        }
        
        if (leader_commit > commit_index_) {
            commit_index_ = std::min(leader_commit, (int)log_.size() - 1);
        }

        while (last_applied_ < commit_index_) {
            last_applied_++;
            kv_store_.apply_command(log_[last_applied_].command);
        }

        return "Success " + std::to_string(current_term_) + "\n";
    }
    return "UnknownRPC\n";
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
    client_callbacks_[new_log_index] = callback;

    std::cout << "[Node " << id_ << "] Leader received command: '" << command << "'. Appending at index " << new_log_index << "." << std::endl;
}

void RaftNode::send_rpc(const std::string& peer_address, const std::string& rpc_message, std::function<void(const std::string&)> callback) {
    auto self = shared_from_this();
    boost::asio::co_spawn(io_context_, [this, self, peer_address, rpc_message, callback]() -> boost::asio::awaitable<void> {
        try {
            tcp::resolver resolver(io_context_);
            size_t colon_pos = peer_address.find(':');
            std::string host = peer_address.substr(0, colon_pos);
            std::string port = peer_address.substr(colon_pos + 1);

            auto endpoints = co_await resolver.async_resolve(host, port, boost::asio::use_awaitable);
            tcp::socket socket(io_context_);
            co_await boost::asio::async_connect(socket, endpoints, boost::asio::use_awaitable);
            co_await boost::asio::async_write(socket, boost::asio::buffer(rpc_message), boost::asio::use_awaitable);
            
            boost::asio::streambuf response_buffer;
            co_await boost::asio::async_read_until(socket, response_buffer, "\n", boost::asio::use_awaitable);
            
            std::istream is(&response_buffer);
            std::string response;
            std::getline(is, response);
            response += "\n";
            
            boost::asio::post(io_context_, [callback, response](){ callback(response); });
        } catch (std::exception& e) {
            boost::asio::post(io_context_, [callback](){ callback("RPC_FAILED\n"); });
        }
    }, boost::asio::detached);
}

