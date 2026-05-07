from __future__ import annotations

from ModelInquisitor.core.models import BPMNModel, Claim, ClaimKind
from ModelInquisitor.strategies.base import TranslatorNamingStrategy


class MCFGenerator:
    def __init__(self, strategy: TranslatorNamingStrategy) -> None:
        self.strategy = strategy

    def generate(self, claim: Claim, model: BPMNModel) -> str:
        if claim.kind == ClaimKind.DEADLOCK_FREEDOM:
            return self._deadlock_formula(claim, model)
        if claim.kind == ClaimKind.ACTION_PRESERVATION:
            return self._action_preservation_formula(claim, model)
        if claim.kind == ClaimKind.MESSAGE_SYNCHRONIZATION:
            return self._message_synchronization_formula(claim, model)
        if claim.kind == ClaimKind.CAUSALITY:
            return self._causality_formula(claim, model)
        if claim.kind == ClaimKind.MUTEX:
            return self._mutex_formula(claim, model)
        raise ValueError(f"unsupported claim kind: {claim.kind}")

    def _deadlock_formula(self, claim: Claim, model: BPMNModel) -> str:
        end_actions = [
            action
            for node_id in claim.branch_node_ids
            for action in self.strategy.observable_actions_for_node(model.node(node_id))
        ]
        if not end_actions:
            return "% No end action could be resolved for this process.\nfalse"
        action_expr = " || ".join(self._modal(action) for action in sorted(set(end_actions)))
        return (
            f"% {claim.description}\n"
            f"% Reachability-style deadlock freedom approximation.\n"
            f"<true*>({action_expr})"
        )

    def _action_preservation_formula(self, claim: Claim, model: BPMNModel) -> str:
        action = self._single_action(model, claim.node_id)
        if not action:
            return "% Action preservation claim has unresolved actions.\nfalse"
        return (
            f"% {claim.description}\n"
            f"% The translated model should still be able to observe this BPMN action.\n"
            f"<true*>({self._modal(action)})"
        )

    def _message_synchronization_formula(self, claim: Claim, model: BPMNModel) -> str:
        message_flow_id = claim.metadata.get("message_flow_id") or claim.node_id
        message_flow = next(
            (flow for flow in model.message_flows if flow.id == message_flow_id),
            None,
        )
        if message_flow is None:
            return "% Message synchronization claim has an unknown message flow.\nfalse"

        send, receive, communicated = self.strategy.message_actions(message_flow)
        return (
            f"% {claim.description}\n"
            f"% The message must be observable as a synchronized communication, not as raw send/receive actions.\n"
            f"<true*>({self._modal(communicated)}) &&\n"
            f"[true* . ({self._action_formula(send)})]false &&\n"
            f"[true* . ({self._action_formula(receive)})]false"
        )

    def _causality_formula(self, claim: Claim, model: BPMNModel) -> str:
        source = self._single_action(model, claim.source_node_id)
        target = self._single_action(model, claim.target_node_id)
        if not source or not target:
            return "% Causality claim has unresolved actions.\nfalse"
        return (
            f"% {claim.description}\n"
            f"% Target must not occur before source.\n"
            f"[(!({self._action_formula(source)}))* . ({self._action_formula(target)})]false"
        )

    def _mutex_formula(self, claim: Claim, model: BPMNModel) -> str:
        if len(claim.branch_node_ids) != 2:
            return "% Mutex claim requires exactly two branch nodes.\nfalse"
        left = self._single_action(model, claim.branch_node_ids[0])
        right = self._single_action(model, claim.branch_node_ids[1])
        if not left or not right:
            return "% Mutex claim has unresolved actions.\nfalse"
        return (
            f"% {claim.description}\n"
            f"[true* . ({self._action_formula(left)}) . true* . ({self._action_formula(right)})]false &&\n"
            f"[true* . ({self._action_formula(right)}) . true* . ({self._action_formula(left)})]false"
        )

    def _single_action(self, model: BPMNModel, node_id: str | None) -> str | None:
        if not node_id:
            return None
        actions = self.strategy.observable_actions_for_node(model.node(node_id))
        return actions[0] if actions else None

    def _modal(self, action: str) -> str:
        return f"<{self._action_formula(action)}>true"

    def _action_formula(self, action: str) -> str:
        return f"exists oid: OrderId. {action}(oid)"
