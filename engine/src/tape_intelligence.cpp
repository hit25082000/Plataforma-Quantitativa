#include "tape_intelligence.h"
#include "profit_types.h"

#include <algorithm>
#include <cmath>
#include <cctype>
#include <chrono>
#include <iostream>
#include <atomic>
#include <sstream>

namespace tape_intelligence {

namespace {
int64_t system_now_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
}
} // namespace

TapeIntelligenceEngine::TapeIntelligenceEngine(std::string ticker, int64_t tick_size)
    : ticker_(std::move(ticker))
    , tick_size_(tick_size > 0 ? tick_size : 5) {}

void TapeIntelligenceEngine::set_ticker(std::string ticker) {
    std::lock_guard<std::mutex> lock(mutex_);
    ticker_ = std::move(ticker);
    levels_by_player_.clear();
    session_by_player_.clear();
}

void TapeIntelligenceEngine::reset() {
    std::lock_guard<std::mutex> lock(mutex_);
    levels_by_player_.clear();
    session_by_player_.clear();
}

void TapeIntelligenceEngine::set_region_ticks(int poc_ticks, int val_ticks, int vah_ticks) {
    std::lock_guard<std::mutex> lock(mutex_);
    poc_region_ticks_ = std::max(0, poc_ticks);
    val_region_ticks_ = std::max(0, val_ticks);
    vah_region_ticks_ = std::max(0, vah_ticks);
}

void TapeIntelligenceEngine::set_min_absorption_contracts(uint64_t min_contracts) {
    std::lock_guard<std::mutex> lock(mutex_);
    min_absorption_contracts_ = min_contracts;
}

void TapeIntelligenceEngine::set_min_participation_pct(double pct) {
    std::lock_guard<std::mutex> lock(mutex_);
    min_participation_pct_ = std::max(0.0, pct);
}

void TapeIntelligenceEngine::set_top_player_avg_config(TopAvgRankMode mode,
                                                        size_t max_lines,
                                                        uint64_t min_contracts) {
    std::lock_guard<std::mutex> lock(mutex_);
    top_avg_rank_mode_ = mode;
    top_avg_max_lines_ = max_lines > 0 ? max_lines : 6;
    top_avg_min_contracts_ = min_contracts;
}

int64_t TapeIntelligenceEngine::normalize_price(double price) const {
    if (!std::isfinite(price)) return 0;
    const double tick = static_cast<double>(tick_size_);
    return static_cast<int64_t>(std::llround(price / tick) * tick_size_);
}

std::vector<LevelSnapshot> TapeIntelligenceEngine::serialize_ranked_region(
    const std::map<int32_t, PlayerLevels>& levels_by_player,
    int64_t center_price,
    int64_t tick_size,
    int region_ticks,
    size_t limit)
{
    std::vector<LevelSnapshot> out;
    const int rt = std::max(0, region_ticks);
    for (const auto& [player, levels] : levels_by_player) {
        LevelSnapshot agg{};
        agg.player = player;
        agg.price = center_price;
        for (int t = -rt; t <= rt; ++t) {
            const int64_t price = center_price + static_cast<int64_t>(t) * tick_size;
            auto it = levels.find(price);
            if (it == levels.end()) continue;
            const auto& acc = it->second;
            agg.bid_vol += acc.bid_vol;
            agg.ask_vol += acc.ask_vol;
            agg.neutral_vol += acc.neutral_vol;
            agg.buy_absorption += acc.buy_absorption;
            agg.sell_absorption += acc.sell_absorption;
            agg.total_vol += acc.total();
        }
        if (agg.total_vol == 0) continue;
        out.push_back(agg);
    }
    std::sort(out.begin(), out.end(), [](const auto& a, const auto& b) {
        if (a.total_vol != b.total_vol) return a.total_vol > b.total_vol;
        return a.player < b.player;
    });
    if (out.size() > limit) out.resize(limit);
    return out;
}

int32_t TapeIntelligenceEngine::choose_player_total(const std::vector<LevelSnapshot>& levels) {
    if (levels.empty()) return 0;
    int32_t best_player = 0;
    uint64_t best = 0;
    for (const auto& lvl : levels) {
        if (lvl.total_vol > best || (lvl.total_vol == best && lvl.player < best_player)) {
            best = lvl.total_vol;
            best_player = lvl.player;
        }
    }
    return best_player;
}

