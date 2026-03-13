#pragma once

#include "alert_bus.h"
#include "alert_types.h"
#include "dom_snapshot.h"
#include "event_bus.h"
#include "event_dispatcher.h"
#include "trade_stream.h"
#include "agent_ranking.h"
#include <zmq.hpp>
#include <atomic>
#include <functional>
#include <memory>
#include <string>
#include <thread>

namespace zmq_publisher {

class ZmqPublisher {
public:
    ZmqPublisher(event_bus::EventQueue& queue,
                 dom_snapshot::DOMSnapshotEngine& dom,
                 trade_stream::TradeStreamProcessor& trade_proc,
                 const std::string& address,
                 const std::string& ticker,
                 alert_bus::AlertBus* alert_bus = nullptr,
                 event_dispatcher::EventDispatcher* dispatcher = nullptr,
                 AgentRanking* agent_ranking = nullptr,
                 std::function<std::string(int32_t)> agent_name_resolver = nullptr,
                 std::function<std::string(int32_t)> agent_short_name_resolver = nullptr);
    ~ZmqPublisher();

    void start();
    void stop();
    void set_ticker(const std::string& t) { ticker_ = t; }

    bool is_bound() const { return bound_.load(); }

private:
    void run();
    void publish_alert(zmq::socket_t& pub, const rules::Alert& a);

    event_bus::EventQueue&           queue_;
    dom_snapshot::DOMSnapshotEngine& dom_;
    trade_stream::TradeStreamProcessor& trade_proc_;
    std::string address_;
    std::string ticker_;
    alert_bus::AlertBus*            alert_bus_ = nullptr;
    event_dispatcher::EventDispatcher* dispatcher_ = nullptr;
    AgentRanking*                   agent_ranking_ = nullptr;
    std::function<std::string(int32_t)> agent_name_resolver_;
    std::function<std::string(int32_t)> agent_short_name_resolver_;

    std::thread thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> bound_{false};
    std::atomic<int>  msg_count_{0};
};

} // namespace zmq_publisher
