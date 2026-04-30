#include "volume_profile.h"
#include "profit_types.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cctype>
#include <ctime>
#include <iomanip>
#include <iterator>
#include <sstream>

namespace volume_profile {

namespace {
int64_t system_now_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
}

std::tm zero_tm() {
    std::tm tm{};
    tm.tm_isdst = -1;
    return tm;
}

std::tm local_tm(std::time_t value) {
    std::tm out{};
#ifdef _WIN32
    localtime_s(&out, &value);
#else
    out = *std::localtime(&value);
#endif
    return out;
}

std::tm add_days(std::tm value, int delta_days) {
    value.tm_mday += delta_days;
    value.tm_isdst = -1;
    std::mktime(&value);
    return value;
}

void trim_in_place(std::string& s) {
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.front()))) {
        s.erase(s.begin());
    }
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.back()))) {
        s.pop_back();
    }
}
} // namespace

VolumeProfileEngine::VolumeProfileEngine(std::string ticker, int64_t tick_size)
    : ticker_(std::move(ticker))
    , tick_size_(tick_size > 0 ? tick_size : 5) {}

void VolumeProfileEngine::set_ticker(std::string ticker) {
    ticker_ = std::move(ticker);
    reset();
}

void VolumeProfileEngine::set_period(Period period) {
    if (period_ == period) return;
    period_ = period;
    reset();
}

void VolumeProfileEngine::reset() {
    levels_.clear();
    last_period_key_.clear();
}

std::string VolumeProfileEngine::normalize_trade_date(const std::string& trade_date) {
    std::string out;
    out.reserve(trade_date.size());
    for (char c : trade_date) {
        if (c == '\r' || c == '\n' || c == '\t') continue;
        out.push_back(c);
    }
    trim_in_place(out);
    return out;
}

bool VolumeProfileEngine::parse_trade_date(const std::string& trade_date, std::tm& out_tm) {
    const std::string normalized = normalize_trade_date(trade_date);
    if (normalized.empty()) return false;

    auto try_parse = [&](const char* fmt) -> bool {
        std::tm candidate = zero_tm();
        std::istringstream iss(normalized);
        iss >> std::get_time(&candidate, fmt);
        if (iss.fail()) return false;
        out_tm = candidate;
        return true;
    };

    return try_parse("%Y-%m-%d") || try_parse("%d/%m/%Y") || try_parse("%d-%m-%Y");
}

std::string VolumeProfileEngine::format_tm_date(const std::tm& tm_value) {
    std::tm copy = tm_value;
    std::ostringstream oss;
    oss << std::put_time(&copy, "%Y-%m-%d");
    return oss.str();
}

std::string VolumeProfileEngine::period_name() const {
    switch (period_) {
    case Period::Week: return "week";
    case Period::Manual: return "manual";
    case Period::Day:
    default:
        return "day";
    }
}

std::string VolumeProfileEngine::period_key_for_trade_date(const std::string& trade_date) const {
    const std::string normalized = normalize_trade_date(trade_date);
    if (normalized.empty()) return {};
    if (period_ == Period::Manual) return "manual";

    std::tm tm_value = zero_tm();
    if (!parse_trade_date(normalized, tm_value)) {
        return normalized;
    }

    std::time_t raw = std::mktime(&tm_value);
    if (raw == static_cast<std::time_t>(-1)) {
        return normalized;
    }

    if (period_ == Period::Day) {
        return format_tm_date(local_tm(raw));
    }

    std::tm local = local_tm(raw);
    const int wday = local.tm_wday; // 0 = Sunday
    const int days_to_monday = (wday == 0) ? -6 : (1 - wday);
    std::tm monday = add_days(local, days_to_monday);
    monday.tm_hour = 0;
    monday.tm_min = 0;
    monday.tm_sec = 0;
    monday.tm_isdst = -1;
    return format_tm_date(monday);
}

void VolumeProfileEngine::maybe_reset_for_trade_date(const std::string& trade_date) {
    if (period_ == Period::Manual) return;
    const std::string key = period_key_for_trade_date(trade_date);
    if (key.empty()) return;
    if (key != last_period_key_) {
        levels_.clear();
        last_period_key_ = key;
    }
}

int64_t VolumeProfileEngine::normalize_price(double price) const {
    if (!std::isfinite(price)) return 0;
    const double tick = static_cast<double>(tick_size_);
    return static_cast<int64_t>(std::llround(price / tick) * tick_size_);
}

