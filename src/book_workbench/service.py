"""Shared export boundary: validate original inputs again before writing Excel."""
from __future__ import annotations
from typing import Any
from .schedule import ScheduleValidationError, prepare_schedule_input, validate_schedule
from .settlement import SettlementValidationError, calculate_settlement, validate_transfers

def _validated_export_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Recalculate before export so stale browser state cannot become a final workbook."""

    checked = dict(payload)
    if kind == "schedule":
        schedule = prepare_schedule_input(payload.get("schedule") or {})
        checked["schedule"] = schedule
        validation = validate_schedule(schedule)
        if not validation.get("ok"):
            raise ScheduleValidationError("排班校验未通过：" + "；".join(validation.get("errors", [])))
        checked["validation"] = validation
    elif kind == "settlement_summary":
        people = payload.get("people") or []
        normalized = calculate_settlement(
            [
                {
                    "name": row.get("name"),
                    "actual_hours": row.get("actual_hours"),
                    "issued_hours": 0,
                }
                for row in people
                if isinstance(row, dict)
            ],
            issued_cap=0,
        )["people"]
        notes = {str(row.get("name", "")).strip(): row.get("notes", "") for row in people if isinstance(row, dict)}
        checked["people"] = [
            {"name": row["name"], "actual_hours": row["actual_hours"], "notes": notes.get(row["name"], "")}
            for row in normalized
        ]
    elif kind in {"settlement", "settlement_public"}:
        people = payload.get("people") or []
        issued_cap = payload.get("issued_cap", "33")
        settlement = calculate_settlement(people, issued_cap=issued_cap)
        transfers = payload.get("transfers") or []
        transfer_validation = validate_transfers(people, transfers, issued_cap=issued_cap)
        if kind == "settlement_public" or not payload.get("draft"):
            if not transfer_validation.get("ok"):
                raise SettlementValidationError(
                    "最终转账配平尚未通过：" + "；".join(transfer_validation.get("errors", []))
                )
        checked["settlement"] = settlement
        checked["transfers"] = transfers
        checked["transfer_validation"] = transfer_validation
    return checked

