#pragma once

#include "event_bus.h"
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include <mutex>
#include <nlohmann/json.hpp>

namespace tape_intelligence {

/** Critério de ranking para `top_player_avg_lines` (ENG-AVG-03). */
enum class TopAvgRankMode : uint8_t {
    TopTotalVolume = 0,
    TopBuyVolume = 1,
    TopSellVolume = 2,
    TopNetVolume = 3,
};

struct LevelAcc {
    uint64_t bid_vol = 0;
    uint64_t ask_vol = 0;
    uint64_t neutral_vol = 0;
    uint64_t buy_aggression = 0;
    uint64_t sell_aggression = 0;
    uint64_t buy_absorption = 0;
    uint64_t sell_absorption = 0;

    uint64_t total() const {
        return bid_vol + ask_vol + neutral_vol + buy_absorption + sell_absorption;
    }
};

struct LevelSnapshot {
    int32_t player = 0;
    int64_t price = 0;
    uint64_t total_vol = 0;
    uint64_t bid_vol = 0;
    uint64_t ask_vol = 0;
    uint64_t neutral_vol = 0;
    uint64_t buy_absorption = 0;
    uint64_t sell_absorption = 0;
};

struct PlayerSessionStats {
    uint64_t buy_qty = 0;
    uint64_t sell_qty = 0;
    uint64_t total_qty = 0;
    double buy_notional = 0.0;
    double sell_notional = 0.0;
    double total_notional = 0.0;
    int64_t last_trade_ts = 0;
};

class TapeIntelligenceEngine {
public:
    explicit TapeIntelligenceEngine(std::string ticker = {}, int64_t tick_size = 5);

    void set_ticker(std::string ticker);
    void reset();

    void set_region_ticks(int poc_ticks, int val_ticks, int vah_ticks);
    void set_min_absorption_contracts(uint64_t min_contracts);
    void set_min_participation_pct(double pct);
    void set_top_player_avg_config(TopAvgRankMode mode, size_t max_lines, uint64_t min_contracts);

    std::optional<nlohmann::json> on_trade(const event_bus::TradeEvent& ev,
                                          int64_t poc_price,
                                          int64_t vah_price,
                                          int64_t val_price);
    nlohmann::json build_payload(int64_t poc_price,
                                 int64_t vah_price,
                                 int64_t val_price) const;

    nlohmann::json export_player_sessions_json() const;

private:
    using PlayerLevels = std::map<int64_t, LevelAcc>;

    static std::string normalize_name(std::string value);
    int64_t normalize_price(double price) const;
    static std::vector<LevelSnapshot> serialize_ranked_region(const std::map<int32_t, PlayerLevels>& levels_by_player,
                                                             int64_t center_price,
                                                             int64_t tick_size,
                                                             int region_ticks,
                                                             size_t limit);
    static int32_t choose_player_total(const std::vector<LevelSnapshot>& levels);
    static int32_t choose_player_buy_absorption(const std::vector<LevelSnapshot>& levels);
    static int32_t choose_player_sell_absorption(const std::vector<LevelSnapshot>& levels);
    void apply_trade_unlocked(const event_bus::TradeEvent& ev, int64_t level_price);
    nlohmann::json build_top_player_avg_lines_unlocked() const;
    nlohmann::json build_payload_unlocked(int64_t poc_price,
                                          int64_t vah_price,
                                          int64_t val_price) const;

    std::string ticker_;
    int64_t tick_size_ = 5;
    int poc_region_ticks_ = 0;
    int val_region_ticks_ = 0;
    int vah_region_ticks_ = 0;
    uint64_t min_absorption_contracts_ = 1;
    double min_participation_pct_ = 0.0;
    TopAvgRankMode top_avg_rank_mode_ = TopAvgRankMode::TopTotalVolume;
    size_t top_avg_max_lines_ = 6;
    uint64_t top_avg_min_contracts_ = 1;
    std::map<int32_t, PlayerLevels> levels_by_player_;
    std::map<int32_t, PlayerSessionStats> session_by_player_;
    mutable std::mutex mutex_;
};

} // namespace tape_intelligence
