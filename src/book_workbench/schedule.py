"""Deterministic validation and summaries for a weekly schedule draft."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from .schedule_balance import balance_schedule


class ScheduleValidationError(ValueError):
    """Raised when the schedule input has no usable structure."""


def _hours(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ScheduleValidationError(f"{field} must be a number") from None
    if not result.is_finite() or result < 0:
        raise ScheduleValidationError(f"{field} must be a non-negative number")
    return result


def _render_hours(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f")


def _normalise_name(value: Any, field: str = "name") -> str:
    if value is None or not str(value).strip():
        raise ScheduleValidationError(f"{field} is required")
    return str(value).strip()


def _identity_name(value: Any) -> str:
    return "".join(str(value).split())


def _parse_date(value: Any, field: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ScheduleValidationError(f"{field} must use YYYY-MM-DD") from None


def _key(day: str, shift_id: str) -> tuple[str, str]:
    return day, shift_id


def prepare_schedule_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve the complete confirmed rules before filtering or calculating.

    Explicit ``constraints`` is authoritative for web requests. Legacy callers
    without it continue to supply ``people[].unavailable``. Only whitespace is
    normalised: names are never guessed or silently dropped.
    """
    if not isinstance(payload, dict):
        raise ScheduleValidationError("schedule input must be an object")
    result = deepcopy(payload)
    people = result.get("people")
    if not isinstance(people, list) or not people:
        return result
    names = {}
    for person in people:
        if isinstance(person, dict) and person.get("name"):
            name = str(person["name"]).strip()
            key = _identity_name(name)
            if key in names:
                raise ScheduleValidationError(f"名单中有重复姓名：{name}")
            names[key] = name
    if "constraints" in result:
        rules = result["constraints"]
        if not isinstance(rules, list):
            raise ScheduleValidationError("不可排规则必须是列表")
        shifts = {str(s.get("id")) for s in (result.get("shifts") or []) if isinstance(s, dict)}
        compiled = defaultdict(list)
        for index, rule in enumerate(rules, start=1):
            if not isinstance(rule, dict):
                raise ScheduleValidationError(f"第{index}条不可排规则格式不正确")
            key = _identity_name(rule.get("name", ""))
            if key not in names:
                raise ScheduleValidationError(f"第{index}条不可排规则的姓名不在本期名单中：{rule.get('name', '')}")
            day = _parse_date(rule.get("date"), f"第{index}条不可排日期").isoformat()
            shift_id = str(rule.get("shift_id", ""))
            if shift_id not in shifts:
                raise ScheduleValidationError(f"第{index}条不可排规则的班次不存在：{shift_id}")
            slot = {"date": day, "shift_id": shift_id}
            if slot not in compiled[key]:
                compiled[key].append(slot)
        for person in people:
            if isinstance(person, dict):
                person["unavailable"] = compiled[_identity_name(person.get("name", ""))]
    for assignment in (result.get("assignments") or []):
        if isinstance(assignment, dict) and isinstance(assignment.get("people"), list):
            assignment["people"] = [names.get(_identity_name(n), str(n).strip()) for n in assignment["people"]]
    return result


