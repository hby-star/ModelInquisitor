from __future__ import annotations

from dataclasses import dataclass, field

from ModelInquisitor.core.graph import find_join
from ModelInquisitor.core.interleave import TraceSet, interleave_multi
from ModelInquisitor.core.lts import LTS, strip_data_params
from ModelInquisitor.core.models import BPMNModel, ProcessModel
from ModelInquisitor.strategies.base import TranslatorNamingStrategy

Trace = tuple[str, ...]


@dataclass(frozen=True)
class TraceConfig:
    max_trace_length: int = 50
    max_trace_count: int = 1000


@dataclass
class TraceComparison:
    bpmn_only: TraceSet
    mcrl2_only: TraceSet
    common: TraceSet

    @property
    def is_equivalent(self) -> bool:
        return not self.bpmn_only and not self.mcrl2_only


class TraceExtractor:
    """Extract observable traces from BPMN models and mCRL2 LTS."""

    def __init__(self, strategy: TranslatorNamingStrategy, config: TraceConfig | None = None) -> None:
        self.strategy = strategy
        self.config = config or TraceConfig()

    def per_process_claim_actions(self, model: BPMNModel) -> dict[str, set[str]]:
        """Compute per-process observable action sets from the naming strategy.

        Each process's set includes observable actions of its own nodes plus
        communicated actions from message flows that touch the process.
        """
        result: dict[str, set[str]] = {}
        for process_id, process in model.processes.items():
            actions: set[str] = set()
            for node in process.nodes.values():
                actions.update(self.strategy.observable_actions_for_node(node))
            result[process_id] = actions
        # Add communicated actions from message flows to both participant processes
        for message_flow in model.message_flows:
            _, _, communicated = self.strategy.message_actions(message_flow)
            if message_flow.source_process_id and message_flow.source_process_id in result:
                result[message_flow.source_process_id].add(communicated)
            if message_flow.target_process_id and message_flow.target_process_id in result:
                result[message_flow.target_process_id].add(communicated)
        return result

    # -- BPMN side --

    def bpmn_traces(self, model: BPMNModel) -> dict[str, TraceSet]:
        """Extract per-process observable trace sets from a BPMN model."""
        result: dict[str, TraceSet] = {}
        for process_id, process in model.processes.items():
            result[process_id] = self.bpmn_traces_for_process(model, process)
        return result

    def bpmn_traces_for_process(self, model: BPMNModel, process: ProcessModel) -> TraceSet:
        """Extract all observable action traces for a single process."""
        all_traces: set[Trace] = set()
        for start_id in process.starts:
            for trace in self._walk(start_id, process, model, set()):
                if len(all_traces) < self.config.max_trace_count:
                    all_traces.add(trace)
        return frozenset(all_traces)

    def _walk(
        self,
        node_id: str,
        process: ProcessModel,
        model: BPMNModel,
        visited_forks: set[str],
    ) -> list[Trace]:
        """Recursively walk the process graph, producing traces of observable actions."""
        node = process.nodes.get(node_id)
        if node is None:
            return [()]

        # Current node's observable actions (may be empty for gateways, plain start events)
        current_actions: tuple[str, ...] = ()
        if node.is_observable:
            current_actions = self.strategy.observable_actions_for_node(node)

        successors = process.successors(node_id)

        # Terminal node (end event, dead end)
        if not successors:
            if current_actions:
                return [current_actions]
            return [()]

        # Parallel gateway fork: interleave branch traces
        if node.type == "parallelGateway" and len(successors) > 1 and node_id not in visited_forks:
            join = find_join(process, successors)
            branch_sets: list[TraceSet] = []
            for succ in successors:
                branch_traces = self._walk_branch(succ, process, model, join, visited_forks | {node_id})
                branch_sets.append(frozenset(branch_traces))
            interleaved, truncated = interleave_multi(branch_sets, max_count=self.config.max_trace_count)
            if truncated:
                interleaved = frozenset(list(interleaved)[:self.config.max_trace_count])
            after_join: list[Trace] = []
            if join and join in process.nodes:
                after_join = self._walk(join, process, model, visited_forks | {node_id})
            else:
                after_join = [()]
            result: list[Trace] = []
            for il in interleaved:
                for suffix in after_join:
                    full_trace = current_actions + il + suffix
                    if len(full_trace) <= self.config.max_trace_length:
                        result.append(full_trace)
            return result

        # Exclusive gateway: union of branch traces
        if node.type == "exclusiveGateway" and len(successors) > 1:
            join = find_join(process, successors)
            result: list[Trace] = []
            for succ in successors:
                branch_traces = self._walk_branch(succ, process, model, join, visited_forks)
                for bt in branch_traces:
                    full_trace = current_actions + bt
                    if len(full_trace) <= self.config.max_trace_length:
                        result.append(full_trace)
            if join and join in process.nodes:
                after_join = self._walk(join, process, model, visited_forks)
                extended: list[Trace] = []
                for t in result:
                    for suffix in after_join:
                        extended.append(t + suffix)
                return extended
            return result

        # Regular successor traversal (single or multiple)
        result: list[Trace] = []
        for succ in successors:
            suffixes = self._walk(succ, process, model, visited_forks)
            for suffix in suffixes:
                full_trace = current_actions + suffix
                if len(full_trace) <= self.config.max_trace_length:
                    result.append(full_trace)
        return result

    def _walk_branch(
        self,
        start_id: str,
        process: ProcessModel,
        model: BPMNModel,
        stop_at: str | None,
        visited_forks: set[str],
    ) -> list[Trace]:
        """Walk a branch from start_id up to (but not including) stop_at."""
        node = process.nodes.get(start_id)
        if node is None or start_id == stop_at:
            return [()]

        current_actions: tuple[str, ...] = ()
        if node.is_observable:
            current_actions = self.strategy.observable_actions_for_node(node)

        successors = process.successors(start_id)

        # If we reach stop_at among successors, the branch ends here
        filtered = [s for s in successors if s != stop_at]
        if not filtered:
            if current_actions:
                return [current_actions]
            return [()]

        # Parallel gateway within branch
        if node.type == "parallelGateway" and len(filtered) > 1 and start_id not in visited_forks:
            join = find_join(process, filtered)
            branch_sets: list[TraceSet] = []
            for succ in filtered:
                bt = self._walk_branch(succ, process, model, join, visited_forks | {start_id})
                branch_sets.append(frozenset(bt))
            interleaved, truncated = interleave_multi(branch_sets, max_count=self.config.max_trace_count)
            if truncated:
                interleaved = frozenset(list(interleaved)[:self.config.max_trace_count])
            after: list[Trace] = []
            if join and join != stop_at and join in process.nodes:
                after = self._walk_branch(join, process, model, stop_at, visited_forks | {start_id})
            else:
                after = [()]
            result: list[Trace] = []
            for il in interleaved:
                for suffix in after:
                    result.append(current_actions + il + suffix)
            return result

        # Exclusive gateway within branch
        if node.type == "exclusiveGateway" and len(filtered) > 1:
            join = find_join(process, filtered)
            result: list[Trace] = []
            for succ in filtered:
                bt = self._walk_branch(succ, process, model, join, visited_forks)
                for t in bt:
                    result.append(current_actions + t)
            if join and join != stop_at and join in process.nodes:
                after = self._walk_branch(join, process, model, stop_at, visited_forks)
                extended: list[Trace] = []
                for t in result:
                    for suffix in after:
                        extended.append(t + suffix)
                return extended
            return result

        # Regular successor
        result: list[Trace] = []
        for succ in filtered:
            suffixes = self._walk_branch(succ, process, model, stop_at, visited_forks)
            for suffix in suffixes:
                result.append(current_actions + suffix)
        return result

    # -- mCRL2 LTS side --

    def mcrl2_traces(self, lts: LTS, claim_actions: set[str]) -> TraceSet:
        """Extract all observable traces from an mCRL2 LTS, filtering to claim actions."""
        traces: set[Trace] = set()
        # Iterative DFS with explicit stack
        # Each stack entry: (current_state, trace_so_far, tau_visited_states)
        stack: list[tuple[int, Trace, set[int]]] = [(lts.initial_state, (), set())]

        while stack and len(traces) < self.config.max_trace_count:
            state, trace, tau_visited = stack.pop()

            outgoing = lts.outgoing(state)

            if not outgoing:
                # Terminal state: finalize trace (including empty trace)
                traces.add(trace)
                continue

            has_observable = False
            for trans in outgoing:
                bare_label = strip_data_params(trans.label)
                if bare_label in claim_actions:
                    has_observable = True
                    if len(trace) + 1 <= self.config.max_trace_length:
                        stack.append((trans.target, trace + (bare_label,), set()))
                else:
                    # Tau-like transition: move without recording
                    if trans.target not in tau_visited and len(trace) <= self.config.max_trace_length:
                        stack.append((trans.target, trace, tau_visited | {state}))

            # If state has no observable outgoing transitions and all tau paths
            # lead back (tau-loop), or state is a tau-dead-end,
            # consider this trace maximal (including empty trace).
            if not has_observable:
                # Check if we can reach a different state via tau transitions
                reachable_via_tau = False
                for trans in outgoing:
                    bare_label = strip_data_params(trans.label)
                    if bare_label not in claim_actions and trans.target not in tau_visited:
                        reachable_via_tau = True
                        break
                if not reachable_via_tau:
                    traces.add(trace)

        return frozenset(traces)

    # -- Comparison --

    def compare_traces(self, bpmn_traces: TraceSet, mcrl2_traces: TraceSet) -> TraceComparison:
        """Compare two trace sets and categorize differences."""
        return TraceComparison(
            bpmn_only=bpmn_traces - mcrl2_traces,
            mcrl2_only=mcrl2_traces - bpmn_traces,
            common=bpmn_traces & mcrl2_traces,
        )