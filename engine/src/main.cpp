#include "alert_bus.h"
#include "asset_controller.h"
#include "config.h"
#include "mock_feed.h"
#include "dom_snapshot.h"
#include "event_bus.h"
#include "event_dispatcher.h"
#include "profit_bridge.h"
#include "profit_types.h"
#include "hft_tuning.h"
#include "rules/rule1_aggression.h"
#include "rules/rule2_wall.h"
#include "rules/rule3_vwap.h"
#include "rules/rule5_convergence.h"
#include "rules/rule6_absorption.h"
#include "agent_ranking.h"
#include "trade_stream.h"
#include "mock_broker_catalog.h"
#include "zmq_publisher.h"
#include <array>
#include <chrono>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <system_error>
#include <thread>
#include <tuple>
#include <utility>
#include <vector>

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

namespace {

std::string get_mock_agent_short_name(int32_t id) {
    const char* s = mock_broker_sigla_for_id(id);
    if (s && *s) return std::string(s);
    return std::to_string(id);
}

double parse_run_seconds(int argc, char* argv[]) {
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i] ? std::string(argv[i]) : std::string();
        const std::string prefix = "--run-seconds=";
        if (arg.rfind(prefix, 0) == 0) {
            try {
                const double value = std::stod(arg.substr(prefix.size()));
                return value > 0.0 ? value : 0.0;
            } catch (...) {
                return 0.0;
            }
        }
        if (arg == "--run-seconds" && (i + 1) < argc) {
            try {
                const double value = std::stod(std::string(argv[i + 1]));
                return value > 0.0 ? value : 0.0;
            } catch (...) {
                return 0.0;
            }
        }
    }
    return 0.0;
}

bool env_truthy(const char* name, bool default_value) {
    const char* raw = std::getenv(name);
    if (!raw || !*raw) return default_value;
    std::string value(raw);
    for (char& c : value) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (value == "1" || value == "true" || value == "yes" || value == "on") return true;
    if (value == "0" || value == "false" || value == "no" || value == "off") return false;
    return default_value;
}

bool is_terminal_login_error(int32_t login_result) {
    return login_result == profit::LOGIN_INVALID ||
           login_result == profit::LOGIN_INVALID_PASS ||
           login_result == profit::LOGIN_BLOCKED_PASS ||
           login_result == profit::LOGIN_EXPIRED_PASS ||
           login_result == profit::LOGIN_UNKNOWN_ERR;
}

bool should_autoreset_profit_runtime() {
    return env_truthy("PROFIT_RUNTIME_AUTORESET", true);
}

bool reset_profit_runtime_artifacts() {
    namespace fs = std::filesystem;
    std::error_code ec;
    const fs::path cwd = fs::current_path(ec);
    if (ec) {
        std::cerr << "[Profit][SelfHeal] failed to resolve cwd: " << ec.message() << std::endl;
        return false;
    }

    const std::array<const char*, 5> dirs = {
        "database", "Logs", "MarketHours2", "PopupManagerV2", "strategy"
    };
    const std::array<const char*, 10> files = {
        "exchangeinfo2.dat",
        "HadesSSLServerAddr3.dat",
        "InfoSSLServerAddr3.dat",
        "newagents.dat",
        "newInfoReg7.dat",
        "ProfitChart.dat",
        "ReplayServerAddr3.dat",
        "ServerAddr6.dat",
        "timezone2.dat",
        "holidays.dat"
    };

    bool removed_any = false;
    auto remove_path = [&](const fs::path& path) {
        std::error_code stat_ec;
        if (!fs::exists(path, stat_ec) || stat_ec) return;
        std::error_code rm_ec;
        if (fs::is_directory(path, rm_ec) && !rm_ec) {
            const auto removed = fs::remove_all(path, rm_ec);
            if (rm_ec) {
                std::cerr << "[Profit][SelfHeal] failed to remove directory " << path.string()
                          << ": " << rm_ec.message() << std::endl;
                return;
            }
            if (removed > 0) {
                removed_any = true;
                std::cerr << "[Profit][SelfHeal] removed directory " << path.string()
                          << " (" << removed << " entries)" << std::endl;
            }
            return;
        }
        if (rm_ec) {
            std::cerr << "[Profit][SelfHeal] failed to stat " << path.string()
                      << ": " << rm_ec.message() << std::endl;
            return;
        }
        if (fs::remove(path, rm_ec)) {
            removed_any = true;
            std::cerr << "[Profit][SelfHeal] removed file " << path.string() << std::endl;
        } else if (rm_ec) {
            std::cerr << "[Profit][SelfHeal] failed to remove file " << path.string()
                      << ": " << rm_ec.message() << std::endl;
        }
    };

    for (const char* dir_name : dirs) remove_path(cwd / dir_name);
    for (const char* file_name : files) remove_path(cwd / file_name);

    return removed_any;
}
} // namespace

