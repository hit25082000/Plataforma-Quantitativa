#include "zmq_publisher.h"
#include "alert_types.h"
#include "hft_tuning.h"
#include "profit_types.h"
#include "tape_intelligence.h"
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
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

int64_t steady_now_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

int64_t read_env_int64_ms(const char* name, int64_t default_ms) {
    const char* v = std::getenv(name);
    if (!v || !*v) return default_ms;
    try {
        long long x = std::stoll(std::string(v));
        if (x < 0) return 0;
        return static_cast<int64_t>(x);
    } catch (...) {
        return default_ms;
    }
}

bool read_env_bool(const char* name, bool default_value) {
    const char* v = std::getenv(name);
    if (!v || !*v) return default_value;
    std::string raw(v);
    for (char& c : raw) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (raw == "1" || raw == "true" || raw == "yes" || raw == "on") return true;
    if (raw == "0" || raw == "false" || raw == "no" || raw == "off") return false;
    return default_value;
}

template <typename Resolver>
std::string resolve_with_cache(
    int32_t agent_id,
    Resolver resolver,
    std::unordered_map<int32_t, std::string>& cache,
    std::mutex& cache_mutex)
{
    {
        std::lock_guard<std::mutex> lock(cache_mutex);
        auto it = cache.find(agent_id);
        if (it != cache.end()) return it->second;
    }
    std::string resolved = resolver(agent_id);
    {
        std::lock_guard<std::mutex> lock(cache_mutex);
        cache.emplace(agent_id, resolved);
    }
    return resolved;
}

void enrich_tape_intelligence_agent_names(
    nlohmann::json& ti,
    const std::function<std::string(int32_t)>& agent_name_resolver,
    std::unordered_map<int32_t, std::string>& agent_name_cache,
    std::mutex& agent_cache_mutex)
{
    if (!agent_name_resolver) return;
    auto resolve = [&](int32_t id) {
        return resolve_with_cache(id, agent_name_resolver, agent_name_cache, agent_cache_mutex);
    };
    if (ti.contains("poc_player")) {
        const int32_t id = ti["poc_player"].get<int32_t>();
        ti["poc_player_name"] = resolve(id);
    }
    if (ti.contains("val_buyer")) {
        const int32_t id = ti["val_buyer"].get<int32_t>();
        ti["val_buyer_name"] = resolve(id);
    }
    if (ti.contains("vah_seller")) {
        const int32_t id = ti["vah_seller"].get<int32_t>();
        ti["vah_seller_name"] = resolve(id);
    }
    for (const char* arr_key : {"poc_top3", "vah_top3", "val_top3"}) {
        if (!ti.contains(arr_key) || !ti[arr_key].is_array()) continue;
        for (auto& row : ti[arr_key]) {
            if (!row.contains("player")) continue;
            const int32_t pid = row["player"].get<int32_t>();
            row["player_id"] = pid;
            row["player_name"] = resolve(pid);
        }
    }
    if (ti.contains("top_player_avg_lines") && ti["top_player_avg_lines"].is_array()) {
        for (auto& row : ti["top_player_avg_lines"]) {
            if (!row.is_object() || !row.contains("player_id")) continue;
            const int32_t pid = row["player_id"].get<int32_t>();
            row["player_name"] = resolve(pid);
        }
    }
}

tape_intelligence::TopAvgRankMode parse_top_avg_rank_mode_env() {
    const char* v = std::getenv("TAPE_TOP_AVG_RANK_MODE");
    std::string raw;
    if (!v || !*v) {
        raw = "total";
    } else {
        raw.assign(v);
        for (char& c : raw)
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        while (!raw.empty() && raw.front() == ' ')
            raw.erase(raw.begin());
        while (!raw.empty() && raw.back() == ' ')
            raw.pop_back();
    }
    if (raw == "buy" || raw == "buy_volume" || raw == "top_buy_volume") {
        return tape_intelligence::TopAvgRankMode::TopBuyVolume;
    }
    if (raw == "sell" || raw == "sell_volume" || raw == "top_sell_volume") {
        return tape_intelligence::TopAvgRankMode::TopSellVolume;
    }
    if (raw == "net" || raw == "net_volume" || raw == "top_net_volume") {
        return tape_intelligence::TopAvgRankMode::TopNetVolume;
    }
    return tape_intelligence::TopAvgRankMode::TopTotalVolume;
}

