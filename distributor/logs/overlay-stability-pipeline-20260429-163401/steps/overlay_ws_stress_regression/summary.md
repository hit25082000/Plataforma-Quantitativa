# Overlay WS stress/regression summary

- overall_ok: `1`
- scenarios: `3`

| scenario | backlog_stable | pub_rate_hz | p95_ms | p99_ms | max_ms | replaced |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| hf_240hz_always_diff | 1 | 9.583 | 0.0 | 0.0 | 0.0 | 0 |
| hf_480hz_mixed_diff | 1 | 9.917 | 0.0 | 0.0 | 0.0 | 2760 |
| hf_600hz_burst_diff | 1 | 7.9 | 0.0 | 0.0 | 0.667 | 4888 |

## Gates

- `queue_max <= 1`
- `latency_p99_ms <= 120.0`
- `published_count >= 1`
