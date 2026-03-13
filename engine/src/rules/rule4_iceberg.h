#pragma once

#include "rule_base.h"
#include <vector>

namespace rules {

struct RecentRemoval {
    int64_t offer_id;
    int64_t qty;
    int32_t agent_id;
    int64_t ts_ms;
    bool had_trade = false;
};

class Rule4Iceberg : public RuleBase {
public:
    explicit Rule4Iceberg(alert_bus::AlertBus& ab);

    void on_wall_add(const WallAddEvent& ev) override;
    void on_wall_remove(const WallRemoveEvent& ev) override;
    void on_trade(const TradeEvent& ev) override;
    std::string_view name() const override { return "Rule4Iceberg"; }

    RecentRemoval* find_removal_at_price(double price);

private:
    std::vector<std::pair<double, RecentRemoval>> recent_removals_;
};

} // namespace rules
