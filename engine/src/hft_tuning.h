#pragma once

namespace hft_tuning {

bool cpu_pinning_enabled();
bool prefetch_enabled();
int read_core_env(const char* env_name, int default_core);
void apply_process_priority();
void pin_current_thread_to_core(int core, const char* role);
void maybe_pin_current_thread_from_env(const char* env_name, int default_core, const char* role);
void prefetch_read(const void* ptr);
void prefetch_write(const void* ptr);
void record_profit_callback_tick();
void record_publisher_tick();
void dump_qpc_stats();

} // namespace hft_tuning
