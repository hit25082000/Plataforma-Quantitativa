#include "event_dispatcher.h"
#include <chrono>

namespace event_dispatcher {

EventDispatcher::EventDispatcher(alert_bus::AlertBus& alert_bus,
                                 dom_snapshot::DOMSnapshotEngine& dom,
                                 trade_stream::TradeStreamProcessor& trade_proc,
                                 const std::string& ticker)
    : alert_bus_(alert_bus)
    , dom_(dom)
    , trade_proc_(trade_proc)
    , ticker_(ticker)
{}

void EventDispatcher::add_rule(std::unique_ptr<rules::RuleBase> rule) {
    rules_.push_back(std::move(rule));
}

void EventDispatcher::dispatch_trade(const event_bus::TradeEvent& raw,
                                     double vwap, int64_t net_aggression,
                                     const trade_stream::AgentStats& agent_stats) {
    if (raw.ticker != ticker_) return;

    rules::TradeEvent ev;
    ev.ticker = raw.ticker;
    ev.price = raw.price;
    ev.qty = raw.qty;
    ev.buy_agent = raw.buy_agent;
    ev.sell_agent = raw.sell_agent;
    ev.trade_type = raw.trade_type;
    ev.vwap_atual = vwap;
    ev.net_aggression = net_aggression;
    ev.agent_stats.buy_aggression_qty = agent_stats.buy_aggression_qty;
    ev.agent_stats.sell_aggression_qty = agent_stats.sell_aggression_qty;

    for (auto& r : rules_) {
        r->on_trade(ev);
    }
}

void EventDispatcher::dispatch_wall_add(const dom_snapshot::WallEvent& w) {
    if (w.ticker != ticker_) return;

    rules::WallAddEvent ev;
    ev.ticker = w.ticker;
    ev.offer_id = w.offer_id;
    ev.price = w.price;
    ev.qty = w.qty;
    ev.side = w.side;
    ev.agent_id = w.agent_id;
    ev.timestamp_ms = w.timestamp_ms;

    for (auto& r : rules_) {
        r->on_wall_add(ev);
    }
}

void EventDispatcher::dispatch_wall_remove(const dom_snapshot::WallRemoveEvent& w) {
    if (w.ticker != ticker_) return;

    rules::WallRemoveEvent ev;
    ev.ticker = w.ticker;
    ev.offer_id = w.offer_id;
    ev.price = w.price;
    ev.qty = w.qty;
    ev.agent_id = w.agent_id;
    ev.elapsed_ms = w.elapsed_ms;
    ev.was_traded = w.was_traded;

    for (auto& r : rules_) {
        r->on_wall_remove(ev);
    }
}

void EventDispatcher::dispatch_dom_snapshot(const dom_snapshot::DOMSnapshotEvent& snap) {
    if (snap.ticker != ticker_) return;

    rules::DomSnapshotEvent ev;
    ev.ticker = snap.ticker;
    for (const auto& [p, q, c] : snap.buy) {
        ev.buy_side.push_back({p, q});
    }
    for (const auto& [p, q, c] : snap.sell) {
        ev.sell_side.push_back({p, q});
    }

    for (auto& r : rules_) {
        r->on_dom_snapshot(ev);
    }
}

void EventDispatcher::dispatch_alert(const rules::Alert& a) {
    for (auto& r : rules_) {
        r->on_alert(a);
    }
}

void EventDispatcher::dispatch_daily(const event_bus::DailyEvent& d) {
    rules::DailyInfoEvent ev;
    ev.ticker = d.ticker;
    ev.high = d.high;
    ev.low = d.low;
    ev.open = d.open;
    ev.close = d.close;

    for (auto& r : rules_) {
        r->on_daily(ev);
    }
}

} // namespace event_dispatcher