std::optional<nlohmann::json> VolumeProfileEngine::on_trade(const event_bus::TradeEvent& ev) {
    if (!ticker_.empty() && ev.ticker != ticker_) return std::nullopt;
    if (ev.qty <= 0) return std::nullopt;

    maybe_reset_for_trade_date(ev.trade_date);

    const int64_t level_price = normalize_price(ev.price);
    if (level_price == 0 && ev.price != 0.0) return std::nullopt;

    LevelAcc& acc = levels_[level_price];
    if (ev.trade_type == profit::TRADE_TYPE_SELL_AGGRESSION) {
        acc.ask_vol += static_cast<uint64_t>(ev.qty);
    } else {
        acc.bid_vol += static_cast<uint64_t>(ev.qty);
    }

    return build_payload();
}

std::vector<LevelSnapshot> VolumeProfileEngine::build_levels(uint64_t max_total) const {
    std::vector<LevelSnapshot> out;
    out.reserve(levels_.size());
    for (const auto& [price, acc] : levels_) {
        const uint64_t total = acc.total();
        LevelSnapshot snap;
        snap.price = price;
        snap.total_vol = total;
        snap.bid_vol = acc.bid_vol;
        snap.ask_vol = acc.ask_vol;
        snap.pct_of_max = max_total > 0
            ? static_cast<double>(total) / static_cast<double>(max_total)
            : 0.0;
        out.push_back(snap);
    }
    return out;
}

std::pair<int64_t, int64_t> VolumeProfileEngine::compute_value_area() const {
    if (levels_.empty()) return {0, 0};

    std::vector<std::pair<int64_t, uint64_t>> ordered;
    ordered.reserve(levels_.size());
    uint64_t total_volume = 0;
    for (const auto& [price, acc] : levels_) {
        const uint64_t total = acc.total();
        ordered.emplace_back(price, total);
        total_volume += total;
    }

    auto poc_it = std::max_element(
        ordered.begin(),
        ordered.end(),
        [](const auto& a, const auto& b) {
            if (a.second != b.second) return a.second < b.second;
            return a.first < b.first;
        });
    if (poc_it == ordered.end()) return {0, 0};

    const size_t poc_index = static_cast<size_t>(std::distance(ordered.begin(), poc_it));
    size_t left = poc_index;
    size_t right = poc_index;
    uint64_t selected = poc_it->second;
    const uint64_t target = static_cast<uint64_t>(std::ceil(static_cast<double>(total_volume) * 0.70));

    while (selected < target && (left > 0 || right + 1 < ordered.size())) {
        const uint64_t lower = left > 0 ? ordered[left - 1].second : 0;
        const uint64_t higher = right + 1 < ordered.size() ? ordered[right + 1].second : 0;

        if (higher > lower) {
            ++right;
            selected += higher;
            continue;
        }
        if (lower > higher) {
            --left;
            selected += lower;
            continue;
        }
        if (right + 1 < ordered.size()) {
            ++right;
            selected += higher;
            continue;
        }
        if (left > 0) {
            --left;
            selected += lower;
            continue;
        }
        break;
    }

    return {ordered[left].first, ordered[right].first};
}

nlohmann::json VolumeProfileEngine::build_payload() const {
    uint64_t total_volume = 0;
    uint64_t max_total = 0;
    int64_t poc = 0;
    uint64_t poc_total = 0;
    bool has_levels = false;

    for (const auto& [price, acc] : levels_) {
        const uint64_t total = acc.total();
        total_volume += total;
        if (!has_levels || total > poc_total || (total == poc_total && price > poc)) {
            has_levels = true;
            poc = price;
            poc_total = total;
        }
        max_total = std::max(max_total, total);
    }

    const auto [val, vah] = compute_value_area();
    nlohmann::json payload = {
        {"topic", "market"},
        {"type", "volume_profile"},
        {"ticker", ticker_},
        {"period", period_name()},
        {"timestamp", system_now_ms()},
        {"price_step", tick_size_},
        {"total_vol", total_volume},
        {"poc", poc},
        {"vah", vah},
        {"val", val},
        {"levels", nlohmann::json::array()},
    };

    for (const auto& lvl : build_levels(max_total)) {
        payload["levels"].push_back({
            {"price", lvl.price},
            {"total_vol", lvl.total_vol},
            {"bid_vol", lvl.bid_vol},
            {"ask_vol", lvl.ask_vol},
            {"pct_of_max", lvl.pct_of_max},
        });
    }

    return payload;
}

} // namespace volume_profile
