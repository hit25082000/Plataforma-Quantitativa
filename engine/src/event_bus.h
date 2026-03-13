#pragma once

#include <atomic>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <variant>

namespace event_bus {

// Eventos que vêm dos callbacks da DLL (cópia rápida, sem chamar DLL)
struct OfferBookEvent {
    std::string ticker;
    std::string bolsa;
    int32_t     nAction;
    int32_t     nPosition;
    int32_t     side;
    int64_t     nQtd;
    int32_t     nAgent;
    int64_t     nOfferID;
    double      sPrice;
};

struct TradeEvent {
    std::string ticker;
    std::string bolsa;
    double      price;
    int64_t     qty;
    int32_t     buy_agent;
    int32_t     sell_agent;
    uint8_t     trade_type;
};

struct DailyEvent {
    std::string ticker;
    double high;
    double low;
    double open;
    double close;
    double volume;
};

using Event = std::variant<OfferBookEvent, TradeEvent, DailyEvent>;

class EventQueue {
public:
    void push(Event e);
    bool try_pop(Event& out);
    void wait_and_pop(Event& out);
    void stop();
    bool is_stopped() const { return stopped_.load(); }

private:
    std::queue<Event>     queue_;
    mutable std::mutex    mutex_;
    std::condition_variable cv_;
    std::atomic<bool>     stopped_{false};
};

} // namespace event_bus