def validate_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a confirmed schedule draft and return an auditable summary.

    The input deliberately separates the roster, shift definitions, constraints
    and assignments. A person may work multiple different shifts on the same
    day by default, but may not appear twice in one day/shift.
    """

    if not isinstance(payload, dict):
        raise ScheduleValidationError("schedule input must be an object")
    payload = prepare_schedule_input(payload)
    cycle = payload.get("cycle") or {}
    start = _parse_date(cycle.get("start_date"), "cycle.start_date")
    end = _parse_date(cycle.get("end_date"), "cycle.end_date")
    if end < start:
        raise ScheduleValidationError("cycle.end_date cannot be before start_date")

    people = payload.get("people")
    if not isinstance(people, list) or not people:
        raise ScheduleValidationError("people must be a non-empty list")
    roster: dict[str, dict[str, Any]] = {}
    for row_no, person in enumerate(people, start=1):
        if not isinstance(person, dict):
            raise ScheduleValidationError(f"people row {row_no} must be an object")
        name = _normalise_name(person.get("name"), f"people[{row_no}].name")
        identity = _identity_name(name)
        if identity in roster:
            raise ScheduleValidationError(f"duplicate person name: {name}")
        unavailable = set()
        for item in person.get("unavailable", []):
            if not isinstance(item, dict):
                raise ScheduleValidationError(f"unavailable for {name} must contain objects")
            unavailable.add(_key(str(item.get("date")), str(item.get("shift_id"))))
        roster[identity] = {"name": name, "unavailable": unavailable}

    shifts = payload.get("shifts")
    if not isinstance(shifts, list) or not shifts:
        raise ScheduleValidationError("shifts must be a non-empty list")
    shift_map: dict[str, dict[str, Any]] = {}
    for row_no, shift in enumerate(shifts, start=1):
        if not isinstance(shift, dict):
            raise ScheduleValidationError(f"shifts row {row_no} must be an object")
        shift_id = _normalise_name(shift.get("id"), f"shifts[{row_no}].id")
        if shift_id in shift_map:
            raise ScheduleValidationError(f"duplicate shift id: {shift_id}")
        required = shift.get("required_people")
        if not isinstance(required, int) or isinstance(required, bool) or required < 0:
            raise ScheduleValidationError(f"required_people must be a non-negative integer for {shift_id}")
        duration = shift.get("duration_hours")
        if duration is None:
            raise ScheduleValidationError(f"duration_hours is required for {shift_id}")
        shift_map[shift_id] = {
            "id": shift_id,
            "name": str(shift.get("name") or shift_id),
            "duration_hours": _hours(duration, f"duration_hours for {shift_id}"),
            "required_people": required,
        }

    days = payload.get("days")
    if days is None:
        days = []
        current = start
        while current <= end:
            days.append({"date": current.isoformat()})
            current = current.fromordinal(current.toordinal() + 1)
    if not isinstance(days, list) or not days:
        raise ScheduleValidationError("days must be a non-empty list")
    day_values: list[str] = []
    for row_no, item in enumerate(days, start=1):
        raw = item.get("date") if isinstance(item, dict) else item
        parsed = _parse_date(raw, f"days[{row_no}].date")
        if parsed < start or parsed > end:
            raise ScheduleValidationError(f"day {parsed.isoformat()} is outside the cycle")
        day_values.append(parsed.isoformat())
    if len(set(day_values)) != len(day_values):
        raise ScheduleValidationError("duplicate day")

    for person in roster.values():
        for unavailable_day, unavailable_shift in person["unavailable"]:
            parsed_unavailable_day = _parse_date(
                unavailable_day,
                f"unavailable date for {person['name']}",
            ).isoformat()
            if parsed_unavailable_day not in day_values:
                raise ScheduleValidationError(
                    f"unavailable date for {person['name']} is outside the cycle: {parsed_unavailable_day}"
                )
            if unavailable_shift not in shift_map:
                raise ScheduleValidationError(
                    f"unknown unavailable shift for {person['name']}: {unavailable_shift}"
                )

    raw_day_requirements = payload.get("day_requirements")
    if raw_day_requirements is None:
        raw_day_requirements = {}
    if not isinstance(raw_day_requirements, dict):
        raise ScheduleValidationError("day_requirements must be an object")
    day_requirements: dict[str, dict[str, int]] = {}
    for raw_day, overrides in raw_day_requirements.items():
        parsed_day = _parse_date(raw_day, "day_requirements date")
        day = parsed_day.isoformat()
        if day not in day_values:
            raise ScheduleValidationError(f"day_requirements date {day} is not a declared day")
        if not isinstance(overrides, dict):
            raise ScheduleValidationError(f"day_requirements for {day} must be an object")
        day_requirements[day] = {}
        for shift_id, required in overrides.items():
            shift_id = str(shift_id)
            if shift_id not in shift_map:
                raise ScheduleValidationError(f"unknown shift in day_requirements: {shift_id}")
            if not isinstance(required, int) or isinstance(required, bool) or required < 0:
                raise ScheduleValidationError(
                    f"day_requirements must be non-negative integers for {day}/{shift_id}"
                )
            day_requirements[day][shift_id] = required

    assignments = payload.get("assignments", [])
    if not isinstance(assignments, list):
        raise ScheduleValidationError("assignments must be a list")
    assignment_map: dict[tuple[str, str], list[str]] = defaultdict(list)
    errors: list[str] = []
    warnings: list[str] = []
    for row_no, assignment in enumerate(assignments, start=1):
        if not isinstance(assignment, dict):
            errors.append(f"assignment row {row_no} must be an object")
            continue
        day = str(assignment.get("date"))
        shift_id = str(assignment.get("shift_id"))
        try:
            parsed_day = _parse_date(day, f"assignments[{row_no}].date")
        except ScheduleValidationError as exc:
            errors.append(str(exc))
            continue
        if day not in day_values or parsed_day < start or parsed_day > end:
            errors.append(f"assignment row {row_no} is outside the cycle or declared days")
        if shift_id not in shift_map:
            errors.append(f"unknown shift: {shift_id}")
        assigned_people = assignment.get("people", [])
        if not isinstance(assigned_people, list):
            errors.append(f"assignment row {row_no}.people must be a list")
            continue
        assignment_map[_key(day, shift_id)].extend(str(person).strip() for person in assigned_people)

    shift_results: list[dict[str, Any]] = []
    person_hours: Counter[str] = Counter()
    person_shift_counts: dict[str, Counter[str]] = defaultdict(Counter)
    filled_slots = 0
    planned_slots = 0
    planned_hours = Decimal("0")
    filled_hours = Decimal("0")

    for day in day_values:
        for shift_id, shift in shift_map.items():
            assigned = assignment_map.get(_key(day, shift_id), [])
            counts = Counter(assigned)
            duplicates = sorted(name for name, count in counts.items() if count > 1)
            unknown = sorted(name for name in counts if _identity_name(name) not in roster)
            unavailable = sorted(
                name for name in counts
                if _identity_name(name) in roster
                and _key(day, shift_id) in roster[_identity_name(name)]["unavailable"]
            )
            if duplicates:
                errors.append(f"duplicate person in {day}/{shift_id}: {', '.join(duplicates)}")
            if unknown:
                errors.append(f"unknown person in {day}/{shift_id}: {', '.join(unknown)}")
            if unavailable:
                errors.append(f"unavailable person assigned in {day}/{shift_id}: {', '.join(unavailable)}")

            required = day_requirements.get(day, {}).get(shift_id, shift["required_people"])
            actual_count = len(assigned)
            vacancy = max(required - actual_count, 0)
            excess = max(actual_count - required, 0)
            if vacancy:
                warnings.append(f"{day}/{shift_id} has {vacancy} vacancy")
            if excess:
                errors.append(f"{day}/{shift_id} has {excess} excess assignment(s)")

            planned_slots += required
            filled_slots += actual_count
            planned_hours += shift["duration_hours"] * required
            filled_hours += shift["duration_hours"] * actual_count
            for name in assigned:
                identity = _identity_name(name)
                if identity not in roster:
                    continue
                canonical_name = roster[identity]["name"]
                person_hours[canonical_name] += shift["duration_hours"]
                person_shift_counts[canonical_name][shift_id] += 1
            shift_results.append(
                {
                    "date": day,
                    "shift_id": shift_id,
                    "shift_name": shift["name"],
                    "required_people": required,
                    "assigned_people": assigned,
                    "assigned_count": actual_count,
                    "vacancy_count": vacancy,
                    "excess_count": excess,
                    "duplicates": duplicates,
                    "unknown_people": unknown,
                    "unavailable_people": unavailable,
                }
            )

    people_summary = []
    for person in roster.values():
        name = person["name"]
        counts = person_shift_counts.get(name, Counter())
        people_summary.append(
            {
                "name": name,
                "morning_or_shift_counts": dict(counts),
                "assigned_hours": _render_hours(person_hours.get(name, Decimal("0"))),
            }
        )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "shift_results": shift_results,
        "people": people_summary,
        "fairness": {
            "average_required_hours": _render_hours(planned_hours / len(roster)),
            "average_assigned_hours": _render_hours(filled_hours / len(roster)),
            "minimum_hours": _render_hours(min(person_hours.get(p["name"], Decimal(0)) for p in roster.values())),
            "maximum_hours": _render_hours(max(person_hours.get(p["name"], Decimal(0)) for p in roster.values())),
            "hour_spread": _render_hours(max(person_hours.get(p["name"], Decimal(0)) for p in roster.values()) - min(person_hours.get(p["name"], Decimal(0)) for p in roster.values())),
        },
        "totals": {
            "planned_slots": planned_slots,
            "filled_slots": filled_slots,
            "vacancy_slots": max(planned_slots - filled_slots, 0),
            "planned_hours": _render_hours(planned_hours),
            "filled_hours": _render_hours(filled_hours),
        },
    }


def generate_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate a deterministic, editable draft, then validate it.

    Build a complete feasible seed, then minimise hour spread across the whole
    period using exact integer quota/flow checks. The duration mode also tries
    balanced counts within each duration group. If the bounded search cannot
    prove the optimum, return an explicitly marked feasible seed. Explicit
    personal targets retain the legacy target-based heuristic.
    """

    if not isinstance(payload, dict):
        raise ScheduleValidationError("schedule input must be an object")
    payload = prepare_schedule_input(payload)
    allocation_mode = str(payload.get("allocation_mode") or "total_hours")
    if allocation_mode not in {"total_hours", "by_duration"}:
        raise ScheduleValidationError("allocation_mode must be total_hours or by_duration")
    # Let the validator enforce the structural rules before generation.
    base = dict(payload)
    base["assignments"] = []
    validate_schedule(base)

    cycle = payload["cycle"]
    start = _parse_date(cycle["start_date"], "cycle.start_date")
    end = _parse_date(cycle["end_date"], "cycle.end_date")
    days = payload.get("days")
    if days is None:
        days = []
        current = start
        while current <= end:
            days.append({"date": current.isoformat()})
            current = current.fromordinal(current.toordinal() + 1)
    day_values = [
        _parse_date(item.get("date") if isinstance(item, dict) else item, "day.date").isoformat()
        for item in days
    ]
    day_requirements = payload.get("day_requirements") or {}

    def required_for(day: str, shift_id: str, default: int) -> int:
        return int(day_requirements.get(day, {}).get(shift_id, default))

    roster: dict[str, dict[str, Any]] = {}
    for person in payload["people"]:
        name = _normalise_name(person.get("name"))
        identity = _identity_name(name)
        unavailable = {
            _key(str(item.get("date")), str(item.get("shift_id")))
            for item in person.get("unavailable", [])
        }
        preferred = {
            _key(str(item.get("date")), str(item.get("shift_id")))
            for item in person.get("preferred", [])
            if isinstance(item, dict)
        }
        target = person.get("target_hours", payload.get("target_hours", {}).get(name))
        roster[identity] = {
            "name": name,
            "unavailable": unavailable,
            "preferred": preferred,
            "target": _hours(target, f"target_hours for {name}") if target is not None else None,
        }

    shift_map: dict[str, dict[str, Any]] = {}
    for shift in payload["shifts"]:
        shift_id = _normalise_name(shift.get("id"))
        shift_map[shift_id] = {
            "id": shift_id,
            "duration": _hours(shift.get("duration_hours"), f"duration_hours for {shift_id}"),
            "required": int(shift.get("required_people", 0)),
        }

    planned = sum(
        shift["duration"] * required_for(day, shift["id"], shift["required"])
        for day in day_values
        for shift in shift_map.values()
    )
    default_target = planned / Decimal(len(roster)) if roster else Decimal("0")
    for row in roster.values():
        if row["target"] is None:
            row["target"] = default_target

    duration_targets: dict[Decimal, Decimal] = {}
    if allocation_mode == "by_duration":
        duration_totals: defaultdict[Decimal, Decimal] = defaultdict(Decimal)
        for day in day_values:
            for shift in shift_map.values():
                duration_totals[shift["duration"]] += (
                    shift["duration"] * required_for(day, shift["id"], shift["required"])
                )
        duration_targets = {
            duration: total / Decimal(len(roster))
            for duration, total in duration_totals.items()
        }

    current_hours: Counter[str] = Counter()
    duration_hours: dict[Decimal, Counter[str]] = defaultdict(Counter)
    assignments: list[dict[str, Any]] = []
    # Scarcer shifts first on each day reduces the chance that a restricted
    # shift is left until the end.
    for day in day_values:
        ordered_shifts = sorted(
            shift_map.values(),
            key=lambda shift: (
                sum(
                    1
                    for row in roster.values()
                    if (day, shift["id"]) not in row["unavailable"]
                ),
                shift["id"],
            ),
        )
        for shift in ordered_shifts:
            required = required_for(day, shift["id"], shift["required"])
            candidates: list[tuple[tuple[Decimal, int, str], str]] = []
            for identity, row in roster.items():
                if (day, shift["id"]) in row["unavailable"]:
                    continue
                preference_bonus = Decimal("0.25") if (day, shift["id"]) in row["preferred"] else Decimal("0")
                target = row["target"] or Decimal("0")
                # An explicit zero target means "尽量不排". Treating it as a
                # zero ratio would make that person look permanently under-
                # allocated and therefore select them first.
                overall_ratio = (
                    current_hours[row["name"]] / target
                    if target > 0
                    else Decimal("1000000") + current_hours[row["name"]]
                )
                if allocation_mode == "by_duration":
                    duration_target = duration_targets.get(shift["duration"], Decimal("0"))
                    duration_ratio = (
                        duration_hours[shift["duration"]][row["name"]] / duration_target
                        if duration_target > 0
                        else Decimal("0")
                    )
                    score = duration_ratio + overall_ratio * Decimal("0.05") - preference_bonus
                    balance_hours = duration_hours[shift["duration"]][row["name"]]
                else:
                    score = overall_ratio - preference_bonus
                    balance_hours = current_hours[row["name"]]
                candidates.append(
                    ((score, balance_hours, current_hours[row["name"]], row["name"]), row["name"])
                )
            candidates.sort(key=lambda item: item[0])
            chosen = [name for _, name in candidates[:required]]
            for name in chosen:
                current_hours[name] += shift["duration"]
                if allocation_mode == "by_duration":
                    duration_hours[shift["duration"]][name] += shift["duration"]
            assignments.append({"date": day, "shift_id": shift["id"], "people": chosen})

    assignments, balance_report = balance_schedule(payload, assignments)
    generated = {**payload, "days": days, "assignments": assignments}
    validation = validate_schedule(generated)
    return {"schedule": generated, "validation": validation, "balance_report": balance_report}
