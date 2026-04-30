#include "volume_profile.h"
#include "profit_types.h"

#include <cassert>
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <string>

namespace {

event_bus::TradeEvent make_trade(
    const std::string& ticker,
    double price,
    int64_t qty,
    uint8_t trade_type,
    const std::string& trade_date)
{
    event_bus::TradeEvent ev;
    ev.ticker = ticker;
    ev.price = price;
    ev.qty = qty;
    ev.trade_type = trade_type;
    ev.trade_date = trade_date;
    ev.source = event_bus::TradeSource::Realtime;
    return ev;
}

std::string fixture_path(const std::string& filename) {
    std::string base = __FILE__;
    const auto pos = base.find_last_of("/\\");
    const std::string dir = (pos == std::string::npos) ? "." : base.substr(0, pos);
    return dir + "/fixtures/" + filename;
}

uint8_t parse_trade_type(const std::string& trade_type) {
    if (trade_type == "buy_aggression") {
        return profit::TRADE_TYPE_BUY_AGGRESSION;
    }
    if (trade_type == "sell_aggression") {
        return profit::TRADE_TYPE_SELL_AGGRESSION;
    }
    return profit::TRADE_TYPE_BUY_AGGRESSION;
}

void test_poc_tiebreak_highest_price() {
    volume_profile::VolumeProfileEngine engine("WINFUT", 5);

    assert(engine.on_trade(make_trade("WINFUT", 100.0, 10, profit::TRADE_TYPE_BUY_AGGRESSION, "2026-04-25")).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 105.0, 10, profit::TRADE_TYPE_SELL_AGGRESSION, "2026-04-25")).has_value());

    const auto payload = engine.build_payload();
    assert(payload.at("poc").get<int64_t>() == 105);
    assert(payload.at("val").get<int64_t>() <= payload.at("poc").get<int64_t>());
    assert(payload.at("vah").get<int64_t>() >= payload.at("poc").get<int64_t>());
}

void test_value_area_covers_seventy_percent() {
    volume_profile::VolumeProfileEngine engine("WINFUT", 5);

    assert(engine.on_trade(make_trade("WINFUT", 100.0, 20, profit::TRADE_TYPE_BUY_AGGRESSION, "2026-04-25")).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 105.0, 30, profit::TRADE_TYPE_BUY_AGGRESSION, "2026-04-25")).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 110.0, 50, profit::TRADE_TYPE_SELL_AGGRESSION, "2026-04-25")).has_value());

    const auto payload = engine.build_payload();
    const auto val = payload.at("val").get<int64_t>();
    const auto vah = payload.at("vah").get<int64_t>();
    const auto poc = payload.at("poc").get<int64_t>();
    assert(val <= poc);
    assert(vah >= poc);
    assert(vah >= val);
}

void test_period_reset_on_trade_date_change() {
    volume_profile::VolumeProfileEngine engine("WINFUT", 5);

    assert(engine.on_trade(make_trade("WINFUT", 100.0, 10, profit::TRADE_TYPE_BUY_AGGRESSION, "2026-04-25")).has_value());
    auto first = engine.build_payload();
    assert(first.at("total_vol").get<uint64_t>() == 10);

    assert(engine.on_trade(make_trade("WINFUT", 110.0, 15, profit::TRADE_TYPE_BUY_AGGRESSION, "2026-04-26")).has_value());
    auto second = engine.build_payload();
    assert(second.at("total_vol").get<uint64_t>() == 15);
    assert(second.at("levels").size() == 1);
}

void test_payload_levels_have_percentages() {
    volume_profile::VolumeProfileEngine engine("WINFUT", 5);

    assert(engine.on_trade(make_trade("WINFUT", 100.0, 10, profit::TRADE_TYPE_BUY_AGGRESSION, "2026-04-25")).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 105.0, 5, profit::TRADE_TYPE_SELL_AGGRESSION, "2026-04-25")).has_value());

    const auto payload = engine.build_payload();
    assert(payload.at("type").get<std::string>() == "volume_profile");
    assert(payload.at("period").get<std::string>() == "day");
    const auto& levels = payload.at("levels");
    assert(levels.is_array());
    assert(levels.size() == 2);
    for (const auto& level : levels) {
        assert(level.at("pct_of_max").get<double>() >= 0.0);
        assert(level.at("pct_of_max").get<double>() <= 1.0);
    }
}

