#include "asset_controller.h"
#include <chrono>
#include <cstring>
#include <iostream>
#include <sstream>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace asset_controller {

namespace {

#ifdef _WIN32
using sock_t = SOCKET;
const sock_t INVALID_SOCK = INVALID_SOCKET;
inline int close_sock(sock_t s) { return closesocket(s); }
#else
using sock_t = int;
const sock_t INVALID_SOCK = -1;
inline int close_sock(sock_t s) { return close(s); }
#endif

bool read_line(sock_t fd, std::string& out) {
    out.clear();
    char buf[256];
    while (out.size() < 200) {
        int n = recv(fd, buf, 1, 0);
        if (n <= 0) return false;
        if (buf[0] == '\n') return true;
        if (buf[0] != '\r') out += buf[0];
    }
    return true;
}

bool write_all(sock_t fd, const char* data, size_t len) {
    while (len > 0) {
        int n = send(fd, data, static_cast<int>(len), 0);
        if (n <= 0) return false;
        data += n;
        len -= static_cast<size_t>(n);
    }
    return true;
}

} // namespace

AssetController::AssetController() = default;

AssetController::~AssetController() {
    stop();
}

void AssetController::start(uint16_t port) {
    if (running_.exchange(true)) return;
    thread_ = std::thread(&AssetController::listener_loop, this, port);
}

void AssetController::stop() {
    running_.store(false);
    if (thread_.joinable()) {
        cv_.notify_all();
        thread_.join();
    }
}

bool AssetController::poll_switch(SwitchRequest& out) {
    std::lock_guard<std::mutex> lk(mtx_);
    if (!pending_.has_value()) return false;
    out = *pending_;
    pending_.reset();
    completed_ = false;
    return true;
}

void AssetController::complete_switch(const std::string& result) {
    std::lock_guard<std::mutex> lk(mtx_);
    result_ = result;
    completed_ = true;
    cv_.notify_all();
}

void AssetController::listener_loop(uint16_t port) {
#ifdef _WIN32
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        std::cerr << "[AssetController] WSAStartup failed" << std::endl;
        return;
    }
#endif

    sock_t listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd == INVALID_SOCK) {
        std::cerr << "[AssetController] socket() failed" << std::endl;
        return;
    }

    int opt = 1;
#ifdef _WIN32
    setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, (const char*)&opt, sizeof(opt));
#else
    setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#endif

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons(port);

    if (bind(listen_fd, (sockaddr*)&addr, sizeof(addr)) != 0) {
        std::cerr << "[AssetController] bind failed on port " << port << std::endl;
        close_sock(listen_fd);
        return;
    }

    if (listen(listen_fd, 1) != 0) {
        std::cerr << "[AssetController] listen failed" << std::endl;
        close_sock(listen_fd);
        return;
    }

    std::cerr << "[AssetController] Listening on 127.0.0.1:" << port << std::endl;

    while (running_.load()) {
        struct timeval tv;
        tv.tv_sec = 1;
        tv.tv_usec = 0;
        fd_set rd;
        FD_ZERO(&rd);
        FD_SET(listen_fd, &rd);
#ifdef _WIN32
        int r = select(0, &rd, nullptr, nullptr, &tv);
#else
        int r = select(static_cast<int>(listen_fd) + 1, &rd, nullptr, nullptr, &tv);
#endif
        if (r <= 0) continue;
        if (!FD_ISSET(listen_fd, &rd)) continue;

        sockaddr_in client_addr{};
        socklen_t len = sizeof(client_addr);
        sock_t client = accept(listen_fd, (sockaddr*)&client_addr, &len);
        if (client == INVALID_SOCK) continue;

        std::string line;
        if (!read_line(client, line)) {
            close_sock(client);
            continue;
        }

        std::istringstream iss(line);
        std::string cmd, ticker, bolsa;
        if (iss >> cmd >> ticker >> bolsa && cmd == "SWITCH") {
            {
                std::lock_guard<std::mutex> lk(mtx_);
                pending_ = SwitchRequest{std::move(ticker), std::move(bolsa)};
                completed_ = false;
                result_.clear();
            }
            cv_.notify_all();

            {
                std::unique_lock<std::mutex> lk(mtx_);
                cv_.wait_for(lk, std::chrono::seconds(10), [this] { return completed_; });
                std::string resp = completed_ ? result_ : "ERR: timeout";
                if (resp.empty() || resp == "OK") resp = "OK";
                resp += "\n";
                write_all(client, resp.c_str(), resp.size());
            }
        } else {
            std::string err = "ERR: invalid command\n";
            write_all(client, err.c_str(), err.size());
        }

        close_sock(client);
    }

    close_sock(listen_fd);
#ifdef _WIN32
    WSACleanup();
#endif
}

} // namespace asset_controller
