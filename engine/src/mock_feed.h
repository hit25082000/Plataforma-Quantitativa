#pragma once

#include "event_bus.h"
#include <atomic>
#include <memory>
#include <thread>

namespace mock_feed {

class MockFeed {
public:
    explicit MockFeed(event_bus::EventQueue& queue);
    ~MockFeed();

    void start();
    void stop();

private:
    void run();

    event_bus::EventQueue& queue_;
    std::thread thread_;
    std::atomic<bool> running_{false};
};

} // namespace mock_feed
