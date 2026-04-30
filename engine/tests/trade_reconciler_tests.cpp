#include "trade_reconciler.h"

#include <cassert>
#include <cstddef>
#include <iostream>

// Mantido alinhado a TradeReconciler::kMaxSeen em trade_reconciler.h
constexpr std::size_t kExpectedMaxSeen = 100000;

namespace {

event_bus::TradeEvent make_ev(int64_t epoch_ms) {
    event_bus::TradeEvent ev;
    ev.ticker = "WIN";
    ev.bolsa = "B";
    ev.trade_date = "2026-04-26";
    ev.price = 100000.0;
    ev.qty = 1;
    ev.buy_agent = 1;
    ev.sell_agent = 2;
    ev.trade_type = 1;
    ev.trade_number = 0;
    ev.trade_epoch_ms = epoch_ms;
    ev.source = event_bus::TradeSource::Realtime;
    return ev;
}

void test_seen_bounded_after_many_unique() {
    TradeReconciler r;
    const size_t n = kExpectedMaxSeen + 500;
    for (size_t i = 0; i < n; ++i) {
        const auto res = r.apply(make_ev(static_cast<int64_t>(i)));
        assert(res.accepted);
        assert(!res.is_duplicate);
    }
    assert(r.seen_size() == kExpectedMaxSeen);
}

void test_after_eviction_same_key_is_accepted_again() {
    TradeReconciler r;
    for (int64_t i = 0; i < static_cast<int64_t>(kExpectedMaxSeen); ++i) {
        (void)r.apply(make_ev(i));
    }
    assert(r.seen_size() == kExpectedMaxSeen);
    auto dup = r.apply(make_ev(0));
    assert(dup.is_duplicate);
    (void)r.apply(make_ev(static_cast<int64_t>(kExpectedMaxSeen) + 9999));
    assert(r.seen_size() == kExpectedMaxSeen);
    auto again = r.apply(make_ev(0));
    assert(again.accepted);
    assert(!again.is_duplicate);
}

} // namespace

int main() {
    test_seen_bounded_after_many_unique();
    test_after_eviction_same_key_is_accepted_again();
    std::cout << "trade_reconciler_tests passed\n";
    return 0;
}
