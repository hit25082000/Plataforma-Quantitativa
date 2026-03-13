#pragma once

#include <cstdint>
#include <cstddef>

#ifdef _WIN32
#define PROFIT_STDCALL __stdcall
#else
#define PROFIT_STDCALL
#endif

namespace profit {

// Tipos base (Delphi packed record alignment)
using ProfitInt    = int32_t;
using ProfitInt64  = int64_t;
using ProfitUInt   = uint32_t;
using ProfitDouble = double;
using ProfitChar   = char;
using ProfitWChar  = const wchar_t*;

// TAssetIDRec (TAssetID) - usado em OfferBook, TinyBook, etc.
struct TAssetIDRec {
    const wchar_t* pwcTicker;
    const wchar_t* pwcBolsa;
    int32_t        nFeed;
};

// TConnectorAssetIdentifier - usado em TradeCallbackV2, PriceDepth
struct TConnectorAssetIdentifier {
    uint8_t        Version;
    const wchar_t* Ticker;
    const wchar_t* Exchange;
    uint8_t        FeedType;
};

// SystemTime (Delphi TSystemTime)
struct SystemTime {
    uint16_t wYear;
    uint16_t wMonth;
    uint16_t wDayOfWeek;
    uint16_t wDay;
    uint16_t wHour;
    uint16_t wMinute;
    uint16_t wSecond;
    uint16_t wMilliseconds;
};

// TConnectorTrade - resultado de TranslateTrade
struct TConnectorTrade {
    uint8_t        Version;
    SystemTime      TradeDate;
    uint32_t       TradeNumber;
    double         Price;
    int64_t        Quantity;
    double         Volume;
    int32_t        BuyAgent;
    int32_t        SellAgent;
    uint8_t        TradeType;
};

// Ações do OfferBook (nAction)
enum OfferBookAction : int {
    atAdd       = 0,
    atEdit      = 1,
    atDelete    = 2,
    atDeleteFrom= 3,
    atFullBook  = 4
};

// Lado do livro (Side)
enum BookSide : int {
    SideBuy  = 0,
    SideSell = 1
};

// TradeType: 2 = compra agressão, 3 = venda agressão
constexpr uint8_t TRADE_TYPE_BUY_AGGRESSION  = 2;
constexpr uint8_t TRADE_TYPE_SELL_AGGRESSION  = 3;

// TNewDailyCallback parameters (individual params per DLL manual, NOT a struct)
// The DLL calls this callback with 19 individual parameters via stdcall.

// Callbacks (stdcall obrigatório no Windows)
using StateCallback_t = void (PROFIT_STDCALL *)(int32_t nConnStateType, int32_t nResult);

using OfferBookV2_t = void (PROFIT_STDCALL *)(
    TAssetIDRec rAssetID,
    int32_t     nAction,
    int32_t     nPosition,
    int32_t     Side,
    int64_t     nQtd,
    int32_t     nAgent,
    int64_t     nOfferID,
    double      dPrice,
    char        bHasPrice,
    char        bHasQtd,
    char        bHasDate,
    char        bHasOfferID,
    char        bHasAgent,
    const wchar_t* pwcDate,
    void*       pArraySell,
    void*       pArrayBuy
);

using TradeCallbackV2_t = void (PROFIT_STDCALL *)(
    TConnectorAssetIdentifier assetId,
    size_t                    pTrade,
    uint32_t                  flags
);

using TinyBookCallback_t = void (PROFIT_STDCALL *)(
    TAssetIDRec rAssetID,
    double      price,
    int32_t     qtd,
    int32_t     side
);

using ProgressCallback_t = void (PROFIT_STDCALL *)(
    TAssetIDRec rAssetID,
    int32_t     nProgress
);

// DLLInitializeMarketLogin - Market Data only
using DLLInitMarketLogin_t = int32_t (PROFIT_STDCALL *)(
    const wchar_t* pwcActivationKey,
    const wchar_t* pwcUser,
    const wchar_t* pwcPassword,
    StateCallback_t    StateCallback,
    void*              NewTradeCallback,   // pode ser null se usar SetTradeCallbackV2
    void*              NewDailyCallback,
    void*              PriceBookCallback,
    void*              OfferBookCallback,  // pode ser null se usar SetOfferBookCallbackV2
    void*              HistoryTradeCallback,
    ProgressCallback_t ProgressCallback,
    TinyBookCallback_t TinyBookCallback
);

using DLLFinalize_t     = int32_t (PROFIT_STDCALL *)();
using SubscribeTicker_t = int32_t (PROFIT_STDCALL *)(const wchar_t* pwcTicker, const wchar_t* pwcBolsa);
using UnsubscribeTicker_t = int32_t (PROFIT_STDCALL *)(const wchar_t* pwcTicker, const wchar_t* pwcBolsa);
using SubscribeOfferBook_t  = int32_t (PROFIT_STDCALL *)(const wchar_t* pwcTicker, const wchar_t* pwcBolsa);
using UnsubscribeOfferBook_t = int32_t (PROFIT_STDCALL *)(const wchar_t* pwcTicker, const wchar_t* pwcBolsa);

using SetStateCallback_t     = int32_t (PROFIT_STDCALL *)(StateCallback_t);
using SetOfferBookCallbackV2_t = int32_t (PROFIT_STDCALL *)(OfferBookV2_t);
using SetTradeCallbackV2_t    = int32_t (PROFIT_STDCALL *)(TradeCallbackV2_t);
using SetTinyBookCallback_t   = int32_t (PROFIT_STDCALL *)(TinyBookCallback_t);

using NewDailyCallback_t = void (PROFIT_STDCALL *)(
    TAssetIDRec rAssetID,
    const wchar_t* pwcDate,
    double dOpen, double dHigh, double dLow, double dClose,
    double dVol, double dAjuste, double dMaxLimit, double dMinLimit,
    double dVolBuyer, double dVolSeller,
    int32_t nQtd, int32_t nNegocios, int32_t nContratosOpen,
    int32_t nQtdBuyer, int32_t nQtdSeller, int32_t nNegBuyer, int32_t nNegSeller
);
using SetDailyCallback_t = int32_t (PROFIT_STDCALL *)(NewDailyCallback_t);

// TranslateTrade(pTrade, &TConnectorTrade) -> int
using TranslateTrade_t = int32_t (PROFIT_STDCALL *)(size_t pTrade, TConnectorTrade* pOut);

// GetAgentNameByID(nID) -> nome da corretora (ou null)
using GetAgentNameByID_t = const wchar_t* (PROFIT_STDCALL *)(int32_t nID);
// GetAgentShortNameByID(nID) -> nome abreviado da corretora (ou null)
using GetAgentShortNameByID_t = const wchar_t* (PROFIT_STDCALL *)(int32_t nID);

// Error codes (Delphi/C# ProfitConstants)
constexpr int32_t NL_OK                 = 0x00000000;
constexpr int32_t NL_INTERNAL_ERROR      = static_cast<int32_t>(0x80000001);
constexpr int32_t NL_NOT_INITIALIZED     = NL_INTERNAL_ERROR + 1;
constexpr int32_t NL_INVALID_ARGS       = NL_NOT_INITIALIZED + 1;
constexpr int32_t NL_WAITING_SERVER     = NL_INVALID_ARGS + 1;
constexpr int32_t NL_INVALID_TICKER     = static_cast<int32_t>(0x8000001F);  // Ticker/bolsa inválido para esta função
constexpr int32_t NL_MARKET_ONLY        = -2147483635;  // Não possui roteamento

// Connection state types
constexpr int32_t CONNECTION_STATE_LOGIN        = 0;
constexpr int32_t CONNECTION_STATE_ROTEAMENTO  = 1;
constexpr int32_t CONNECTION_STATE_MARKET_DATA = 2;
constexpr int32_t CONNECTION_STATE_ACTIVATION  = 3;

// Results
constexpr int32_t LOGIN_CONNECTED      = 0;
constexpr int32_t MARKET_CONNECTED     = 4;
constexpr int32_t CONNECTION_ACTIVATE_VALID = 0;

} // namespace profit
