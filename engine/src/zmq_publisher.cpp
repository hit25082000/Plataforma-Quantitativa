#include "zmq_publisher.h"
#include "alert_types.h"
#include <chrono>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <zmq.hpp>
#include <nlohmann/json.hpp>

namespace zmq_publisher {

namespace {
std::string timestamp_iso() {
    auto now = std::chrono::system_clock::now();
    auto t = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        now.time_since_epoch()) % 1000;
    std::ostringstream oss;
    oss << std::put_time(std::gmtime(&t), "%Y-%m-%dT%H:%M:%S");
    oss << '.' << std::setfill('0') << std::setw(3) << ms.count() << 'Z';
    return oss.str();
}
} // namespace

ZmqPublisher::ZmqPublisher(event_bus::EventQueue& queue,
                         dom_snapshot::DOMSnapshotEngine& dom,
                         trade_stream::TradeStreamProcessor& trade_proc,
                         const std::string& address,
                         const std::string& ticker,
                         alert_bus::AlertBus* alert_bus,
                         event_dispatcher::EventDispatcher* dispatcher,
                         AgentRanking* agent_ranking)
    : queue_(queue)
    , dom_(dom)
    , trade_proc_(trade_proc)
    , address_(address)
    , ticker_(ticker)
    , alert_bus_(alert_bus)
    , dispatcher_(dispatcher)
    , agent_ranking_(agent_ranking)
{}

ZmqPublisher::~ZmqPublisher() {
    stop();
}

void ZmqPublisher::start() {
    running_.store(true);
    thread_ = std::thread(&ZmqPublisher::run, this);
}

void ZmqPublisher::stop() {
    running_.store(false);
    queue_.stop();
    if (thread_.joinable()) thread_.join();
}

