#pragma once

#include <atomic>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

namespace asset_controller {

struct SwitchRequest {
    std::string ticker;
    std::string bolsa;
};

class AssetController {
public:
    AssetController();
    ~AssetController();

    void start(uint16_t port);
    void stop();

    /// `VP_PERIOD\t<day|week|manual>` — resposta imediata; string vazia = OK, senão texto do erro.
    void set_vp_period_handler(std::function<std::string(const std::string& period)> h);

    /** Returns true if there is a pending switch request. Caller must call complete_switch() after processing. */
    bool poll_switch(SwitchRequest& out);

    /** Signal that switch is done. Pass "OK" or "ERR: message". */
    void complete_switch(const std::string& result);

private:
    void listener_loop(uint16_t port);

    std::thread thread_;
    std::atomic<bool> running_{false};

    std::mutex mtx_;
    std::condition_variable cv_;
    std::optional<SwitchRequest> pending_;
    std::string result_;
    bool completed_ = false;

    std::function<std::string(const std::string&)> vp_period_handler_;
};

} // namespace asset_controller
