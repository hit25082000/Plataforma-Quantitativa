#include "profit_bridge.h"
#include "config.h"
#include "profit_types.h"
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <atomic>
#include <mutex>
#include <sstream>
#include <string>

#ifdef _WIN32
#include <windows.h>
#define LOAD_LIB(name) LoadLibraryW(name)
#define GET_PROC(lib, name) GetProcAddress((HMODULE)lib, name)
#define FREE_LIB(lib) FreeLibrary((HMODULE)lib)
#else
#include <dlfcn.h>
#define LOAD_LIB(name) dlopen(name, RTLD_LAZY)
#define GET_PROC(lib, name) dlsym(lib, name)
#define FREE_LIB(lib) dlclose(lib)
#endif

namespace profit_bridge {

namespace {

event_bus::EventQueue* g_queue = nullptr;
profit::TranslateTrade_t g_translate_trade = nullptr;

std::mutex g_market_mutex;
std::condition_variable g_market_cv;
bool g_market_connected = false;
bool g_activation_valid = false;

std::atomic<bool> g_first_trade{true};
std::atomic<bool> g_first_offerbook{true};
std::atomic<bool> g_first_daily{true};

std::string wide_to_utf8(const wchar_t* w) {
    if (!w || !*w) return {};
#ifdef _WIN32
    int len = WideCharToMultiByte(CP_UTF8, 0, w, -1, nullptr, 0, nullptr, nullptr);
    if (len <= 0) return {};
    std::string s(static_cast<size_t>(len), 0);
    WideCharToMultiByte(CP_UTF8, 0, w, -1, &s[0], len, nullptr, nullptr);
    s.resize(static_cast<size_t>(len) - 1);
    return s;
#else
    std::string s;
    while (*w) {
        char c = static_cast<char>(*w & 0xFF);
        if (c) s += c;
        ++w;
    }
    return s;
#endif
}

static std::string trim_ticker(std::string s) {
    auto start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    auto end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end == std::string::npos ? std::string::npos : end - start + 1);
}

void PROFIT_STDCALL state_callback(int32_t nType, int32_t nResult) {
    const char* type_str = "?";
    switch (nType) {
        case profit::CONNECTION_STATE_LOGIN:       type_str = "Login"; break;
        case profit::CONNECTION_STATE_ROTEAMENTO:  type_str = "Roteamento"; break;
        case profit::CONNECTION_STATE_MARKET_DATA: type_str = "Market"; break;
        case profit::CONNECTION_STATE_ACTIVATION:  type_str = "Ativacao"; break;
    }
    std::cerr << "[Profit] " << type_str << ": " << nResult << std::endl;
    {
        std::lock_guard<std::mutex> lk(g_market_mutex);
        if (nType == profit::CONNECTION_STATE_MARKET_DATA && nResult == profit::MARKET_CONNECTED)
            g_market_connected = true;
        if (nType == profit::CONNECTION_STATE_ACTIVATION && nResult == profit::CONNECTION_ACTIVATE_VALID)
            g_activation_valid = true;
        if (g_market_connected && g_activation_valid)
            g_market_cv.notify_all();
    }
}

void PROFIT_STDCALL progress_callback(profit::TAssetIDRec rAssetID, int32_t nProgress) {
    (void)rAssetID;
    (void)nProgress;
    // Progresso de download de histórico - ignorar
}

void PROFIT_STDCALL tiny_book_callback(profit::TAssetIDRec rAssetID, double price, int32_t qtd, int32_t side) {
    (void)rAssetID;
    (void)price;
    (void)qtd;
    (void)side;
    // Heartbeat leve - ignorar por ora
}

void PROFIT_STDCALL daily_callback(
    profit::TAssetIDRec rAssetID,
    const wchar_t* /*pwcDate*/,
    double dOpen, double dHigh, double dLow, double dClose,
    double dVol, double /*dAjuste*/, double /*dMaxLimit*/, double /*dMinLimit*/,
    double /*dVolBuyer*/, double /*dVolSeller*/,
    int32_t /*nQtd*/, int32_t /*nNegocios*/, int32_t /*nContratosOpen*/,
    int32_t /*nQtdBuyer*/, int32_t /*nQtdSeller*/, int32_t /*nNegBuyer*/, int32_t /*nNegSeller*/)
{
    std::string ticker = trim_ticker(wide_to_utf8(rAssetID.pwcTicker));
    if (!g_queue) return;
    if (g_first_daily.exchange(false))
        std::cerr << "[Profit] First DAILY for " << ticker
                  << " O=" << dOpen << " H=" << dHigh << " L=" << dLow << " C=" << dClose << std::endl;
    event_bus::DailyEvent ev;
    ev.ticker = ticker;
    ev.high   = dHigh;
    ev.low    = dLow;
    ev.open   = dOpen;
    ev.close  = dClose;
    ev.volume = dVol;
    g_queue->push(ev);
}

void PROFIT_STDCALL offer_book_callback_v2(
    profit::TAssetIDRec rAssetID, int32_t nAction, int32_t nPosition,
    int32_t Side, int64_t nQtd, int32_t nAgent, int64_t nOfferID, double dPrice,
    char, char, char, char, char, const wchar_t*, void*, void*)
{
    std::string ticker = trim_ticker(wide_to_utf8(rAssetID.pwcTicker));
    if (!g_queue) return;
    if (g_first_offerbook.exchange(false))
        std::cerr << "[Profit] First OFFER_BOOK for " << ticker
                  << " action=" << nAction << " price=" << dPrice << " qty=" << nQtd << std::endl;
    event_bus::OfferBookEvent ev;
    ev.ticker    = ticker;
    ev.bolsa     = trim_ticker(wide_to_utf8(rAssetID.pwcBolsa));
    ev.nAction   = nAction;
    ev.nPosition = nPosition;
    ev.side      = Side;
    ev.nQtd      = nQtd;
    ev.nAgent    = nAgent;
    ev.nOfferID  = nOfferID;
    ev.sPrice    = dPrice;
    g_queue->push(ev);
}

void PROFIT_STDCALL trade_callback_v2(
    profit::TConnectorAssetIdentifier assetId, size_t pTrade, uint32_t flags)
{
    std::string ticker = trim_ticker(wide_to_utf8(assetId.Ticker));
    if (!g_queue || !g_translate_trade) return;
    profit::TConnectorTrade trade{};
    trade.Version = 0;
    int32_t tr_result = g_translate_trade(pTrade, &trade);
    if (tr_result == profit::NL_OK) {
        if (g_first_trade.exchange(false))
            std::cerr << "[Profit] First TRADE for " << ticker
                      << " price=" << trade.Price << " qty=" << trade.Quantity
                      << " type=" << (int)trade.TradeType << std::endl;
        event_bus::TradeEvent ev;
        ev.ticker     = ticker;
        ev.bolsa      = wide_to_utf8(assetId.Exchange);
        ev.price      = trade.Price;
        ev.qty        = trade.Quantity;
        ev.buy_agent  = trade.BuyAgent;
        ev.sell_agent = trade.SellAgent;
        ev.trade_type = trade.TradeType;
        (void)flags;
        g_queue->push(ev);
    }
}

} // namespace

