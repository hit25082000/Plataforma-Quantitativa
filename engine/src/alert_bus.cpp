#include "alert_bus.h"
#include "alert_types.h"

namespace alert_bus {

void AlertBus::push(rules::Alert a) {
    {
        std::lock_guard lock(mutex_);
        if (stopped_.load()) return;
        queue_.push(std::move(a));
    }
    cv_.notify_one();
}

bool AlertBus::try_pop(rules::Alert& out) {
    std::lock_guard lock(mutex_);
    if (queue_.empty()) return false;
    out = std::move(queue_.front());
    queue_.pop();
    return true;
}

void AlertBus::wait_and_pop(rules::Alert& out) {
    std::unique_lock lock(mutex_);
    cv_.wait(lock, [this] { return stopped_.load() || !queue_.empty(); });
    if (stopped_.load() && queue_.empty()) return;
    if (!queue_.empty()) {
        out = std::move(queue_.front());
        queue_.pop();
    }
}

void AlertBus::stop() {
    stopped_.store(true);
    cv_.notify_all();
}

} // namespace alert_bus