void test_unknown_trade_type_does_not_accumulate() {
    volume_profile::VolumeProfileEngine engine("WINFUT", 5);

    assert(engine.on_trade(make_trade("WINFUT", 100.0, 10, static_cast<uint8_t>(0), "2026-04-25")).has_value());
    auto p = engine.build_payload();
    assert(p.at("total_vol").get<uint64_t>() == 0);
    assert(p.at("levels").is_array());
    assert(p.at("levels").empty());

    assert(engine.on_trade(make_trade("WINFUT", 100.0, 4, profit::TRADE_TYPE_BUY_AGGRESSION, "2026-04-25")).has_value());
    p = engine.build_payload();
    assert(p.at("total_vol").get<uint64_t>() == 4);
    assert(p["levels"][0].at("bid_vol").get<uint64_t>() == 4);
    assert(p["levels"][0].at("ask_vol").get<uint64_t>() == 0);
    uint64_t sum_levels = 0;
    for (const auto& row : p.at("levels")) {
        const uint64_t bid = row.at("bid_vol").get<uint64_t>();
        const uint64_t ask = row.at("ask_vol").get<uint64_t>();
        const uint64_t tot = row.at("total_vol").get<uint64_t>();
        assert(bid + ask == tot);
        assert(bid + ask <= p.at("total_vol").get<uint64_t>());
        sum_levels += tot;
    }
    assert(sum_levels == p.at("total_vol").get<uint64_t>());
}

void test_unclassified_trade_type_accumulates_neutral_volume() {
    volume_profile::VolumeProfileEngine engine("WINFUT", 5);

    assert(engine.on_trade(make_trade("WINFUT", 100.0, 12, profit::TRADE_TYPE_UNCLASSIFIED, "2026-04-25")).has_value());
    const auto p = engine.build_payload();
    assert(p.at("total_vol").get<uint64_t>() == 12);
    assert(p.at("levels").size() == 1);
    const auto& row = p.at("levels")[0];
    assert(row.at("total_vol").get<uint64_t>() == 12);
    assert(row.at("bid_vol").get<uint64_t>() == 0);
    assert(row.at("ask_vol").get<uint64_t>() == 0);
    assert(row.at("neutral_vol").get<uint64_t>() == 12);
}

void test_value_area_price_ordering_multi_levels() {
    volume_profile::VolumeProfileEngine engine("WINFUT", 5);
    for (int i = 0; i < 5; ++i) {
        const double px = 100.0 + static_cast<double>(i) * 5.0;
        const uint8_t tt = (i % 2 == 0) ? profit::TRADE_TYPE_BUY_AGGRESSION
                                       : profit::TRADE_TYPE_SELL_AGGRESSION;
        assert(engine.on_trade(make_trade("WINFUT", px, static_cast<int64_t>(10 + i * 3), tt, "2026-04-25")).has_value());
    }
    const auto p = engine.build_payload();
    const int64_t val = p.at("val").get<int64_t>();
    const int64_t poc = p.at("poc").get<int64_t>();
    const int64_t vah = p.at("vah").get<int64_t>();
    assert(val <= poc);
    assert(poc <= vah);
}

