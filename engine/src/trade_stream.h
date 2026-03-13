#pragma once

#include "event_bus.h"
#include <string>
#include <unordered_map>

namespace trade_stream {

struct AgentStats {
    int64_t buy_aggression_qty  = 0;
    int64_t sell_aggression_qty = 0;
};

struct DayAccumulators {
    double vwap_num    = 0;
    double vwap_denom  = 0;
    int64_t net_aggression = 0;
    std::unordered_map<int32_t, AgentStats> by_agent;

    double vwap() const {
        return vwap_denom > 0 ? vwap_num / vwap_denom : 0.0;
    }
};

class TradeStreamProcessor {
public:
    void process(const event_bus::TradeEvent& ev);
    void set_ticker(const std::string& t) { ticker_ = t; }
    void reset();

    DayAccumulators get_accumulators() const { return accum_; }

private:
    std::string ticker_;
    DayAccumulators accum_;
};

} // namespace trade_stream
