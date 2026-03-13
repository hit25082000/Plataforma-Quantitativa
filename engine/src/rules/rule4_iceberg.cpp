#include "rule4_iceberg.h"
#include <algorithm>
#include <chrono>
#include <cmath>

namespace rules {

namespace {
constexpr int     R4_RENEWAL_WINDOW_MS = 500;
constexpr int64_t R4_MIN_RENEWAL_QTY   = 300;
} // namespace

Rule4Iceberg::Rule4Iceberg(alert_bus::AlertBus& ab) : RuleBase(ab) {}

namespace {
constexpr double PRICE_TOLERANCE = 0.01;
}

void Rule4Iceberg::on_wall_remove(const WallRemoveEvent& ev) {
    int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    recent_removals_.erase(
        std::remove_if(recent_removals_.begin(), recent_removals_.end(),
            [now_ms](const auto& p) {
                return now_ms - p.second.ts_ms > R4_RENEWAL_WINDOW_MS * 3;
            }),
        recent_removals_.end());
    RecentRemoval rr;
    rr.offer_id = ev.offer_id;
    rr.qty = ev.qty;
    rr.agent_id = ev.agent_id;
    rr.ts_ms = now_ms - ev.elapsed_ms;
    rr.had_trade = ev.was_traded;
    recent_removals_.emplace_back(ev.price, rr);
}

void Rule4Iceberg::on_trade(const TradeEvent& ev) {
    for (auto& [price, rr] : recent_removals_) {
        if (std::abs(price - ev.price) < PRICE_TOLERANCE) {
            rr.had_trade = true;
        }
    }
}

RecentRemoval* Rule4Iceberg::find_removal_at_price(double price) {
    for (auto& [p, rr] : recent_removals_) {
        if (std::abs(p - price) < PRICE_TOLERANCE) return &rr;
    }
    return nullptr;
}

void Rule4Iceberg::on_wall_add(const WallAddEvent& ev) {
    RecentRemoval* rr = find_removal_at_price(ev.price);
    if (!rr) return;

    int64_t elapsed = ev.timestamp_ms - rr->ts_ms;

    if (elapsed > R4_RENEWAL_WINDOW_MS * 3) {
        recent_removals_.erase(
            std::remove_if(recent_removals_.begin(), recent_removals_.end(),
                [price = ev.price](const auto& p) {
                    return std::abs(p.first - price) < PRICE_TOLERANCE;
                }),
            recent_removals_.end());
        return;
    }

    if (elapsed >= R4_RENEWAL_WINDOW_MS) {
        recent_removals_.erase(
            std::remove_if(recent_removals_.begin(), recent_removals_.end(),
                [price = ev.price](const auto& p) {
                    return std::abs(p.first - price) < PRICE_TOLERANCE;
                }),
            recent_removals_.end());
        return;
    }

    if (ev.qty < R4_MIN_RENEWAL_QTY) {
        recent_removals_.erase(
            std::remove_if(recent_removals_.begin(), recent_removals_.end(),
                [price = ev.price](const auto& p) {
                    return std::abs(p.first - price) < PRICE_TOLERANCE;
                }),
            recent_removals_.end());
        return;
    }

    Alert a;
    a.rule = Rule::R4;
    a.direction = Direction::Neutral;
    a.price = ev.price;
    a.ticker = ev.ticker;
    a.timestamp_ms = ev.timestamp_ms;
    a.data["offer_id"] = ev.offer_id;
    a.data["qty"] = ev.qty;
    a.data["agent_id"] = ev.agent_id;

    if (rr->had_trade && rr->agent_id == ev.agent_id) {
        a.conviction = Conviction::High;
        a.label = "Iceberg Confirmado";
    } else if (rr->agent_id == ev.agent_id) {
        a.conviction = Conviction::Medium;
        a.label = "Renovação Passiva";
    }

    recent_removals_.erase(
        std::remove_if(recent_removals_.begin(), recent_removals_.end(),
            [price = ev.price](const auto& p) {
                return std::abs(p.first - price) < PRICE_TOLERANCE;
            }),
        recent_removals_.end());

    if (!a.label.empty()) {
        alert_bus_.push(std::move(a));
    }
}

} // namespace rules
