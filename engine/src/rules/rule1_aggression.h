#pragma once

#include "rule_base.h"
#include "../dom_snapshot.h"
#include "../agent_ranking.h"
#include <deque>
#include <vector>

namespace rules {

class Rule1Aggression : public RuleBase {
public:
    Rule1Aggression(alert_bus::AlertBus& ab,
                    const dom_snapshot::DOMSnapshotEngine& dom,
                    const AgentRanking& ranking);

    void on_trade(const TradeEvent& ev) override;
    void on_daily(const DailyInfoEvent& ev) override;
    std::string_view name() const override { return "Rule1Aggression"; }

private:
    enum class State { IDLE, BREAKOUT_HIGH, BREAKOUT_LOW };

    State state_ = State::IDLE;
    double day_high_ = 0;
    double day_low_  = 1e18;
    double breakout_price_ = 0;
    int64_t breakout_ts_ = 0;
    int64_t opposite_agg_accum_ = 0;

    // Top 5 agentes no momento do breakout (para checar exaustão)
    std::vector<std::pair<int32_t, int64_t>> breakout_top_agents_;

    const dom_snapshot::DOMSnapshotEngine& dom_;
    const AgentRanking& ranking_;

    bool validate_dom_ralo(bool is_high_breakout, double price) const;
    bool validate_agent_exhaustion() const;
    void fire_alert(const TradeEvent& ev, bool is_high);
    void reset_state();
};

} // namespace rules
