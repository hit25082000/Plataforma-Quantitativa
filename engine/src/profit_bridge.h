#pragma once

#include "event_bus.h"
#include "profit_types.h"
#include <chrono>
#include <memory>
#include <mutex>
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
    int32_t GetHistoryTrades(const wchar_t* ticker, const wchar_t* bolsa,
                             const wchar_t* date_start, const wchar_t* date_end);

    // Registrar callbacks (chama SetXxx após init)
    void register_callbacks();

    /** Bloqueia até o Market estar conectado (callback type 2, result 4) ou timeout. */
    bool wait_for_market_connected(std::chrono::milliseconds timeout);
    /** Último status de login (callback type 0). */
    int32_t last_login_result() const;
    /** Último status de market data (callback type 2). */
    int32_t last_market_result() const;
    /** Último status de ativação (callback type 3). */
    int32_t last_activation_result() const;
    /** Dispara download do histórico do dia atual (dd/mm/yyyy..dd/mm/yyyy). */
    int32_t request_history_today(const wchar_t* ticker, const wchar_t* bolsa);
    /** Aguarda fim do histórico atual (TC_LAST_PACKET). */
    bool wait_for_history_ready(std::chrono::milliseconds timeout);
    /** Limpa estado de sincronização de histórico para novo ativo. */
    void reset_history_state();

    /** Nome da corretora por ID (UTF-8). Se DLL não exportar a função ou retornar null, retorna "#" + id. */
    std::string get_agent_name(int32_t agent_id) const;
    /** Nome abreviado da corretora por ID (UTF-8). Se DLL não exportar ou retornar null, retorna "#" + id. */
    std::string get_agent_short_name(int32_t agent_id) const;

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
    profit::SetHistoryTradeCallbackV2_t fn_SetHistoryTradeCallbackV2_ = nullptr;
    profit::SetTinyBookCallback_t   fn_SetTinyBookCallback_        = nullptr;
    profit::TranslateTrade_t        fn_TranslateTrade_            = nullptr;
    profit::GetHistoryTrades_t      fn_GetHistoryTrades_          = nullptr;
    profit::SetDailyCallback_t      fn_SetDailyCallback_          = nullptr;
    profit::GetAgentNameByID_t      fn_GetAgentNameByID_          = nullptr;
    profit::GetAgentShortNameByID_t fn_GetAgentShortNameByID_     = nullptr;

    mutable std::mutex dll_mutex_;
};

/** Escreve uma linha de log de startup no DEBUG_LOG_PATH (para diagnóstico). */
void write_engine_startup_log(int32_t subscribe_ticker_ret, int32_t subscribe_offer_book_ret);

} // namespace profit_bridge
