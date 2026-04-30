#include "hft_tuning.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <mutex>
#include <numeric>
#include <string>
#include <vector>
#if defined(_M_X64) || defined(_M_IX86) || defined(__x86_64__) || defined(__i386__)
#include <immintrin.h>
#endif

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace hft_tuning {

namespace {

enum class QpcMetricId : size_t {
    ProfitCallbackInterval = 0,
    PublisherLoopInterval = 1,
    Count = 2
};

bool read_env_bool(const char* name, bool default_value) {
    const char* v = std::getenv(name);
    if (!v || !*v) return default_value;
    std::string raw(v);
    for (char& c : raw) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (raw == "1" || raw == "true" || raw == "yes" || raw == "on") return true;
    if (raw == "0" || raw == "false" || raw == "no" || raw == "off") return false;
    return default_value;
}

int read_env_int(const char* name, int default_value) {
    const char* v = std::getenv(name);
    if (!v || !*v) return default_value;
    try {
        return std::stoi(std::string(v));
    } catch (...) {
        return default_value;
    }
}

uint64_t read_env_u64(const char* name, uint64_t default_value) {
    const char* v = std::getenv(name);
    if (!v || !*v) return default_value;
    try {
        unsigned long long x = std::stoull(std::string(v));
        return static_cast<uint64_t>(x);
    } catch (...) {
        return default_value;
    }
}

#ifdef _WIN32
enum class CoreIndexMode {
    Logical = 0,
    Physical = 1
};

CoreIndexMode read_core_index_mode() {
    const char* raw = std::getenv("HFT_CORE_INDEX_MODE");
    if (!raw || !*raw) return CoreIndexMode::Physical;
    std::string value(raw);
    for (char& c : value) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (value == "logical") return CoreIndexMode::Logical;
    if (value == "physical") return CoreIndexMode::Physical;
    return CoreIndexMode::Physical;
}

unsigned int active_cpu_count() {
    unsigned int n = GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
    if (n > 0) return n;
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    return info.dwNumberOfProcessors > 0 ? info.dwNumberOfProcessors : 1U;
}

int least_significant_set_bit_index(KAFFINITY mask) {
    if (mask == 0) return -1;
    int idx = 0;
    while ((mask & static_cast<KAFFINITY>(1)) == 0) {
        mask >>= 1;
        ++idx;
    }
    return idx;
}

const std::vector<int>& physical_core_logical_indices() {
    static std::vector<int> indices;
    static std::once_flag once;
    std::call_once(once, []() {
        DWORD required = 0;
        const BOOL first = GetLogicalProcessorInformationEx(RelationProcessorCore, nullptr, &required);
        if (first != FALSE || required == 0 || GetLastError() != ERROR_INSUFFICIENT_BUFFER) {
            return;
        }
        std::vector<unsigned char> raw(static_cast<size_t>(required), 0);
        auto* buffer = reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(raw.data());
        if (!GetLogicalProcessorInformationEx(RelationProcessorCore, buffer, &required)) {
            return;
        }

        size_t offset = 0;
        while (offset + sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX) <= required) {
            auto* info = reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(raw.data() + offset);
            if (info->Size == 0 || offset + info->Size > required) break;
            if (info->Relationship == RelationProcessorCore) {
                const WORD group_count = info->Processor.GroupCount;
                for (WORD g = 0; g < group_count; ++g) {
                    const GROUP_AFFINITY& gm = info->Processor.GroupMask[g];
                    if (gm.Group != 0) continue;
                    const int logical = least_significant_set_bit_index(gm.Mask);
                    if (logical < 0) continue;
                    if (std::find(indices.begin(), indices.end(), logical) == indices.end()) {
                        indices.push_back(logical);
                    }
                }
            }
            offset += info->Size;
        }
        std::sort(indices.begin(), indices.end());
    });
    return indices;
}

int resolve_logical_core(int core, const char* role, bool* used_physical_mode) {
    if (used_physical_mode) *used_physical_mode = false;
    if (core < 0) return -1;

    if (read_core_index_mode() != CoreIndexMode::Physical) {
        return core;
    }

    const auto& physical = physical_core_logical_indices();
    if (physical.empty()) {
        std::cerr << "[HFT] Physical-core map unavailable for " << role
                  << "; falling back to logical index mode." << std::endl;
        return core;
    }
    if (core >= static_cast<int>(physical.size())) {
        std::cerr << "[HFT] Skip pinning " << role << ": physical core index " << core
                  << " unavailable (physical_cores=" << physical.size() << ")" << std::endl;
        return -1;
    }
    if (used_physical_mode) *used_physical_mode = true;
    return physical[static_cast<size_t>(core)];
}
#endif

struct QpcMetricSamples {
    std::vector<uint64_t> values_ns;
};

struct QpcDiagState {
    bool enabled{false};
    uint64_t sample_every{1};
    uint64_t max_samples{1'000'000};
    int64_t freq{0};
    std::array<QpcMetricSamples, static_cast<size_t>(QpcMetricId::Count)> metrics{};
    std::mutex metrics_mutex;
    bool dumped{false};
};

const char* metric_name(QpcMetricId metric) {
    switch (metric) {
        case QpcMetricId::ProfitCallbackInterval:
            return "profit_callback_interval";
        case QpcMetricId::PublisherLoopInterval:
            return "publisher_loop_interval";
        case QpcMetricId::Count:
        default:
            return "unknown";
    }
}

QpcDiagState& qpc_state() {
    static QpcDiagState state;
    return state;
}

void ensure_qpc_initialized() {
    QpcDiagState& state = qpc_state();
    static std::once_flag init_once;
    std::call_once(init_once, [&state]() {
        state.enabled = read_env_bool("HFT_QPC_DIAG", false);
        if (!state.enabled) return;

#ifdef _WIN32
        LARGE_INTEGER fq{};
        if (!QueryPerformanceFrequency(&fq) || fq.QuadPart <= 0) {
            state.enabled = false;
            return;
        }
        state.freq = fq.QuadPart;
        state.sample_every = std::max<uint64_t>(1, read_env_u64("HFT_QPC_SAMPLE_EVERY", 1));
        state.max_samples = std::max<uint64_t>(1, read_env_u64("HFT_QPC_MAX_SAMPLES", 1'000'000));
        const size_t reserve_n = static_cast<size_t>(
            std::min<uint64_t>(state.max_samples, static_cast<uint64_t>(std::numeric_limits<size_t>::max() / 2)));
        for (auto& metric : state.metrics) {
            metric.values_ns.reserve(reserve_n);
        }
        std::cerr << "[HFT] QPC diagnostics enabled sample_every=" << state.sample_every
                  << " max_samples=" << state.max_samples << std::endl;
#else
        state.enabled = false;
#endif
    });
}

uint64_t percentile_ns(const std::vector<uint64_t>& sorted_values, double p) {
    if (sorted_values.empty()) return 0;
    if (sorted_values.size() == 1) return sorted_values[0];
    const double idx = (static_cast<double>(sorted_values.size()) - 1.0) * p;
    const size_t lo = static_cast<size_t>(idx);
    const size_t hi = std::min(lo + 1, sorted_values.size() - 1);
    const double w = idx - static_cast<double>(lo);
    return static_cast<uint64_t>(
        static_cast<double>(sorted_values[lo]) * (1.0 - w) + static_cast<double>(sorted_values[hi]) * w);
}

#ifdef _WIN32
void record_qpc_interval_tick(QpcMetricId metric) {
    ensure_qpc_initialized();
    QpcDiagState& state = qpc_state();
    if (!state.enabled || state.freq <= 0) return;

    constexpr size_t kMetricCount = static_cast<size_t>(QpcMetricId::Count);
    const size_t metric_idx = static_cast<size_t>(metric);
    if (metric_idx >= kMetricCount) return;

    thread_local std::array<uint64_t, kMetricCount> local_counters{0, 0};
    thread_local std::array<int64_t, kMetricCount> local_last_ticks{0, 0};

    local_counters[metric_idx] += 1;
    if ((local_counters[metric_idx] % state.sample_every) != 0) return;

    LARGE_INTEGER now_qpc{};
    QueryPerformanceCounter(&now_qpc);
    const int64_t now_ticks = now_qpc.QuadPart;
    const int64_t prev_ticks = local_last_ticks[metric_idx];
    local_last_ticks[metric_idx] = now_ticks;
    if (prev_ticks <= 0 || now_ticks <= prev_ticks) return;

    const uint64_t delta_ticks = static_cast<uint64_t>(now_ticks - prev_ticks);
    const uint64_t ns = static_cast<uint64_t>(
        (static_cast<long double>(delta_ticks) * 1'000'000'000.0L) / static_cast<long double>(state.freq));
    std::lock_guard<std::mutex> lock(state.metrics_mutex);
    auto& values = state.metrics[metric_idx].values_ns;
    if (values.size() < static_cast<size_t>(state.max_samples)) {
        values.push_back(ns);
    }
}
#endif

} // namespace

bool cpu_pinning_enabled() {
    return read_env_bool("HFT_CPU_PINNING", false);
}

bool prefetch_enabled() {
    static bool enabled = read_env_bool("HFT_PREFETCH", true);
    return enabled;
}

int read_core_env(const char* env_name, int default_core) {
    return read_env_int(env_name, default_core);
}

void apply_process_priority() {
    if (!cpu_pinning_enabled()) return;
    if (!read_env_bool("HFT_PROCESS_PRIORITY", true)) return;

#ifdef _WIN32
    HANDLE process = GetCurrentProcess();
    if (!SetPriorityClass(process, HIGH_PRIORITY_CLASS)) {
        std::cerr << "[HFT] Failed to set HIGH_PRIORITY_CLASS (err=" << GetLastError() << ")" << std::endl;
        return;
    }
    if (!SetProcessPriorityBoost(process, TRUE)) {
        std::cerr << "[HFT] Failed to disable process priority boost (err=" << GetLastError() << ")" << std::endl;
    }
    std::cerr << "[HFT] Process priority set to HIGH_PRIORITY_CLASS (priority boost disabled)." << std::endl;
#endif
}

void pin_current_thread_to_core(int core, const char* role) {
    if (!cpu_pinning_enabled()) return;
    if (core < 0) return;

#ifdef _WIN32
    bool used_physical_mode = false;
    const int logical_core = resolve_logical_core(core, role, &used_physical_mode);
    if (logical_core < 0) return;

    const unsigned int cpu_count = active_cpu_count();
    if (static_cast<unsigned int>(logical_core) >= cpu_count) {
        std::cerr << "[HFT] Skip pinning " << role << ": core " << logical_core
                  << " unavailable (cpu_count=" << cpu_count << ")" << std::endl;
        return;
    }
    constexpr int kMaskBits = static_cast<int>(sizeof(DWORD_PTR) * 8);
    if (logical_core >= kMaskBits) {
        std::cerr << "[HFT] Skip pinning " << role << ": core " << logical_core
                  << " exceeds affinity mask width (" << kMaskBits << ")" << std::endl;
        return;
    }

    const DWORD_PTR mask = (static_cast<DWORD_PTR>(1) << logical_core);
    const DWORD_PTR prev = SetThreadAffinityMask(GetCurrentThread(), mask);
    if (prev == 0) {
        std::cerr << "[HFT] Failed to pin " << role << " to core " << logical_core
                  << " (err=" << GetLastError() << ")" << std::endl;
        return;
    }
    if (used_physical_mode) {
        std::cerr << "[HFT] Pinned " << role << " thread to physical_core_index " << core
                  << " (logical_core=" << logical_core << ")" << std::endl;
    } else {
        std::cerr << "[HFT] Pinned " << role << " thread to core " << logical_core << std::endl;
    }
#else
    (void)role;
#endif
}

void maybe_pin_current_thread_from_env(const char* env_name, int default_core, const char* role) {
    const int core = read_core_env(env_name, default_core);
    pin_current_thread_to_core(core, role);
}

void prefetch_read(const void* ptr) {
    if (!prefetch_enabled() || ptr == nullptr) return;
#if defined(_M_X64) || defined(_M_IX86) || defined(__x86_64__) || defined(__i386__)
    _mm_prefetch(static_cast<const char*>(ptr), _MM_HINT_T0);
#else
    (void)ptr;
#endif
}

void prefetch_write(const void* ptr) {
    if (!prefetch_enabled() || ptr == nullptr) return;
#if defined(_M_X64) || defined(_M_IX86) || defined(__x86_64__) || defined(__i386__)
    _mm_prefetch(static_cast<const char*>(ptr), _MM_HINT_T0);
#else
    (void)ptr;
#endif
}

void record_profit_callback_tick() {
#ifdef _WIN32
    record_qpc_interval_tick(QpcMetricId::ProfitCallbackInterval);
#endif
}

void record_publisher_tick() {
#ifdef _WIN32
    record_qpc_interval_tick(QpcMetricId::PublisherLoopInterval);
#endif
}

void dump_qpc_stats() {
    ensure_qpc_initialized();
    QpcDiagState& state = qpc_state();
    if (!state.enabled || state.freq <= 0 || state.dumped) return;

    std::array<std::vector<uint64_t>, static_cast<size_t>(QpcMetricId::Count)> local_copy;
    {
        std::lock_guard<std::mutex> lock(state.metrics_mutex);
        for (size_t i = 0; i < local_copy.size(); ++i) {
            local_copy[i] = state.metrics[i].values_ns;
        }
    }

    for (size_t i = 0; i < local_copy.size(); ++i) {
        auto& values = local_copy[i];
        if (values.empty()) continue;
        std::sort(values.begin(), values.end());
        const size_t n = values.size();
        const uint64_t p50 = percentile_ns(values, 0.50);
        const uint64_t p95 = percentile_ns(values, 0.95);
        const uint64_t p99 = percentile_ns(values, 0.99);
        const uint64_t p999 = percentile_ns(values, 0.999);
        const uint64_t max_v = values.back();
        const long double sum = std::accumulate(values.begin(), values.end(), 0.0L);
        const long double mean = sum / static_cast<long double>(n);
        std::cerr << "[HFT] QPC " << metric_name(static_cast<QpcMetricId>(i))
                  << " ns: count=" << n << " p50=" << p50
                  << " p95=" << p95 << " p99=" << p99
                  << " p999=" << p999 << " max=" << max_v
                  << " mean=" << static_cast<double>(mean) << std::endl;
    }
    state.dumped = true;
}

} // namespace hft_tuning
