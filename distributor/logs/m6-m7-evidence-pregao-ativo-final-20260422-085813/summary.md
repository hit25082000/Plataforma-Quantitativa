# M6/M7 Evidence Summary

- overall_ok: `0`
- hft_windows: `1`
- hft_aggregate_enabled: `0`
- hft_aggregate_ok: `1`
- ipc_windows: `1`
- ipc_aggregate_enabled: `0`
- ipc_aggregate_ok: `1`

## HFT

| scenario | window | ok | reason | attempts | retried | p99(ns) | p999(ns) | target p99 | target p999 |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| lp0-numa0 | 1 | 0 | metric_not_found | 1 | 0 | -1 | -1 | 10000 | 20000 |

## HFT Aggregate

| scenario | windows | failed_windows | ok | reason | max p99(ns) | max p999(ns) | target p99 | target p999 |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| lp0-numa0 | 1 | 1 | 0 | metric_not_found | -1 | -1 | 10000 | 20000 |

- aggregate_gate_enabled: `0`
- aggregate_gate_ok: `1`
- aggregate_gate_reason: `disabled`

## IPC Windows

| window | ok | reason | attempts | retried | gap_messages | ring_dropped_delta | observed_trades |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
|  | 0 | mode_not_session | 1 | 0 | -1 | -1 | -1 |

## IPC Aggregate

- ok: `0`
- reason: `mode_not_session`
- gap_messages: `-1`
- ring_dropped_delta: `-1`
- observed_trades: `-1`
- aggregate_gate_enabled: `0`
- aggregate_gate_ok: `1`
- aggregate_gate_reason: `disabled`