size_t read_env_uz(const char* name, size_t default_value) {
    const char* v = std::getenv(name);
    if (!v || !*v) return default_value;
    try {
        unsigned long long x = std::stoull(std::string(v));
        return static_cast<size_t>(x);
    } catch (...) {
        return default_value;
    }
}

bool parse_volume_profile_period(const std::string& raw, volume_profile::Period& out) {
    std::string s;
    s.reserve(raw.size());
    for (char c : raw) {
        if (c == '\r' || c == '\n' || c == '\t') continue;
        s.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
    }
    while (!s.empty() && s.front() == ' ') s.erase(s.begin());
    while (!s.empty() && s.back() == ' ') s.pop_back();
    if (s == "day" || s == "dia") {
        out = volume_profile::Period::Day;
        return true;
    }
    if (s == "week" || s == "semana") {
        out = volume_profile::Period::Week;
        return true;
    }
    if (s == "manual") {
        out = volume_profile::Period::Manual;
        return true;
    }
    return false;
}

} // namespace

ZmqPublisher::ZmqPublisher(event_bus::EventQueue& queue,
                         dom_snapshot::DOMSnapshotEngine& dom,
                         trade_stream::TradeStreamProcessor& trade_proc,
                         const std::string& address,
                         const std::string& ticker,
                         alert_bus::AlertBus* alert_bus,
                         event_dispatcher::EventDispatcher* dispatcher,
                         AgentRanking* agent_ranking,
                         std::function<std::string(int32_t)> agent_name_resolver,
                         std::function<std::string(int32_t)> agent_short_name_resolver)
    : queue_(queue)
    , dom_(dom)
    , trade_proc_(trade_proc)
    , address_(address)
    , ticker_(ticker)
    , alert_bus_(alert_bus)
    , dispatcher_(dispatcher)
    , agent_ranking_(agent_ranking)
    , agent_name_resolver_(std::move(agent_name_resolver))
    , agent_short_name_resolver_(std::move(agent_short_name_resolver))
{
    dom_snapshot_publish_min_ms_ =
        read_env_int64_ms("DOM_SNAPSHOT_PUBLISH_MIN_MS", 100);
    volume_profile_publish_min_ms_ =
        read_env_int64_ms("VOLUME_PROFILE_PUBLISH_MIN_MS", 100);
    tape_intelligence_publish_min_ms_ =
        read_env_int64_ms("TAPE_INTELLIGENCE_PUBLISH_MIN_MS", 200);
    volume_profile_.set_ticker(ticker_);
    tape_intelligence_.set_ticker(ticker_);
    tape_intelligence_.set_top_player_avg_config(
        parse_top_avg_rank_mode_env(),
        std::max<size_t>(1u, read_env_uz("TAPE_TOP_AVG_MAX_LINES", 6)),
        static_cast<uint64_t>(
            std::max<long long>(
                0LL,
                static_cast<long long>(read_env_uz("TAPE_TOP_AVG_MIN_CONTRACTS", 1)))));
    shm_enabled_ = read_env_bool("SHM_ENABLED", false);
    if (shm_enabled_) {
        shm_writer_ = std::make_unique<shared_memory_ipc::SharedMemoryRingWriter>(
            shared_memory_ipc::default_mapping_name(),
            shared_memory_ipc::default_mapping_size_bytes());
        if (!shm_writer_->is_ready()) {
            std::cerr << "[ZmqPublisher] SHM enabled but initialization failed. Continuing with ZMQ only."
                      << std::endl;
            shm_writer_.reset();
        }
    }
}

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

