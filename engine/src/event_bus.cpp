#include "event_bus.h"
#include <chrono>

namespace event_bus {

namespace {
int64_t now_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
} // namespace

void EventQueue::push(Event e) {
    {
        std::lock_guard lock(mutex_);
        if (stopped_.load()) return;
        std::visit([](auto& event) { event.enqueue_ts_ms = now_ms(); }, e);
        if (std::holds_alternative<TradeEvent>(e)) {
            trade_queue_.push(std::move(e));
        } else {
            normal_queue_.push(std::move(e));
        }
    }
    cv_.notify_one();
}

bool EventQueue::try_pop(Event& out) {
    std::lock_guard lock(mutex_);
    if (!trade_queue_.empty()) {
        out = std::move(trade_queue_.front());
        trade_queue_.pop();
        return true;
    }
    if (normal_queue_.empty()) return false;
    out = std::move(normal_queue_.front());
    normal_queue_.pop();
    return true;
}

void EventQueue::wait_and_pop(Event& out) {
    std::unique_lock lock(mutex_);
    cv_.wait(lock, [this] {
        return stopped_.load() || !trade_queue_.empty() || !normal_queue_.empty();
    });
    if (stopped_.load() && trade_queue_.empty() && normal_queue_.empty()) return;
    if (!trade_queue_.empty()) {
        out = std::move(trade_queue_.front());
        trade_queue_.pop();
        return;
    }
    if (!normal_queue_.empty()) {
        out = std::move(normal_queue_.front());
        normal_queue_.pop();
    }
}

void EventQueue::stop() {
    stopped_.store(true);
    cv_.notify_all();
}

EventQueue::QueueMetrics EventQueue::metrics() const {
    std::lock_guard lock(mutex_);
    QueueMetrics m;
    m.trade_size = trade_queue_.size();
    m.normal_size = normal_queue_.size();
    return m;
}

} // namespace event_bus
