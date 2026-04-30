# OVR STAB QA Evidence (Local)

- overall_ok: `1`
- suites: `4`

## Suites

| suite | ok | exit_code | elapsed_s | OVRs |
| --- | ---: | ---: | ---: | --- |
| qa_axis_overlay_contract | 1 | 0 | 1.742 | OVR-STAB-QA-01,OVR-STAB-QA-03,OVR-STAB-OBS-09 |
| qa_overlay_proxy_endpoints | 1 | 0 | 2.632 | OVR-STAB-QA-02,OVR-STAB-OBS-09 |
| qa_enrich_overlay_axis_health | 1 | 0 | 0.24 | OVR-STAB-QA-01,OVR-STAB-QA-05,OVR-STAB-OBS-09 |
| qa_overlay_ws_stress_regression_harness | 1 | 0 | 1.713 | OVR-STAB-QA-05,OVR-STAB-OBS-09 |

## OVR Status (partial/local)

| OVR | state | coverage | suites |
| --- | --- | --- | --- |
| OVR-STAB-QA-01 | partial-done | local-tests-mocked | qa_axis_overlay_contract,qa_enrich_overlay_axis_health |
| OVR-STAB-QA-02 | partial-done | local-tests-mocked | qa_overlay_proxy_endpoints |
| OVR-STAB-QA-03 | partial-done | local-tests-mocked | qa_axis_overlay_contract |
| OVR-STAB-QA-04 | not-covered | none |  |
| OVR-STAB-QA-05 | partial-done | local-tests-mocked | qa_enrich_overlay_axis_health,qa_overlay_ws_stress_regression_harness |
| OVR-STAB-OBS-09 | partial-done | local-tests-mocked | qa_axis_overlay_contract,qa_overlay_proxy_endpoints,qa_enrich_overlay_axis_health,qa_overlay_ws_stress_regression_harness |

## CEN-05 Threshold Contract

| metric | operator | threshold |
| --- | --- | ---: |
| queue_max | <= | 1 |
| backlog_growth_ratio | <= | 1.5 |
| latency_p95_ms | <= | 60.0 |
| latency_p99_ms | <= | 120.0 |
| consumer_fps | >= | 90.0 |
| publish_rate_floor_ratio | >= | 0.75 |
| publish_rate_overshoot_ratio | <= | 1.15 |
| publish_interval_jitter_cv | <= | 0.35 |

