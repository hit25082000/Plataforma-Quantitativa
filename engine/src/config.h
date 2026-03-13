#pragma once

#include <cstdlib>
#include <string>

namespace config {

// DLL / Login - usar env PROFIT_ACTIVATION_KEY, PROFIT_USER, PROFIT_PASSWORD
inline const char* activation_key() {
    const char* v = std::getenv("PROFIT_ACTIVATION_KEY");
    return v ? v : "";
}
inline const char* user() {
    const char* v = std::getenv("PROFIT_USER");
    return v ? v : "";
}
inline const char* password() {
    const char* v = std::getenv("PROFIT_PASSWORD");
    return v ? v : "";
}

// Ativo - configurável via env PROFIT_TICKER e PROFIT_BOLSA
// WINFUT = ticker contínuo do mini-índice (sempre aponta para o contrato ativo)
inline const char* ticker_default() {
    const char* v = std::getenv("PROFIT_TICKER");
    return v ? v : "WINFUT";
}
inline const char* bolsa_default() {
    const char* v = std::getenv("PROFIT_BOLSA");
    return v ? v : "F";
}

// ZeroMQ
inline const char* zmq_address = "tcp://*:5555";

// Regras de negócio (M1)
inline int64_t wall_threshold    = 500;   // qty >= 500 = muralha
inline int64_t spoofing_timer_ms = 5000;  // timer anti-spoofing

// M2 Rule Engine
inline constexpr int64_t R2_WALL_THRESHOLD    = 500;
inline constexpr int64_t R2_SPOOFING_TIMER_MS = 2000;
inline constexpr double R2_PRICE_TOLERANCE    = 5.0;
inline constexpr double R3_VWAP_DEVIATION_PCT = 0.001;
inline constexpr int64_t R3_AGENT_VOLUME_THRESHOLD = 500;

// Rule 1 - Motor de Armadilhas em Rompimentos
inline constexpr int64_t R1_DOM_RALO_THRESHOLD    = 200;  // soma 10 linhas < X = ralo
inline constexpr int     R1_DOM_DEPTH_LEVELS       = 10;
inline constexpr int64_t R1_CONFIRM_WINDOW_MS      = 3000; // janela para agressão oposta
inline constexpr int64_t R1_CONFIRM_AGG_THRESHOLD  = 200;  // agressão oposta mínima
inline constexpr int64_t R1_AGENT_DELTA_WINDOW_MS  = 5000; // janela para exaustão

// Rule 5 - Sentinela de MAs
inline constexpr int     R5_RSI_PERIOD           = 14;
inline constexpr double  R5_RSI_OVERBOUGHT      = 75.0;
inline constexpr double  R5_RSI_OVERSOLD        = 25.0;
inline constexpr int     R5_MA_SHORT_PERIOD        = 200;
inline constexpr int     R5_MA_LONG_PERIOD         = 550;
inline constexpr double  R5_MA_PROXIMITY_POINTS    = 30.0;
inline constexpr int64_t R5_AGG_THRESHOLD          = 300;
inline constexpr int64_t R5_WALL_THRESHOLD         = 500;
inline constexpr int     R5_MIN_CONFIRMING_RULES   = 2;
inline constexpr int     R5_SIGNAL_WINDOW_MS       = 30000;
inline constexpr double  R5_RENKO_SIZE             = 42.0;  // 42 pontos por brick Renko

// Rule 6 - Absorção Institucional
inline constexpr int     R6_TOP_N_AGENTS           = 5;
inline constexpr double  R6_VOLUME_MULTIPLIER      = 2.0;
inline constexpr int     R6_CANDLE_LOOKBACK        = 20;
inline constexpr double  R6_SPREAD_THRESHOLD       = 50.0; // pontos
inline constexpr int     R6_CANDLE_PERIOD_SECONDS   = 1800; // 30 min
inline constexpr int     R6_ICEBERG_WINDOW_MS       = 500;
inline constexpr int64_t R6_ICEBERG_MIN_QTY         = 300;

// DLL path (relativo ao executável): manual exige ProfitDLL64.dll para 64 bits, ProfitDLL.dll para 32 bits
#if defined(_WIN64)
inline const char* dll_path = "ProfitDLL64.dll";
#else
inline const char* dll_path = "ProfitDLL.dll";
#endif

} // namespace config
