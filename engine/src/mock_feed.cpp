#include "mock_feed.h"
#include "profit_types.h"
#include <chrono>
#include <cmath>
#include <iostream>
#include <random>

namespace mock_feed {

namespace {

constexpr const char* TICKER = "TESTE";
constexpr const char* BOLSA = "SIM";
constexpr double BASE_PRICE = 100000.0;
constexpr double TICK_SIZE = 5.0;
constexpr int NUM_LEVELS = 5;
constexpr int64_t QTY_BASE = 100;
constexpr int32_t AGENT_BASE = 1000;
constexpr int64_t OFFER_ID_BASE = 50000;

} // namespace

MockFeed::MockFeed(event_bus::EventQueue& queue) : queue_(queue) {}

MockFeed::~MockFeed() {
    stop();
}

void MockFeed::start() {
    if (running_.exchange(true)) return;
    thread_ = std::thread(&MockFeed::run, this);
    std::cerr << "[MockFeed] Started for " << TICKER << std::endl;
}

void MockFeed::stop() {
    running_.store(false);
    if (thread_.joinable()) thread_.join();
    std::cerr << "[MockFeed] Stopped" << std::endl;
}

void MockFeed::run() {
    std::mt19937 rng(static_cast<unsigned>(
        std::chrono::steady_clock::now().time_since_epoch().count()));
    std::uniform_int_distribution<int> buy_sell_dist(0, 1);
    std::uniform_int_distribution<int64_t> qty_dist(5, 200);
    std::uniform_int_distribution<int> agent_dist(0, 9);
    std::uniform_real_distribution<double> drift_dist(-1.0, 1.0);

    int64_t offer_id = OFFER_ID_BASE;
    double mid_price = BASE_PRICE;
    double daily_open = BASE_PRICE;
    double daily_high = BASE_PRICE;
    double daily_low = BASE_PRICE;
    double daily_volume = 0;
    int tick_count = 0;

    // Build initial book via atAdd (one per level per side)
    auto build_initial_book = [&]() {
        for (int i = 0; i < NUM_LEVELS; ++i) {
            double bid_price = mid_price - TICK_SIZE * (i + 1);
            event_bus::OfferBookEvent ev{};
            ev.ticker = TICKER;
            ev.bolsa = BOLSA;
            ev.nAction = profit::atAdd;
            ev.nPosition = static_cast<int32_t>(i);
            ev.side = profit::SideBuy;
            ev.nQtd = QTY_BASE + qty_dist(rng);
            ev.nAgent = AGENT_BASE + (i % 10);
            ev.nOfferID = offer_id++;
            ev.sPrice = bid_price;
            queue_.push(ev);
        }
        for (int i = 0; i < NUM_LEVELS; ++i) {
            double ask_price = mid_price + TICK_SIZE * (i + 1);
            event_bus::OfferBookEvent ev{};
            ev.ticker = TICKER;
            ev.bolsa = BOLSA;
            ev.nAction = profit::atAdd;
            ev.nPosition = static_cast<int32_t>(i);
            ev.side = profit::SideSell;
            ev.nQtd = QTY_BASE + qty_dist(rng);
            ev.nAgent = AGENT_BASE + 10 + (i % 10);
            ev.nOfferID = offer_id++;
            ev.sPrice = ask_price;
            queue_.push(ev);
        }
        std::cerr << "[MockFeed] Initial book built: " << NUM_LEVELS << " levels per side" << std::endl;
    };

    // Send initial daily so the UI has OHLC from the start
    {
        event_bus::DailyEvent dev{};
        dev.ticker = TICKER;
        dev.high = daily_high;
        dev.low = daily_low;
        dev.open = daily_open;
        dev.close = mid_price;
        dev.volume = 0;
        queue_.push(dev);
    }

    build_initial_book();

    while (running_.load()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
        if (!running_.load()) break;

        mid_price += drift_dist(rng) * TICK_SIZE;

        // Generate a trade
        bool is_buy = buy_sell_dist(rng) != 0;
        double trade_price = is_buy
            ? mid_price + TICK_SIZE
            : mid_price - TICK_SIZE;
        int64_t qty = qty_dist(rng);
        int32_t buy_agent = AGENT_BASE + agent_dist(rng);
        int32_t sell_agent = AGENT_BASE + 10 + agent_dist(rng);

        event_bus::TradeEvent tev{};
        tev.ticker = TICKER;
        tev.bolsa = BOLSA;
        tev.price = trade_price;
        tev.qty = qty;
        tev.buy_agent = buy_agent;
        tev.sell_agent = sell_agent;
        tev.trade_type = is_buy
            ? profit::TRADE_TYPE_BUY_AGGRESSION
            : profit::TRADE_TYPE_SELL_AGGRESSION;
        queue_.push(tev);

        daily_volume += qty;
        daily_high = std::max(daily_high, trade_price);
        daily_low = std::min(daily_low, trade_price);

        // Every 5 ticks, update daily
        if (tick_count % 5 == 0) {
            event_bus::DailyEvent dev{};
            dev.ticker = TICKER;
            dev.high = daily_high;
            dev.low = daily_low;
            dev.open = daily_open;
            dev.close = mid_price;
            dev.volume = daily_volume;
            queue_.push(dev);
        }

        // Every 10 ticks, add a new level to simulate book activity
        // (triggers dom_snapshot rebuild + publish)
        if (tick_count % 10 == 0) {
            int side = buy_sell_dist(rng);
            double price = (side == profit::SideBuy)
                ? mid_price - TICK_SIZE * (NUM_LEVELS + 1 + (tick_count / 10) % 3)
                : mid_price + TICK_SIZE * (NUM_LEVELS + 1 + (tick_count / 10) % 3);
            event_bus::OfferBookEvent ev{};
            ev.ticker = TICKER;
            ev.bolsa = BOLSA;
            ev.nAction = profit::atAdd;
            ev.nPosition = 0;
            ev.side = side;
            ev.nQtd = qty_dist(rng);
            ev.nAgent = AGENT_BASE + agent_dist(rng);
            ev.nOfferID = offer_id++;
            ev.sPrice = price;
            queue_.push(ev);
        }

        tick_count++;
        if (tick_count <= 3) {
            std::cerr << "[MockFeed] Tick " << tick_count
                      << ": mid=" << mid_price
                      << " trade=" << trade_price
                      << " qty=" << qty << std::endl;
        }
    }
}

} // namespace mock_feed
