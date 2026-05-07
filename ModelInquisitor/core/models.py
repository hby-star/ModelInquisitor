from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ClaimKind(str, Enum):
    DEADLOCK_FREEDOM = "deadlock_freedom"
    ACTION_PRESERVATION = "action_preservation"
    MESSAGE_SYNCHRONIZATION = "message_synchronization"
    CAUSALITY = "causality"
    MUTEX = "mutex"


@dataclass(frozen=True)
class BPMNNode:
    id: str
    name: str
    type: str
    process_id: str
    event_definitions: tuple[str, ...] = ()
    attached_to: str | None = None
    cancel_activity: bool = True
    condition_texts: tuple[str, ...] = ()

    @property
    def is_task(self) -> bool:
        return self.type in {
            "serviceTask",
            "receiveTask",
            "sendTask",
            "userTask",
            "task",
            "scriptTask",
        }

    @property
    def is_observable(self) -> bool:
        return self.is_task or self.type in {
            "endEvent",
            "boundaryEvent",
            "intermediateCatchEvent",
            "intermediateThrowEvent",
        } or (self.type == "startEvent" and bool(self.event_definitions))


@dataclass(frozen=True)
class SequenceFlow:
    id: str
    source_ref: str
    target_ref: str
    name: str = ""
    process_id: str = ""


@dataclass(frozen=True)
class MessageFlow:
    id: str
    source_ref: str
    target_ref: str
    name: str = ""
    source_process_id: str | None = None
    target_process_id: str | None = None


@dataclass(frozen=True)
class Participant:
    id: str
    name: str
    process_ref: str | None


@dataclass
class ProcessModel:
    id: str
    nodes: dict[str, BPMNNode] = field(default_factory=dict)
    sequence_flows: list[SequenceFlow] = field(default_factory=list)
    starts: list[str] = field(default_factory=list)

    def successors(self, node_id: str) -> list[str]:
        return [flow.target_ref for flow in self.sequence_flows if flow.source_ref == node_id]

    def predecessors(self, node_id: str) -> list[str]:
        return [flow.source_ref for flow in self.sequence_flows if flow.target_ref == node_id]

    def graph_edges(self) -> list[tuple[str, str]]:
        return [(flow.source_ref, flow.target_ref) for flow in self.sequence_flows]

    def to_networkx(self) -> Any:
        """Return a NetworkX DiGraph with BPMN node/edge metadata."""
        import networkx as nx

        graph = nx.DiGraph(process_id=self.id)
        for node in self.nodes.values():
            graph.add_node(node.id, name=node.name, type=node.type, bpmn=node)
        for flow in self.sequence_flows:
            graph.add_edge(
                flow.source_ref,
                flow.target_ref,
                id=flow.id,
                name=flow.name,
                bpmn=flow,
            )
        return graph


@dataclass
class BPMNModel:
    processes: dict[str, ProcessModel] = field(default_factory=dict)
    participants: dict[str, Participant] = field(default_factory=dict)
    message_flows: list[MessageFlow] = field(default_factory=list)
    node_to_process: dict[str, str] = field(default_factory=dict)
    boundary_events_by_attachment: dict[str, list[str]] = field(default_factory=dict)

    def node(self, node_id: str) -> BPMNNode:
        return self.processes[self.node_to_process[node_id]].nodes[node_id]

    def process_for_node(self, node_id: str) -> ProcessModel:
        return self.processes[self.node_to_process[node_id]]


@dataclass(frozen=True)
class Claim:
    kind: ClaimKind
    process_id: str | None = None
    node_id: str | None = None
    source_node_id: str | None = None
    target_node_id: str | None = None
    branch_node_ids: tuple[str, ...] = ()
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
