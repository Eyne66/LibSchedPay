"""Deterministic work-hour difference and transfer calculations.

This module deliberately does not contain language-model logic or spreadsheet
formatting. It accepts already-confirmed rows and returns auditable, typed
calculation results.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


class SettlementValidationError(ValueError):
    """Raised when confirmed settlement input is incomplete or invalid."""


def _decimal(value: Any, field: str, row_no: int | None = None) -> Decimal:
    location = f" on row {row_no}" if row_no is not None else ""
    if value is None or value == "":
        raise SettlementValidationError(f"{field} is required{location}")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise SettlementValidationError(f"{field} must be a number{location}") from None
    if not result.is_finite():
        raise SettlementValidationError(f"{field} must be finite{location}")
    return result


def _hours(value: Decimal) -> str:
    """Render Decimal hours without binary floating-point artefacts."""

    if value == value.to_integral_value():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f")


def _name_key(name: str) -> str:
    return "".join(name.split())


def _status(difference: Decimal) -> str:
    if difference > 0:
        return "应收"
    if difference < 0:
        return "应转出"
    return "无差额"


def _normalise_rows(rows: Iterable[dict[str, Any]], issued_cap: Any) -> list[dict[str, Any]]:
    cap = _decimal(issued_cap, "issued_cap")
    if cap < 0:
        raise SettlementValidationError("issued_cap cannot be negative")

    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_no, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise SettlementValidationError(f"row {row_no} must be an object")
        raw_name = row.get("name")
        if raw_name is None or not str(raw_name).strip():
            raise SettlementValidationError(f"name is required on row {row_no}")
        name = str(raw_name).strip()
        key = _name_key(name)
        if key in seen:
            raise SettlementValidationError(f"duplicate person name: {name}")
        seen.add(key)

        actual = _decimal(row.get("actual_hours"), "actual_hours", row_no)
        issued = _decimal(row.get("issued_hours"), "issued_hours", row_no)
        if actual < 0:
            raise SettlementValidationError(f"actual_hours cannot be negative on row {row_no}")
        if issued < 0:
            raise SettlementValidationError(f"issued_hours cannot be negative on row {row_no}")
        if issued > cap:
            raise SettlementValidationError(
                f"issued_hours for {name} is {_hours(issued)}, above the cap {_hours(cap)}"
            )

        difference = actual - issued
        normalised.append(
            {
                "person_id": str(row["person_id"]).strip() if row.get("person_id") else None,
                "name": name,
                "actual_hours": actual,
                "issued_hours": issued,
                "difference_hours": difference,
                "status": _status(difference),
            }
        )
    if not normalised:
        raise SettlementValidationError("at least one person is required")
    return normalised


def calculate_settlement(rows: Iterable[dict[str, Any]], issued_cap: Any = "33") -> dict[str, Any]:
    """Calculate differences and a stable greedy transfer draft.

    Positive difference means the person should receive a private adjustment.
    Negative difference means the person has received more official hours than
    their confirmed actual hours and is a payer in the private adjustment.

    The function never changes ``issued_hours`` and never forces an unbalanced
    case to zero. Any remaining amount is reported as an external adjustment.
    """

    people = _normalise_rows(rows, issued_cap)
    receivers = [
        {"name": row["name"], "remaining": row["difference_hours"]}
        for row in people
        if row["difference_hours"] > 0
    ]
    payers = [
        {"name": row["name"], "remaining": -row["difference_hours"]}
        for row in people
        if row["difference_hours"] < 0
    ]

    transfers: list[dict[str, str]] = []
    # First close exact equal differences one-to-one. This avoids splitting a
    # transfer when a payer and receiver happen to have the same amount.
    for receiver in receivers:
        if receiver["remaining"] <= 0:
            continue
        for payer in payers:
            if payer["remaining"] > 0 and payer["remaining"] == receiver["remaining"]:
                transfers.append(
                    {
                        "payer": payer["name"],
                        "receiver": receiver["name"],
                        "hours": _hours(receiver["remaining"]),
                    }
                )
                payer["remaining"] = Decimal("0")
                receiver["remaining"] = Decimal("0")
                break

    receivers = [row for row in receivers if row["remaining"] > 0]
    payers = [row for row in payers if row["remaining"] > 0]
    # Then use largest residuals first. It is deterministic and usually keeps
    # the number of split transfers low while remaining easy to audit.
    receivers.sort(key=lambda row: (-row["remaining"], row["name"]))
    payers.sort(key=lambda row: (-row["remaining"], row["name"]))
    receiver_index = 0
    payer_index = 0
    while receiver_index < len(receivers) and payer_index < len(payers):
        receiver = receivers[receiver_index]
        payer = payers[payer_index]
        amount = min(receiver["remaining"], payer["remaining"])
        if amount > 0:
            transfers.append(
                {
                    "payer": payer["name"],
                    "receiver": receiver["name"],
                    "hours": _hours(amount),
                }
            )
        receiver["remaining"] -= amount
        payer["remaining"] -= amount
        if receiver["remaining"] == 0:
            receiver_index += 1
        if payer["remaining"] == 0:
            payer_index += 1

    actual_total = sum((row["actual_hours"] for row in people), Decimal("0"))
    issued_total = sum((row["issued_hours"] for row in people), Decimal("0"))
    difference_total = actual_total - issued_total
    receivable_total = sum((row["difference_hours"] for row in people if row["difference_hours"] > 0), Decimal("0"))
    payable_total = sum((-row["difference_hours"] for row in people if row["difference_hours"] < 0), Decimal("0"))
    transfer_total = sum((_decimal(item["hours"], "transfer hours") for item in transfers), Decimal("0"))

    return {
        "people": [
            {
                **row,
                "actual_hours": _hours(row["actual_hours"]),
                "issued_hours": _hours(row["issued_hours"]),
                "difference_hours": _hours(row["difference_hours"]),
            }
            for row in people
        ],
        "totals": {
            "actual_hours": _hours(actual_total),
            "issued_hours": _hours(issued_total),
            "difference_hours": _hours(difference_total),
            "receivable_hours": _hours(receivable_total),
            "payable_hours": _hours(payable_total),
            "draft_transfer_hours": _hours(transfer_total),
            "external_adjustment_hours": _hours(difference_total),
        },
        "transfers": transfers,
        "checks": {
            "issued_hours_within_cap": True,
            "people_unique": True,
            "difference_reconciles": actual_total - issued_total == difference_total,
            "draft_transfer_balanced_between_people": transfer_total == min(receivable_total, payable_total),
            "net_difference_is_zero": difference_total == 0,
        },
    }


def validate_transfers(
    rows: Iterable[dict[str, Any]],
    transfers: Iterable[dict[str, Any]],
    issued_cap: Any = "33",
) -> dict[str, Any]:
    """Validate an edited transfer draft against confirmed person differences."""

    normalised = _normalise_rows(rows, issued_cap)
    by_name = {_name_key(row["name"]): row for row in normalised}
    paid = defaultdict(lambda: Decimal("0"))
    received = defaultdict(lambda: Decimal("0"))
    errors: list[str] = []

    for row_no, transfer in enumerate(transfers, start=1):
        if not isinstance(transfer, dict):
            errors.append(f"transfer row {row_no} must be an object")
            continue
        payer_name = str(transfer.get("payer", "")).strip()
        receiver_name = str(transfer.get("receiver", "")).strip()
        try:
            amount = _decimal(transfer.get("hours"), "transfer hours", row_no)
        except SettlementValidationError as exc:
            errors.append(str(exc))
            continue
        payer = by_name.get(_name_key(payer_name))
        receiver = by_name.get(_name_key(receiver_name))
        if payer is None:
            errors.append(f"unknown payer: {payer_name}")
        if receiver is None:
            errors.append(f"unknown receiver: {receiver_name}")
        if amount <= 0:
            errors.append(f"transfer hours must be positive on row {row_no}")
        if payer_name and receiver_name and _name_key(payer_name) == _name_key(receiver_name):
            errors.append(f"payer and receiver cannot be the same person on row {row_no}")
        if payer is not None:
            if payer["difference_hours"] >= 0:
                errors.append(f"payer {payer_name} does not have a negative difference")
            paid[_name_key(payer_name)] += amount
        if receiver is not None:
            if receiver["difference_hours"] <= 0:
                errors.append(f"receiver {receiver_name} does not have a positive difference")
            received[_name_key(receiver_name)] += amount

    for key, row in by_name.items():
        allowed_paid = max(-row["difference_hours"], Decimal("0"))
        allowed_received = max(row["difference_hours"], Decimal("0"))
        if paid[key] > allowed_paid:
            errors.append(f"payer {row['name']} is over-allocated")
        if received[key] > allowed_received:
            errors.append(f"receiver {row['name']} is over-allocated")

    difference_total = sum((row["difference_hours"] for row in normalised), Decimal("0"))
    if difference_total != 0:
        errors.append(
            f"overall difference is {_hours(difference_total)}; adjust official issued hours before final transfer"
        )
    else:
        for key, row in by_name.items():
            required_paid = max(-row["difference_hours"], Decimal("0"))
            required_received = max(row["difference_hours"], Decimal("0"))
            if paid[key] != required_paid:
                errors.append(f"payer {row['name']} is not fully allocated")
            if received[key] != required_received:
                errors.append(f"receiver {row['name']} is not fully allocated")

    total_paid = sum(paid.values(), Decimal("0"))
    total_received = sum(received.values(), Decimal("0"))
    return {
        "ok": not errors and total_paid == total_received,
        "errors": errors if total_paid == total_received else [*errors, "paid and received totals do not match"],
        "paid_hours": _hours(total_paid),
        "received_hours": _hours(total_received),
        "unmatched_difference_hours": _hours(total_received - total_paid),
    }
