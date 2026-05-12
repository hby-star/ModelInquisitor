from __future__ import annotations

Trace = tuple[str, ...]
TraceSet = frozenset[Trace]


def interleave_sequences(
    seq_a: Trace,
    seq_b: Trace,
) -> set[Trace]:
    """All interleavings of two sequences preserving internal order (shuffle product)."""
    if not seq_a:
        return {seq_b}
    if not seq_b:
        return {seq_a}
    result: set[Trace] = set()
    for suffix in interleave_sequences(seq_a[1:], seq_b):
        result.add((seq_a[0],) + suffix)
    for suffix in interleave_sequences(seq_a, seq_b[1:]):
        result.add((seq_b[0],) + suffix)
    return result


def interleave_trace_sets(
    set_a: TraceSet,
    set_b: TraceSet,
    *,
    max_count: int = 1000,
) -> tuple[TraceSet, bool]:
    """Interleave two trace sets. Returns (result, truncated) where truncated is True if max_count was hit."""
    result: set[Trace] = set()
    truncated = False
    for a in set_a:
        for b in set_b:
            for interleaved in interleave_sequences(a, b):
                result.add(interleaved)
                if len(result) >= max_count:
                    truncated = True
                    return frozenset(result), truncated
    return frozenset(result), truncated


def interleave_multi(
    branch_sets: list[TraceSet],
    *,
    max_count: int = 1000,
) -> tuple[TraceSet, bool]:
    """Interleave N trace sets (for N parallel branches). Chains pairwise."""
    if not branch_sets:
        return frozenset({()}), False
    if len(branch_sets) == 1:
        return branch_sets[0], False

    current = branch_sets[0]
    truncated = False
    for i in range(1, len(branch_sets)):
        current, t = interleave_trace_sets(current, branch_sets[i], max_count=max_count)
        if t:
            truncated = True
    return current, truncated