void ZmqPublisher::set_ticker(const std::string& t) {
    ticker_ = t;
    reconciler_.reset();
    volume_profile_.set_ticker(t);
    tape_intelligence_.set_ticker(t);
    last_volume_profile_pub_ms_ = 0;
    last_vp_anchor_valid_ = false;
    last_tape_intelligence_pub_ms_ = 0;
    last_ti_anchor_valid_ = false;
    {
        std::lock_guard<std::mutex> lock(agent_cache_mutex_);
        agent_name_cache_.clear();
        agent_short_name_cache_.clear();
    }
}

void ZmqPublisher::reset_volume_profile() {
    volume_profile_.reset();
}

std::string ZmqPublisher::apply_volume_profile_period_name(const std::string& name) {
    volume_profile::Period p;
    if (!parse_volume_profile_period(name, p)) {
        return "ERR: use day, week or manual for VP period";
    }
    if (volume_profile_.period() == p) {
        return {};
    }
    with_processing_paused([&]() {
        volume_profile_.set_period(p);
        tape_intelligence_.reset();
        last_volume_profile_pub_ms_ = 0;
        last_vp_anchor_valid_ = false;
        last_tape_intelligence_pub_ms_ = 0;
        last_ti_anchor_valid_ = false;
    });
    return {};
}

void ZmqPublisher::with_processing_paused(const std::function<void()>& fn) {
    std::lock_guard<std::mutex> lock(processing_mutex_);
    fn();
}

