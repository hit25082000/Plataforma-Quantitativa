#pragma once

#include <deque>
#include <cmath>

namespace rules {

// RSI Wilder, 14 períodos (header-only)
class RsiCalculator {
public:
    explicit RsiCalculator(int period = 14) : period_(period) {}

    void push_price(double price) {
        prices_.push_back(price);
        if (static_cast<int>(prices_.size()) > period_ + 1) {
            prices_.pop_front();
        }
    }

    double compute() const {
        if (static_cast<int>(prices_.size()) < period_ + 1) return 50.0;

        double avg_gain = 0;
        double avg_loss = 0;

        for (int i = 1; i <= period_; ++i) {
            double change = prices_[i] - prices_[i - 1];
            if (change > 0) {
                avg_gain += change;
            } else {
                avg_loss += -change;
            }
        }

        avg_gain /= period_;
        avg_loss /= period_;

        if (avg_loss < 1e-10) return 100.0;
        double rs = avg_gain / avg_loss;
        return 100.0 - (100.0 / (1.0 + rs));
    }

    bool ready() const {
        return static_cast<int>(prices_.size()) >= period_ + 1;
    }

private:
    int period_;
    std::deque<double> prices_;
};

} // namespace rules
