#include "event_bus.h"

namespace event_bus {

void EventQueue::push(Event e) {
    {
        std::lock_guard lock(mutex_);
        if (stopped_.load()) return;
        queue_.push(std::move(e));
    }
    cv_.notify_one();
}

bool EventQueue::try_pop(Event& out) {
    std::lock_guard lock(mutex_);
    if (queue_.empty()) return false;
    out = std::move(queue_.front());
    queue_.pop();
    return true;
}

void EventQueue::wait_and_pop(Event& out) {
    std::unique_lock lock(mutex_);
    cv_.wait(lock, [this] { return stopped_.load() || !queue_.empty(); });
    if (stopped_.load() && queue_.empty()) return;
    if (!queue_.empty()) {
        out = std::move(queue_.front());
        queue_.pop();
    }
}

void EventQueue::stop() {
    stopped_.store(true);
    cv_.notify_all();
}

} // namespace event_bus
