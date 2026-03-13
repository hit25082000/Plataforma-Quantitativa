#include "rule1_aggression.h"
#include "../config.h"
#include <chrono>
#include <cmath>

namespace rules {

Rule1Aggression::Rule1Aggression(alert_bus::AlertBus& ab,
                                 const dom_snapshot::DOMSnapshotEngine& dom,
                                 const AgentRanking& ranking)
    : RuleBase(ab), dom_(dom), ranking_(ranking)
{}

void Rule1Aggression::on_daily(const DailyInfoEvent& ev) {
    day_high_ = ev.high;
    day_low_  = ev.low;
}

void Rule1Aggression::on_trade(const TradeEvent& ev) {
    int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();

    // Atualizar high/low a partir dos trades tambem (fallback caso DailyCallback nao chegue)
    if (ev.price > day_high_ && day_high_ > 0) {
        // O preço acabou de ultrapassar a máxima - possivel breakout
    }
    if (ev.price < day_low_ && day_low_ < 1e18) {
        // O preço acabou de ultrapassar a mínima - possivel breakout
    }

    switch (state_) {
        case State::IDLE: {
            // Gatilho: preço ultrapassa a Máxima do dia
            if (day_high_ > 0 && ev.price >= day_high_) {
                // Filtro 1: DOM ralo nas 10 linhas acima
                if (validate_dom_ralo(true, ev.price)) {
                    state_ = State::BREAKOUT_HIGH;
                    breakout_price_ = ev.price;
                    breakout_ts_ = now_ms;
                    opposite_agg_accum_ = 0;
                    breakout_top_agents_ = ranking_.top_buyers(5);
                }
                // Atualizar high para o próximo breakout
                day_high_ = ev.price;
            }
            // Gatilho: preço ultrapassa a Mínima do dia
            else if (day_low_ < 1e18 && ev.price <= day_low_) {
                // Filtro 1: DOM ralo nas 10 linhas abaixo
                if (validate_dom_ralo(false, ev.price)) {
                    state_ = State::BREAKOUT_LOW;
                    breakout_price_ = ev.price;
                    breakout_ts_ = now_ms;
                    opposite_agg_accum_ = 0;
                    breakout_top_agents_ = ranking_.top_sellers(5);
                }
                // Atualizar low para o próximo breakout
                day_low_ = ev.price;
            }
            break;
        }

        case State::BREAKOUT_HIGH: {
            // Timeout: se passou tempo demais sem confirmação, resetar
            if (now_ms - breakout_ts_ > config::R1_CONFIRM_WINDOW_MS) {
                reset_state();
                break;
            }

            // Tiro de Confirmação: agressão de VENDA após rompimento de topo
            if (ev.trade_type == 3) { // SELL_AGGRESSION
                opposite_agg_accum_ += ev.qty;

                // Filtro 2: exaustão dos top 4 compradores
                // Filtro 3: agressão oposta acumulada suficiente
                if (validate_agent_exhaustion() &&
                    opposite_agg_accum_ >= config::R1_CONFIRM_AGG_THRESHOLD) {
                    fire_alert(ev, true);
                    reset_state();
                }
            }
            break;
        }

        case State::BREAKOUT_LOW: {
            if (now_ms - breakout_ts_ > config::R1_CONFIRM_WINDOW_MS) {
                reset_state();
                break;
            }

            // Tiro de Confirmação: agressão de COMPRA após rompimento de fundo
            if (ev.trade_type == 2) { // BUY_AGGRESSION
                opposite_agg_accum_ += ev.qty;

                if (validate_agent_exhaustion() &&
                    opposite_agg_accum_ >= config::R1_CONFIRM_AGG_THRESHOLD) {
                    fire_alert(ev, false);
                    reset_state();
                }
            }
            break;
        }
    }
}

bool Rule1Aggression::validate_dom_ralo(bool is_high_breakout, double price) const {
    if (is_high_breakout) {
        // Somar qty das 10 linhas ASK acima do preço de rompimento
        int64_t ask_depth = dom_.sum_ask_depth(price, config::R1_DOM_DEPTH_LEVELS);
        return ask_depth < config::R1_DOM_RALO_THRESHOLD;
    } else {
        // Somar qty das 10 linhas BID abaixo do preço de rompimento
        int64_t bid_depth = dom_.sum_bid_depth(price, config::R1_DOM_DEPTH_LEVELS);
        return bid_depth < config::R1_DOM_RALO_THRESHOLD;
    }
}

bool Rule1Aggression::validate_agent_exhaustion() const {
    // Verificar se os top 4 agentes que estavam puxando o breakout
    // pararam de agredir (delta de saldo ~ 0 na janela recente)
    for (const auto& [agent_id, _qty] : breakout_top_agents_) {
        int64_t delta = ranking_.agent_delta(agent_id, config::R1_AGENT_DELTA_WINDOW_MS);
        // Se algum dos top 4 ainda está agredindo fortemente, não confirma exaustão
        if (std::abs(delta) > config::R1_CONFIRM_AGG_THRESHOLD / 2) {
            return false;
        }
    }
    return !breakout_top_agents_.empty();
}

void Rule1Aggression::fire_alert(const TradeEvent& ev, bool is_high) {
    Alert a;
    a.rule = Rule::R1;
    a.direction = is_high ? Direction::Sell : Direction::Buy;
    a.conviction = Conviction::High;
    a.price = ev.price;
    a.ticker = ev.ticker;
    a.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();

    if (is_high) {
        a.label = "Armadilha / Falso Rompimento de Topo";
    } else {
        a.label = "Armadilha / Falso Rompimento de Fundo";
    }

    a.data["breakout_price"] = breakout_price_;
    a.data["opposite_aggression"] = opposite_agg_accum_;
    a.data["price"] = ev.price;
    a.data["day_high"] = day_high_;
    a.data["day_low"] = day_low_;

    alert_bus_.push(std::move(a));
}

void Rule1Aggression::reset_state() {
    state_ = State::IDLE;
    breakout_price_ = 0;
    breakout_ts_ = 0;
    opposite_agg_accum_ = 0;
    breakout_top_agents_.clear();
}

} // namespace rules