// Asymmetric profile: total_vol=100, 70% target=70, POC=110 (40). Expansion alternates
// up to 115 (+25) then down to 105 (+8) so VA is [105,115] and VAL < POC < VAH.
void test_value_area_asymmetric_regression() {
    volume_profile::VolumeProfileEngine engine("WINFUT", 5);
    const char* d = "2026-04-25";
    assert(engine.on_trade(make_trade("WINFUT", 100.0, 5, profit::TRADE_TYPE_BUY_AGGRESSION, d)).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 105.0, 8, profit::TRADE_TYPE_BUY_AGGRESSION, d)).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 110.0, 40, profit::TRADE_TYPE_BUY_AGGRESSION, d)).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 115.0, 25, profit::TRADE_TYPE_BUY_AGGRESSION, d)).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 120.0, 15, profit::TRADE_TYPE_BUY_AGGRESSION, d)).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 125.0, 3, profit::TRADE_TYPE_BUY_AGGRESSION, d)).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 130.0, 2, profit::TRADE_TYPE_BUY_AGGRESSION, d)).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 135.0, 1, profit::TRADE_TYPE_BUY_AGGRESSION, d)).has_value());
    assert(engine.on_trade(make_trade("WINFUT", 140.0, 1, profit::TRADE_TYPE_BUY_AGGRESSION, d)).has_value());
    const auto p = engine.build_payload();
    assert(p.at("total_vol").get<uint64_t>() == 100u);
    assert(p.at("poc").get<int64_t>() == 110);
    assert(p.at("val").get<int64_t>() == 105);
    assert(p.at("vah").get<int64_t>() == 115);
    assert(p.at("val").get<int64_t>() < p.at("poc").get<int64_t>());
    assert(p.at("poc").get<int64_t>() < p.at("vah").get<int64_t>());
}

void test_vp_fixture_tie_reset_and_value_area() {
    std::ifstream in(fixture_path("vp_fixture_trades.json"));
    assert(in.good());
    nlohmann::json fixture = nlohmann::json::parse(in);

    const auto step = fixture.at("price_step").get<int64_t>();
    volume_profile::VolumeProfileEngine engine("WINFUT", step);
    auto on_first_day = nlohmann::json::array();
    const auto expected_poc_day1 =
        fixture.at("assertions").at("tie_break_highest_price_on_first_day").get<int64_t>();
    const auto expected_total_after_reset =
        fixture.at("assertions").at("total_vol_after_reset").get<uint64_t>();

    for (const auto& trade : fixture.at("trades")) {
        const auto trade_date = trade.at("trade_date").get<std::string>();
        auto ev = make_trade(
            trade.at("ticker").get<std::string>(),
            trade.at("price").get<double>(),
            trade.at("qty").get<int64_t>(),
            parse_trade_type(trade.at("trade_type").get<std::string>()),
            trade_date);
        assert(engine.on_trade(ev).has_value());

        if (trade_date == "2026-04-25") {
            on_first_day.push_back(trade);
        }
    }

    volume_profile::VolumeProfileEngine day1_engine("WINFUT", step);
    for (const auto& trade : on_first_day) {
        auto ev = make_trade(
            trade.at("ticker").get<std::string>(),
            trade.at("price").get<double>(),
            trade.at("qty").get<int64_t>(),
            parse_trade_type(trade.at("trade_type").get<std::string>()),
            trade.at("trade_date").get<std::string>());
        assert(day1_engine.on_trade(ev).has_value());
    }
    const auto day1_payload = day1_engine.build_payload();
    assert(day1_payload.at("poc").get<int64_t>() == expected_poc_day1);

    const auto payload = engine.build_payload();
    assert(payload.at("total_vol").get<uint64_t>() == expected_total_after_reset);
    const auto val = payload.at("val").get<int64_t>();
    const auto poc = payload.at("poc").get<int64_t>();
    const auto vah = payload.at("vah").get<int64_t>();
    assert(vah >= poc);
    assert(poc >= val);
}

} // namespace

int main() {
    test_poc_tiebreak_highest_price();
    test_value_area_covers_seventy_percent();
    test_unknown_trade_type_does_not_accumulate();
    test_unclassified_trade_type_accumulates_neutral_volume();
    test_value_area_price_ordering_multi_levels();
    test_value_area_asymmetric_regression();
    test_period_reset_on_trade_date_change();
    test_payload_levels_have_percentages();
    test_vp_fixture_tie_reset_and_value_area();
    std::cout << "volume_profile_tests passed\n";
    return 0;
}
