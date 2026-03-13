#pragma once

#include "event_bus.h"
#include "profit_types.h"
#include <chrono>
#include <memory>
#include <string>

namespace profit_bridge {

class ProfitBridge {
public:
    explicit ProfitBridge(event_bus::EventQueue& queue);
    ~ProfitBridge();

    bool load(const std::string& dll_path);
    void unload();

    bool is_loaded() const { return dll_handle_ != nullptr; }

    // Inicialização Market Data only
    int32_t DLLInitializeMarketLogin(
        const wchar_t* activation_key,
        const wchar_t* user,
        const wchar_t* password);

    int32_t DLLFinalize();

    // Subscribe
    int32_t SubscribeTicker(const wchar_t* ticker, const wchar_t* bolsa);
    int32_t UnsubscribeTicker(const wchar_t* ticker, const wchar_t* bolsa);
    int32_t SubscribeOfferBook(const wchar_t* ticker, const wchar_t* bolsa);
    int32_t UnsubscribeOfferBook(const wchar_t* ticker, const wchar_t* bolsa);

    // Registrar callbacks (chama SetXxx após init)
    void register_callbacks();

    /** Bloqueia até o Market estar conectado (callback type 2, result 4) ou timeout. */
    bool wait_for_market_connected(std::chrono::milliseconds timeout);

private:
    void* dll_handle_ = nullptr;
    event_bus::EventQueue& queue_;

    // Function pointers
    profit::DLLInitMarketLogin_t    fn_DLLInitializeMarketLogin_   = nullptr;
    profit::DLLFinalize_t           fn_DLLFinalize_               = nullptr;
    profit::SubscribeTicker_t        fn_SubscribeTicker_           = nullptr;
    profit::UnsubscribeTicker_t     fn_UnsubscribeTicker_          = nullptr;
    profit::SubscribeOfferBook_t    fn_SubscribeOfferBook_        = nullptr;
    profit::UnsubscribeOfferBook_t  fn_UnsubscribeOfferBook_       = nullptr;
    profit::SetStateCallback_t      fn_SetStateCallback_          = nullptr;
    profit::SetOfferBookCallbackV2_t fn_SetOfferBookCallbackV2_     = nullptr;
    profit::SetTradeCallbackV2_t    fn_SetTradeCallbackV2_         = nullptr;
    profit::SetTinyBookCallback_t   fn_SetTinyBookCallback_        = nullptr;
    profit::TranslateTrade_t        fn_TranslateTrade_            = nullptr;
    profit::SetDailyCallback_t      fn_SetDailyCallback_          = nullptr;
};

/** Escreve uma linha de log de startup no DEBUG_LOG_PATH (para diagnóstico). */
void write_engine_startup_log(int32_t subscribe_ticker_ret, int32_t subscribe_offer_book_ret);

} // namespace profit_bridge
