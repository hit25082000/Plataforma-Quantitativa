#include "profit_bridge.h"
#include "config.h"
#include "hft_tuning.h"
#include "profit_types.h"
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <fstream>
#include <iostream>
#include <atomic>
#include <ctime>
#include <limits>
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
constexpr int32_t UNKNOWN_CONN_STATE = std::numeric_limits<int32_t>::lowest();
std::atomic<int32_t> g_login_result{UNKNOWN_CONN_STATE};
std::atomic<int32_t> g_market_result{UNKNOWN_CONN_STATE};
std::atomic<int32_t> g_activation_result{UNKNOWN_CONN_STATE};

std::mutex g_history_mutex;
std::condition_variable g_history_cv;
bool g_history_in_progress = false;
bool g_history_ready = false;
int64_t g_history_trades_received = 0;
std::atomic<bool> g_history_last_packet{false};

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

static std::string format_trade_date(const profit::SystemTime& st) {
    if (st.wYear == 0 || st.wMonth == 0 || st.wDay == 0) return {};
    char buf[16];
    std::snprintf(buf, sizeof(buf), "%04u%02u%02u", st.wYear, st.wMonth, st.wDay);
    return std::string(buf);
}

static int64_t system_time_to_epoch_ms(const profit::SystemTime& st) {
    if (st.wYear == 0 || st.wMonth == 0 || st.wDay == 0) return 0;
    std::tm tmv{};
    tmv.tm_year = static_cast<int>(st.wYear) - 1900;
    tmv.tm_mon = static_cast<int>(st.wMonth) - 1;
    tmv.tm_mday = static_cast<int>(st.wDay);
    tmv.tm_hour = static_cast<int>(st.wHour);
    tmv.tm_min = static_cast<int>(st.wMinute);
    tmv.tm_sec = static_cast<int>(st.wSecond);
    std::time_t tt = std::mktime(&tmv);
    if (tt < 0) return 0;
    return static_cast<int64_t>(tt) * 1000 + static_cast<int64_t>(st.wMilliseconds);
}

static void push_trade_event(
    const std::string& ticker,
    const std::string& bolsa,
    const profit::TConnectorTrade& trade,
    uint32_t flags,
    event_bus::TradeSource source)
{
    if (!g_queue) return;
    event_bus::TradeEvent ev;
    ev.ticker = ticker;
    ev.bolsa = bolsa;
    ev.trade_date = format_trade_date(trade.TradeDate);
    ev.price = trade.Price;
    ev.qty = trade.Quantity;
    ev.buy_agent = trade.BuyAgent;
    ev.sell_agent = trade.SellAgent;
    ev.trade_type = trade.TradeType;
    ev.trade_number = trade.TradeNumber;
    ev.trade_flags = flags;
    ev.trade_epoch_ms = system_time_to_epoch_ms(trade.TradeDate);
    ev.source = source;
    g_queue->push(ev);
}

static inline void maybe_pin_profit_callback_thread_once() {
    thread_local bool pinned = false;
    if (pinned) return;
    hft_tuning::maybe_pin_current_thread_from_env("HFT_PROFIT_CALLBACK_CORE", 2, "profit_callback");
    pinned = true;
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
        if (nType == profit::CONNECTION_STATE_LOGIN) {
            g_login_result.store(nResult);
        }
        if (nType == profit::CONNECTION_STATE_MARKET_DATA) {
            g_market_connected = (nResult == profit::MARKET_CONNECTED);
            g_market_result.store(nResult);
        }
        if (nType == profit::CONNECTION_STATE_MARKET_LOGIN) {
            g_activation_valid = (nResult == profit::CONNECTION_ACTIVATE_VALID);
            g_activation_result.store(nResult);
        }
        if (g_market_connected && g_activation_valid)
            g_market_cv.notify_all();
    }
}

void PROFIT_STDCALL progress_callback(profit::TAssetIDRec rAssetID, int32_t nProgress) {
    (void)rAssetID;
    if (nProgress >= 1000) {
        {
            std::lock_guard<std::mutex> lk(g_history_mutex);
            g_history_in_progress = false;
            g_history_ready = true;
        }
        g_history_cv.notify_all();
    }
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
    const wchar_t* pwcDate,
    double dOpen, double dHigh, double dLow, double dClose,
    double dVol, double /*dAjuste*/, double /*dMaxLimit*/, double /*dMinLimit*/,
    double /*dVolBuyer*/, double /*dVolSeller*/,
    int32_t /*nQtd*/, int32_t /*nNegocios*/, int32_t /*nContratosOpen*/,
    int32_t /*nQtdBuyer*/, int32_t /*nQtdSeller*/, int32_t /*nNegBuyer*/, int32_t /*nNegSeller*/)
{
    maybe_pin_profit_callback_thread_once();
    hft_tuning::record_profit_callback_tick();
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
    ev.trade_date = trim_ticker(wide_to_utf8(pwcDate));
    g_queue->push(ev);
}

void PROFIT_STDCALL offer_book_callback_v2(
    profit::TAssetIDRec rAssetID, int32_t nAction, int32_t nPosition,
    int32_t Side, int64_t nQtd, int32_t nAgent, int64_t nOfferID, double dPrice,
    int32_t, int32_t, int32_t, int32_t, int32_t, const wchar_t*, void*, void*)
{
    maybe_pin_profit_callback_thread_once();
    hft_tuning::record_profit_callback_tick();
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
    maybe_pin_profit_callback_thread_once();
    hft_tuning::record_profit_callback_tick();
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
        push_trade_event(
            ticker,
            wide_to_utf8(assetId.Exchange),
            trade,
            flags,
            event_bus::TradeSource::Realtime);
    }
}

