#include "dom_snapshot.h"
#include "profit_types.h"
#include <algorithm>
#include <chrono>
#include <tuple>

namespace dom_snapshot {

namespace {
int64_t now_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
} // namespace

DOMSnapshotEngine::DOMSnapshotEngine(int64_t wall_threshold, int64_t spoofing_timer_ms)
    : wall_threshold_(wall_threshold)
    , spoofing_timer_ms_(spoofing_timer_ms)
{}

void DOMSnapshotEngine::build_pending_dom() {
    pending_dom_.ticker = ticker_;
    pending_dom_.buy.clear();
    pending_dom_.sell.clear();
    for (const auto& pl : buy_side_) {
        int64_t tq = pl.total_quantity();
        if (tq > 0) pending_dom_.buy.emplace_back(pl.price, tq, pl.offers.size());
    }
    for (const auto& pl : sell_side_) {
        int64_t tq = pl.total_quantity();
        if (tq > 0) pending_dom_.sell.emplace_back(pl.price, tq, pl.offers.size());
    }
    std::sort(pending_dom_.buy.begin(), pending_dom_.buy.end(), [](const auto& a, const auto& b) { return std::get<0>(a) > std::get<0>(b); });
    std::sort(pending_dom_.sell.begin(), pending_dom_.sell.end(), [](const auto& a, const auto& b) { return std::get<0>(a) < std::get<0>(b); });
    has_dom_ = true;
}

void DOMSnapshotEngine::process(const event_bus::OfferBookEvent& ev) {
    if (ev.ticker != ticker_) return;

    switch (ev.nAction) {
        case profit::atAdd:
            apply_add(ev.side, ev.nPosition, ev.nQtd, ev.nAgent, ev.nOfferID, ev.sPrice);
            build_pending_dom();
            break;
        case profit::atEdit:
            apply_edit(ev.side, ev.nPosition, ev.nQtd, ev.nAgent, ev.nOfferID);
            build_pending_dom();
            break;
        case profit::atDelete:
            apply_delete(ev.side, ev.nPosition);
            build_pending_dom();
            break;
        case profit::atDeleteFrom:
            apply_delete_from(ev.side, ev.nPosition);
            build_pending_dom();
            break;
        case profit::atFullBook:
            apply_full_book(ev);
            return;
        default:
            break;
    }
}

void DOMSnapshotEngine::apply_add(int side, int position, int64_t qty, int32_t agent, int64_t offer_id, double price) {
    auto& levels = (side == profit::SideBuy) ? buy_side_ : sell_side_;
    // Add: insert at (size - nPosition) per Python logic
    int idx = static_cast<int>(levels.size()) - position;

    OfferEntry e{offer_id, qty, agent, now_ms()};
    offer_timestamps_[offer_id] = {e.timestamp_ms, qty};

    if (idx >= 0 && idx <= static_cast<int>(levels.size())) {
        PriceLevel pl;
        pl.price = price;
        pl.offers.push_back(e);
        levels.insert(levels.begin() + idx, pl);
        check_wall_add(side, pl, offer_id, agent);
    }
}

void DOMSnapshotEngine::apply_edit(int side, int position, int64_t qty, int32_t agent, int64_t offer_id_from_ev) {
    (void)offer_id_from_ev;
    auto& levels = (side == profit::SideBuy) ? buy_side_ : sell_side_;
    int idx = position_to_index(side, position);
    if (idx < 0 || idx >= static_cast<int>(levels.size())) return;

    auto& pl = levels[idx];
    for (auto it = pl.offers.begin(); it != pl.offers.end(); ++it) {
        if (it->agent_id == agent) {
            int64_t orig_qty = it->quantity;
            it->quantity += qty;
            if (it->quantity <= 0) {
                check_wall_remove(it->offer_id, pl.price, orig_qty, it->agent_id, true);
                offer_timestamps_.erase(it->offer_id);
                pl.offers.erase(it);
            } else {
                it->timestamp_ms = now_ms();
                offer_timestamps_[it->offer_id] = {it->timestamp_ms, it->quantity};
            }
            break;
        }
    }
}

void DOMSnapshotEngine::apply_delete(int side, int position) {
    auto& levels = (side == profit::SideBuy) ? buy_side_ : sell_side_;
    int idx = position_to_index(side, position);
    if (idx < 0 || idx >= static_cast<int>(levels.size())) return;

    auto& pl = levels[idx];
    for (const auto& o : pl.offers) {
        check_wall_remove(o.offer_id, pl.price, o.quantity, o.agent_id, false);
        offer_timestamps_.erase(o.offer_id);
    }
    levels.erase(levels.begin() + idx);
}

void DOMSnapshotEngine::apply_delete_from(int side, int position) {
    auto& levels = (side == profit::SideBuy) ? buy_side_ : sell_side_;
    int idx = position_to_index(side, position);
    if (idx < 0) return;

    while (idx < static_cast<int>(levels.size())) {
        auto& pl = levels[idx];
        for (const auto& o : pl.offers) {
            check_wall_remove(o.offer_id, pl.price, o.quantity, o.agent_id, false);
            offer_timestamps_.erase(o.offer_id);
        }
        levels.erase(levels.begin() + idx);
    }
}

void DOMSnapshotEngine::apply_full_book(const event_bus::OfferBookEvent&) {
    build_pending_dom();
}

int DOMSnapshotEngine::position_to_index(int side, int position) const {
    const auto& levels = (side == profit::SideBuy) ? buy_side_ : sell_side_;
    int n = static_cast<int>(levels.size());
    return n - 1 - position;  // nPosition é offset a partir do final
}

void DOMSnapshotEngine::check_wall_add(int side, const PriceLevel& level, int64_t offer_id, int32_t agent_id) {
    if (level.total_quantity() >= wall_threshold_) {
        int64_t ts = level.offers.empty() ? now_ms() : level.offers.front().timestamp_ms;
        pending_wall_add_ = {ticker_, level.price, level.total_quantity(), side, offer_id, agent_id, ts};
        has_wall_add_ = true;
    }
}

void DOMSnapshotEngine::check_wall_remove(int64_t offer_id, double price, int64_t qty, int32_t agent_id, bool was_traded) {
    auto it = offer_timestamps_.find(offer_id);
    if (it != offer_timestamps_.end()) {
        int64_t elapsed = now_ms() - it->second.first;
        if (elapsed < spoofing_timer_ms_) {
            pending_wall_remove_ = {ticker_, offer_id, price, qty, agent_id, elapsed, was_traded};
            has_wall_remove_ = true;
        }
        offer_timestamps_.erase(it);
    }
}

bool DOMSnapshotEngine::get_wall_add(WallEvent& out) {
    if (!has_wall_add_) return false;
    out = pending_wall_add_;
    has_wall_add_ = false;
    return true;
}

bool DOMSnapshotEngine::get_wall_remove(WallRemoveEvent& out) {
    if (!has_wall_remove_) return false;
    out = pending_wall_remove_;
    has_wall_remove_ = false;
    return true;
}

bool DOMSnapshotEngine::get_dom_snapshot(DOMSnapshotEvent& out) {
    if (!has_dom_) return false;
    out = pending_dom_;
    has_dom_ = false;
    return true;
}

void DOMSnapshotEngine::clear_pending() {
    has_wall_add_ = false;
    has_wall_remove_ = false;
    has_dom_ = false;
}

void DOMSnapshotEngine::reset() {
    buy_side_.clear();
    sell_side_.clear();
    offer_timestamps_.clear();
    clear_pending();
}

int64_t DOMSnapshotEngine::sum_ask_depth(double ref_price, int n_levels) const {
    int64_t total = 0;
    int count = 0;
    // sell_side_ é ordenado por preço crescente (menor ask no início)
    for (const auto& pl : sell_side_) {
        if (pl.price > ref_price) {
            total += pl.total_quantity();
            if (++count >= n_levels) break;
        }
    }
    return total;
}

int64_t DOMSnapshotEngine::sum_bid_depth(double ref_price, int n_levels) const {
    int64_t total = 0;
    int count = 0;
    // buy_side_ é ordenado por preço decrescente (maior bid no início)
    for (const auto& pl : buy_side_) {
        if (pl.price < ref_price) {
            total += pl.total_quantity();
            if (++count >= n_levels) break;
        }
    }
    return total;
}

bool DOMSnapshotEngine::has_wall_near(double price, double tolerance, int64_t min_qty) const {
    auto check = [&](const PriceLevels& levels) {
        for (const auto& pl : levels) {
            if (std::abs(pl.price - price) <= tolerance && pl.total_quantity() >= min_qty) {
                return true;
            }
        }
        return false;
    };
    return check(buy_side_) || check(sell_side_);
}

} // namespace dom_snapshot
