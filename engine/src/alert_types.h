#pragma once

#include <nlohmann/json.hpp>
#include <cstdint>
#include <string>
#include <vector>

namespace rules {

enum class Rule : int { R1 = 1, R2 = 2, R3 = 3, R5 = 5, R6 = 6 };
enum class Direction { Buy, Sell, Neutral };
enum class Conviction { Low, Medium, High };

struct Alert {
    Rule        rule;
    Direction   direction;
    Conviction  conviction;
    std::string label;
    double      price;
    std::string ticker;
    nlohmann::json data;
    int64_t     timestamp_ms;
};

// Eventos enriquecidos para as regras (diferentes dos eventos brutos do event_bus)
struct AgentStats {
    int64_t buy_aggression_qty  = 0;
    int64_t sell_aggression_qty = 0;
};

struct TradeEvent {
    std::string ticker;
    double      price;
    int64_t     qty;
    int32_t     buy_agent;
    int32_t     sell_agent;
    uint8_t     trade_type;
    double      vwap_atual;
    int64_t     net_aggression;
    AgentStats  agent_stats;
};

struct WallAddEvent {
    std::string ticker;
    int64_t     offer_id;
    double      price;
    int64_t     qty;
    int32_t     side;
    int32_t     agent_id;
    int64_t     timestamp_ms;
};

struct WallRemoveEvent {
    std::string ticker;
    int64_t     offer_id;
    double      price;
    int64_t     qty;
    int32_t     agent_id;
    int64_t     elapsed_ms;
    bool        was_traded;
};

struct PriceLevel {
    double price;
    int64_t total_qty;
};

struct DomSnapshotEvent {
    std::string ticker;
    std::vector<PriceLevel> buy_side;
    std::vector<PriceLevel> sell_side;
};

struct DailyInfoEvent {
    std::string ticker;
    double high;
    double low;
    double open;
    double close;
};

} // namespace rules
