#include "tape_intelligence.h"
#include "profit_types.h"

#include <cassert>
#include <cmath>
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
    int32_t buy_agent,
    int32_t sell_agent)
{
    event_bus::TradeEvent ev;
    ev.ticker = ticker;
    ev.price = price;
    ev.qty = qty;
    ev.trade_type = trade_type;
    ev.buy_agent = buy_agent;
    ev.sell_agent = sell_agent;
    ev.trade_date = "2026-04-25";
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

void test_tape_intelligence_emits_rankings() {
    tape_intelligence::TapeIntelligenceEngine engine("WINFUT", 5);

    auto payload1 = engine.on_trade(
        make_trade("WINFUT", 100.0, 20, profit::TRADE_TYPE_BUY_AGGRESSION, 101, 201),
        100, 105, 95);
    assert(payload1.has_value());
    assert(payload1->at("type").get<std::string>() == "tape_intelligence");
    assert(payload1->at("poc_player").get<int32_t>() == 101);
    assert(payload1->contains("val_buyer"));

    auto payload2 = engine.on_trade(
        make_trade("WINFUT", 105.0, 15, profit::TRADE_TYPE_SELL_AGGRESSION, 102, 202),
        100, 105, 95);
    assert(payload2.has_value());
    auto payload2b = engine.on_trade(
        make_trade("WINFUT", 105.0, 20, profit::TRADE_TYPE_BUY_AGGRESSION, 103, 202),
        100, 105, 95);
    assert(payload2b.has_value());
    assert(payload2b->at("vah_seller").get<int32_t>() == 202);
    assert(payload2->at("poc_top3").is_array());
    assert(payload2->at("vah_top3").is_array());
    assert(payload2->at("val_top3").is_array());
}

void test_tape_intelligence_fixture_top3_val_buyer_vah_seller() {
    std::ifstream in(fixture_path("tt_fixture_trades.json"));
    assert(in.good());
    nlohmann::json fixture = nlohmann::json::parse(in);

    const auto anchors = fixture.at("anchor_prices");
    const int64_t poc_price = static_cast<int64_t>(anchors.at("poc_price").get<double>());
    const int64_t vah_price = static_cast<int64_t>(anchors.at("vah_price").get<double>());
    const int64_t val_price = static_cast<int64_t>(anchors.at("val_price").get<double>());
    const auto step = fixture.at("price_step").get<int64_t>();
    tape_intelligence::TapeIntelligenceEngine engine("WINFUT", step);

    std::optional<nlohmann::json> last_payload;
    for (const auto& trade : fixture.at("trades")) {
        auto ev = make_trade(
            trade.at("ticker").get<std::string>(),
            trade.at("price").get<double>(),
            trade.at("qty").get<int64_t>(),
            parse_trade_type(trade.at("trade_type").get<std::string>()),
            trade.at("buy_agent").get<int32_t>(),
            trade.at("sell_agent").get<int32_t>());
        last_payload = engine.on_trade(ev, poc_price, vah_price, val_price);
    }
    assert(last_payload.has_value());

    const auto expected = fixture.at("assertions");
    assert(last_payload->at("poc_player").get<int32_t>() == expected.at("poc_player").get<int32_t>());
    assert(last_payload->at("val_buyer").get<int32_t>() == expected.at("val_buyer").get<int32_t>());
    assert(last_payload->at("vah_seller").get<int32_t>() == expected.at("vah_seller").get<int32_t>());
    const auto top3_limit = expected.at("top3_limit").get<size_t>();
    assert(last_payload->at("poc_top3").size() <= top3_limit);
    assert(last_payload->at("vah_top3").size() <= top3_limit);
    assert(last_payload->at("val_top3").size() <= top3_limit);
}

void test_vp_overlay_absorption_fixture() {
    std::ifstream in(fixture_path("vp_overlay_absorption_trades.json"));
    assert(in.good());
    nlohmann::json fixture = nlohmann::json::parse(in);

    const auto anchors = fixture.at("anchor_prices");
    const int64_t poc_price = static_cast<int64_t>(anchors.at("poc_price").get<double>());
    const int64_t vah_price = static_cast<int64_t>(anchors.at("vah_price").get<double>());
    const int64_t val_price = static_cast<int64_t>(anchors.at("val_price").get<double>());
    const auto step = fixture.at("price_step").get<int64_t>();
    tape_intelligence::TapeIntelligenceEngine engine("WINFUT", step);
    if (fixture.contains("region_ticks")) {
        const auto& r = fixture.at("region_ticks");
        engine.set_region_ticks(r.at("poc").get<int>(), r.at("val").get<int>(), r.at("vah").get<int>());
    }

    std::optional<nlohmann::json> last_payload;
    for (const auto& trade : fixture.at("trades")) {
        auto ev = make_trade(
            trade.at("ticker").get<std::string>(),
            trade.at("price").get<double>(),
            trade.at("qty").get<int64_t>(),
            parse_trade_type(trade.at("trade_type").get<std::string>()),
            trade.at("buy_agent").get<int32_t>(),
            trade.at("sell_agent").get<int32_t>());
        last_payload = engine.on_trade(ev, poc_price, vah_price, val_price);
    }
    assert(last_payload.has_value());
    const auto expected = fixture.at("assertions");
    assert(last_payload->at("poc_player").get<int32_t>() == expected.at("poc_player").get<int32_t>());
    assert(last_payload->at("val_buyer").get<int32_t>() == expected.at("val_buyer").get<int32_t>());
    assert(last_payload->at("vah_seller").get<int32_t>() == expected.at("vah_seller").get<int32_t>());
    int32_t val_pid = expected.at("val_buyer").get<int32_t>();
    uint64_t buy_abs = 0;
    for (const auto& row : last_payload->at("val_top3")) {
        if (row.at("player").get<int32_t>() == val_pid) {
            buy_abs = row.at("buy_absorption").get<uint64_t>();
            break;
        }
    }
    assert(buy_abs == static_cast<uint64_t>(expected.at("val_buy_absorption_total").get<int>()));
}

void test_top_player_avg_lines_rank_total() {
    tape_intelligence::TapeIntelligenceEngine engine("WINFUT", 5);
    engine.set_top_player_avg_config(tape_intelligence::TopAvgRankMode::TopTotalVolume, 4, 1);

    auto ev = [&](double px, int64_t qty, uint8_t tt, int32_t buy, int32_t sell) {
        return make_trade("WINFUT", px, qty, tt, buy, sell);
    };

    (void)engine.on_trade(ev(100.0, 100, profit::TRADE_TYPE_BUY_AGGRESSION, 10, 99), 100, 105, 95);
    (void)engine.on_trade(ev(101.0, 500, profit::TRADE_TYPE_BUY_AGGRESSION, 20, 88), 100, 105, 95);
    (void)engine.on_trade(ev(102.0, 300, profit::TRADE_TYPE_SELL_AGGRESSION, 99, 30), 100, 105, 95);

    auto j = engine.build_payload(100, 105, 95);
    assert(j.contains("top_player_avg_lines"));
    const auto& arr = j.at("top_player_avg_lines");
    assert(arr.is_array());
    assert(!arr.empty());
    const int32_t first = arr[0].at("player_id").get<int32_t>();
    assert(first == 20);
    assert(arr[0].at("mode").get<std::string>() == "total");
    assert(arr[0].contains("avg_price"));
}

void test_unclassified_trade_type_counts_total_player_avg_only() {
    tape_intelligence::TapeIntelligenceEngine engine("WINFUT", 5);
    engine.set_top_player_avg_config(tape_intelligence::TopAvgRankMode::TopTotalVolume, 4, 1);

    auto payload = engine.on_trade(
        make_trade("WINFUT", 100.0, 12, profit::TRADE_TYPE_UNCLASSIFIED, 101, 202),
        100, 105, 95);
    assert(payload.has_value());

    const auto sessions = engine.export_player_sessions_json();
    for (const std::string pid : {"101", "202"}) {
        assert(sessions.contains(pid));
        const auto& st = sessions.at(pid);
        assert(st.at("buy_qty").get<uint64_t>() == 0);
        assert(st.at("sell_qty").get<uint64_t>() == 0);
        assert(st.at("total_qty").get<uint64_t>() == 12);
        assert(std::abs(st.at("total_avg_price").get<double>() - 100.0) < 0.01);
    }

    const auto& poc = payload->at("poc_top3");
    assert(!poc.empty());
    assert(poc[0].at("total_vol").get<uint64_t>() == 12);
    assert(poc[0].at("bid_vol").get<uint64_t>() == 0);
    assert(poc[0].at("ask_vol").get<uint64_t>() == 0);
    assert(poc[0].at("neutral_vol").get<uint64_t>() == 12);

    const auto& avg = payload->at("top_player_avg_lines");
    assert(!avg.empty());
    assert(avg[0].at("mode").get<std::string>() == "total");
    assert(avg[0].at("player_id").get<int32_t>() == 101);
}

void test_vp_overlay_player_avg_fixture() {
    std::ifstream in(fixture_path("vp_overlay_player_avg_trades.json"));
    assert(in.good());
    nlohmann::json fixture = nlohmann::json::parse(in);

    const auto anchors = fixture.at("anchor_prices");
    const int64_t poc_price = static_cast<int64_t>(anchors.at("poc_price").get<double>());
    const int64_t vah_price = static_cast<int64_t>(anchors.at("vah_price").get<double>());
    const int64_t val_price = static_cast<int64_t>(anchors.at("val_price").get<double>());
    const auto step = fixture.at("price_step").get<int64_t>();
    tape_intelligence::TapeIntelligenceEngine engine("WINFUT", step);

    for (const auto& trade : fixture.at("trades")) {
        auto ev = make_trade(
            trade.at("ticker").get<std::string>(),
            trade.at("price").get<double>(),
            trade.at("qty").get<int64_t>(),
            parse_trade_type(trade.at("trade_type").get<std::string>()),
            trade.at("buy_agent").get<int32_t>(),
            trade.at("sell_agent").get<int32_t>());
        (void)engine.on_trade(ev, poc_price, vah_price, val_price);
    }
    const auto j = engine.export_player_sessions_json();
    const int32_t pid = fixture.at("assertions").at("player").get<int32_t>();
    const std::string pk = std::to_string(pid);
    assert(j.contains(pk));
    const auto& st = j.at(pk);
    assert(st.at("buy_qty").get<uint64_t>() == fixture.at("assertions").at("buy_qty").get<uint64_t>());
    assert(st.at("sell_qty").get<uint64_t>() == fixture.at("assertions").at("sell_qty").get<uint64_t>());
    assert(st.at("total_qty").get<uint64_t>() == fixture.at("assertions").at("total_qty").get<uint64_t>());
    const double want_avg = fixture.at("assertions").at("total_avg_price").get<double>();
    const double got_avg = st.at("total_avg_price").get<double>();
    assert(std::abs(got_avg - want_avg) < 0.02);
}

} // namespace

int main() {
    test_tape_intelligence_emits_rankings();
    test_tape_intelligence_fixture_top3_val_buyer_vah_seller();
    test_vp_overlay_absorption_fixture();
    test_top_player_avg_lines_rank_total();
    test_unclassified_trade_type_counts_total_player_avg_only();
    test_vp_overlay_player_avg_fixture();
    std::cout << "tape_intelligence_tests passed\n";
    return 0;
}
