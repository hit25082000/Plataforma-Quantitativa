#pragma once

#include "event_bus.h"
#include <cstdint>
#include <ctime>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include <nlohmann/json.hpp>

namespace volume_profile {

enum class Period {
    Day,
    Week,
    Manual,
};

struct LevelAcc {
    uint64_t bid_vol = 0;
    uint64_t ask_vol = 0;

    uint64_t total() const { return bid_vol + ask_vol; }
};

struct LevelSnapshot {
    int64_t  price = 0;
    uint64_t total_vol = 0;
    uint64_t bid_vol = 0;
    uint64_t ask_vol = 0;
    double   pct_of_max = 0.0;
};

class VolumeProfileEngine {
public:
    explicit VolumeProfileEngine(std::string ticker = {}, int64_t tick_size = 5);

    void set_ticker(std::string ticker);
    void set_period(Period period);
    Period period() const { return period_; }
    void reset();

    std::optional<nlohmann::json> on_trade(const event_bus::TradeEvent& ev);
    nlohmann::json build_payload() const;

private:
    void maybe_reset_for_trade_date(const std::string& trade_date);
    std::string period_name() const;
    std::string period_key_for_trade_date(const std::string& trade_date) const;
    static std::string normalize_trade_date(const std::string& trade_date);
    static bool parse_trade_date(const std::string& trade_date, std::tm& out_tm);
    static std::string format_tm_date(const std::tm& tm_value);
    int64_t normalize_price(double price) const;
    std::pair<int64_t, int64_t> compute_value_area() const;
    std::vector<LevelSnapshot> build_levels(uint64_t max_total) const;

    std::string ticker_;
    Period period_ = Period::Day;
    int64_t tick_size_ = 5;
    std::map<int64_t, LevelAcc> levels_;
    std::string last_period_key_;
};

} // namespace volume_profile
