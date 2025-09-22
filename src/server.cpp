#include "kv_store.h"
#include "raft.h"
#include "thread_pool.h"
#include <boost/asio.hpp>
#include <filesystem>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

using boost::asio::ip::tcp;

class Session : public std::enable_shared_from_this<Session> {
public:
    Session(tcp::socket socket, std::shared_ptr<RaftNode> raft_node)
        : socket_(std::move(socket)), raft_node_(raft_node) {}

    void start() { do_read(); }

private:
    void do_read() {
        auto self(shared_from_this());
        boost::asio::async_read_until(
            socket_, buffer_, "\n",
            [this, self](boost::system::error_code ec, std::size_t) {
                if (!ec) {
                    std::istream is(&buffer_);
                    std::string line;
                    std::getline(is, line);
                    // Remove potential carriage return
                    if (!line.empty() && line.back() == '\r') line.pop_back();

                    std::stringstream ss(line);
                    std::string first_word;
                    ss >> first_word;
                    
                    if (first_word == "RequestVote" || first_word == "AppendEntries") {
                        std::string response = raft_node_->handle_rpc(line + "\n");
                        do_write(response, false); 
                    } else {
                        // The callback ensures the reply is only sent after the command is committed.
                        raft_node_->submit_command(line, [this, self](const std::string& response){
                            do_write(response, true);
                        });
                    }
                }
            });
    }

    void do_write(const std::string& response, bool keep_alive) {
        auto self(shared_from_this());
        boost::asio::async_write(
            socket_, boost::asio::buffer(response),
            [this, self, keep_alive](boost::system::error_code ec, std::size_t) {
                if (!ec && keep_alive) {
                    do_read();
                }
            });
    }

    tcp::socket socket_;
    std::shared_ptr<RaftNode> raft_node_;
    boost::asio::streambuf buffer_;
};

class Server {
public:
    Server(boost::asio::io_context& io_context, short port, std::shared_ptr<RaftNode> raft_node)
        : acceptor_(io_context, tcp::endpoint(tcp::v4(), port)), raft_node_(raft_node) {
        do_accept();
    }
private:
    void do_accept() {
        acceptor_.async_accept([this](boost::system::error_code ec, tcp::socket socket) {
            if (!ec) {
                std::make_shared<Session>(std::move(socket), raft_node_)->start();
            }
            do_accept();
        });
    }
    tcp::acceptor acceptor_;
    std::shared_ptr<RaftNode> raft_node_;
};

int main(int argc, char* argv[]) {
    try {
        if (argc < 3) {
            std::cerr << "Usage: " << argv[0] << " <my_id> <peer0_addr> [peer1_addr] ...\n";
            return 1;
        }

        int my_id = std::stoi(argv[1]);
        std::vector<std::string> peer_addresses;
        for (int i = 2; i < argc; ++i) peer_addresses.push_back(argv[i]);

        if (my_id < 0 || my_id >= (int)peer_addresses.size()) {
            std::cerr << "Error: my_id is out of range.\n";
            return 1;
        }

        const auto& my_address = peer_addresses[my_id];
        size_t colon_pos = my_address.find(':');
        if (colon_pos == std::string::npos) {
             std::cerr << "Error: Invalid address format for self: " << my_address << std::endl;
             return 1;
        }
        const short port = std::stoi(my_address.substr(colon_pos + 1));

        boost::asio::io_context io_context;
        
        // Create the AOFs directory if it doesn't exist
        std::filesystem::create_directory("AOFs");

        KeyValueStore kv_store("AOFs/kv_store_" + std::to_string(my_id) + ".aof");
        auto raft_node = std::make_shared<RaftNode>(my_id, peer_addresses, kv_store, io_context);
        
        Server server(io_context, port, raft_node);
        std::cout << "Server listening on port " << port << "..." << std::endl;
        
        raft_node->start();

        std::vector<std::thread> threads;
        const int num_threads = std::max(2, (int)std::thread::hardware_concurrency());
        for (int i = 0; i < num_threads; ++i) {
            threads.emplace_back([&io_context] { io_context.run(); });
        }
        for (auto& t : threads) t.join();
        raft_node->stop();
    } catch (std::exception& e) {
        std::cerr << "Server error: " << e.what() << std::endl;
    }
    return 0;
}

