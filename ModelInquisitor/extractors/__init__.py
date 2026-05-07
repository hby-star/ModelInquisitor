"""Claim extractors."""

from ModelInquisitor.core.models import BPMNModel, Claim
from ModelInquisitor.extractors.action_preservation import ActionPreservationExtractor
from ModelInquisitor.extractors.causality import CausalityExtractor
from ModelInquisitor.extractors.deadlock import DeadlockFreedomExtractor
from ModelInquisitor.extractors.message_synchronization import MessageSynchronizationExtractor
from ModelInquisitor.extractors.mutex import MutexExtractor


def extract_claims(model: BPMNModel) -> list[Claim]:
    claims: list[Claim] = []
    for extractor in (
        DeadlockFreedomExtractor(),
        ActionPreservationExtractor(),
        MessageSynchronizationExtractor(),
        CausalityExtractor(),
        MutexExtractor(),
    ):
        claims.extend(extractor.extract(model))
    return claims


__all__ = [
    "ActionPreservationExtractor",
    "CausalityExtractor",
    "DeadlockFreedomExtractor",
    "MessageSynchronizationExtractor",
    "MutexExtractor",
    "extract_claims",
]