int32_t TapeIntelligenceEngine::choose_player_buy_absorption(const std::vector<LevelSnapshot>& levels) {
    if (levels.empty()) return 0;
    int32_t best_player = 0;
    uint64_t best = 0;
    for (const auto& lvl : levels) {
        if (lvl.buy_absorption > best || (lvl.buy_absorption == best && lvl.player < best_player)) {
            best = lvl.buy_absorption;
            best_player = lvl.player;
        }
    }
    return best_player;
}

int32_t TapeIntelligenceEngine::choose_player_sell_absorption(const std::vector<LevelSnapshot>& levels) {
    if (levels.empty()) return 0;
    int32_t best_player = 0;
    uint64_t best = 0;
    for (const auto& lvl : levels) {
        if (lvl.sell_absorption > best || (lvl.sell_absorption == best && lvl.player < best_player)) {
            best = lvl.sell_absorption;
            best_player = lvl.player;
        }
    }
    return best_player;
}

nlohmann::json TapeIntelligenceEngine::build_top_player_avg_lines_unlocked() const {
    nlohmann::json arr = nlohmann::json::array();
    const size_t cap = top_avg_max_lines_;
    if (cap == 0 || session_by_player_.empty()) {
        return arr;
    }

    struct Row {
        int32_t pid = 0;
        uint64_t rk = 0;
        double avg = 0.0;
        std::string mode;
        bool dashed = false;
    };
    std::vector<Row> rows;
    rows.reserve(session_by_player_.size());

    const uint64_t mn = top_avg_min_contracts_;

    for (const auto& [pid, st] : session_by_player_) {
        if (pid == 0) continue;
        switch (top_avg_rank_mode_) {
        case TopAvgRankMode::TopTotalVolume:
            if (st.total_qty < mn) continue;
            if (st.total_qty == 0) continue;
            rows.push_back(
                {pid,
                 st.total_qty,
                 st.total_notional / static_cast<double>(st.total_qty),
                 "total",
                 false});
            break;
        case TopAvgRankMode::TopBuyVolume:
            if (st.buy_qty < mn) continue;
            if (st.buy_qty == 0) continue;
            rows.push_back(
                {pid,
                 st.buy_qty,
                 st.buy_notional / static_cast<double>(st.buy_qty),
                 "buy",
                 true});
            break;
        case TopAvgRankMode::TopSellVolume:
            if (st.sell_qty < mn) continue;
            if (st.sell_qty == 0) continue;
            rows.push_back(
                {pid,
                 st.sell_qty,
                 st.sell_notional / static_cast<double>(st.sell_qty),
                 "sell",
                 true});
            break;
        case TopAvgRankMode::TopNetVolume: {
            if (st.total_qty < mn) continue;
            const int64_t net =
                static_cast<int64_t>(st.buy_qty) - static_cast<int64_t>(st.sell_qty);
            const uint64_t ab = net >= 0 ? static_cast<uint64_t>(net)
                                         : static_cast<uint64_t>(-net);
            if (st.total_qty == 0) continue;
            rows.push_back({pid,
                            ab,
                            st.total_notional / static_cast<double>(st.total_qty),
                            "net",
                            false});
            break;
        }
        }
    }

    std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) {
        if (a.rk != b.rk) return a.rk > b.rk;
        return a.pid < b.pid;
    });

    const size_t n = std::min(cap, rows.size());
    for (size_t i = 0; i < n; ++i) {
        const Row& r = rows[i];
        char prefix = 'T';
        if (r.mode == "buy") {
            prefix = 'B';
        } else if (r.mode == "sell") {
            prefix = 'S';
        } else if (r.mode == "net") {
            prefix = 'N';
        }
        std::string label = std::string(1, prefix) + std::to_string(r.pid);
        arr.push_back({
            {"player_id", r.pid},
            {"mode", r.mode},
            {"avg_price", r.avg},
            {"label", label},
            {"dashed", r.dashed},
        });
    }
    return arr;
}

