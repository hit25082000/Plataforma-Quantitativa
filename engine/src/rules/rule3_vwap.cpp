#include "rule3_vwap.h"
#include <chrono>
#include <cmath>

namespace rules {

namespace {
constexpr double   R3_VWAP_DEVIATION_PCT     = 0.001;
constexpr int64_t  R3_AGENT_VOLUME_THRESHOLD = 500;
} // namespace

Rule3Vwap::Rule3Vwap(alert_bus::AlertBus& ab) : RuleBase(ab) {}

void Rule3Vwap::on_trade(const TradeEvent& ev) {
    double day_vwap = (day_vwap_denom_ > 0) ? day_vwap_num_ / day_vwap_denom_ : 0;
    day_vwap_num_   += ev.price * ev.qty;
    day_vwap_denom_ += ev.qty;
    day_vwap = (day_vwap_denom_ > 0) ? day_vwap_num_ / day_vwap_denom_ : 0;

    int32_t agent_id = -1;
    if (ev.trade_type == 2) agent_id = ev.buy_agent;
    else if (ev.trade_type == 3) agent_id = ev.sell_agent;
    if (agent_id < 0) return;

    auto& av = agent_vwaps_[agent_id];
    av.vwap_num   += ev.price * ev.qty;
    av.vwap_denom += ev.qty;
    av.total_qty += ev.qty;

    if (av.total_qty < R3_AGENT_VOLUME_THRESHOLD) return;
    if (day_vwap < 1e-10) return;

    double agent_vwap = (av.vwap_denom > 0) ? av.vwap_num / av.vwap_denom : 0;
    double deviation = std::abs(agent_vwap - day_vwap) / day_vwap;

    if (deviation >= R3_VWAP_DEVIATION_PCT) {
        Alert a;
        a.rule = Rule::R3;
        a.price = ev.price;
        a.ticker = ev.ticker;
        a.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();

        if (agent_vwap < day_vwap) {
            a.direction = Direction::Buy;
            a.label = "Acúmulo Institucional Abaixo da VWAP";
        } else {
            a.direction = Direction::Sell;
            a.label = "Distribuição Institucional Acima da VWAP";
        }
        a.conviction = Conviction::Medium;
        a.data["agent_id"] = agent_id;
        a.data["agent_vwap"] = agent_vwap;
        a.data["day_vwap"] = day_vwap;
        a.data["agent_qty"] = av.total_qty;
        a.data["deviation_pct"] = deviation * 100.0;
        alert_bus_.push(std::move(a));
    }
}

} // namespace rules
