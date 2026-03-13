#pragma once

#include "rule_base.h"
#include <unordered_map>

namespace rules {

class Rule3Vwap : public RuleBase {
public:
    explicit Rule3Vwap(alert_bus::AlertBus& ab);

    void on_trade(const TradeEvent& ev) override;
    std::string_view name() const override { return "Rule3Vwap"; }

private:
    struct AgentVwap {
        double vwap_num   = 0;
        double vwap_denom = 0;
        int64_t total_qty = 0;
    };
    std::unordered_map<int32_t, AgentVwap> agent_vwaps_;
    double day_vwap_num_   = 0;
    double day_vwap_denom_ = 0;
};

} // namespace rules
