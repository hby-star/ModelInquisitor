from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ModelInquisitor.core.lts import LTS, parse_aut
from ModelInquisitor.core.traces import TraceComparison, TraceConfig, TraceExtractor, TraceSet
from ModelInquisitor.parsers.bpmn import BPMNParser
from ModelInquisitor.runners.lts_generator import LTSGenerator, LTSGenerationResult
from ModelInquisitor.strategies.base import TranslatorNamingStrategy
from ModelInquisitor.strategies.third_party_bpmn2mcrl2 import ThirdPartyBpmn2Mcrl2Strategy


@dataclass
class TraceVerificationResult:
    status: str  # "equivalent", "not_equivalent", "model_error", "not_run", "bounded"
    per_process: dict[str, TraceComparison] = field(default_factory=dict)
    config: TraceConfig = field(default_factory=TraceConfig)
    output: str = ""
    lts_result: LTSGenerationResult | None = None

    @property
    def is_equivalent(self) -> bool:
        return self.status == "equivalent"


class TraceVerificationRunner:
    """Run trace equivalence checking between BPMN and mCRL2."""

    def __init__(
        self,
        strategy: TranslatorNamingStrategy | None = None,
        config: TraceConfig | None = None,
    ) -> None:
        self.strategy = strategy or ThirdPartyBpmn2Mcrl2Strategy()
        self.config = config or TraceConfig()

    def verify(
        self,
        bpmn_path: str | Path,
        mcrl2_path: str | Path,
        *,
        work_dir: str | Path | None = None,
    ) -> TraceVerificationResult:
        # 1. Parse BPMN and prepare strategy
        model = BPMNParser().parse(bpmn_path)
        self.strategy.prepare(model)
        claim_actions = self.strategy.all_claim_actions(model)

        # 2. Generate LTS from mCRL2
        lts_generator = LTSGenerator()
        lts_result = lts_generator.generate(mcrl2_path, work_dir=work_dir)

        if lts_result.status != "success":
            return TraceVerificationResult(
                status="model_error" if lts_result.status == "model_error" else "not_run",
                config=self.config,
                output=lts_result.output,
                lts_result=lts_result,
            )

        # 3. Parse the .aut file
        aut_path = lts_result.lts_path
        if not aut_path or not aut_path.exists():
            return TraceVerificationResult(
                status="model_error",
                config=self.config,
                output=f"Generated .aut file not found at {aut_path}",
                lts_result=lts_result,
            )

        aut_text = aut_path.read_text(encoding="utf-8")
        lts = parse_aut(aut_text)

        # 4. Extract traces and compare per process
        extractor = TraceExtractor(self.strategy, self.config)
        bpmn_traces_dict = extractor.bpmn_traces(model)
        per_process_actions = extractor.per_process_claim_actions(model)

        per_process: dict[str, TraceComparison] = {}
        all_equivalent = True

        for process_id, bpmn_traces in bpmn_traces_dict.items():
            # Project global LTS traces onto this process's claim actions.
            # Actions belonging to other processes become tau (transparent).
            process_actions = per_process_actions.get(process_id, claim_actions)
            mcrl2_traces = extractor.mcrl2_traces(lts, process_actions)
            comparison = extractor.compare_traces(bpmn_traces, mcrl2_traces)
            per_process[process_id] = comparison
            if not comparison.is_equivalent:
                all_equivalent = False

        # Check for trace count bounds
        total_trace_count = sum(len(c.common) + len(c.bpmn_only) + len(c.mcrl2_only) for c in per_process.values())
        bounded = total_trace_count >= self.config.max_trace_count

        if bounded:
            status = "bounded"
        elif all_equivalent:
            status = "equivalent"
        else:
            status = "not_equivalent"

        return TraceVerificationResult(
            status=status,
            per_process=per_process,
            config=self.config,
            lts_result=lts_result,
        )