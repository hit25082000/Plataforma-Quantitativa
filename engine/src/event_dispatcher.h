#pragma once

#include "alert_bus.h"
#include "alert_types.h"
#include "dom_snapshot.h"
#include "rules/rule_base.h"
#include "trade_stream.h"
#include <memory>
#include <vector>

namespace event_dispatcher {

class EventDispatcher {
public:
    EventDispatcher(alert_bus::AlertBus& alert_bus,
                    dom_snapshot::DOMSnapshotEngine& dom,
                    trade_stream::TradeStreamProcessor& trade_proc,
                    const std::string& ticker);

    void add_rule(std::unique_ptr<rules::RuleBase> rule);
    void set_ticker(const std::string& t) { ticker_ = t; }

    void dispatch_trade(const event_bus::TradeEvent& raw,
                        double vwap, int64_t net_aggression,
                        const trade_stream::AgentStats& agent_stats);
    void dispatch_wall_add(const dom_snapshot::WallEvent& w);
    void dispatch_wall_remove(const dom_snapshot::WallRemoveEvent& w);
    void dispatch_dom_snapshot(const dom_snapshot::DOMSnapshotEvent& snap);
    void dispatch_alert(const rules::Alert& a);
    void dispatch_daily(const event_bus::DailyEvent& d);

private:
    alert_bus::AlertBus& alert_bus_;
    dom_snapshot::DOMSnapshotEngine& dom_;
    trade_stream::TradeStreamProcessor& trade_proc_;
    std::string ticker_;
    std::vector<std::unique_ptr<rules::RuleBase>> rules_;
};

} // namespace event_dispatcher
