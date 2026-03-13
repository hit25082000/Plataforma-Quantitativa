#pragma once

#include "rule_base.h"
#include <unordered_map>

namespace rules {

struct PendingWall {
    double price;
    int64_t ts_ms;
    bool traded;
    int32_t agent_id;
};

class Rule2Wall : public RuleBase {
public:
    explicit Rule2Wall(alert_bus::AlertBus& ab);

    void on_wall_add(const WallAddEvent& ev) override;
    void on_wall_remove(const WallRemoveEvent& ev) override;
    void on_trade(const TradeEvent& ev) override;
    std::string_view name() const override { return "Rule2Wall"; }

private:
    std::unordered_map<int64_t, PendingWall> pending_walls_;
};

} // namespace rules
