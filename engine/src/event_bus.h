#pragma once

#include <atomic>
#include <cstdint>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <variant>

namespace event_bus {

enum class TradeSource : uint8_t {
    Realtime = 0,
    History = 1
};

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
    int64_t     enqueue_ts_ms{0};
};

struct TradeEvent {
    std::string ticker;
    std::string bolsa;
    std::string trade_date;
    double      price;
    int64_t     qty;
    int32_t     buy_agent;
    int32_t     sell_agent;
    uint8_t     trade_type;
    uint32_t    trade_number{0};
    uint32_t    trade_flags{0};
    int64_t     trade_epoch_ms{0};
    TradeSource source{TradeSource::Realtime};
    int64_t     enqueue_ts_ms{0};
};

struct DailyEvent {
    std::string ticker;
    double high;
    double low;
    double open;
    double close;
    double volume;
    /** Data do pregão (UTF-8), ex. callback da DLL; vazio se indisponível. */
    std::string trade_date;
    int64_t     enqueue_ts_ms{0};
};

using Event = std::variant<OfferBookEvent, TradeEvent, DailyEvent>;

class EventQueue {
public:
    struct QueueMetrics {
        size_t trade_size{0};
        size_t normal_size{0};
    };

    void push(Event e);
    bool try_pop(Event& out);
    void wait_and_pop(Event& out);
    void stop();
    bool is_stopped() const { return stopped_.load(); }
    QueueMetrics metrics() const;

private:
    std::queue<Event>     trade_queue_;
    std::queue<Event>     normal_queue_;
    mutable std::mutex    mutex_;
    std::condition_variable cv_;
    std::atomic<bool>     stopped_{false};
};

} // namespace event_bus