void ZmqPublisher::run() {
    hft_tuning::maybe_pin_current_thread_from_env("HFT_PUBLISHER_CORE", 1, "publisher");

    zmq::context_t ctx(1);
    zmq::socket_t pub(ctx, ZMQ_PUB);
    try {
        pub.bind(address_);
        bound_.store(true);
        std::cerr << "[ZmqPublisher] Bound to " << address_
                  << " dom_snapshot_publish_min_ms=" << dom_snapshot_publish_min_ms_
                  << std::endl;
    } catch (const zmq::error_t& e) {
        std::cerr << "[ZmqPublisher] BIND FAILED on " << address_
                  << ": " << e.what() << " (errno " << e.num() << ")"
                  << " — another engine may be using this port!" << std::endl;
        return;
    }

    metrics_next_log_ms_ = steady_now_ms() + 5000;
    while (running_.load()) {
        event_bus::Event ev;
        queue_.wait_and_pop(ev);
        hft_tuning::record_publisher_tick();

        if (queue_.is_stopped()) break;

        int count = msg_count_.fetch_add(1);
        if (count == 0) {
            std::cerr << "[ZmqPublisher] Processing first event from queue" << std::endl;
        }

        {
            std::lock_guard<std::mutex> lock(processing_mutex_);
            std::visit([&](auto&& e) {
                using T = std::decay_t<decltype(e)>;
                if constexpr (std::is_same_v<T, event_bus::TradeEvent>) {
                trade_events_processed_++;
                auto rec = reconciler_.apply(e);
                if (!rec.accepted) {
                    if (rec.is_duplicate) reconcile_duplicates_ignored_++;
                    return;
                }
                if (e.enqueue_ts_ms > 0) {
                    int64_t latency_ms = steady_now_ms() - e.enqueue_ts_ms;
                    if (latency_ms >= 0) {
                        trade_latency_sum_ms_ += latency_ms;
                        trade_latency_count_ += 1;
                        if (latency_ms > max_trade_latency_ms_) max_trade_latency_ms_ = latency_ms;
                    }
                }
                auto vp_msg = volume_profile_.on_trade(e);
                const nlohmann::json vp_snapshot = volume_profile_.build_payload();
                auto ti_msg = tape_intelligence_.on_trade(
                    e,
                    vp_snapshot.value("poc", 0),
                    vp_snapshot.value("vah", 0),
                    vp_snapshot.value("val", 0));
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
                    } else if (e.trade_type == profit::TRADE_TYPE_SELL_AGGRESSION) {
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
                    {"trade_number", e.trade_number},
                    {"trade_date", e.trade_date},
                    {"trade_source", e.source == event_bus::TradeSource::History ? "history" : "realtime"},
                    {"is_edit", (e.trade_flags & profit::TC_IS_EDIT) == profit::TC_IS_EDIT},
                    {"vwap", acc.vwap()},
                    {"net_aggression", acc.net_aggression},
                    {"ts", timestamp_iso()}
                };
                if (agent_name_resolver_) {
                    j["buy_agent_name"] = resolve_with_cache(
                        e.buy_agent,
                        agent_name_resolver_,
                        agent_name_cache_,
                        agent_cache_mutex_);
                    j["sell_agent_name"] = resolve_with_cache(
                        e.sell_agent,
                        agent_name_resolver_,
                        agent_name_cache_,
                        agent_cache_mutex_);
                }
                if (agent_short_name_resolver_) {
                    j["buy_agent_short_name"] = resolve_with_cache(
                        e.buy_agent,
                        agent_short_name_resolver_,
                        agent_short_name_cache_,
                        agent_cache_mutex_);
                    j["sell_agent_short_name"] = resolve_with_cache(
                        e.sell_agent,
                        agent_short_name_resolver_,
                        agent_short_name_cache_,
                        agent_cache_mutex_);
                }
                if (shm_writer_) {
                    shm_writer_->write_trade(e, acc.vwap(), acc.net_aggression);
                }
                zmq::message_t msg(j.dump());
                pub.send(msg, zmq::send_flags::none);
                if (vp_msg) {
                    const int64_t poc = vp_snapshot.value("poc", 0);
                    const int64_t vah = vp_snapshot.value("vah", 0);
                    const int64_t val = vp_snapshot.value("val", 0);
                    const bool anchor_changed =
                        !last_vp_anchor_valid_ ||
                        poc != last_vp_poc_ ||
                        vah != last_vp_vah_ ||
                        val != last_vp_val_;
                    const int64_t now_vp_ms = steady_now_ms();
                    const bool allow_vp_zmq =
                        volume_profile_publish_min_ms_ <= 0 ||
                        last_volume_profile_pub_ms_ == 0 ||
                        (now_vp_ms - last_volume_profile_pub_ms_ >=
                         volume_profile_publish_min_ms_) ||
                        anchor_changed;
                    if (allow_vp_zmq) {
                        last_volume_profile_pub_ms_ = now_vp_ms;
                        last_vp_poc_ = poc;
                        last_vp_vah_ = vah;
                        last_vp_val_ = val;
                        last_vp_anchor_valid_ = true;
                        zmq::message_t vp_out(vp_msg->dump());
                        pub.send(vp_out, zmq::send_flags::none);
                    } else {
                        volume_profile_throttle_skips_ += 1;
                    }
                }
                if (ti_msg) {
                    const int64_t poc = vp_snapshot.value("poc", 0);
                    const int64_t vah = vp_snapshot.value("vah", 0);
                    const int64_t val = vp_snapshot.value("val", 0);
                    const bool anchor_changed =
                        !last_ti_anchor_valid_ ||
                        poc != last_ti_poc_ ||
                        vah != last_ti_vah_ ||
                        val != last_ti_val_;
                    const int64_t now_ti_ms = steady_now_ms();
                    const bool allow_ti_zmq =
                        tape_intelligence_publish_min_ms_ <= 0 ||
                        last_tape_intelligence_pub_ms_ == 0 ||
                        (now_ti_ms - last_tape_intelligence_pub_ms_ >=
                         tape_intelligence_publish_min_ms_) ||
                        anchor_changed;
                    if (allow_ti_zmq) {
                        last_tape_intelligence_pub_ms_ = now_ti_ms;
                        last_ti_poc_ = poc;
                        last_ti_vah_ = vah;
                        last_ti_val_ = val;
                        last_ti_anchor_valid_ = true;
                        nlohmann::json ti_body = *ti_msg;
                        enrich_tape_intelligence_agent_names(
                            ti_body,
                            agent_name_resolver_,
                            agent_name_cache_,
                            agent_cache_mutex_);
                        zmq::message_t ti_out(ti_body.dump());
                        pub.send(ti_out, zmq::send_flags::none);
                    } else {
                        tape_intelligence_throttle_skips_ += 1;
                    }
                }
                if (alert_bus_ && dispatcher_) {
                    rules::Alert alert;
                    while (alert_bus_->try_pop(alert)) {
                        dispatcher_->dispatch_alert(alert);
                        publish_alert(pub, alert);
                    }
                }
                } else if constexpr (std::is_same_v<T, event_bus::OfferBookEvent>) {
                offer_events_processed_++;
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
                    int64_t now_ms_dom = steady_now_ms();
                    const bool allow_dom_zmq =
                        dom_snapshot_publish_min_ms_ <= 0 ||
                        (now_ms_dom - last_dom_snapshot_pub_ms_ >=
                         dom_snapshot_publish_min_ms_);
                    if (allow_dom_zmq) {
                        last_dom_snapshot_pub_ms_ = now_ms_dom;
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
                    } else {
                        dom_snapshot_throttle_skips_ += 1;
                    }
                }


                if (alert_bus_ && dispatcher_) {
                    rules::Alert alert;
                    while (alert_bus_->try_pop(alert)) {
                        dispatcher_->dispatch_alert(alert);
                        publish_alert(pub, alert);
                    }
                }
                } else if constexpr (std::is_same_v<T, event_bus::DailyEvent>) {
                daily_events_processed_++;
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
                if (!e.trade_date.empty())
                    j["trade_date"] = e.trade_date;
                zmq::message_t msg(j.dump());
                pub.send(msg, zmq::send_flags::none);
                }
            }, ev);
        }

        int64_t now_ms = steady_now_ms();
        if (now_ms >= metrics_next_log_ms_) {
            auto qm = queue_.metrics();
            auto rstats = reconciler_.stats();
            auto shm_stats = shm_writer_ ? shm_writer_->stats() : shared_memory_ipc::SharedMemoryRingWriter::Stats{};
            double avg_trade_latency = trade_latency_count_ > 0
                ? static_cast<double>(trade_latency_sum_ms_) / static_cast<double>(trade_latency_count_)
                : 0.0;
            std::cerr
                << "[ZmqPublisher] Metrics: q_trade=" << qm.trade_size
                << " q_normal=" << qm.normal_size
                << " events(trade/offer/daily)=" << trade_events_processed_
                << "/" << offer_events_processed_
                << "/" << daily_events_processed_
                << " trade_latency_ms(avg/max)=" << avg_trade_latency
                << "/" << max_trade_latency_ms_
                << " reconciler_duplicates=" << reconcile_duplicates_ignored_
                << " history_trades_received=" << rstats.history_trades_received
                << " realtime_trades_received=" << rstats.realtime_trades_received
                << " edits_applied=" << rstats.edits_applied
                << " duplicates_ignored=" << rstats.duplicates_ignored
                << " reconciler_seen=" << reconciler_.seen_size()
                << " reconcile_errors=" << rstats.reconcile_errors
                << " dom_snapshot_skipped=" << dom_snapshot_throttle_skips_
                << " volume_profile_skipped=" << volume_profile_throttle_skips_
                << " tape_intelligence_skipped=" << tape_intelligence_throttle_skips_
                << " shm_enabled=" << (shm_writer_ ? 1 : 0)
                << " shm_write_seq=" << shm_stats.write_seq
                << " shm_dropped=" << shm_stats.dropped
                << " shm_capacity=" << shm_stats.capacity
                << " shm_mapped_bytes=" << shm_stats.mapped_size_bytes
                << " shm_large_pages=" << shm_stats.large_pages
                << " shm_numa_node=" << shm_stats.numa_node
                << std::endl;
            metrics_next_log_ms_ = now_ms + 5000;
        }
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