void ZmqPublisher::run() {
    zmq::context_t ctx(1);
    zmq::socket_t pub(ctx, ZMQ_PUB);
    try {
        pub.bind(address_);
        bound_.store(true);
        std::cerr << "[ZmqPublisher] Bound to " << address_ << std::endl;
    } catch (const zmq::error_t& e) {
        std::cerr << "[ZmqPublisher] BIND FAILED on " << address_
                  << ": " << e.what() << " (errno " << e.num() << ")"
                  << " — another engine may be using this port!" << std::endl;
        return;
    }

    while (running_.load()) {
        event_bus::Event ev;
        queue_.wait_and_pop(ev);

        if (queue_.is_stopped()) break;

        int count = msg_count_.fetch_add(1);
        if (count == 0) {
            std::cerr << "[ZmqPublisher] Processing first event from queue" << std::endl;
        }

        std::visit([&](auto&& e) {
            using T = std::decay_t<decltype(e)>;
            if constexpr (std::is_same_v<T, event_bus::TradeEvent>) {
                trade_proc_.process(e);
                if (count < 3) {
                    std::cerr << "[ZmqPublisher] Trade event: ticker=" << e.ticker
                              << " price=" << e.price << " qty=" << e.qty << std::endl;
                }
                if (agent_ranking_) {
                    int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                        std::chrono::system_clock::now().time_since_epoch()).count();
                    agent_ranking_->on_trade(e.buy_agent, e.sell_agent, e.qty, e.trade_type, now_ms);
                }
                auto acc = trade_proc_.get_accumulators();
                if (dispatcher_) {
                    trade_stream::AgentStats astats;
                    if (e.trade_type == 2) {
                        auto it = acc.by_agent.find(e.buy_agent);
                        if (it != acc.by_agent.end()) astats = it->second;
                    } else if (e.trade_type == 3) {
                        auto it = acc.by_agent.find(e.sell_agent);
                        if (it != acc.by_agent.end()) astats = it->second;
                    }
                    dispatcher_->dispatch_trade(e, acc.vwap(), acc.net_aggression, astats);
                }
                nlohmann::json j = {
                    {"topic", "market"},
                    {"type", "trade"},
                    {"ticker", e.ticker},
                    {"price", e.price},
                    {"qty", e.qty},
                    {"buy_agent", e.buy_agent},
                    {"sell_agent", e.sell_agent},
                    {"trade_type", e.trade_type},
                    {"vwap", acc.vwap()},
                    {"net_aggression", acc.net_aggression},
                    {"ts", timestamp_iso()}
                };
                zmq::message_t msg(j.dump());
                pub.send(msg, zmq::send_flags::none);
                if (alert_bus_ && dispatcher_) {
                    rules::Alert alert;
                    while (alert_bus_->try_pop(alert)) {
                        dispatcher_->dispatch_alert(alert);
                        publish_alert(pub, alert);
                    }
                }
            } else if constexpr (std::is_same_v<T, event_bus::OfferBookEvent>) {
                dom_.process(e);
                if (count < 3) {
                    std::cerr << "[ZmqPublisher] OfferBook event: ticker=" << e.ticker
                              << " action=" << e.nAction << " price=" << e.sPrice << std::endl;
                }

                dom_snapshot::WallEvent wall_add;
                while (dom_.get_wall_add(wall_add)) {
                    if (dispatcher_) dispatcher_->dispatch_wall_add(wall_add);
                    nlohmann::json j = {
                        {"topic", "market"},
                        {"type", "wall_add"},
                        {"ticker", wall_add.ticker},
                        {"price", wall_add.price},
                        {"qty", wall_add.qty},
                        {"side", wall_add.side},
                        {"offer_id", wall_add.offer_id},
                        {"agent_id", wall_add.agent_id},
                        {"ts", timestamp_iso()}
                    };
                    zmq::message_t msg(j.dump());
                    pub.send(msg, zmq::send_flags::none);
                }

                dom_snapshot::WallRemoveEvent wall_rem;
                while (dom_.get_wall_remove(wall_rem)) {
                    if (dispatcher_) dispatcher_->dispatch_wall_remove(wall_rem);
                    nlohmann::json j = {
                        {"topic", "market"},
                        {"type", "wall_remove"},
                        {"ticker", wall_rem.ticker},
                        {"offer_id", wall_rem.offer_id},
                        {"elapsed_ms", wall_rem.elapsed_ms},
                        {"was_traded", wall_rem.was_traded},
                        {"ts", timestamp_iso()}
                    };
                    zmq::message_t msg(j.dump());
                    pub.send(msg, zmq::send_flags::none);
                }

                dom_snapshot::DOMSnapshotEvent snap;
                if (dom_.get_dom_snapshot(snap)) {
                    if (dispatcher_) dispatcher_->dispatch_dom_snapshot(snap);
                    nlohmann::json j = {
                        {"topic", "market"},
                        {"type", "dom_snapshot"},
                        {"ticker", snap.ticker},
                        {"buy", nlohmann::json::array()},
                        {"sell", nlohmann::json::array()}
                    };
                    for (const auto& [p, q, c] : snap.buy) {
                        j["buy"].push_back({{"price", p}, {"qty", q}, {"count", c}});
                    }
                    for (const auto& [p, q, c] : snap.sell) {
                        j["sell"].push_back({{"price", p}, {"qty", q}, {"count", c}});
                    }
                    zmq::message_t msg(j.dump());
                    pub.send(msg, zmq::send_flags::none);
                }

                if (alert_bus_ && dispatcher_) {
                    rules::Alert alert;
                    while (alert_bus_->try_pop(alert)) {
                        dispatcher_->dispatch_alert(alert);
                        publish_alert(pub, alert);
                    }
                }
            } else if constexpr (std::is_same_v<T, event_bus::DailyEvent>) {
                // Despachar para as regras
                if (dispatcher_) {
                    dispatcher_->dispatch_daily(e);
                }
                // Publicar no ZMQ
                nlohmann::json j = {
                    {"topic", "market"},
                    {"type", "daily"},
                    {"ticker", e.ticker},
                    {"high", e.high},
                    {"low", e.low},
                    {"open", e.open},
                    {"close", e.close},
                    {"volume", e.volume},
                    {"ts", timestamp_iso()}
                };
                zmq::message_t msg(j.dump());
                pub.send(msg, zmq::send_flags::none);
            }
        }, ev);
    }
}

void ZmqPublisher::publish_alert(zmq::socket_t& pub, const rules::Alert& a) {
    std::string dir = (a.direction == rules::Direction::Buy) ? "buy" :
                      (a.direction == rules::Direction::Sell) ? "sell" : "neutral";
    std::string conv = (a.conviction == rules::Conviction::Low) ? "low" :
                       (a.conviction == rules::Conviction::Medium) ? "medium" : "high";

    auto now = std::chrono::system_clock::now();
    auto t = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        now.time_since_epoch()) % 1000;
    std::ostringstream oss;
    oss << std::put_time(std::gmtime(&t), "%Y-%m-%dT%H:%M:%S");
    oss << '.' << std::setfill('0') << std::setw(3) << ms.count() << 'Z';

    nlohmann::json j = {
        {"topic", "alert"},
        {"rule", static_cast<int>(a.rule)},
        {"ticker", a.ticker},
        {"direction", dir},
        {"conviction", conv},
        {"label", a.label},
        {"price", a.price},
        {"data", a.data},
        {"ts", oss.str()}
    };
    zmq::message_t msg(j.dump());
    pub.send(msg, zmq::send_flags::none);
}

} // namespace zmq_publisher
