# M6/M7 Evidence Summary

- overall_ok: `1`
- hft_windows: `1`
- hft_aggregate_enabled: `0`
- hft_aggregate_ok: `1`
- ipc_windows: `1`
- ipc_aggregate_enabled: `0`
- ipc_aggregate_ok: `1`

## HFT

| scenario | window | ok | reason | attempts | retried | p99(ns) | p999(ns) | target p99 | target p999 |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| lp0-numa_auto | 1 | 1 | ok | 1 | 0 | 6500 | 15353 | 10000 | 20000 |

## HFT Aggregate

| scenario | windows | failed_windows | ok | reason | max p99(ns) | max p999(ns) | target p99 | target p999 |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| lp0-numa_auto | 1 | 0 | 1 | ok | 6500 | 15353 | 10000 | 20000 |

- aggregate_gate_enabled: `0`
- aggregate_gate_ok: `1`
- aggregate_gate_reason: `disabled`

## IPC Windows

| window | ok | reason | attempts | retried | gap_messages | ring_dropped_delta | observed_trades |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
|  | 1 | ok | 1 | 0 | 0 | 0 | 12540 |

## IPC Aggregate

- ok: `1`
- reason: `ok`
- gap_messages: `0`
- ring_dropped_delta: `0`
- observed_trades: `12540`
- aggregate_gate_enabled: `0`
- aggregate_gate_ok: `1`
- aggregate_gate_reason: `disabled`
