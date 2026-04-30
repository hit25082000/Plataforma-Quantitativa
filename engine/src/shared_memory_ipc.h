#pragma once

#include "event_bus.h"
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace shared_memory_ipc {

static constexpr uint32_t kShmMagic = 0x504D4853; // "SHMP"
static constexpr uint32_t kShmVersion = 1;
static constexpr uint32_t kMessageTypeTrade = 1;

constexpr size_t kTickerMax = 24;
constexpr size_t kDateMax = 16;

struct TradePayload {
    char ticker[kTickerMax];
    char trade_date[kDateMax];
    double price;
    int64_t qty;
    int32_t buy_agent;
    int32_t sell_agent;
    uint8_t trade_type;
    uint8_t trade_source;
    uint16_t reserved0;
    uint32_t trade_number;
    uint32_t trade_flags;
    int64_t trade_epoch_ms;
    double vwap;
    int64_t net_aggression;
};

struct RingHeader {
    uint32_t magic;
    uint32_t version;
    uint32_t header_size;
    uint32_t slot_size;
    uint64_t capacity;
    uint64_t write_seq;
    uint64_t dropped;
    uint64_t created_epoch_ms;
    uint64_t reserved[8];
};

struct RingSlot {
    uint64_t committed_seq;
    uint32_t message_type;
    uint32_t payload_size;
    TradePayload trade;
};

class SharedMemoryRingWriter {
public:
    struct Stats {
        uint64_t write_seq{0};
        uint64_t dropped{0};
        uint64_t capacity{0};
        uint64_t mapped_size_bytes{0};
        uint32_t large_pages{0};
        int32_t numa_node{-1};
    };

    SharedMemoryRingWriter(std::string mapping_name, size_t size_bytes);
    ~SharedMemoryRingWriter();

    SharedMemoryRingWriter(const SharedMemoryRingWriter&) = delete;
    SharedMemoryRingWriter& operator=(const SharedMemoryRingWriter&) = delete;

    bool is_ready() const { return header_ != nullptr; }
    bool write_trade(const event_bus::TradeEvent& trade, double vwap, int64_t net_aggression);
    Stats stats() const;
    const std::string& mapping_name() const { return mapping_name_; }

private:
    bool initialize(size_t size_bytes);
    void record_qpc_write_duration_ns(uint64_t ns);
    void dump_qpc_stats_if_any();

    std::string mapping_name_;
    void* mapping_handle_{nullptr};
    std::uint8_t* base_{nullptr};
    RingHeader* header_{nullptr};
    RingSlot* slots_{nullptr};

    bool qpc_diag_{false};
    uint64_t qpc_sample_every_{1};
    uint64_t qpc_max_samples_{1'000'000};
    int64_t qpc_freq_{0};
    uint64_t mapped_size_bytes_{0};
    bool large_pages_active_{false};
    int32_t numa_node_{-1};
    bool prefetch_next_slot_{true};
    mutable std::mutex qpc_mutex_;
    std::vector<uint64_t> qpc_samples_ns_;
};

std::string default_mapping_name();
size_t default_mapping_size_bytes();

} // namespace shared_memory_ipc