void TapeIntelligenceEngine::apply_trade_unlocked(const event_bus::TradeEvent& ev, int64_t level_price) {
    const bool is_sell = ev.trade_type == profit::TRADE_TYPE_SELL_AGGRESSION;
    const bool is_buy = ev.trade_type == profit::TRADE_TYPE_BUY_AGGRESSION;
    const bool is_unclassified = ev.trade_type == profit::TRADE_TYPE_UNCLASSIFIED;
    if (!is_sell && !is_buy && !is_unclassified) return;
    const uint64_t q = static_cast<uint64_t>(ev.qty);
    const double px = ev.price;
    const int64_t ts = system_now_ms();

    auto bump_session = [&](int32_t pid, uint64_t add_buy, uint64_t add_sell, uint64_t add_neutral) {
        if (pid == 0) return;
        auto& st = session_by_player_[pid];
        if (add_buy > 0) {
            st.buy_qty += add_buy;
            st.total_qty += add_buy;
            st.buy_notional += px * static_cast<double>(add_buy);
            st.total_notional += px * static_cast<double>(add_buy);
        }
        if (add_sell > 0) {
            st.sell_qty += add_sell;
            st.total_qty += add_sell;
            st.sell_notional += px * static_cast<double>(add_sell);
            st.total_notional += px * static_cast<double>(add_sell);
        }
        if (add_neutral > 0) {
            st.total_qty += add_neutral;
            st.total_notional += px * static_cast<double>(add_neutral);
        }
        st.last_trade_ts = ts;
    };

    if (is_unclassified) {
        if (ev.buy_agent != 0) {
            levels_by_player_[ev.buy_agent][level_price].neutral_vol += q;
        }
        if (ev.sell_agent != 0) {
            levels_by_player_[ev.sell_agent][level_price].neutral_vol += q;
        }
        bump_session(ev.buy_agent, 0, 0, q);
        bump_session(ev.sell_agent, 0, 0, q);
        return;
    }

    if (is_sell) {
        auto& sell_acc = levels_by_player_[ev.sell_agent][level_price];
        sell_acc.ask_vol += q;
        sell_acc.sell_aggression += q;
        auto& buy_acc = levels_by_player_[ev.buy_agent][level_price];
        buy_acc.buy_absorption += q;
        bump_session(ev.sell_agent, 0, q, 0);
        bump_session(ev.buy_agent, q, 0, 0);
    } else {
        auto& buy_acc = levels_by_player_[ev.buy_agent][level_price];
        buy_acc.bid_vol += q;
        buy_acc.buy_aggression += q;
        auto& sell_acc = levels_by_player_[ev.sell_agent][level_price];
        sell_acc.sell_absorption += q;
        bump_session(ev.buy_agent, q, 0, 0);
        bump_session(ev.sell_agent, 0, q, 0);
    }
}

std::optional<nlohmann::json> TapeIntelligenceEngine::on_trade(
    const event_bus::TradeEvent& ev,
    int64_t poc_price,
    int64_t vah_price,
    int64_t val_price)
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (!ticker_.empty() && ev.ticker != ticker_) return std::nullopt;
    if (ev.qty <= 0) return std::nullopt;

    const int64_t level_price = normalize_price(ev.price);
    if (level_price == 0 && ev.price != 0.0) return std::nullopt;

    const bool is_sell = ev.trade_type == profit::TRADE_TYPE_SELL_AGGRESSION;
    const bool is_buy = ev.trade_type == profit::TRADE_TYPE_BUY_AGGRESSION;
    const bool is_unclassified = ev.trade_type == profit::TRADE_TYPE_UNCLASSIFIED;
    if (!is_sell && !is_buy && !is_unclassified) {
        static std::atomic<int> unknown_logged{0};
        if (unknown_logged.fetch_add(1) < 32) {
            std::cerr << "[TapeIntelligence] ignoring unknown trade_type="
                      << static_cast<int>(ev.trade_type) << " ticker=" << ev.ticker << std::endl;
        }
        return build_payload_unlocked(poc_price, vah_price, val_price);
    }
    apply_trade_unlocked(ev, level_price);
    return build_payload_unlocked(poc_price, vah_price, val_price);
}

nlohmann::json TapeIntelligenceEngine::build_payload(int64_t poc_price,
                                                     int64_t vah_price,
                                                     int64_t val_price) const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return build_payload_unlocked(poc_price, vah_price, val_price);
}

nlohmann::json TapeIntelligenceEngine::export_player_sessions_json() const {
    std::lock_guard<std::mutex> lock(mutex_);
    nlohmann::json out = nlohmann::json::object();
    for (const auto& [pid, st] : session_by_player_) {
        nlohmann::json row = {
            {"buy_qty", st.buy_qty},
            {"sell_qty", st.sell_qty},
            {"total_qty", st.total_qty},
            {"buy_notional", st.buy_notional},
            {"sell_notional", st.sell_notional},
            {"total_notional", st.total_notional},
            {"last_trade_ts", st.last_trade_ts},
        };
        if (st.buy_qty > 0) row["buy_avg_price"] = st.buy_notional / static_cast<double>(st.buy_qty);
        if (st.sell_qty > 0) row["sell_avg_price"] = st.sell_notional / static_cast<double>(st.sell_qty);
        if (st.total_qty > 0) row["total_avg_price"] = st.total_notional / static_cast<double>(st.total_qty);
        out[std::to_string(pid)] = std::move(row);
    }
    return out;
}