int main(int argc, char* argv[]) {
    const double run_seconds = parse_run_seconds(argc, argv);
    const bool bounded_run = run_seconds > 0.0;
    const auto run_deadline = std::chrono::steady_clock::now() + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
        std::chrono::duration<double>(run_seconds));
    if (bounded_run) {
        std::cerr << "[Engine] Bounded run enabled: run_seconds=" << run_seconds << std::endl;
    }

    hft_tuning::apply_process_priority();
    hft_tuning::maybe_pin_current_thread_from_env("HFT_MAIN_CORE", 0, "main");

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
        hft_tuning::dump_qpc_stats();
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
        hft_tuning::dump_qpc_stats();
        return 1;
    }

    // SetXxx callbacks MUST be called after DLLInitializeMarketLogin per the manual:
    // they override the callbacks passed during initialization.
    bridge.register_callbacks();

    std::wstring wticker = to_wide(ticker.c_str());
    std::wstring wbolsa = to_wide(bolsa.c_str());

    // DLL needs time after Market:4 to load instrument definitions internally.
    // Without this delay, SubscribeTicker can crash with Access Violation when
    // instrument record is not ready yet.
    constexpr int STARTUP_MAX_SUBSCRIBE_ATTEMPTS = 20;
    constexpr int STARTUP_SUBSCRIBE_RETRY_DELAY_MS = 1500;
    constexpr int STARTUP_INITIAL_DELAY_MS = 5000;
    constexpr int STARTUP_MARKET_WAIT_MS = 30000;
    constexpr int STARTUP_RELOGIN_DELAY_MS = 1500;

    auto attempt_startup_subscribe = [&](const char* phase_label, bool initial_delay) {
        int32_t ret_t_local = profit::NL_INTERNAL_ERROR;
        int32_t ret_b_local = profit::NL_INTERNAL_ERROR;

        if (!bridge.wait_for_market_connected(std::chrono::milliseconds(STARTUP_MARKET_WAIT_MS))) {
            const int32_t login_state = bridge.last_login_result();
            const int32_t market_state = bridge.last_market_result();
            const int32_t activation_state = bridge.last_activation_result();
            std::cerr << "[Engine] " << phase_label
                      << ": market not connected before subscribe (timeout "
                      << STARTUP_MARKET_WAIT_MS << "ms)"
                      << " login=" << login_state
                      << " market=" << market_state
                      << " activation=" << activation_state << std::endl;
            if (is_terminal_login_error(login_state)) {
                std::cerr << "[Engine] " << phase_label
                          << ": aborting subscribe retries due terminal login status "
                          << login_state << std::endl;
                return std::make_pair(profit::NL_NO_LOGIN, profit::NL_NO_LOGIN);
            }
        }

        if (initial_delay) {
            std::cerr << "[Engine] " << phase_label
                      << ": waiting " << STARTUP_INITIAL_DELAY_MS
                      << "ms for DLL instrument data..." << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(STARTUP_INITIAL_DELAY_MS));
        }

        for (int attempt = 1; attempt <= STARTUP_MAX_SUBSCRIBE_ATTEMPTS; ++attempt) {
            ret_t_local = bridge.SubscribeTicker(wticker.c_str(), wbolsa.c_str());
            ret_b_local = bridge.SubscribeOfferBook(wticker.c_str(), wbolsa.c_str());

            std::cerr << "[Subscribe] phase=" << phase_label
                      << " attempt=" << attempt
                      << "/" << STARTUP_MAX_SUBSCRIBE_ATTEMPTS
                      << " ticker=" << ticker << " bolsa=" << bolsa
                      << " ret_ticker=" << ret_t_local
                      << " ret_book=" << ret_b_local << std::endl;

            if (ret_t_local >= profit::NL_OK && ret_b_local >= profit::NL_OK) {
                std::cerr << "[Subscribe] phase=" << phase_label
                          << " OK on attempt " << attempt << std::endl;
                break;
            }

            if (is_terminal_login_error(bridge.last_login_result())) {
                std::cerr << "[Subscribe] phase=" << phase_label
                          << " aborted due terminal login status "
                          << bridge.last_login_result() << std::endl;
                break;
            }

            if (attempt < STARTUP_MAX_SUBSCRIBE_ATTEMPTS) {
                std::this_thread::sleep_for(std::chrono::milliseconds(STARTUP_SUBSCRIBE_RETRY_DELAY_MS));
            }
        }

        return std::make_pair(ret_t_local, ret_b_local);
    };

    int32_t ret_ticker = profit::NL_INTERNAL_ERROR;
    int32_t ret_book = profit::NL_INTERNAL_ERROR;
    std::tie(ret_ticker, ret_book) = attempt_startup_subscribe("startup", true);

    if (ret_ticker < profit::NL_OK || ret_book < profit::NL_OK) {
        const bool login_unknown = bridge.last_login_result() == profit::LOGIN_UNKNOWN_ERR;
        const bool do_runtime_self_heal = login_unknown && should_autoreset_profit_runtime();
        std::cerr << "[Engine] Startup subscribe still failing; attempting DLL re-login recovery" << std::endl;
        int32_t fin_ret = bridge.DLLFinalize();
        std::cerr << "[Engine] DLLFinalize after startup subscribe failure: " << fin_ret << std::endl;
        if (do_runtime_self_heal) {
            std::cerr << "[Engine] Login returned 200 (unknown). Resetting Profit runtime artifacts before re-login."
                      << std::endl;
            const bool cleaned = reset_profit_runtime_artifacts();
            std::cerr << "[Engine] Profit runtime artifact reset " << (cleaned ? "completed" : "had no changes")
                      << std::endl;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(STARTUP_RELOGIN_DELAY_MS));

        int32_t reinit_ret = bridge.DLLInitializeMarketLogin(
            wkey.c_str(),
            wuser.c_str(),
            wpass.c_str());
        std::cerr << "[Engine] Re-login result after startup subscribe failure: " << reinit_ret << std::endl;

        if (reinit_ret >= profit::NL_OK) {
            bridge.register_callbacks();
            std::tie(ret_ticker, ret_book) = attempt_startup_subscribe("startup-relogin", true);
        }
    }

    bool live_subscription_active = (ret_ticker >= profit::NL_OK && ret_book >= profit::NL_OK);
    if (!live_subscription_active) {
        std::cerr << "[Engine] Startup subscribe failed after recovery; continuing in degraded mode"
                  << " (ticker=" << ret_ticker << ", book=" << ret_book << ")" << std::endl;
    } else {
        bridge.reset_history_state();
        int32_t hist_ret = bridge.request_history_today(wticker.c_str(), wbolsa.c_str());
        if (hist_ret < profit::NL_OK) {
            std::cerr << "[History] GetHistoryTrades failed: " << hist_ret
                      << " (continuing with realtime only)" << std::endl;
        } else {
            bool hist_ok = bridge.wait_for_history_ready(std::chrono::milliseconds(30000));
            if (!hist_ok) {
                std::cerr << "[History] Timeout waiting for historical sync. Continuing in degraded mode."
                          << std::endl;
            } else {
                std::cerr << "[History] Sync complete for " << ticker << std::endl;
            }
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
                                    &alert_bus, &dispatcher, &agent_ranking,
                                    [&bridge, &ticker](int32_t id) {
                                        if (ticker == "TESTE") return get_mock_agent_short_name(id);
                                        return bridge.get_agent_name(id);
                                    },
                                    [&bridge, &ticker](int32_t id) {
                                        if (ticker == "TESTE") return get_mock_agent_short_name(id);
                                        return bridge.get_agent_short_name(id);
                                    });
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
        hft_tuning::dump_qpc_stats();
        return 1;
    }

    asset_controller::AssetController asset_ctrl;
    asset_ctrl.set_vp_period_handler([&pub](const std::string& per) {
        return pub.apply_volume_profile_period_name(per);
    });
    asset_ctrl.start(5556);

    mock_feed::MockFeed mock_feed(queue);

    std::cout << "Engine running. ZMQ at " << config::zmq_address << std::endl;
    std::cout << "Asset control on 127.0.0.1:5556 (SWITCH\\tTICKER\\tBOLSA; VP_PERIOD\\tday|week|manual)" << std::endl;
    if (live_subscription_active) {
        std::cout << "Subscribed to " << ticker << " " << bolsa << std::endl;
    } else {
        std::cout << "Running in degraded mode (not subscribed yet): " << ticker << " " << bolsa << std::endl;
    }
    std::cout << "Press Ctrl+C to exit." << std::endl;

    bool using_mock = false;
    constexpr int RUNTIME_RECOVERY_INTERVAL_MS = 5000;
    auto next_runtime_recovery = std::chrono::steady_clock::now();

    for (;;) {
        if (bounded_run && std::chrono::steady_clock::now() >= run_deadline) {
            std::cerr << "[Engine] run-seconds reached, starting graceful shutdown." << std::endl;
            break;
        }

        if (!using_mock && ticker != "TESTE" && !live_subscription_active &&
            std::chrono::steady_clock::now() >= next_runtime_recovery) {
            next_runtime_recovery = std::chrono::steady_clock::now() +
                std::chrono::milliseconds(RUNTIME_RECOVERY_INTERVAL_MS);

            wticker = to_wide(ticker.c_str());
            wbolsa = to_wide(bolsa.c_str());
            if (!bridge.wait_for_market_connected(std::chrono::milliseconds(1000))) {
                std::cerr << "[Engine] runtime-recovery: market not connected yet for "
                          << ticker << "/" << bolsa << std::endl;
            } else {
                int32_t rr_t = bridge.SubscribeTicker(wticker.c_str(), wbolsa.c_str());
                int32_t rr_b = bridge.SubscribeOfferBook(wticker.c_str(), wbolsa.c_str());
                std::cerr << "[Engine] runtime-recovery subscribe: ticker=" << rr_t
                          << " book=" << rr_b << " for " << ticker << "/" << bolsa << std::endl;
                if (rr_t >= profit::NL_OK && rr_b >= profit::NL_OK) {
                    live_subscription_active = true;
                    bridge.reset_history_state();
                    int32_t ret_h = bridge.request_history_today(wticker.c_str(), wbolsa.c_str());
                    if (ret_h < profit::NL_OK) {
                        std::cerr << "[Engine] runtime-recovery history request failed: " << ret_h << std::endl;
                    } else if (!bridge.wait_for_history_ready(std::chrono::milliseconds(30000))) {
                        std::cerr << "[Engine] runtime-recovery history sync timeout" << std::endl;
                    }
                    std::cerr << "[Engine] runtime-recovery: subscribed to "
                              << ticker << " " << bolsa << std::endl;
                }
            }
        }

        asset_controller::SwitchRequest req;
        if (asset_ctrl.poll_switch(req)) {
            std::string new_ticker = std::move(req.ticker);
            std::string new_bolsa = std::move(req.bolsa);
            for (char& c : new_ticker) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
            for (char& c : new_bolsa) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
            if (new_ticker == "TESTE") {
                new_bolsa = "SIM";
            } else if (new_bolsa == "SIM" || new_bolsa == "S") {
                new_bolsa = "F";
            }
            std::cerr << "[Engine] Switch request: " << ticker << "/" << bolsa
                      << " -> " << new_ticker << "/" << new_bolsa << std::endl;

            if (ticker == new_ticker && bolsa == new_bolsa) {
                asset_ctrl.complete_switch("OK");
                continue;
            }

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

                pub.with_processing_paused([&]() {
                    dom.reset();
                    trade_proc.reset();
                    agent_ranking.reset();
                    bridge.reset_history_state();
                    dom.clear_pending();

                    ticker = new_ticker;
                    bolsa = new_bolsa;
                    dom.set_ticker(ticker);
                    trade_proc.set_ticker(ticker);
                    dispatcher.set_ticker(ticker);
                    pub.set_ticker(ticker);
                });
                wticker = to_wide(ticker.c_str());
                wbolsa = to_wide(bolsa.c_str());

                if (ticker == "TESTE") {
                    using_mock = true;
                    live_subscription_active = true;
                    mock_feed.start();
                } else {
                    mock_feed.stop();
                    constexpr int MAX_SWITCH_SUBSCRIBE_ATTEMPTS = 20;
                    constexpr int SWITCH_SUBSCRIBE_RETRY_DELAY_MS = 1500;
                    constexpr int SWITCH_INITIAL_DELAY_MS = 5000;
                    constexpr int SWITCH_MARKET_WAIT_MS = 30000;
                    constexpr int SWITCH_RELOGIN_DELAY_MS = 1500;

                    auto attempt_subscribe = [&](const char* phase_label, int max_attempts, bool initial_delay) {
                        int32_t ret_t_local = profit::NL_INTERNAL_ERROR;
                        int32_t ret_b_local = profit::NL_INTERNAL_ERROR;

                        if (!bridge.wait_for_market_connected(std::chrono::milliseconds(SWITCH_MARKET_WAIT_MS))) {
                            const int32_t login_state = bridge.last_login_result();
                            const int32_t market_state = bridge.last_market_result();
                            const int32_t activation_state = bridge.last_activation_result();
                            std::cerr << "[Engine] " << phase_label
                                      << ": market not connected before subscribe (timeout "
                                      << SWITCH_MARKET_WAIT_MS << "ms)"
                                      << " login=" << login_state
                                      << " market=" << market_state
                                      << " activation=" << activation_state << std::endl;
                            if (is_terminal_login_error(login_state)) {
                                return std::make_pair(profit::NL_NO_LOGIN, profit::NL_NO_LOGIN);
                            }
                            // Fail-fast: without market connection, subscribe retries will only loop
                            // with NL_INTERNAL_ERROR and delay the SWITCH response.
                            return std::make_pair(profit::NL_NOT_INITIALIZED, profit::NL_NOT_INITIALIZED);
                        }

                        if (initial_delay) {
                            std::this_thread::sleep_for(std::chrono::milliseconds(SWITCH_INITIAL_DELAY_MS));
                        }

                        for (int attempt = 1; attempt <= max_attempts; ++attempt) {
                            ret_t_local = bridge.SubscribeTicker(wticker.c_str(), wbolsa.c_str());
                            ret_b_local = bridge.SubscribeOfferBook(wticker.c_str(), wbolsa.c_str());
                            if (ret_t_local >= profit::NL_OK && ret_b_local >= profit::NL_OK) {
                                break;
                            }
                            if (is_terminal_login_error(bridge.last_login_result())) {
                                std::cerr << "[Engine] " << phase_label
                                          << " aborted due terminal login status "
                                          << bridge.last_login_result() << std::endl;
                                break;
                            }
                            std::cerr << "[Engine] " << phase_label << " subscribe retry " << attempt
                                      << "/" << max_attempts
                                      << " failed: ticker=" << ret_t_local << " book=" << ret_b_local << std::endl;
                            if (attempt < max_attempts) {
                                std::this_thread::sleep_for(std::chrono::milliseconds(SWITCH_SUBSCRIBE_RETRY_DELAY_MS));
                            }
                        }

                        return std::make_pair(ret_t_local, ret_b_local);
                    };

                    auto [ret_t, ret_b] = attempt_subscribe("switch", MAX_SWITCH_SUBSCRIBE_ATTEMPTS, true);
                    const bool market_not_connected =
                        (ret_t == profit::NL_NOT_INITIALIZED && ret_b == profit::NL_NOT_INITIALIZED);

                    if ((ret_t < profit::NL_OK || ret_b < profit::NL_OK) && !market_not_connected) {
                        const bool login_unknown = bridge.last_login_result() == profit::LOGIN_UNKNOWN_ERR;
                        const bool do_runtime_self_heal = login_unknown && should_autoreset_profit_runtime();
                        std::cerr << "[Engine] Switch subscribe still failing; attempting DLL re-login recovery" << std::endl;
                        int32_t fin_ret = bridge.DLLFinalize();
                        std::cerr << "[Engine] DLLFinalize after switch failure: " << fin_ret << std::endl;
                        if (do_runtime_self_heal) {
                            std::cerr << "[Engine] Switch failed with login 200. Resetting Profit runtime artifacts."
                                      << std::endl;
                            const bool cleaned = reset_profit_runtime_artifacts();
                            std::cerr << "[Engine] Profit runtime artifact reset "
                                      << (cleaned ? "completed" : "had no changes") << std::endl;
                        }
                        std::this_thread::sleep_for(std::chrono::milliseconds(SWITCH_RELOGIN_DELAY_MS));

                        int32_t reinit_ret = bridge.DLLInitializeMarketLogin(
                            wkey.c_str(),
                            wuser.c_str(),
                            wpass.c_str());
                        std::cerr << "[Engine] Re-login result after switch failure: " << reinit_ret << std::endl;

                        if (reinit_ret >= profit::NL_OK) {
                            bridge.register_callbacks();
                            std::tie(ret_t, ret_b) = attempt_subscribe("switch-relogin", MAX_SWITCH_SUBSCRIBE_ATTEMPTS, true);
                        }
                    }

                    if (ret_t < profit::NL_OK || ret_b < profit::NL_OK) {
                        live_subscription_active = false;
                        next_runtime_recovery = std::chrono::steady_clock::now() +
                            std::chrono::milliseconds(1500);
                        if (market_not_connected) {
                            std::cerr << "[Engine] Switch aborted: market still disconnected." << std::endl;
                        }
                        std::cerr << "[Engine] Subscribe failed: ticker=" << ret_t << " book=" << ret_b << std::endl;
                        std::ostringstream err;
                        err << "ERR: subscribe failed (ticker=" << ret_t << ", book=" << ret_b << ")";
                        asset_ctrl.complete_switch(err.str());
                    } else {
                        live_subscription_active = true;
                        int32_t ret_h = bridge.request_history_today(wticker.c_str(), wbolsa.c_str());
                        if (ret_h < profit::NL_OK) {
                            std::cerr << "[Engine] History request failed: " << ret_h << std::endl;
                        } else if (!bridge.wait_for_history_ready(std::chrono::milliseconds(30000))) {
                            std::cerr << "[Engine] History sync timeout after switch" << std::endl;
                        }
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
    hft_tuning::dump_qpc_stats();

    return 0;
}
