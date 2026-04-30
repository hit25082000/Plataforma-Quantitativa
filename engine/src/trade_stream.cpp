#include "trade_stream.h"
#include "hft_tuning.h"
#include "profit_types.h"

namespace trade_stream {

void TradeStreamProcessor::reset() {
    accum_ = DayAccumulators{};
}

void TradeStreamProcessor::process(const event_bus::TradeEvent& ev) {
    if (ev.ticker != ticker_) return;
    if (accum_.by_agent.empty()) {
        accum_.by_agent.reserve(1024);
    }

    double contrib = ev.price * ev.qty;
    accum_.vwap_num   += contrib;
    accum_.vwap_denom += ev.qty;

    int64_t agg_delta = 0;
    if (ev.trade_type == profit::TRADE_TYPE_BUY_AGGRESSION) {
        agg_delta = ev.qty;
        auto [it, inserted] = accum_.by_agent.try_emplace(ev.buy_agent, AgentStats{});
        (void)inserted;
        hft_tuning::prefetch_write(&it->second);
        it->second.buy_aggression_qty += ev.qty;
    } else if (ev.trade_type == profit::TRADE_TYPE_SELL_AGGRESSION) {
        agg_delta = -ev.qty;
        auto [it, inserted] = accum_.by_agent.try_emplace(ev.sell_agent, AgentStats{});
        (void)inserted;
        hft_tuning::prefetch_write(&it->second);
        it->second.sell_aggression_qty += ev.qty;
    }
    accum_.net_aggression += agg_delta;
}

} // namespace trade_stream
