#pragma once

#include <algorithm>
#include <cstdint>
#include <deque>
#include <unordered_map>
#include <utility>
#include <vector>
#include <chrono>

class AgentRanking {
public:
    struct AgentEntry {
        int64_t buy_qty = 0;
        int64_t sell_qty = 0;
        int64_t net() const { return buy_qty - sell_qty; }
    };

    void on_trade(int32_t buy_agent, int32_t sell_agent,
                  int64_t qty, uint8_t trade_type, int64_t ts_ms) {
        if (trade_type == 2) {
            agents_[buy_agent].buy_qty += qty;
            trade_log_.push_back({buy_agent, qty, true, ts_ms});
        } else if (trade_type == 3) {
            agents_[sell_agent].sell_qty += qty;
            trade_log_.push_back({sell_agent, qty, false, ts_ms});
        }
        prune_log(ts_ms);
    }

    int64_t agent_net(int32_t agent_id) const {
        auto it = agents_.find(agent_id);
        return it != agents_.end() ? it->second.net() : 0;
    }

    std::vector<std::pair<int32_t, int64_t>> top_buyers(int n) const {
        return top_n(true, n);
    }

    std::vector<std::pair<int32_t, int64_t>> top_sellers(int n) const {
        return top_n(false, n);
    }

    int64_t agent_delta(int32_t agent_id, int64_t window_ms) const {
        if (trade_log_.empty()) return 0;
        int64_t cutoff = trade_log_.back().ts_ms - window_ms;
        int64_t delta = 0;
        for (auto it = trade_log_.rbegin(); it != trade_log_.rend(); ++it) {
            if (it->ts_ms < cutoff) break;
            if (it->agent_id == agent_id) {
                delta += it->is_buy ? it->qty : -it->qty;
            }
        }
        return delta;
    }

    void reset() {
        agents_.clear();
        trade_log_.clear();
    }

private:
    struct TimedTrade {
        int32_t agent_id;
        int64_t qty;
        bool is_buy;
        int64_t ts_ms;
    };

    static constexpr int64_t MAX_LOG_AGE_MS = 60000;

    void prune_log(int64_t now_ms) {
        int64_t cutoff = now_ms - MAX_LOG_AGE_MS;
        while (!trade_log_.empty() && trade_log_.front().ts_ms < cutoff) {
            trade_log_.pop_front();
        }
    }

    std::vector<std::pair<int32_t, int64_t>> top_n(bool buyers, int n) const {
        std::vector<std::pair<int32_t, int64_t>> result;
        for (const auto& [id, entry] : agents_) {
            int64_t score = buyers ? entry.buy_qty : entry.sell_qty;
            if (score > 0) {
                result.emplace_back(id, score);
            }
        }
        std::sort(result.begin(), result.end(),
                  [](const auto& a, const auto& b) { return a.second > b.second; });
        if (static_cast<int>(result.size()) > n) {
            result.resize(n);
        }
        return result;
    }

    std::unordered_map<int32_t, AgentEntry> agents_;
    std::deque<TimedTrade> trade_log_;
};
