#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

CEN03_REQUIRED_CHANNELS = ("hud", "status_endpoint", "trace_jsonl")
CEN03_REQUIRED_TRANSITIONS = ("STABLE->FROZEN|RECALIBRATING", "FROZEN|RECALIBRATING->STABLE")
CEN03_SEMANTIC_TOKENS = (
    "stable",
    "frozen",
    "recalibrating",
    "recovery",
    "recover",
    "degradation",
    "degradacao",
    "bad_frames",
    "laststableaxis",
    "axis_status",
    "transition",
)


def build_incident_evidence_index(field_report_payload: Dict[str, Any]) -> Dict[str, Any]:
    scenarios = field_report_payload.get("scenarios", {})
    if not isinstance(scenarios, dict):
        return {
            "ok": False,
            "checked_incidents": 0,
            "index": {},
            "errors": ["field_report.scenarios_missing_or_invalid"],
        }

    cen03 = scenarios.get("CEN-03", {})
    if not isinstance(cen03, dict):
        return {
            "ok": False,
            "checked_incidents": 0,
            "index": {},
            "errors": ["field_report.scenarios.CEN-03_missing_or_invalid"],
        }

    incident_packages = cen03.get("incident_packages", [])
    if not isinstance(incident_packages, list) or not incident_packages:
        return {
            "ok": False,
            "checked_incidents": 0,
            "index": {},
            "errors": ["CEN-03.incident_packages_missing_or_empty"],
        }

    index: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    for idx, item in enumerate(incident_packages):
        if not isinstance(item, dict):
            errors.append(f"incident[{idx}]:invalid_entry_type")
            continue
        incident_id = str(item.get("incident_id", "")).strip()
        if not incident_id:
            errors.append(f"incident[{idx}]:missing_incident_id")
            continue
        if incident_id in index:
            errors.append(f"{incident_id}:duplicated_incident_id")
            continue

        transitions = item.get("observed_state_transitions", [])
        transitions_list = [str(transition).strip() for transition in transitions if str(transition).strip()]
        comparisons = item.get("expected_vs_observed_by_channel", {})
        channel_evidence: Dict[str, List[str]] = {}
        if isinstance(comparisons, dict):
            for channel in CEN03_REQUIRED_CHANNELS:
                channel_data = comparisons.get(channel)
                evidence_list: List[str] = []
                if isinstance(channel_data, dict):
                    evidence_ref = channel_data.get("evidence_ref")
                    if isinstance(evidence_ref, list):
                        evidence_list = [str(ref).strip() for ref in evidence_ref if str(ref).strip()]
                    else:
                        normalized_ref = str(evidence_ref or "").strip()
                        if normalized_ref:
                            evidence_list = [normalized_ref]
                channel_evidence[channel] = evidence_list
        incident_evidence_refs = item.get("evidence_ref", [])
        incident_refs = [str(ref).strip() for ref in incident_evidence_refs if str(ref).strip()] if isinstance(incident_evidence_refs, list) else []
        index[incident_id] = {
            "incident_id": incident_id,
            "channels_with_evidence": sorted([channel for channel, refs in channel_evidence.items() if refs]),
            "channel_evidence_refs": channel_evidence,
            "observed_state_transitions": transitions_list,
            "evidence_ref": incident_refs,
        }
    return {"ok": len(errors) == 0, "checked_incidents": len(index), "index": index, "errors": errors}


