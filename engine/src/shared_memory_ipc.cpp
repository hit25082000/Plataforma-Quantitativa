#include "shared_memory_ipc.h"
#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <numeric>
#if defined(_M_X64) || defined(_M_IX86) || defined(__x86_64__) || defined(__i386__)
#include <immintrin.h>
#endif

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#ifndef FILE_MAP_LARGE_PAGES
#define FILE_MAP_LARGE_PAGES 0x20000000
#endif
#ifndef NUMA_NO_PREFERRED_NODE
#define NUMA_NO_PREFERRED_NODE static_cast<DWORD>(-1)
#endif
#endif

namespace shared_memory_ipc {

namespace {

int64_t system_epoch_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

bool read_env_bool_local(const char* name, bool default_value) {
    const char* v = std::getenv(name);
    if (!v || !*v) return default_value;
    std::string raw(v);
    for (char& c : raw) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (raw == "1" || raw == "true" || raw == "yes" || raw == "on") return true;
    if (raw == "0" || raw == "false" || raw == "no" || raw == "off") return false;
    return default_value;
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

int read_env_int(const char* name, int default_value) {
    const char* v = std::getenv(name);
    if (!v || !*v) return default_value;
    try {
        return std::stoi(std::string(v));
    } catch (...) {
        return default_value;
    }
}

uint16_t crc16_ccitt(const uint8_t* data, size_t len, uint16_t init = 0xFFFF) {
    if (!data || len == 0) return init;
    uint16_t crc = init;
    for (size_t i = 0; i < len; ++i) {
        crc ^= static_cast<uint16_t>(data[i]) << 8;
        for (int bit = 0; bit < 8; ++bit) {
            if ((crc & 0x8000U) != 0U) {
                crc = static_cast<uint16_t>((crc << 1U) ^ 0x1021U);
            } else {
                crc = static_cast<uint16_t>(crc << 1U);
            }
        }
    }
    return crc;
}

uint16_t compute_slot_crc16(const RingSlot& slot) {
    RingSlot copy = slot;
    copy.trade.reserved0 = 0;
    const auto* ptr = reinterpret_cast<const uint8_t*>(&copy.message_type);
    const size_t span = sizeof(copy.message_type) + sizeof(copy.payload_size) + sizeof(copy.trade);
    return crc16_ccitt(ptr, span, 0xFFFFU);
}

size_t align_up_size(size_t size, size_t align) {
    if (align == 0) return size;
    const size_t rem = size % align;
    if (rem == 0) return size;
    return size + (align - rem);
}

void copy_cstr(char* dst, size_t dst_size, const std::string& src) {
    if (!dst || dst_size == 0) return;
    std::memset(dst, 0, dst_size);
    if (src.empty()) return;
    const size_t max_copy = dst_size - 1;
    const size_t n = (src.size() < max_copy) ? src.size() : max_copy;
    std::memcpy(dst, src.data(), n);
}

#ifdef _WIN32
std::wstring utf8_to_wide(const std::string& text) {
    if (text.empty()) return L"";
    const int needed =
        MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, nullptr, 0);
    if (needed <= 0) return L"";
    std::wstring out(static_cast<size_t>(needed), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, out.data(), needed);
    if (!out.empty() && out.back() == L'\0') out.pop_back();
    return out;
}

size_t mapped_region_size(void* mapped) {
    if (!mapped) return 0;
    MEMORY_BASIC_INFORMATION mbi{};
    SIZE_T rc = VirtualQuery(mapped, &mbi, sizeof(mbi));
    if (rc == 0) return 0;
    return static_cast<size_t>(mbi.RegionSize);
}

using CreateFileMappingNumaWFn = HANDLE(WINAPI*)(HANDLE,
                                                 LPSECURITY_ATTRIBUTES,
                                                 DWORD,
                                                 DWORD,
                                                 DWORD,
                                                 LPCWSTR,
                                                 DWORD);

HANDLE create_file_mapping_windows(HANDLE file_handle,
                                   LPSECURITY_ATTRIBUTES sec_attr,
                                   DWORD protect,
                                   DWORD size_high,
                                   DWORD size_low,
                                   LPCWSTR name,
                                   DWORD preferred_numa_node,
                                   bool* used_numa) {
    if (used_numa) *used_numa = false;
    if (preferred_numa_node != NUMA_NO_PREFERRED_NODE) {
        HMODULE kernel32 = GetModuleHandleW(L"kernel32.dll");
        if (kernel32) {
            auto* fn = reinterpret_cast<CreateFileMappingNumaWFn>(
                GetProcAddress(kernel32, "CreateFileMappingNumaW"));
            if (fn) {
                HANDLE h = fn(file_handle, sec_attr, protect, size_high, size_low, name, preferred_numa_node);
                if (h) {
                    if (used_numa) *used_numa = true;
                    return h;
                }
            }
        }
    }
    return CreateFileMappingW(file_handle, sec_attr, protect, size_high, size_low, name);
}
#endif

} // namespace

std::string default_mapping_name() {
    const char* v = std::getenv("SHM_MAPPING_NAME");
    if (v && *v) return std::string(v);
    return "Local\\PQMarketDataV1";
}

size_t default_mapping_size_bytes() {
    const char* v = std::getenv("SHM_SIZE_MB");
    long long size_mb = 64;
    if (v && *v) {
        try {
            size_mb = std::stoll(std::string(v));
        } catch (...) {
            size_mb = 64;
        }
    }
    if (size_mb < 8) size_mb = 8;
    return static_cast<size_t>(size_mb) * 1024ULL * 1024ULL;
}

SharedMemoryRingWriter::SharedMemoryRingWriter(std::string mapping_name, size_t size_bytes)
    : mapping_name_(std::move(mapping_name)) {
    initialize(size_bytes);
}

SharedMemoryRingWriter::~SharedMemoryRingWriter() {
    dump_qpc_stats_if_any();
#ifdef _WIN32
    if (base_) {
        UnmapViewOfFile(base_);
        base_ = nullptr;
    }
    if (mapping_handle_) {
        CloseHandle(static_cast<HANDLE>(mapping_handle_));
        mapping_handle_ = nullptr;
    }
#endif
    header_ = nullptr;
    slots_ = nullptr;
}

bool SharedMemoryRingWriter::initialize(size_t size_bytes) {
#ifndef _WIN32
    (void)size_bytes;
    std::cerr << "[SHM] Shared memory writer is only enabled on Windows."
              << std::endl;
    return false;
#else
    if (size_bytes <= sizeof(RingHeader) + sizeof(RingSlot)) {
        std::cerr << "[SHM] Invalid mapping size: " << size_bytes << std::endl;
        return false;
    }
    const auto wide_name = utf8_to_wide(mapping_name_);
    if (wide_name.empty()) {
        std::cerr << "[SHM] Invalid mapping name." << std::endl;
        return false;
    }

    const bool prefer_large_pages = read_env_bool_local("SHM_LARGE_PAGES", false);
    const bool strict_large_pages = read_env_bool_local("SHM_LARGE_PAGES_STRICT", false);
    prefetch_next_slot_ = read_env_bool_local("SHM_PREFETCH_NEXT_SLOT", true);
    const int preferred_numa = read_env_int("SHM_NUMA_NODE", -1);
    const DWORD preferred_numa_node = preferred_numa >= 0
        ? static_cast<DWORD>(preferred_numa)
        : NUMA_NO_PREFERRED_NODE;
    numa_node_ = preferred_numa >= 0 ? preferred_numa : -1;

    size_t large_page_min = 0;
    size_t large_page_size_bytes = size_bytes;
    if (prefer_large_pages) {
        const SIZE_T min_large = GetLargePageMinimum();
        if (min_large == 0) {
            std::cerr << "[SHM] SHM_LARGE_PAGES requested but GetLargePageMinimum failed (err="
                      << GetLastError() << ")." << std::endl;
            if (strict_large_pages) return false;
        } else {
            large_page_min = static_cast<size_t>(min_large);
            large_page_size_bytes = align_up_size(size_bytes, large_page_min);
            if (large_page_size_bytes != size_bytes) {
                std::cerr << "[SHM] Aligning SHM size for large pages: requested="
                          << size_bytes << " aligned=" << large_page_size_bytes << std::endl;
            }
        }
    }

    struct MappingAttempt {
        bool large_pages;
        size_t size_bytes;
        DWORD protect;
        DWORD map_access;
    };

    std::vector<MappingAttempt> attempts;
    if (prefer_large_pages && large_page_min > 0) {
        attempts.push_back(
            MappingAttempt{true, large_page_size_bytes, PAGE_READWRITE | SEC_LARGE_PAGES, FILE_MAP_ALL_ACCESS | FILE_MAP_LARGE_PAGES});
        if (!strict_large_pages) {
            attempts.push_back(MappingAttempt{false, size_bytes, PAGE_READWRITE, FILE_MAP_ALL_ACCESS});
        }
    } else {
        attempts.push_back(MappingAttempt{false, size_bytes, PAGE_READWRITE, FILE_MAP_ALL_ACCESS});
    }

    HANDLE h = nullptr;
    std::uint8_t* mapped = nullptr;
    DWORD last_err = 0;
    bool used_numa_mapping = false;
    size_t mapped_requested_bytes = size_bytes;
    for (const auto& attempt : attempts) {
        const uint64_t size_u64 = static_cast<uint64_t>(attempt.size_bytes);
        const DWORD high = static_cast<DWORD>((size_u64 >> 32) & 0xFFFFFFFFULL);
        const DWORD low = static_cast<DWORD>(size_u64 & 0xFFFFFFFFULL);

        bool used_numa_for_attempt = false;
        h = create_file_mapping_windows(
            INVALID_HANDLE_VALUE,
            nullptr,
            attempt.protect,
            high,
            low,
            wide_name.c_str(),
            preferred_numa_node,
            &used_numa_for_attempt);
        if (!h) {
            last_err = GetLastError();
            continue;
        }

        mapped = static_cast<std::uint8_t*>(MapViewOfFile(h, attempt.map_access, 0, 0, 0));
        if (!mapped) {
            last_err = GetLastError();
            CloseHandle(h);
            h = nullptr;
            continue;
        }

        mapped_requested_bytes = attempt.size_bytes;
        large_pages_active_ = attempt.large_pages;
        used_numa_mapping = used_numa_for_attempt;
        break;
    }

    if (!h || !mapped) {
        std::cerr << "[SHM] Failed to create/map shared memory (err=" << last_err << ")" << std::endl;
        return false;
    }

    mapping_handle_ = h;
    base_ = mapped;
    header_ = reinterpret_cast<RingHeader*>(base_);
    slots_ = reinterpret_cast<RingSlot*>(base_ + sizeof(RingHeader));

    mapped_size_bytes_ = static_cast<uint64_t>(mapped_region_size(mapped));
    if (mapped_size_bytes_ == 0) {
        mapped_size_bytes_ = static_cast<uint64_t>(mapped_requested_bytes);
    }
    if (mapped_size_bytes_ <= sizeof(RingHeader) + sizeof(RingSlot)) {
        std::cerr << "[SHM] Mapped region too small: " << mapped_size_bytes_ << std::endl;
        UnmapViewOfFile(base_);
        CloseHandle(static_cast<HANDLE>(mapping_handle_));
        base_ = nullptr;
        mapping_handle_ = nullptr;
        header_ = nullptr;
        slots_ = nullptr;
        return false;
    }

    const bool must_init = header_->magic != kShmMagic ||
                           header_->version != kShmVersion ||
                           header_->slot_size != sizeof(RingSlot);
    if (must_init) {
        std::memset(base_, 0, static_cast<size_t>(mapped_size_bytes_));
        header_->magic = kShmMagic;
        header_->version = kShmVersion;
        header_->header_size = sizeof(RingHeader);
        header_->slot_size = sizeof(RingSlot);
        header_->capacity = static_cast<uint64_t>((mapped_size_bytes_ - sizeof(RingHeader)) / sizeof(RingSlot));
        header_->write_seq = 0;
        header_->dropped = 0;
        header_->created_epoch_ms = static_cast<uint64_t>(system_epoch_ms());
    }
    if (header_->capacity == 0) {
        std::cerr << "[SHM] Capacity is zero." << std::endl;
        return false;
    }

    std::cerr << "[SHM] Ready mapping=" << mapping_name_
              << " requested_size_bytes=" << size_bytes
              << " mapped_size_bytes=" << mapped_size_bytes_
              << " capacity=" << header_->capacity
              << " large_pages=" << (large_pages_active_ ? 1 : 0)
              << " numa_node=" << numa_node_
              << " numa_api_used=" << (used_numa_mapping ? 1 : 0)
              << " prefetch_next_slot=" << (prefetch_next_slot_ ? 1 : 0)
              << std::endl;

    qpc_diag_ = read_env_bool_local("SHM_QPC_DIAG", false);
    if (qpc_diag_) {
        LARGE_INTEGER fq{};
        if (QueryPerformanceFrequency(&fq) && fq.QuadPart > 0) {
            qpc_freq_ = fq.QuadPart;
            qpc_sample_every_ = std::max<uint64_t>(1, read_env_u64("SHM_QPC_SAMPLE_EVERY", 1));
            qpc_max_samples_ = read_env_u64("SHM_QPC_MAX_SAMPLES", 1'000'000);
            qpc_samples_ns_.reserve(static_cast<size_t>(std::min<uint64_t>(
                qpc_max_samples_, static_cast<uint64_t>(std::numeric_limits<size_t>::max() / 2))));
            std::cerr << "[SHM] QPC diagnostics enabled sample_every=" << qpc_sample_every_
                      << " max_samples=" << qpc_max_samples_ << std::endl;
        } else {
            qpc_diag_ = false;
        }
    }
    return true;
#endif
}

void SharedMemoryRingWriter::record_qpc_write_duration_ns(uint64_t ns) {
    if (!qpc_diag_) return;
    std::lock_guard<std::mutex> lock(qpc_mutex_);
    if (qpc_samples_ns_.size() < static_cast<size_t>(qpc_max_samples_)) {
        qpc_samples_ns_.push_back(ns);
    }
}

void SharedMemoryRingWriter::dump_qpc_stats_if_any() {
    if (!qpc_diag_ || qpc_freq_ <= 0) return;
    std::vector<uint64_t> copy;
    {
        std::lock_guard<std::mutex> lock(qpc_mutex_);
        copy.swap(qpc_samples_ns_);
    }
    if (copy.empty()) return;
    std::sort(copy.begin(), copy.end());
    const size_t n = copy.size();
    auto pct = [&](double p) -> uint64_t {
        if (n == 0) return 0;
        if (n == 1) return copy[0];
        const double idx = (static_cast<double>(n) - 1.0) * p;
        const size_t lo = static_cast<size_t>(idx);
        const size_t hi = std::min(lo + 1, n - 1);
        const double w = idx - static_cast<double>(lo);
        return static_cast<uint64_t>(
            static_cast<double>(copy[lo]) * (1.0 - w) + static_cast<double>(copy[hi]) * w);
    };
    const uint64_t p50 = pct(0.50);
    const uint64_t p95 = pct(0.95);
    const uint64_t p99 = pct(0.99);
    const uint64_t p999 = pct(0.999);
    const uint64_t max_v = copy.back();
    const double mean =
        static_cast<double>(std::accumulate(copy.begin(), copy.end(), 0ULL)) / static_cast<double>(n);
    std::cerr << "[SHM] QPC write_trade duration ns: count=" << n << " p50=" << p50 << " p95=" << p95
              << " p99=" << p99 << " p999=" << p999
              << " max=" << max_v << " mean=" << mean << std::endl;
    std::cerr << "[SHM] QPC write_trade duration us: p50=" << (static_cast<double>(p50) * 1e-3)
              << " p95=" << (static_cast<double>(p95) * 1e-3)
              << " p99=" << (static_cast<double>(p99) * 1e-3)
              << " p999=" << (static_cast<double>(p999) * 1e-3)
              << std::endl;
}

bool SharedMemoryRingWriter::write_trade(const event_bus::TradeEvent& trade, double vwap, int64_t net_aggression) {
    if (!header_ || !slots_) return false;
#ifdef _WIN32
    LARGE_INTEGER t0{};
    bool measure_qpc = false;
    if (qpc_diag_ && qpc_freq_ > 0) {
        thread_local uint64_t qpc_write_counter = 0;
        ++qpc_write_counter;
        if ((qpc_write_counter % qpc_sample_every_) == 0) {
            QueryPerformanceCounter(&t0);
            measure_qpc = true;
        }
    }
#endif
    const uint64_t next_seq = header_->write_seq + 1;
    const uint64_t idx = (next_seq - 1) % header_->capacity;
#if defined(_M_X64) || defined(_M_IX86) || defined(__x86_64__) || defined(__i386__)
    if (prefetch_next_slot_ && header_->capacity > 1) {
        const uint64_t next_idx = next_seq % header_->capacity;
        _mm_prefetch(reinterpret_cast<const char*>(&slots_[next_idx]), _MM_HINT_T0);
    }
#endif
    RingSlot& slot = slots_[idx];

    slot.committed_seq = 0;
    slot.message_type = kMessageTypeTrade;
    slot.payload_size = sizeof(TradePayload);

    TradePayload payload{};
    copy_cstr(payload.ticker, sizeof(payload.ticker), trade.ticker);
    copy_cstr(payload.trade_date, sizeof(payload.trade_date), trade.trade_date);
    payload.price = trade.price;
    payload.qty = trade.qty;
    payload.buy_agent = trade.buy_agent;
    payload.sell_agent = trade.sell_agent;
    payload.trade_type = trade.trade_type;
    payload.trade_source = static_cast<uint8_t>(trade.source == event_bus::TradeSource::History ? 1 : 0);
    payload.reserved0 = 0;
    payload.trade_number = trade.trade_number;
    payload.trade_flags = trade.trade_flags;
    payload.trade_epoch_ms = trade.trade_epoch_ms;
    payload.vwap = vwap;
    payload.net_aggression = net_aggression;
    slot.trade = payload;
    slot.trade.reserved0 = compute_slot_crc16(slot);

#ifdef _WIN32
    MemoryBarrier();
#endif
    slot.committed_seq = next_seq;
#ifdef _WIN32
    MemoryBarrier();
#endif
    header_->write_seq = next_seq;
    if (next_seq > header_->capacity) {
        header_->dropped = next_seq - header_->capacity;
    }
#ifdef _WIN32
    if (measure_qpc && qpc_freq_ > 0) {
        LARGE_INTEGER t1{};
        QueryPerformanceCounter(&t1);
        const int64_t ticks = t1.QuadPart - t0.QuadPart;
        const double sec = static_cast<double>(ticks) / static_cast<double>(qpc_freq_);
        const auto ns = static_cast<uint64_t>(sec * 1e9);
        record_qpc_write_duration_ns(ns);
    }
#endif
    return true;
}

SharedMemoryRingWriter::Stats SharedMemoryRingWriter::stats() const {
    Stats out{};
    if (!header_) return out;
    out.write_seq = header_->write_seq;
    out.dropped = header_->dropped;
    out.capacity = header_->capacity;
    out.mapped_size_bytes = mapped_size_bytes_;
    out.large_pages = large_pages_active_ ? 1U : 0U;
    out.numa_node = numa_node_;
    return out;
}

} // namespace shared_memory_ipc