ProfitBridge::ProfitBridge(event_bus::EventQueue& queue) : queue_(queue) {}

ProfitBridge::~ProfitBridge() {
    unload();
}

bool ProfitBridge::load(const std::string& dll_path) {
    auto do_load = [this](const std::string& p) -> bool {
#ifdef _WIN32
        std::wstring wpath(p.begin(), p.end());
        dll_handle_ = LOAD_LIB(wpath.c_str());
#else
        dll_handle_ = LOAD_LIB(p.c_str());
#endif
        return dll_handle_ != nullptr;
    };
    if (do_load(dll_path)) {
        std::cerr << "[Profit] Loaded: " << dll_path << std::endl;
    } else {
#ifdef _WIN64
        if (dll_path == "ProfitDLL64.dll" && do_load("ProfitDLL.dll")) {
            std::cerr << "[Profit] Loaded fallback: ProfitDLL.dll" << std::endl;
        } else
#endif
        {
            std::cerr << "[Profit] Failed to load " << dll_path << ". 64-bit build requires ProfitDLL64.dll (see manual)." << std::endl;
            return false;
        }
    }

#define RESOLVE(name) \
    fn_##name##_ = (decltype(fn_##name##_))GET_PROC(dll_handle_, #name); \
    if (!fn_##name##_) { std::cerr << "Missing: " #name << std::endl; unload(); return false; }

    RESOLVE(DLLInitializeMarketLogin);
    RESOLVE(DLLFinalize);
    RESOLVE(SubscribeTicker);
    RESOLVE(UnsubscribeTicker);
    RESOLVE(SubscribeOfferBook);
    RESOLVE(UnsubscribeOfferBook);
    RESOLVE(SetStateCallback);
    RESOLVE(SetOfferBookCallbackV2);
    RESOLVE(SetTradeCallbackV2);
    RESOLVE(SetTinyBookCallback);
    RESOLVE(TranslateTrade);

    // SetDailyCallback pode não existir em todas as versões da DLL
    fn_SetDailyCallback_ = (decltype(fn_SetDailyCallback_))GET_PROC(dll_handle_, "SetDailyCallback");
    // Não aborta se não encontrar: usaremos fallback no DLLInitializeMarketLogin

    // GetAgentNameByID / GetAgentShortNameByID opcionais (DLLs antigas podem não exportar)
    fn_GetAgentNameByID_ = (decltype(fn_GetAgentNameByID_))GET_PROC(dll_handle_, "GetAgentNameByID");
    fn_GetAgentShortNameByID_ = (decltype(fn_GetAgentShortNameByID_))GET_PROC(dll_handle_, "GetAgentShortNameByID");

#undef RESOLVE
    g_queue = &queue_;
    g_translate_trade = fn_TranslateTrade_;
    return true;
}

void ProfitBridge::unload() {
    g_queue = nullptr;
    g_translate_trade = nullptr;
    {
        std::lock_guard<std::mutex> lk(g_market_mutex);
        g_market_connected = false;
        g_activation_valid = false;
    }
    if (dll_handle_) {
        FREE_LIB(dll_handle_);
        dll_handle_ = nullptr;
    }
    fn_GetAgentNameByID_ = nullptr;
    fn_GetAgentShortNameByID_ = nullptr;
}

std::string ProfitBridge::get_agent_name(int32_t agent_id) const {
    std::lock_guard<std::mutex> lock(dll_mutex_);
    if (!fn_GetAgentNameByID_) return "#" + std::to_string(agent_id);
    const wchar_t* name = fn_GetAgentNameByID_(agent_id);
    if (!name || !*name) return "#" + std::to_string(agent_id);
    std::string utf8 = wide_to_utf8(name);
    return utf8.empty() ? "#" + std::to_string(agent_id) : utf8;
}

std::string ProfitBridge::get_agent_short_name(int32_t agent_id) const {
    std::lock_guard<std::mutex> lock(dll_mutex_);
    if (!fn_GetAgentShortNameByID_) return "#" + std::to_string(agent_id);
    const wchar_t* name = fn_GetAgentShortNameByID_(agent_id);
    if (!name || !*name) return "#" + std::to_string(agent_id);
    std::string utf8 = wide_to_utf8(name);
    return utf8.empty() ? "#" + std::to_string(agent_id) : utf8;
}

bool ProfitBridge::wait_for_market_connected(std::chrono::milliseconds timeout) {
    // Exemplo C++: Subscribe só quando bMarketConnected && bAtivo (Market 4 e Ativação 0)
    std::unique_lock<std::mutex> lock(g_market_mutex);
    return g_market_cv.wait_for(lock, timeout, [] { return g_market_connected && g_activation_valid; });
}

void ProfitBridge::register_callbacks() {
    auto log_set = [](const char* name, int32_t ret) {
        if (ret >= 0) std::cerr << "[Profit] " << name << " OK (" << ret << ")" << std::endl;
        else          std::cerr << "[Profit] " << name << " FAILED (" << ret << ")" << std::endl;
    };
    if (fn_SetStateCallback_)        log_set("SetStateCallback",        fn_SetStateCallback_(state_callback));
    if (fn_SetTinyBookCallback_)     log_set("SetTinyBookCallback",     fn_SetTinyBookCallback_(tiny_book_callback));
    if (fn_SetOfferBookCallbackV2_)  log_set("SetOfferBookCallbackV2",  fn_SetOfferBookCallbackV2_(offer_book_callback_v2));
    if (fn_SetTradeCallbackV2_)      log_set("SetTradeCallbackV2",      fn_SetTradeCallbackV2_(trade_callback_v2));
    if (fn_SetDailyCallback_)        log_set("SetDailyCallback",        fn_SetDailyCallback_(daily_callback));
    else                             std::cerr << "[Profit] SetDailyCallback not available, using init fallback" << std::endl;
}

int32_t ProfitBridge::DLLInitializeMarketLogin(
    const wchar_t* activation_key,
    const wchar_t* user,
    const wchar_t* password)
{
    if (!fn_DLLInitializeMarketLogin_) return profit::NL_NOT_INITIALIZED;
    return fn_DLLInitializeMarketLogin_(
        activation_key,
        user,
        password,
        state_callback,
        nullptr,              // NewTradeCallback - overridden by SetTradeCallbackV2 after init
        (void*)daily_callback,// NewDailyCallback - overridden by SetDailyCallback after init if available
        nullptr,              // PriceBookCallback
        nullptr,              // OfferBookCallback - overridden by SetOfferBookCallbackV2 after init
        nullptr,              // HistoryTradeCallback
        progress_callback,
        tiny_book_callback
    );
}

int32_t ProfitBridge::DLLFinalize() {
    return fn_DLLFinalize_ ? fn_DLLFinalize_() : profit::NL_NOT_INITIALIZED;
}

int32_t ProfitBridge::SubscribeTicker(const wchar_t* ticker, const wchar_t* bolsa) {
    return fn_SubscribeTicker_ ? fn_SubscribeTicker_(ticker, bolsa) : profit::NL_NOT_INITIALIZED;
}

int32_t ProfitBridge::UnsubscribeTicker(const wchar_t* ticker, const wchar_t* bolsa) {
    return fn_UnsubscribeTicker_ ? fn_UnsubscribeTicker_(ticker, bolsa) : profit::NL_NOT_INITIALIZED;
}

int32_t ProfitBridge::SubscribeOfferBook(const wchar_t* ticker, const wchar_t* bolsa) {
    return fn_SubscribeOfferBook_ ? fn_SubscribeOfferBook_(ticker, bolsa) : profit::NL_NOT_INITIALIZED;
}

int32_t ProfitBridge::UnsubscribeOfferBook(const wchar_t* ticker, const wchar_t* bolsa) {
    return fn_UnsubscribeOfferBook_ ? fn_UnsubscribeOfferBook_(ticker, bolsa) : profit::NL_NOT_INITIALIZED;
}

static std::string get_engine_log_path() {
    const char* path = std::getenv("DEBUG_LOG_PATH");
    return path ? std::string(path) : "profit_engine.log";
}

void write_engine_startup_log(int32_t subscribe_ticker_ret, int32_t subscribe_offer_book_ret) {
    std::string filepath = get_engine_log_path();
    std::ofstream f(filepath, std::ios::app);
    if (f) {
        f << "{\"message\":\"engine_started\",\"data\":{"
          << "\"subscribe_ticker_ret\":" << subscribe_ticker_ret
          << ",\"subscribe_offer_book_ret\":" << subscribe_offer_book_ret << "}}\n";
    }
}

} // namespace profit_bridge
