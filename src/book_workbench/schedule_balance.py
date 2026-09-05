"""Bounded, deterministic quota search with exact bipartite feasibility checks.

Whole shifts and confirmed unavailability are never relaxed. Candidate hour
intervals are tested in increasing width. A completed search therefore proves
the minimum hour spread; an exhausted budget returns the valid original draft
with an explicit inconclusive status, never an 'impossible' claim.
"""
from collections import deque
from bisect import bisect_left, bisect_right
from decimal import Decimal


class SearchLimit(Exception):
    pass


class Flow:
    def __init__(self, size):
        self.graph = [[] for _ in range(size)]

    def edge(self, start, end, capacity):
        forward = [end, capacity, len(self.graph[end])]
        backward = [start, 0, len(self.graph[start])]
        self.graph[start].append(forward)
        self.graph[end].append(backward)
        return forward

    def maximum(self, source, sink):
        total = 0
        while True:
            level = [-1] * len(self.graph)
            level[source] = 0
            queue = deque([source])
            while queue:
                node = queue.popleft()
                for end, capacity, _ in self.graph[node]:
                    if capacity and level[end] < 0:
                        level[end] = level[node] + 1
                        queue.append(end)
            if level[sink] < 0:
                return total
            positions = [0] * len(self.graph)

            def send(node, amount):
                if node == sink:
                    return amount
                while positions[node] < len(self.graph[node]):
                    edge = self.graph[node][positions[node]]
                    end, capacity, reverse = edge
                    if capacity and level[end] == level[node] + 1:
                        sent = send(end, min(amount, capacity))
                        if sent:
                            edge[1] -= sent
                            self.graph[end][reverse][1] += sent
                            return sent
                    positions[node] += 1
                return 0

            while True:
                sent = send(source, 10**9)
                if not sent:
                    break
                total += sent


def assign_group(slots, lower, upper):
    """Find a whole-slot assignment meeting every person's count interval."""
    people = len(lower)
    source, sink = len(slots) + people, len(slots) + people + 1
    super_source, super_sink = sink + 1, sink + 2
    flow = Flow(super_sink + 1)
    balance = [0] * (super_sink + 1)
    links = []

    def bounded(start, end, low, high):
        if low > high:
            return None
        balance[start] -= low
        balance[end] += low
        return flow.edge(start, end, high - low)

    total = sum(slot["required"] for slot in slots)
    if sum(lower) > total or sum(upper) < total or any(a > b for a, b in zip(lower, upper)):
        return None
    for index, slot in enumerate(slots):
        bounded(source, index, slot["required"], slot["required"])
        for person in slot["eligible"]:
            edge = bounded(index, len(slots) + person, 0, 1)
            links.append((slot["index"], person, edge))
    for person in range(people):
        bounded(len(slots) + person, sink, lower[person], upper[person])
    bounded(sink, source, 0, total)
    demand = 0
    for node, value in enumerate(balance):
        if value > 0:
            flow.edge(super_source, node, value)
            demand += value
        elif value < 0:
            flow.edge(node, super_sink, -value)
    if flow.maximum(super_source, super_sink) != demand:
        return None
    return [(slot, person) for slot, person, edge in links if edge[1] == 0]


