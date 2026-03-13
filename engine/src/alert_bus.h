#pragma once

#include "alert_types.h"
#include <atomic>
#include <condition_variable>
#include <mutex>
#include <queue>

namespace alert_bus {

class AlertBus {
public:
    void push(rules::Alert a);
    bool try_pop(rules::Alert& out);
    void wait_and_pop(rules::Alert& out);
    void stop();
    bool is_stopped() const { return stopped_.load(); }

private:
    std::queue<rules::Alert> queue_;
    mutable std::mutex    mutex_;
    std::condition_variable cv_;
    std::atomic<bool>     stopped_{false};
};

} // namespace alert_bus
