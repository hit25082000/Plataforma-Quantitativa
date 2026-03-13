#include "rule2_wall.h"
#include <chrono>
#include <cmath>

namespace rules {

namespace {
constexpr int64_t R2_WALL_THRESHOLD    = 500;
constexpr int64_t R2_SPOOFING_TIMER_MS = 2000;
constexpr double  R2_PRICE_TOLERANCE   = 5.0;
} // namespace

Rule2Wall::Rule2Wall(alert_bus::AlertBus& ab) : RuleBase(ab) {}

void Rule2Wall::on_wall_add(const WallAddEvent& ev) {
    if (ev.qty < R2_WALL_THRESHOLD) return;

    PendingWall pw;
    pw.price = ev.price;
    pw.ts_ms = ev.timestamp_ms;
    pw.traded = false;
    pw.agent_id = ev.agent_id;
    pending_walls_[ev.offer_id] = pw;

    Alert a;
    a.rule = Rule::R2;
    a.direction = Direction::Neutral;
    a.conviction = Conviction::Low;
    a.label = "Muralha Detectada";
    a.price = ev.price;
    a.ticker = ev.ticker;
    a.timestamp_ms = ev.timestamp_ms;
    a.data["offer_id"] = ev.offer_id;
    a.data["qty"] = ev.qty;
    a.data["side"] = ev.side;
    a.data["agent_id"] = ev.agent_id;
    alert_bus_.push(std::move(a));
}

void Rule2Wall::on_wall_remove(const WallRemoveEvent& ev) {
    auto it = pending_walls_.find(ev.offer_id);
    if (it == pending_walls_.end()) return;

    const auto& pw = it->second;
    pending_walls_.erase(it);

    if (ev.elapsed_ms < R2_SPOOFING_TIMER_MS && !ev.was_traded) {
        return;
    }

    Alert a;
    a.rule = Rule::R2;
    a.direction = Direction::Neutral;
    a.price = ev.price;
    a.ticker = ev.ticker;
    a.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();

    if (ev.elapsed_ms < R2_SPOOFING_TIMER_MS && ev.was_traded) {
        a.conviction = Conviction::Medium;
        a.label = "Absorção Confirmada";
    } else {
        a.conviction = Conviction::High;
        a.label = "Muralha Resistiu";
    }
    a.data["offer_id"] = ev.offer_id;
    a.data["elapsed_ms"] = ev.elapsed_ms;
    a.data["was_traded"] = ev.was_traded;
    alert_bus_.push(std::move(a));
}

void Rule2Wall::on_trade(const TradeEvent& ev) {
    for (auto& [offer_id, pw] : pending_walls_) {
        if (std::abs(pw.price - ev.price) <= R2_PRICE_TOLERANCE) {
            pw.traded = true;
        }
    }
}

} // namespace rules
