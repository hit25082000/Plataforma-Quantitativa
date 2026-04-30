# OVR STAB QA Evidence (Local)

- overall_ok: `1`
- suites: `3`

## Suites

| suite | ok | exit_code | elapsed_s | OVRs |
| --- | ---: | ---: | ---: | --- |
| qa_axis_overlay_contract | 1 | 0 | 6.722 | OVR-STAB-QA-01,OVR-STAB-QA-03,OVR-STAB-OBS-09 |
| qa_overlay_proxy_endpoints | 1 | 0 | 11.663 | OVR-STAB-QA-02,OVR-STAB-OBS-09 |
| qa_enrich_overlay_axis_health | 1 | 0 | 0.57 | OVR-STAB-QA-01,OVR-STAB-QA-05,OVR-STAB-OBS-09 |

## OVR Status (partial/local)

| OVR | state | coverage | suites |
| --- | --- | --- | --- |
| OVR-STAB-QA-01 | partial-done | local-tests-mocked | qa_axis_overlay_contract,qa_enrich_overlay_axis_health |
| OVR-STAB-QA-02 | partial-done | local-tests-mocked | qa_overlay_proxy_endpoints |
| OVR-STAB-QA-03 | partial-done | local-tests-mocked | qa_axis_overlay_contract |
| OVR-STAB-QA-04 | not-covered | none |  |
| OVR-STAB-QA-05 | partial-done | local-tests-mocked | qa_enrich_overlay_axis_health |
| OVR-STAB-OBS-09 | partial-done | local-tests-mocked | qa_axis_overlay_contract,qa_overlay_proxy_endpoints,qa_enrich_overlay_axis_health |

