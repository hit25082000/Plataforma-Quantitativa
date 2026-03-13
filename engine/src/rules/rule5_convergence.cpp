#include "rule5_convergence.h"
#include "../config.h"
#include <cmath>
#include <chrono>
#include <numeric>

namespace rules {

Rule5Convergence::Rule5Convergence(alert_bus::AlertBus& ab,
                                   const dom_snapshot::DOMSnapshotEngine& dom)
    : RuleBase(ab)
    , dom_(dom)
    , rsi_(config::R5_RSI_PERIOD)
{}

double Rule5Convergence::sma(int period) const {
    if (static_cast<int>(renko_closes_.size()) < period) return 0;
    double sum = 0;
    auto it = renko_closes_.end() - period;
    for (; it != renko_closes_.end(); ++it) {
        sum += *it;
    }
    return sum / period;
}

bool Rule5Convergence::near_ma(double price, double ma_value) const {
    if (ma_value <= 0) return false;
    return std::abs(price - ma_value) <= config::R5_MA_PROXIMITY_POINTS;
}

void Rule5Convergence::on_trade(const TradeEvent& ev) {
    // --- Renko brick builder (42 pontos) ---
    if (!renko_initialized_) {
        renko_ref_ = ev.price;
        renko_initialized_ = true;
        return;
    }

    // Calcular quantos bricks completos o movimento gera
    double delta = ev.price - renko_ref_;
    int bricks = static_cast<int>(std::abs(delta) / RENKO_SIZE);

    if (bricks > 0) {
        double direction = (delta > 0) ? 1.0 : -1.0;
        for (int i = 0; i < bricks; ++i) {
            renko_ref_ += direction * RENKO_SIZE;
            double brick_close = renko_ref_;

            // Cada brick Renko gera um close para o cálculo de MA e RSI
            renko_closes_.push_back(brick_close);
            rsi_.push_price(brick_close);
        }

        // Manter janela suficiente para MA550
        constexpr int MAX_HISTORY = 600;
        while (static_cast<int>(renko_closes_.size()) > MAX_HISTORY) {
            renko_closes_.pop_front();
        }
    }

    // Precisamos de dados suficientes para pelo menos a MA200
    if (static_cast<int>(renko_closes_.size()) < config::R5_MA_SHORT_PERIOD) return;
    if (!rsi_.ready()) return;

    double ma200 = sma(config::R5_MA_SHORT_PERIOD);
    double ma550 = sma(config::R5_MA_LONG_PERIOD);

    // Gatilho: preço dentro de 30 pontos de MA200 ou MA550
    bool near_200 = near_ma(ev.price, ma200);
    bool near_550 = near_ma(ev.price, ma550);
    if (!near_200 && !near_550) return;

    // Validação 1: IFR em exaustão
    double rsi_val = rsi_.compute();
    bool rsi_oversold = rsi_val < config::R5_RSI_OVERSOLD;
    bool rsi_overbought = rsi_val > config::R5_RSI_OVERBOUGHT;
    if (!rsi_oversold && !rsi_overbought) return;

    // Validação 2: Agressão no T&T > 300 contratos
    if (std::abs(ev.net_aggression) < config::R5_AGG_THRESHOLD) return;

    // Validação 3: Escoras >= 500 no DOM (reutiliza dados da R2)
    double check_price = near_200 ? ma200 : ma550;
    if (!dom_.has_wall_near(check_price, config::R5_MA_PROXIMITY_POINTS,
                           config::R5_WALL_THRESHOLD)) return;

    // Todas as validações passaram → Sinal 3.12
    Alert a;
    a.rule = Rule::R5;
    a.price = ev.price;
    a.ticker = ev.ticker;
    a.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();

    if (rsi_oversold) {
        a.direction = Direction::Buy;
        a.label = "Sinal 3.12: Convicção Alta — Exaustão Vendedora";
    } else {
        a.direction = Direction::Sell;
        a.label = "Sinal 3.12: Convicção Alta — Exaustão Compradora";
    }

    a.conviction = Conviction::High;
    a.data["rsi"] = rsi_val;
    a.data["ma200"] = ma200;
    a.data["ma550"] = ma550;
    a.data["near_ma200"] = near_200;
    a.data["near_ma550"] = near_550;
    a.data["renko_bricks"] = static_cast<int>(renko_closes_.size());
    a.data["renko_size"] = RENKO_SIZE;
    a.data["net_aggression"] = ev.net_aggression;
    a.data["price"] = ev.price;

    alert_bus_.push(std::move(a));
}

} // namespace rules
