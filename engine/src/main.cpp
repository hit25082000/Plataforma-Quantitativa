#include "alert_bus.h"
#include "asset_controller.h"
#include "config.h"
#include "mock_feed.h"
#include "dom_snapshot.h"
#include "event_bus.h"
#include "event_dispatcher.h"
#include "profit_bridge.h"
#include "profit_types.h"
#include "rules/rule1_aggression.h"
#include "rules/rule2_wall.h"
#include "rules/rule3_vwap.h"
#include "rules/rule5_convergence.h"
#include "rules/rule6_absorption.h"
#include "agent_ranking.h"
#include "trade_stream.h"
#include "zmq_publisher.h"
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

#ifdef _WIN32
#include <windows.h>
std::wstring to_wide(const char* s) {
    if (!s || !*s) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s, -1, nullptr, 0);
    if (n <= 0) return L"";
    std::wstring w(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s, -1, &w[0], n);
    w.resize(n - 1);
    return w;
}
#else
std::wstring to_wide(const char* s) {
    std::wstring w;
    while (s && *s) w += static_cast<wchar_t>(*s++);
    return w;
}
#endif

int main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;

    std::string ticker = config::ticker_default();
    std::string bolsa  = config::bolsa_default();
    std::string dll_path = config::dll_path;

    event_bus::EventQueue queue;
    dom_snapshot::DOMSnapshotEngine dom(config::wall_threshold, config::spoofing_timer_ms);
    trade_stream::TradeStreamProcessor trade_proc;

    dom.set_ticker(ticker);
    trade_proc.set_ticker(ticker);

    profit_bridge::ProfitBridge bridge(queue);
    if (!bridge.load(dll_path)) {
        std::cerr << "Failed to load " << dll_path << std::endl;
        return 1;
    }

    std::wstring wkey = to_wide(config::activation_key());
    std::wstring wuser = to_wide(config::user());
    std::wstring wpass = to_wide(config::password());

    int32_t ret = bridge.DLLInitializeMarketLogin(
        wkey.c_str(),
        wuser.c_str(),
        wpass.c_str());

    if (ret < profit::NL_OK) {
        std::cerr << "DLLInitializeMarketLogin failed: " << ret << std::endl;
        return 1;
    }

    // SetXxx callbacks MUST be called after DLLInitializeMarketLogin per the manual:
    // they override the callbacks passed during initialization.
    bridge.register_callbacks();

    const auto market_timeout = std::chrono::milliseconds(30000);
    if (!bridge.wait_for_market_connected(market_timeout)) {
        std::cerr << "Market connection timeout. Subscribe may fail." << std::endl;
    }

    std::wstring wticker = to_wide(ticker.c_str());
    std::wstring wbolsa = to_wide(bolsa.c_str());

    // DLL needs time after Market:4 to load instrument definitions internally.
    // Without this delay, SubscribeTicker crashes with Access Violation (null pointer
    // at offset 0x270 = instrument record not yet populated).
    constexpr int MAX_SUBSCRIBE_ATTEMPTS = 10;
    constexpr int SUBSCRIBE_RETRY_DELAY_MS = 3000;

    int32_t ret_ticker = profit::NL_INTERNAL_ERROR;
    int32_t ret_book = profit::NL_INTERNAL_ERROR;

    for (int attempt = 1; attempt <= MAX_SUBSCRIBE_ATTEMPTS; ++attempt) {
        if (attempt == 1) {
            std::cerr << "Waiting 5s for DLL instrument data to load..." << std::endl;
            std::this_thread::sleep_for(std::chrono::seconds(5));
        }

        ret_ticker = bridge.SubscribeTicker(wticker.c_str(), wbolsa.c_str());
        ret_book = bridge.SubscribeOfferBook(wticker.c_str(), wbolsa.c_str());

        std::cerr << "[Subscribe] attempt=" << attempt
                  << " ticker=" << ticker << " bolsa=" << bolsa
                  << " ret_ticker=" << ret_ticker
                  << " ret_book=" << ret_book << std::endl;

        if (ret_ticker >= profit::NL_OK && ret_book >= profit::NL_OK) {
            std::cerr << "[Subscribe] OK on attempt " << attempt << std::endl;
            break;
        }

        if (attempt < MAX_SUBSCRIBE_ATTEMPTS) {
            std::cerr << "[Subscribe] Retrying in " << SUBSCRIBE_RETRY_DELAY_MS << "ms..." << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(SUBSCRIBE_RETRY_DELAY_MS));
        }
    }

    profit_bridge::write_engine_startup_log(ret_ticker, ret_book);

    alert_bus::AlertBus alert_bus;
    AgentRanking agent_ranking;
    event_dispatcher::EventDispatcher dispatcher(alert_bus, dom, trade_proc, ticker);
    dispatcher.add_rule(std::make_unique<rules::Rule1Aggression>(alert_bus, dom, agent_ranking));
    dispatcher.add_rule(std::make_unique<rules::Rule2Wall>(alert_bus));
    dispatcher.add_rule(std::make_unique<rules::Rule3Vwap>(alert_bus));
    dispatcher.add_rule(std::make_unique<rules::Rule5Convergence>(alert_bus, dom));
    dispatcher.add_rule(std::make_unique<rules::Rule6Absorption>(alert_bus, agent_ranking, dom));

    zmq_publisher::ZmqPublisher pub(queue, dom, trade_proc, config::zmq_address, ticker,
                                    &alert_bus, &dispatcher, &agent_ranking);
    pub.start();

    // Wait briefly for ZMQ bind to complete and verify it succeeded
    for (int i = 0; i < 20; ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        if (pub.is_bound()) break;
    }
    if (!pub.is_bound()) {
        std::cerr << "FATAL: ZMQ PUB failed to bind to " << config::zmq_address
                  << ". Another engine process may be using this port. Exiting." << std::endl;
        pub.stop();
        bridge.DLLFinalize();
        return 1;
    }

    asset_controller::AssetController asset_ctrl;
    asset_ctrl.start(5556);

    mock_feed::MockFeed mock_feed(queue);

    std::cout << "Engine running. ZMQ at " << config::zmq_address << std::endl;
    std::cout << "Asset control on 127.0.0.1:5556 (SWITCH\\tTICKER\\tBOLSA)" << std::endl;
    std::cout << "Subscribed to " << ticker << " " << bolsa << std::endl;
    std::cout << "Press Ctrl+C to exit." << std::endl;

    bool using_mock = false;

    for (;;) {
        asset_controller::SwitchRequest req;
        if (asset_ctrl.poll_switch(req)) {
            std::string new_ticker = std::move(req.ticker);
            std::string new_bolsa = std::move(req.bolsa);
            std::cerr << "[Engine] Switch request: " << ticker << "/" << bolsa
                      << " -> " << new_ticker << "/" << new_bolsa << std::endl;

            if (ticker != new_ticker || bolsa != new_bolsa) {
                if (!using_mock) {
                    std::wstring wold = to_wide(ticker.c_str());
                    std::wstring woldb = to_wide(bolsa.c_str());
                    int32_t unsub_t = bridge.UnsubscribeTicker(wold.c_str(), woldb.c_str());
                    int32_t unsub_b = bridge.UnsubscribeOfferBook(wold.c_str(), woldb.c_str());
                    std::cerr << "[Engine] Unsubscribe: ticker=" << unsub_t << " book=" << unsub_b << std::endl;
                }
                if (using_mock) mock_feed.stop();
                using_mock = false;

                dom.reset();
                trade_proc.reset();
                agent_ranking.reset();
                dom.clear_pending();

                ticker = new_ticker;
                bolsa = new_bolsa;
                std::wstring wticker = to_wide(ticker.c_str());
                std::wstring wbolsa = to_wide(bolsa.c_str());

                dom.set_ticker(ticker);
                trade_proc.set_ticker(ticker);
                dispatcher.set_ticker(ticker);
                pub.set_ticker(ticker);

                if (ticker == "TESTE") {
                    using_mock = true;
                    mock_feed.start();
                } else {
                    mock_feed.stop();
                    int32_t ret_t = bridge.SubscribeTicker(wticker.c_str(), wbolsa.c_str());
                    int32_t ret_b = bridge.SubscribeOfferBook(wticker.c_str(), wbolsa.c_str());
                    if (ret_t < profit::NL_OK || ret_b < profit::NL_OK) {
                        std::cerr << "[Engine] Subscribe failed: ticker=" << ret_t << " book=" << ret_b << std::endl;
                        asset_ctrl.complete_switch("ERR: subscribe failed");
                    } else {
                        std::cerr << "[Engine] Subscribed to " << ticker << " " << bolsa << std::endl;
                        asset_ctrl.complete_switch("OK");
                    }
                }
            }
            if (using_mock) {
                asset_ctrl.complete_switch("OK");
            }
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        if (queue.is_stopped()) break;
    }

    asset_ctrl.stop();
    if (using_mock) mock_feed.stop();
    queue.stop();
    pub.stop();
    alert_bus.stop();
    if (!using_mock) {
        std::wstring wfin = to_wide(ticker.c_str());
        std::wstring wfinb = to_wide(bolsa.c_str());
        bridge.UnsubscribeOfferBook(wfin.c_str(), wfinb.c_str());
        bridge.UnsubscribeTicker(wfin.c_str(), wfinb.c_str());
    }
    bridge.DLLFinalize();

    return 0;
}
