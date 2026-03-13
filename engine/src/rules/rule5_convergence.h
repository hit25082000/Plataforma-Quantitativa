#pragma once

#include "rule_base.h"
#include "rsi_calculator.h"
#include "../dom_snapshot.h"
#include "../config.h"
#include <deque>
#include <vector>

namespace rules {

class Rule5Convergence : public RuleBase {
public:
    Rule5Convergence(alert_bus::AlertBus& ab,
                     const dom_snapshot::DOMSnapshotEngine& dom);

    void on_trade(const TradeEvent& ev) override;
    std::string_view name() const override { return "Rule5Convergence"; }

private:
    const dom_snapshot::DOMSnapshotEngine& dom_;
    RsiCalculator rsi_;

    // --- Renko brick builder ---
    static constexpr double RENKO_SIZE = config::R5_RENKO_SIZE;  // pontos por brick
    double renko_ref_ = 0;           // preço de referência do brick atual
    bool   renko_initialized_ = false;

    // Closes de bricks Renko (cada brick fechado gera um close)
    std::deque<double> renko_closes_;

    double sma(int period) const;
    bool near_ma(double price, double ma_value) const;
};

} // namespace rules
