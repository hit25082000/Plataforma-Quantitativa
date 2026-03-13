#pragma once

#include "../alert_bus.h"
#include <string_view>
#include "../alert_types.h"

namespace rules {

class RuleBase {
public:
    virtual void on_trade(const TradeEvent&) {}
    virtual void on_wall_add(const WallAddEvent&) {}
    virtual void on_wall_remove(const WallRemoveEvent&) {}
    virtual void on_dom_snapshot(const DomSnapshotEvent&) {}
    virtual void on_alert(const Alert&) {}
    virtual void on_daily(const DailyInfoEvent&) {}
    virtual std::string_view name() const = 0;
    virtual ~RuleBase() = default;

protected:
    alert_bus::AlertBus& alert_bus_;
    explicit RuleBase(alert_bus::AlertBus& ab) : alert_bus_(ab) {}
};

} // namespace rules
