#include "trade_reconciler.h"

#include "profit_types.h"
#include <iomanip>
#include <sstream>

namespace {
std::string fallback_key(const event_bus::TradeEvent& ev) {
    std::ostringstream oss;
    oss << ev.ticker << '|'
        << ev.bolsa << '|'
        << ev.trade_date << '|'
        << ev.trade_epoch_ms << '|'
        << std::fixed << std::setprecision(8) << ev.price << '|'
        << ev.qty << '|'
        << ev.buy_agent << '|'
        << ev.sell_agent << '|'
        << static_cast<int>(ev.trade_type);
    return oss.str();
}
} // namespace

TradeReconciler::ApplyResult TradeReconciler::apply(const event_bus::TradeEvent& ev) {
    ApplyResult out;
    out.is_edit = (ev.trade_flags & profit::TC_IS_EDIT) == profit::TC_IS_EDIT;
    out.key = make_key(ev);

    if (ev.source == event_bus::TradeSource::History) stats_.history_trades_received++;
    else stats_.realtime_trades_received++;

    TradeIdentity incoming{
        ev.buy_agent,
        ev.sell_agent,
        ev.qty,
        ev.price,
        ev.trade_type,
        ev.trade_date
    };

    auto it = seen_.find(out.key);
    if (it == seen_.end()) {
        seen_.emplace(out.key, incoming);
        out.accepted = true;
        if (out.is_edit) stats_.edits_applied++;
        return out;
    }

    if (!out.is_edit && same_identity(it->second, incoming)) {
        out.is_duplicate = true;
        stats_.duplicates_ignored++;
        return out;
    }

    it->second = incoming;
    out.accepted = true;
    if (out.is_edit) stats_.edits_applied++;
    return out;
}

void TradeReconciler::reset() {
    seen_.clear();
    stats_ = Stats{};
}

std::string TradeReconciler::make_key(const event_bus::TradeEvent& ev) const {
    if (ev.trade_number > 0) {
        std::ostringstream oss;
        oss << ev.ticker << '|' << ev.bolsa << '|' << ev.trade_date << '|' << ev.trade_number;
        return oss.str();
    }
    return fallback_key(ev);
}

bool TradeReconciler::same_identity(const TradeIdentity& a, const TradeIdentity& b) {
    return a.buy_agent == b.buy_agent &&
           a.sell_agent == b.sell_agent &&
           a.qty == b.qty &&
           a.price == b.price &&
           a.trade_type == b.trade_type &&
           a.trade_date == b.trade_date;
}
