#pragma once

#include "event_bus.h"
#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>

class TradeReconciler {
public:
    struct Stats {
        int64_t history_trades_received = 0;
        int64_t realtime_trades_received = 0;
        int64_t edits_applied = 0;
        int64_t duplicates_ignored = 0;
        int64_t reconcile_errors = 0;
    };

    struct ApplyResult {
        bool accepted = false;
        bool is_edit = false;
        bool is_duplicate = false;
        std::string key;
    };

    ApplyResult apply(const event_bus::TradeEvent& ev);
    void reset();
    Stats stats() const { return stats_; }

private:
    struct TradeIdentity {
        int32_t buy_agent = 0;
        int32_t sell_agent = 0;
        int64_t qty = 0;
        double price = 0.0;
        uint8_t trade_type = 0;
        std::string trade_date;
    };

    std::string make_key(const event_bus::TradeEvent& ev) const;
    static bool same_identity(const TradeIdentity& a, const TradeIdentity& b);

    std::unordered_map<std::string, TradeIdentity> seen_;
    Stats stats_{};
};
