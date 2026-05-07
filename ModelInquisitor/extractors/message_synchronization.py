from __future__ import annotations

from ModelInquisitor.core.models import BPMNModel, Claim, ClaimKind


class MessageSynchronizationExtractor:
    def extract(self, model: BPMNModel) -> list[Claim]:
        claims: list[Claim] = []
        for message_flow in model.message_flows:
            claims.append(
                Claim(
                    kind=ClaimKind.MESSAGE_SYNCHRONIZATION,
                    node_id=message_flow.id,
                    description=f"Message flow {message_flow.id} should synchronize through a communicated action.",
                    metadata={"message_flow_id": message_flow.id},
                )
            )
        return claims