def balance_schedule(payload, assignments, node_budget=2000):
    people = payload["people"]
    count = len(people)
    # Explicit personal targets intentionally override equal-per-person hours.
    if payload.get("target_hours") or any(person.get("target_hours") is not None for person in people):
        return assignments, {"status": "personal_targets", "minimum_spread_proven": False}
    shift_map = {shift["id"]: shift for shift in payload["shifts"]}
    durations = sorted({Decimal(str(shift["duration_hours"])) for shift in payload["shifts"] if Decimal(str(shift["duration_hours"])) > 0})
    if not durations or len(durations) > 4 or len(assignments) * count > 20000:
        return assignments, {"status": "search_limit", "minimum_spread_proven": False}
    names = [str(person["name"]).strip() for person in people]
    name_index = {name: index for index, name in enumerate(names)}
    unavailable = [{(item["date"], item["shift_id"]) for item in person.get("unavailable", [])} for person in people]
    groups = [[] for _ in durations]
    hours = [Decimal(0) for _ in people]
    for index, assignment in enumerate(assignments):
        length = Decimal(str(shift_map[assignment["shift_id"]]["duration_hours"]))
        for name in assignment["people"]:
            hours[name_index[name]] += length
        if not length:
            continue
        eligible = [i for i in range(count) if (assignment["date"], assignment["shift_id"]) not in unavailable[i]]
        groups[durations.index(length)].append({"index": index, "required": len(assignment["people"]), "eligible": eligible})
    totals = [sum(slot["required"] for slot in group) for group in groups]
    average = sum(hours) / count
    initial_spread = max(hours) - min(hours)
    maximum_hours = average + initial_spread
    available = [[sum(person in slot["eligible"] for slot in group if slot["required"]) for group in groups] for person in range(count)]
    patterns = []
    try:
        for person in range(count):
            choices = []

            def enumerate_patterns(group, selected, total_hours):
                if len(choices) > 10000:
                    raise SearchLimit
                if group == len(groups):
                    choices.append((tuple(selected), total_hours))
                    return
                maximum = min(available[person][group], totals[group], int((maximum_hours - total_hours) // durations[group]))
                for number in range(maximum + 1):
                    enumerate_patterns(group + 1, selected + [number], total_hours + number * durations[group])

            enumerate_patterns(0, [], Decimal(0))
            patterns.append(choices)
    except SearchLimit:
        return assignments, {"status": "search_limit", "minimum_spread_proven": False}

    values = sorted({hours for choices in patterns for _, hours in choices})
    # Bound interval preparation too, before allocating a quadratic table.
    first_high = bisect_left(values, average)
    if sum(max(0, bisect_right(values, low + initial_spread) - first_high)
           for low in values if low <= average) > 20000:
        return assignments, {"status": "search_limit", "minimum_spread_proven": False}
    intervals = [(high - low, max(average - low, high - average), low, high)
                 for low in values if low <= average
                 for high in values if high >= average and high - low <= initial_spread]
    intervals.sort()
    visited = 0
    by_duration = payload.get("allocation_mode") == "by_duration"

    def search(options):
        nonlocal visited
        visited += 1
        if visited > node_budget:
            raise SearchLimit
        if any(not choices for choices in options):
            return None
        # These count bounds also reject aggregate incompatibilities before flow.
        for dimension in range(len(groups) + 1):
            value = (lambda pattern: sum(pattern)) if dimension == len(groups) else (lambda pattern, g=dimension: pattern[g])
            required = sum(totals) if dimension == len(groups) else totals[dimension]
            if sum(min(value(p) for p in choices) for choices in options) > required or sum(max(value(p) for p in choices) for choices in options) < required:
                return None
        solutions = []
        for group, slots in enumerate(groups):
            solution = assign_group(slots, [min(p[group] for p in choices) for choices in options], [max(p[group] for p in choices) for choices in options])
            if solution is None:
                return None
            solutions.extend(solution)
        if all(len(choices) == 1 for choices in options):
            return solutions
        person = min((i for i in range(count) if len(options[i]) > 1), key=lambda i: (len(options[i]), sum(available[i]), names[i]))
        def preference(pattern):
            duration_error = sum((pattern[g] * count - totals[g]) ** 2 for g in range(len(groups)))
            hour_error = abs(sum(pattern[g] * durations[g] for g in range(len(groups))) - average)
            return (duration_error, hour_error, pattern) if by_duration else (hour_error, pattern)
        for pattern in sorted(options[person], key=preference):
            narrowed = list(options)
            narrowed[person] = [pattern]
            # Apply necessary remaining-total bounds to the other choices.
            changed = True
            while changed:
                changed = False
                minimum = [[min(p[g] for p in choices) for g in range(len(groups))] for choices in narrowed]
                maximum = [[max(p[g] for p in choices) for g in range(len(groups))] for choices in narrowed]
                for i in range(count):
                    filtered = [p for p in narrowed[i] if all(sum(minimum[j][g] for j in range(count) if j != i) <= totals[g] - p[g] <= sum(maximum[j][g] for j in range(count) if j != i) for g in range(len(groups)))]
                    if not filtered:
                        break
                    if len(filtered) != len(narrowed[i]):
                        narrowed[i] = filtered
                        changed = True
                else:
                    if changed:
                        continue
                    result = search(narrowed)
                    if result is not None:
                        return result
                break
        return None

    try:
        for spread, _, low, high in intervals:
            options = [[pattern for pattern, hours in choices if low <= hours <= high] for choices in patterns]
            if any(not choices for choices in options):
                continue
            # Both modes prioritise hours. The second mode additionally tries
            # the theoretical best per-duration floor/ceil count distribution.
            group_balanced = False
            result = None
            if by_duration:
                balanced = [[p for p in choices if all(totals[g] // count <= p[g] <= (totals[g] + count - 1) // count for g in range(len(groups)))] for choices in options]
                if all(balanced):
                    result = search(balanced)
                    group_balanced = result is not None
            if result is None:
                result = search(options)
            if result is not None:
                final = [{**assignment, "people": [] if Decimal(str(shift_map[assignment["shift_id"]]["duration_hours"])) else list(assignment["people"])} for assignment in assignments]
                for slot, person in result:
                    final[slot]["people"].append(names[person])
                return final, {"status": "optimal_spread", "minimum_spread_proven": True,
                               "duration_counts_floor_ceil": group_balanced,
                               "hour_spread": str(spread), "search_nodes": visited}
    except SearchLimit:
        return assignments, {"status": "search_limit", "minimum_spread_proven": False, "search_nodes": visited}
    return assignments, {"status": "search_limit", "minimum_spread_proven": False, "search_nodes": visited}
