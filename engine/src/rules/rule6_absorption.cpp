#include "rule6_absorption.h"
#include "../config.h"
#include <algorithm>
#include <chrono>

namespace rules {

Rule6Absorption::Rule6Absorption(alert_bus::AlertBus& ab,
                                 const AgentRanking& ranking,
                                 const dom_snapshot::DOMSnapshotEngine& dom)
    : RuleBase(ab)
    , ranking_(ranking)
    , dom_(dom)
    , rsi_30m_(config::R5_RSI_PERIOD)
{}

void Rule6Absorption::on_trade(const TradeEvent& ev) {
    int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();

    // --- Construir candles sintéticos de 30 min ---
    if (!current_candle_.active) {
        current_candle_.open = ev.price;
        current_candle_.high = ev.price;
        current_candle_.low = ev.price;
        current_candle_.close = ev.price;
        current_candle_.volume = ev.qty;
        current_candle_.start_ms = now_ms;
        current_candle_.active = true;
    } else {
        current_candle_.close = ev.price;
        if (ev.price > current_candle_.high) current_candle_.high = ev.price;
        if (ev.price < current_candle_.low) current_candle_.low = ev.price;
        current_candle_.volume += ev.qty;

        // Verificar se o candle de 30min fechou
        int64_t elapsed_s = (now_ms - current_candle_.start_ms) / 1000;
        if (elapsed_s >= config::R6_CANDLE_PERIOD_SECONDS) {
            close_candle();
        }
    }

    // --- Iceberg detection (absorvida da R4) ---
    // Marcar removals que tiveram trade no mesmo preço
    for (auto& rr : recent_removals_) {
        constexpr double PRICE_TOL = 0.01;
        if (std::abs(rr.price - ev.price) < PRICE_TOL) {
            rr.had_trade = true;
        }
    }
}

void Rule6Absorption::on_wall_remove(const WallRemoveEvent& ev) {
    int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();

    // Limpar entradas antigas
    recent_removals_.erase(
        std::remove_if(recent_removals_.begin(), recent_removals_.end(),
            [now_ms](const IcebergEntry& e) {
                return now_ms - e.ts_ms > config::R6_ICEBERG_WINDOW_MS * 3;
            }),
        recent_removals_.end());

    IcebergEntry entry;
    entry.offer_id = ev.offer_id;
    entry.price = ev.price;
    entry.qty = ev.qty;
    entry.agent_id = ev.agent_id;
    entry.ts_ms = now_ms - ev.elapsed_ms;
    entry.had_trade = ev.was_traded;
    recent_removals_.push_back(entry);
}

void Rule6Absorption::on_wall_add(const WallAddEvent& ev) {
    constexpr double PRICE_TOL = 0.01;

    // Procurar remoção recente no mesmo preço pelo mesmo agente
    auto it = std::find_if(recent_removals_.begin(), recent_removals_.end(),
        [&](const IcebergEntry& e) {
            return std::abs(e.price - ev.price) < PRICE_TOL &&
                   e.agent_id == ev.agent_id;
        });

    if (it == recent_removals_.end()) return;

    int64_t elapsed = ev.timestamp_ms - it->ts_ms;
    if (elapsed > config::R6_ICEBERG_WINDOW_MS * 3) {
        recent_removals_.erase(it);
        return;
    }

    if (elapsed <= config::R6_ICEBERG_WINDOW_MS &&
        ev.qty >= config::R6_ICEBERG_MIN_QTY) {
        // Iceberg confirmado: renovação rápida pelo mesmo agente
        iceberg_score_ += ev.qty;
    }

    // Limpar a entrada processada
    recent_removals_.erase(it);
}

void Rule6Absorption::close_candle() {
    rsi_30m_.push_price(current_candle_.close);
    candles_.push_back(current_candle_);

    if (static_cast<int>(candles_.size()) > config::R6_CANDLE_LOOKBACK + 5) {
        candles_.pop_front();
    }

    // Avaliar condições de absorção
    if (rsi_30m_.ready() && check_effort_vs_result(current_candle_)) {
        if (check_top4_accumulating()) {
            double rsi_val = rsi_30m_.compute();
            bool rsi_exhaustion = rsi_val < 25.0 || rsi_val > 75.0;

            if (rsi_exhaustion || iceberg_score_ > 0) {
                Alert a;
                a.rule = Rule::R6;
                a.price = current_candle_.close;
                a.ticker = ""; // será preenchido pelo dispatcher
                a.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::system_clock::now().time_since_epoch()).count();

                auto top_buy = ranking_.top_buyers(config::R6_TOP_N_AGENTS);
                auto top_sell = ranking_.top_sellers(config::R6_TOP_N_AGENTS);
                int64_t buy_balance = 0, sell_balance = 0;
                for (const auto& [id, qty] : top_buy) buy_balance += qty;
                for (const auto& [id, qty] : top_sell) sell_balance += qty;

                if (buy_balance > sell_balance) {
                    a.direction = Direction::Buy;
                    a.label = "ABSORÇÃO INSTITUCIONAL — POWWW (Acumulação)";
                } else {
                    a.direction = Direction::Sell;
                    a.label = "ABSORÇÃO INSTITUCIONAL — POWWW (Distribuição)";
                }

                a.conviction = Conviction::High;
                a.data["rsi_30m"] = rsi_val;
                a.data["candle_volume"] = current_candle_.volume;
                a.data["candle_spread"] = std::abs(current_candle_.close - current_candle_.open);
                a.data["avg_volume"] = avg_volume();
                a.data["iceberg_score"] = iceberg_score_;
                a.data["top4_buy_balance"] = buy_balance;
                a.data["top4_sell_balance"] = sell_balance;

                alert_bus_.push(std::move(a));
            }
        }
    }

    // Reset para o próximo candle
    iceberg_score_ = 0;
    current_candle_ = Candle{};
}

bool Rule6Absorption::check_effort_vs_result(const Candle& c) const {
    // Esforço: volume > 2x média dos últimos N candles
    double avg_vol = avg_volume();
    if (avg_vol <= 0) return false;
    if (c.volume < static_cast<int64_t>(avg_vol * config::R6_VOLUME_MULTIPLIER)) return false;

    // Resultado: corpo estreito (|close - open| < 50 pontos)
    double spread = std::abs(c.close - c.open);
    return spread < config::R6_SPREAD_THRESHOLD;
}

bool Rule6Absorption::check_top4_accumulating() const {
    auto top_buy = ranking_.top_buyers(config::R6_TOP_N_AGENTS);
    auto top_sell = ranking_.top_sellers(config::R6_TOP_N_AGENTS);

    // Pelo menos um dos lados deve ter players ativos
    int64_t total_top_volume = 0;
    for (const auto& [id, qty] : top_buy) total_top_volume += qty;
    for (const auto& [id, qty] : top_sell) total_top_volume += qty;

    // Os Top 4 devem representar volume significativo
    return total_top_volume > 0;
}

double Rule6Absorption::avg_volume() const {
    if (candles_.empty()) return 0;
    int count = std::min(static_cast<int>(candles_.size()), config::R6_CANDLE_LOOKBACK);
    int64_t sum = 0;
    auto it = candles_.end() - count;
    for (; it != candles_.end(); ++it) {
        sum += it->volume;
    }
    return static_cast<double>(sum) / count;
}

} // namespace rules
