#pragma once

#include "event_bus.h"
#include <chrono>
#include <string>
#include <unordered_map>
#include <vector>

namespace dom_snapshot {

struct OfferEntry {
    int64_t offer_id;
    int64_t quantity;
    int32_t agent_id;
    int64_t timestamp_ms;
};

struct PriceLevel {
    double price;
    std::vector<OfferEntry> offers;

    int64_t total_quantity() const {
        int64_t sum = 0;
        for (const auto& o : offers) sum += o.quantity;
        return sum;
    }
};

struct WallEvent {
    std::string ticker;
    double      price;
    int64_t     qty;
    int32_t     side;
    int64_t     offer_id;
    int32_t     agent_id;
    int64_t     timestamp_ms;
};

struct WallRemoveEvent {
    std::string ticker;
    int64_t     offer_id;
    double      price;
    int64_t     qty;
    int32_t     agent_id;
    int64_t     elapsed_ms;
    bool        was_traded;
};

struct DOMSnapshotEvent {
    std::string ticker;
    std::vector<std::tuple<double, int64_t, size_t>> buy;   // price, total_qty, count
    std::vector<std::tuple<double, int64_t, size_t>> sell;
};

class DOMSnapshotEngine {
public:
    DOMSnapshotEngine(int64_t wall_threshold, int64_t spoofing_timer_ms);

    void process(const event_bus::OfferBookEvent& ev);
    void set_ticker(const std::string& t) { ticker_ = t; }

    // Callbacks para publicar (retornam true se há mensagem)
    bool get_wall_add(WallEvent& out);
    bool get_wall_remove(WallRemoveEvent& out);
    bool get_dom_snapshot(DOMSnapshotEvent& out);

    void clear_pending();
    void reset();

    // Query API para as regras
    // Soma qty das N primeiras linhas do ASK acima de ref_price
    int64_t sum_ask_depth(double ref_price, int n_levels) const;
    // Soma qty das N primeiras linhas do BID abaixo de ref_price
    int64_t sum_bid_depth(double ref_price, int n_levels) const;
    // Verifica se existe muralha >= min_qty perto de um preço
    bool has_wall_near(double price, double tolerance, int64_t min_qty) const;

private:
    using PriceLevels = std::vector<PriceLevel>;
    using OfferMap = std::unordered_map<int64_t, std::pair<int64_t, int64_t>>;  // offer_id -> (timestamp_ms, qty)

    void build_pending_dom();
    void apply_add(int side, int position, int64_t qty, int32_t agent, int64_t offer_id, double price);
    void apply_edit(int side, int position, int64_t qty, int32_t agent, int64_t offer_id_from_ev);
    void apply_delete(int side, int position);
    void apply_delete_from(int side, int position);
    void apply_full_book(const event_bus::OfferBookEvent& ev);

    int position_to_index(int side, int position) const;
    void check_wall_add(int side, const PriceLevel& level, int64_t offer_id, int32_t agent_id);
    void check_wall_remove(int64_t offer_id, double price, int64_t qty, int32_t agent_id, bool was_traded);

    std::string ticker_;
    PriceLevels buy_side_;
    PriceLevels sell_side_;
    int64_t     wall_threshold_;
    int64_t     spoofing_timer_ms_;
    OfferMap    offer_timestamps_;

    WallEvent       pending_wall_add_;
    WallRemoveEvent pending_wall_remove_;
    DOMSnapshotEvent pending_dom_;
    bool has_wall_add_    = false;
    bool has_wall_remove_ = false;
    bool has_dom_         = false;
};

} // namespace dom_snapshot
