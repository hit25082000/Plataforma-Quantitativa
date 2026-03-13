#pragma once

#include "rule_base.h"
#include "rsi_calculator.h"
#include "../dom_snapshot.h"
#include "../agent_ranking.h"
#include <deque>
#include <vector>
#include <cmath>

namespace rules {

class Rule6Absorption : public RuleBase {
public:
    Rule6Absorption(alert_bus::AlertBus& ab,
                    const AgentRanking& ranking,
                    const dom_snapshot::DOMSnapshotEngine& dom);

    void on_trade(const TradeEvent& ev) override;
    void on_wall_add(const WallAddEvent& ev) override;
    void on_wall_remove(const WallRemoveEvent& ev) override;
    std::string_view name() const override { return "Rule6Absorption"; }

private:
    const AgentRanking& ranking_;
    const dom_snapshot::DOMSnapshotEngine& dom_;

    // Candles sintéticos de 30 min
    struct Candle {
        double open = 0, high = 0, low = 1e18, close = 0;
        int64_t volume = 0;
        int64_t start_ms = 0;
        bool active = false;
    };
    std::deque<Candle> candles_;
    Candle current_candle_{};

    // RSI para o TG de 30 min (sobre closes de candles)
    RsiCalculator rsi_30m_;

    // Iceberg detection (absorvida da R4)
    struct IcebergEntry {
        int64_t offer_id;
        double price;
        int64_t qty;
        int32_t agent_id;
        int64_t ts_ms;
        bool had_trade;
    };
    std::vector<IcebergEntry> recent_removals_;
    int64_t iceberg_score_ = 0;

    void close_candle();
    bool check_effort_vs_result(const Candle& c) const;
    bool check_top4_accumulating() const;
    double avg_volume() const;
};

} // namespace rules
