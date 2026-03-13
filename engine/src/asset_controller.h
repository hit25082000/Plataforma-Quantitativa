#pragma once

#include <atomic>
#include <condition_variable>
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
};

} // namespace asset_controller
