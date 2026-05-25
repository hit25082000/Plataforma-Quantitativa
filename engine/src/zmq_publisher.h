#pragma once

#include "alert_bus.h"
#include "alert_types.h"
#include "dom_snapshot.h"
#include "event_bus.h"
#include "event_dispatcher.h"
#include "trade_stream.h"
#include "agent_ranking.h"
#include "trade_reconciler.h"
#include "volume_profile.h"
#include "tape_intelligence.h"
#include "shared_memory_ipc.h"
#include <zmq.hpp>
#include <atomic>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <chrono>

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
    void set_ticker(const std::string& t);
    void reset_volume_profile();
    /// Aplica `day` | `week` | `manual` (ignora case). Vazio = OK, senão mensagem de erro.
    std::string apply_volume_profile_period_name(const std::string& name);
    void with_processing_paused(const std::function<void()>& fn);

    bool is_bound() const { return bound_.load(); }

private:
    void run();
    void publish_alert(zmq::socket_t& pub, const rules::Alert& a);
    void send_payload(zmq::socket_t& pub, const std::string& payload, const char* market_type);

    event_bus::EventQueue&           queue_;
    dom_snapshot::DOMSnapshotEngine& dom_;
    trade_stream::TradeStreamProcessor& trade_proc_;
    std::string address_;
    std::string ticker_;
    alert_bus::AlertBus*            alert_bus_ = nullptr;
    event_dispatcher::EventDispatcher* dispatcher_ = nullptr;
    AgentRanking*                   agent_ranking_ = nullptr;
    TradeReconciler                 reconciler_;
    volume_profile::VolumeProfileEngine volume_profile_;
    tape_intelligence::TapeIntelligenceEngine tape_intelligence_;
    std::function<std::string(int32_t)> agent_name_resolver_;
    std::function<std::string(int32_t)> agent_short_name_resolver_;
    std::unordered_map<int32_t, std::string> agent_name_cache_;
    std::unordered_map<int32_t, std::string> agent_short_name_cache_;
    std::mutex agent_cache_mutex_;

    std::thread thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> bound_{false};
    std::atomic<int>  msg_count_{0};
    std::mutex processing_mutex_;
    std::unique_ptr<shared_memory_ipc::SharedMemoryRingWriter> shm_writer_;
    bool shm_enabled_{false};
    int64_t metrics_next_log_ms_{0};
    int64_t trade_latency_sum_ms_{0};
    int64_t trade_latency_count_{0};
    int64_t max_trade_latency_ms_{0};
    int64_t trade_events_processed_{0};
    int64_t offer_events_processed_{0};
    int64_t daily_events_processed_{0};
    int64_t reconcile_duplicates_ignored_{0};
    int64_t published_total_{0};
    bool first_market_event_published_{false};

    /** Mínimo intervalo entre publicações dom_snapshot no ZMQ (dispatch_dom_snapshot a cada tick); 0 = sem limite. */
    int64_t dom_snapshot_publish_min_ms_{100};
    int64_t last_dom_snapshot_pub_ms_{0};
    int64_t dom_snapshot_throttle_skips_{0};
    int64_t volume_profile_publish_min_ms_{100};
    int64_t last_volume_profile_pub_ms_{0};
    int64_t volume_profile_throttle_skips_{0};
    int64_t last_vp_poc_{0};
    int64_t last_vp_vah_{0};
    int64_t last_vp_val_{0};
    bool last_vp_anchor_valid_{false};
    /** Mínimo intervalo entre publicações tape_intelligence no ZMQ; 0 = sem limite. */
    int64_t tape_intelligence_publish_min_ms_{200};
    int64_t last_tape_intelligence_pub_ms_{0};
    int64_t tape_intelligence_throttle_skips_{0};
    int64_t last_ti_poc_{0};
    int64_t last_ti_vah_{0};
    int64_t last_ti_val_{0};
    bool last_ti_anchor_valid_{false};
};

} // namespace zmq_publisher