void PROFIT_STDCALL history_trade_callback_v2(
    profit::TConnectorAssetIdentifier assetId, size_t pTrade, uint32_t flags)
{
    maybe_pin_profit_callback_thread_once();
    hft_tuning::record_profit_callback_tick();
    std::string ticker = trim_ticker(wide_to_utf8(assetId.Ticker));
    if (!g_queue || !g_translate_trade) return;
    profit::TConnectorTrade trade{};
    trade.Version = 0;
    int32_t tr_result = g_translate_trade(pTrade, &trade);
    if (tr_result == profit::NL_OK) {
        push_trade_event(
            ticker,
            wide_to_utf8(assetId.Exchange),
            trade,
            flags,
            event_bus::TradeSource::History);
        {
            std::lock_guard<std::mutex> lk(g_history_mutex);
            g_history_trades_received++;
            if ((flags & profit::TC_LAST_PACKET) == profit::TC_LAST_PACKET) {
                g_history_last_packet.store(true);
                g_history_in_progress = false;
                g_history_ready = true;
            }
        }
        if ((flags & profit::TC_LAST_PACKET) == profit::TC_LAST_PACKET) {
            g_history_cv.notify_all();
        }
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
    fn_SetHistoryTradeCallbackV2_ = (decltype(fn_SetHistoryTradeCallbackV2_))GET_PROC(dll_handle_, "SetHistoryTradeCallbackV2");
    fn_GetHistoryTrades_ = (decltype(fn_GetHistoryTrades_))GET_PROC(dll_handle_, "GetHistoryTrades");

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
    g_login_result.store(UNKNOWN_CONN_STATE);
    g_market_result.store(UNKNOWN_CONN_STATE);
    g_activation_result.store(UNKNOWN_CONN_STATE);
    if (dll_handle_) {
        FREE_LIB(dll_handle_);
        dll_handle_ = nullptr;
    }
    fn_GetAgentNameByID_ = nullptr;
    fn_GetAgentShortNameByID_ = nullptr;
    fn_SetHistoryTradeCallbackV2_ = nullptr;
    fn_GetHistoryTrades_ = nullptr;
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
    if (fn_GetAgentShortNameByID_) {
        const wchar_t* sname = fn_GetAgentShortNameByID_(agent_id);
        if (sname && *sname) {
            std::string utf8 = wide_to_utf8(sname);
            if (!utf8.empty()) return utf8;
        }
    }
    if (fn_GetAgentNameByID_) {
        const wchar_t* lname = fn_GetAgentNameByID_(agent_id);
        if (lname && *lname) {
            std::string utf8 = wide_to_utf8(lname);
            if (!utf8.empty()) return utf8;
        }
    }
    return "#" + std::to_string(agent_id);
}

bool ProfitBridge::wait_for_market_connected(std::chrono::milliseconds timeout) {
    // Exemplo C++: Subscribe só quando bMarketConnected && bAtivo (Market 4 e Ativação 0)
    std::unique_lock<std::mutex> lock(g_market_mutex);
    return g_market_cv.wait_for(lock, timeout, [] { return g_market_connected && g_activation_valid; });
}

int32_t ProfitBridge::last_login_result() const {
    return g_login_result.load();
}

int32_t ProfitBridge::last_market_result() const {
    return g_market_result.load();
}

int32_t ProfitBridge::last_activation_result() const {
    return g_activation_result.load();
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
    if (fn_SetHistoryTradeCallbackV2_) log_set("SetHistoryTradeCallbackV2", fn_SetHistoryTradeCallbackV2_(history_trade_callback_v2));
    else                             std::cerr << "[Profit] SetHistoryTradeCallbackV2 not available" << std::endl;
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

int32_t ProfitBridge::GetHistoryTrades(const wchar_t* ticker, const wchar_t* bolsa,
                                       const wchar_t* date_start, const wchar_t* date_end) {
    return fn_GetHistoryTrades_
        ? fn_GetHistoryTrades_(ticker, bolsa, date_start, date_end)
        : profit::NL_NOT_INITIALIZED;
}

int32_t ProfitBridge::request_history_today(const wchar_t* ticker, const wchar_t* bolsa) {
    std::time_t t = std::time(nullptr);
    std::tm tm_buf{};
#ifdef _WIN32
    localtime_s(&tm_buf, &t);
#else
    localtime_r(&t, &tm_buf);
#endif
    wchar_t date_buf[16];
    std::swprintf(date_buf, sizeof(date_buf) / sizeof(wchar_t), L"%02d/%02d/%04d",
                  tm_buf.tm_mday, tm_buf.tm_mon + 1, tm_buf.tm_year + 1900);
    {
        std::lock_guard<std::mutex> lk(g_history_mutex);
        g_history_in_progress = true;
        g_history_ready = false;
        g_history_trades_received = 0;
        g_history_last_packet.store(false);
    }
    int32_t ret = GetHistoryTrades(ticker, bolsa, date_buf, date_buf);
    if (ret < profit::NL_OK) {
        std::lock_guard<std::mutex> lk(g_history_mutex);
        g_history_in_progress = false;
        g_history_ready = false;
    }
    return ret;
}

bool ProfitBridge::wait_for_history_ready(std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lk(g_history_mutex);
    return g_history_cv.wait_for(lk, timeout, [] {
        return g_history_ready || g_history_last_packet.load();
    });
}

void ProfitBridge::reset_history_state() {
    std::lock_guard<std::mutex> lk(g_history_mutex);
    g_history_in_progress = false;
    g_history_ready = false;
    g_history_trades_received = 0;
    g_history_last_packet.store(false);
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
