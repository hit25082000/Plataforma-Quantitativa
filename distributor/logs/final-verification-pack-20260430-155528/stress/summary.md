# Overlay WS stress/regression summary

- overall_ok: `1`
- scenarios: `3`

| scenario | backlog_stable | backlog_growth | pub_rate_hz | consumer_fps | floor_ratio | overshoot | jitter_cv | p95_ms | p99_ms | max_ms | replaced |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hf_240hz_always_diff | 1 | 0.0 | 9.583 | 240.0 | 0.958 | 0.958 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| hf_480hz_mixed_diff | 1 | 0.0 | 9.917 | 250.0 | 0.992 | 0.992 | 0.0 | 0.0 | 0.0 | 0.0 | 2760 |
| hf_600hz_burst_diff | 1 | 0.0 | 7.9 | 111.2 | 0.948 | 0.948 | 0.0 | 0.0 | 0.0 | 0.667 | 4888 |

## Gates

- `queue_max <= 1`
- `latency_p95_ms <= 60.0`
- `latency_p99_ms <= 120.0`
- `backlog_growth_ratio <= 1.5`
- `consumer_fps >= 90.0`
- `publish_rate_floor_ratio >= 0.75`
- `publish_rate_overshoot_ratio <= 1.15`
- `publish_interval_jitter_cv <= 0.35`
- `published_count >= 1`
