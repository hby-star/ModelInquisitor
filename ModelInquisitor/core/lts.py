from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LTSTransition:
    source: int
    label: str
    target: int


@dataclass
class LTS:
    initial_state: int
    states: set[int]
    transitions: list[LTSTransition]
    _adj: dict[int, list[LTSTransition]] = field(default_factory=dict, repr=False)

    def outgoing(self, state: int) -> list[LTSTransition]:
        return self._adj.get(state, [])

    def is_terminal(self, state: int) -> bool:
        return state not in self._adj


_HEADER_RE = re.compile(r"des\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_TRANSITION_RE = re.compile(r"\(\s*(\d+)\s*,\s*\"([^\"]*)\"\s*,\s*(\d+)\s*\)")


def strip_data_params(label: str) -> str:
    """Remove parenthesized data parameters from an mCRL2 action label.

    e.g. "c_send_request(order_id(1))" -> "c_send_request"
    """
    paren = label.find("(")
    if paren == -1:
        return label
    return label[:paren]


def parse_aut(text: str) -> LTS:
    """Parse an Aldebaran (.aut) format LTS file into an LTS model."""
    lines = text.strip().splitlines()
    if not lines:
        raise ValueError("Empty .aut file")

    header_match = _HEADER_RE.match(lines[0])
    if not header_match:
        raise ValueError(f"Invalid .aut header: {lines[0]}")
    initial_state = int(header_match.group(1))

    transitions: list[LTSTransition] = []
    states: set[int] = {initial_state}
    adj: dict[int, list[LTSTransition]] = {}

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        match = _TRANSITION_RE.match(line)
        if not match:
            continue
        source = int(match.group(1))
        label = match.group(2)
        target = int(match.group(3))
        trans = LTSTransition(source=source, label=label, target=target)
        transitions.append(trans)
        states.add(source)
        states.add(target)
        adj.setdefault(source, []).append(trans)

    return LTS(
        initial_state=initial_state,
        states=states,
        transitions=transitions,
        _adj=adj,
    )