nlohmann::json TapeIntelligenceEngine::build_payload_unlocked(int64_t poc_price,
                                                              int64_t vah_price,
                                                              int64_t val_price) const
{
    const int64_t step = tick_size_;
    const auto poc_levels = serialize_ranked_region(levels_by_player_, poc_price, step, poc_region_ticks_, 3);
    const auto vah_levels = serialize_ranked_region(levels_by_player_, vah_price, step, vah_region_ticks_, 3);
    const auto val_levels = serialize_ranked_region(levels_by_player_, val_price, step, val_region_ticks_, 3);

    int32_t poc_player = choose_player_total(poc_levels);
    int32_t val_buyer = choose_player_buy_absorption(val_levels);
    int32_t vah_seller = choose_player_sell_absorption(vah_levels);

    auto sum_buy_abs = [](const std::vector<LevelSnapshot>& lv) -> uint64_t {
        uint64_t s = 0;
        for (const auto& x : lv) s += x.buy_absorption;
        return s;
    };
    auto sum_sell_abs = [](const std::vector<LevelSnapshot>& lv) -> uint64_t {
        uint64_t s = 0;
        for (const auto& x : lv) s += x.sell_absorption;
        return s;
    };
    auto winner_buy_abs = [&](int32_t pid) -> uint64_t {
        if (pid == 0) return 0;
        for (const auto& x : val_levels) {
            if (x.player == pid) return x.buy_absorption;
        }
        return 0;
    };
    auto winner_sell_abs = [&](int32_t pid) -> uint64_t {
        if (pid == 0) return 0;
        for (const auto& x : vah_levels) {
            if (x.player == pid) return x.sell_absorption;
        }
        return 0;
    };

    const uint64_t val_abs_total = sum_buy_abs(val_levels);
    const uint64_t vah_abs_total = sum_sell_abs(vah_levels);
    const uint64_t val_w = winner_buy_abs(val_buyer);
    const uint64_t vah_w = winner_sell_abs(vah_seller);

    std::string val_state = "ok";
    std::string vah_state = "ok";
    if (val_abs_total < min_absorption_contracts_ || val_w < min_absorption_contracts_) {
        val_buyer = 0;
        val_state = "unconfirmed";
    } else if (min_participation_pct_ > 0.0 && val_abs_total > 0) {
        const double pct = 100.0 * static_cast<double>(val_w) / static_cast<double>(val_abs_total);
        if (pct + 1e-9 < min_participation_pct_) {
            val_buyer = 0;
            val_state = "low_confidence";
        }
    }
    if (vah_abs_total < min_absorption_contracts_ || vah_w < min_absorption_contracts_) {
        vah_seller = 0;
        vah_state = "unconfirmed";
    } else if (min_participation_pct_ > 0.0 && vah_abs_total > 0) {
        const double pct = 100.0 * static_cast<double>(vah_w) / static_cast<double>(vah_abs_total);
        if (pct + 1e-9 < min_participation_pct_) {
            vah_seller = 0;
            vah_state = "low_confidence";
        }
    }

    auto serialize = [](const std::vector<LevelSnapshot>& levels) {
        nlohmann::json out = nlohmann::json::array();
        for (const auto& lvl : levels) {
            out.push_back({
                {"player", lvl.player},
                {"price", lvl.price},
                {"total_vol", lvl.total_vol},
                {"bid_vol", lvl.bid_vol},
                {"ask_vol", lvl.ask_vol},
                {"neutral_vol", lvl.neutral_vol},
                {"buy_absorption", lvl.buy_absorption},
                {"sell_absorption", lvl.sell_absorption},
            });
        }
        return out;
    };

    return nlohmann::json{
        {"topic", "market"},
        {"type", "tape_intelligence"},
        {"ticker", ticker_},
        {"timestamp", system_now_ms()},
        {"poc_price", poc_price},
        {"vah_price", vah_price},
        {"val_price", val_price},
        {"poc_player", poc_player},
        {"val_buyer", val_buyer},
        {"vah_seller", vah_seller},
        {"val_holder_state", val_state},
        {"vah_holder_state", vah_state},
        {"poc_top3", serialize(poc_levels)},
        {"vah_top3", serialize(vah_levels)},
        {"val_top3", serialize(val_levels)},
        {"top_player_avg_lines", build_top_player_avg_lines_unlocked()},
    };
}

} // namespace tape_intelligence