def validate_cen03_incident_packages(field_report_payload: Dict[str, Any]) -> Dict[str, Any]:
    index_report = build_incident_evidence_index(field_report_payload)
    if not index_report.get("checked_incidents"):
        return {
            "ok": False,
            "checked_incidents": 0,
            "errors": list(index_report.get("errors", [])),
            "incident_evidence_index": {},
        }

    scenarios = field_report_payload.get("scenarios", {})
    cen03 = scenarios.get("CEN-03", {})
    incident_packages = cen03.get("incident_packages", [])
    errors: List[str] = []
    errors.extend([str(item) for item in index_report.get("errors", [])])
    for idx, item in enumerate(incident_packages):
        if not isinstance(item, dict):
            errors.append(f"incident[{idx}]:invalid_entry_type")
            continue

        incident_id = str(item.get("incident_id", "")).strip()
        if not incident_id:
            errors.append(f"incident[{idx}]:missing_incident_id")
            incident_id = f"incident[{idx}]"

        comparisons = item.get("expected_vs_observed_by_channel", {})
        if not isinstance(comparisons, dict):
            errors.append(f"{incident_id}:missing_expected_vs_observed_by_channel")
            continue

        incident_evidence_refs = item.get("evidence_ref", [])
        if not isinstance(incident_evidence_refs, list) or len([str(ref).strip() for ref in incident_evidence_refs if str(ref).strip()]) < 3:
            errors.append(f"{incident_id}:insufficient_incident_evidence_refs")

        observed_state_transitions = item.get("observed_state_transitions", [])
        if not isinstance(observed_state_transitions, list):
            errors.append(f"{incident_id}:invalid_observed_state_transitions")
            observed_state_transitions = []
        transitions_set = {str(transition).strip() for transition in observed_state_transitions if str(transition).strip()}
        for required_transition in CEN03_REQUIRED_TRANSITIONS:
            if required_transition not in transitions_set:
                errors.append(f"{incident_id}:missing_transition:{required_transition}")

        semantic_expected_tokens: set[str] = set()
        semantic_observed_tokens: set[str] = set()
        for channel in CEN03_REQUIRED_CHANNELS:
            channel_data = comparisons.get(channel)
            if not isinstance(channel_data, dict):
                errors.append(f"{incident_id}:missing_channel:{channel}")
                continue

            expected = str(channel_data.get("expected", "")).strip()
            observed = str(channel_data.get("observed", "")).strip()
            if not expected or not observed:
                errors.append(f"{incident_id}:incomplete_expected_vs_observed:{channel}")
            expected_lc = expected.lower()
            observed_lc = observed.lower()
            expected_hits = {token for token in CEN03_SEMANTIC_TOKENS if token in expected_lc}
            observed_hits = {token for token in CEN03_SEMANTIC_TOKENS if token in observed_lc}
            semantic_expected_tokens.update(expected_hits)
            semantic_observed_tokens.update(observed_hits)
            if expected_hits and not observed_hits:
                errors.append(f"{incident_id}:semantic_mismatch:{channel}")

            evidence_ref = channel_data.get("evidence_ref")
            if isinstance(evidence_ref, list):
                normalized_refs = [str(ref).strip() for ref in evidence_ref if str(ref).strip()]
                if not normalized_refs:
                    errors.append(f"{incident_id}:missing_channel_evidence_ref:{channel}")
            else:
                if not str(evidence_ref or "").strip():
                    errors.append(f"{incident_id}:missing_channel_evidence_ref:{channel}")

        if "frozen" not in semantic_observed_tokens and "recalibrating" not in semantic_observed_tokens:
            errors.append(f"{incident_id}:missing_protection_signal_in_observed")
        if "stable" not in semantic_observed_tokens and "recover" not in semantic_observed_tokens and "recovery" not in semantic_observed_tokens:
            errors.append(f"{incident_id}:missing_recovery_signal_in_observed")
        if semantic_expected_tokens and not (semantic_expected_tokens & semantic_observed_tokens):
            errors.append(f"{incident_id}:expected_observed_semantic_overlap_missing")

    return {
        "ok": len(errors) == 0,
        "checked_incidents": len(index_report.get("index", {})),
        "errors": errors,
        "incident_evidence_index": index_report.get("index", {}),
    }


def build_incident_package(
    *,
    incident_id: str,
    symptom: str,
    suspected_root_cause: str,
    action_taken: str,
    result: str,
    transitions: List[str],
    evidence_refs: List[str],
    channel_payload: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "incident_id": incident_id.strip(),
        "symptom": symptom.strip(),
        "suspected_root_cause": suspected_root_cause.strip(),
        "action_taken": action_taken.strip(),
        "result": result.strip(),
        "observed_state_transitions": [item.strip() for item in transitions if item.strip()],
        "evidence_ref": [item.strip() for item in evidence_refs if item.strip()],
        "expected_vs_observed_by_channel": {
            channel: {
                "expected": str(values.get("expected", "")).strip(),
                "observed": str(values.get("observed", "")).strip(),
                "evidence_ref": str(values.get("evidence_ref", "")).strip(),
            }
            for channel, values in channel_payload.items()
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monta bloco incident_packages para CEN-03 com expected/observed por canal.")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--symptom", default="")
    parser.add_argument("--suspected-root-cause", default="")
    parser.add_argument("--action-taken", default="")
    parser.add_argument("--result", default="pass")
    parser.add_argument("--transition", action="append", default=[])
    parser.add_argument("--evidence-ref", action="append", default=[])
    parser.add_argument("--hud-expected", required=True)
    parser.add_argument("--hud-observed", required=True)
    parser.add_argument("--hud-evidence-ref", required=True)
    parser.add_argument("--status-expected", required=True)
    parser.add_argument("--status-observed", required=True)
    parser.add_argument("--status-evidence-ref", required=True)
    parser.add_argument("--trace-expected", required=True)
    parser.add_argument("--trace-observed", required=True)
    parser.add_argument("--trace-evidence-ref", required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--field-report-out", type=Path, default=None)
    parser.add_argument("--strict", action="store_true", default=False)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    channel_payload = {
        "hud": {"expected": args.hud_expected, "observed": args.hud_observed, "evidence_ref": args.hud_evidence_ref},
        "status_endpoint": {
            "expected": args.status_expected,
            "observed": args.status_observed,
            "evidence_ref": args.status_evidence_ref,
        },
        "trace_jsonl": {
            "expected": args.trace_expected,
            "observed": args.trace_observed,
            "evidence_ref": args.trace_evidence_ref,
        },
    }
    package = build_incident_package(
        incident_id=args.incident_id,
        symptom=args.symptom,
        suspected_root_cause=args.suspected_root_cause,
        action_taken=args.action_taken,
        result=args.result,
        transitions=args.transition,
        evidence_refs=args.evidence_ref,
        channel_payload=channel_payload,
    )
    field_report = {"scenarios": {"CEN-03": {"incident_packages": [package]}}}
    validation = validate_cen03_incident_packages(field_report)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"incident_packages": [package]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote: {args.out}")
    else:
        print(json.dumps({"incident_packages": [package]}, indent=2, ensure_ascii=False))

    if args.field_report_out is not None:
        args.field_report_out.parent.mkdir(parents=True, exist_ok=True)
        args.field_report_out.write_text(json.dumps(field_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote: {args.field_report_out}")

    if not validation.get("ok", False):
        print(json.dumps(validation, indent=2, ensure_ascii=False))
        if args.strict:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
