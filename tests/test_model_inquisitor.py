from io import StringIO
from pathlib import Path

from ModelInquisitor.core.interleave import interleave_multi, interleave_sequences, interleave_trace_sets
from ModelInquisitor.core.lts import LTS, LTSTransition, parse_aut, strip_data_params
from ModelInquisitor.core.models import ClaimKind
from ModelInquisitor.core.traces import TraceComparison, TraceConfig, TraceExtractor
from ModelInquisitor.extractors import extract_claims
from ModelInquisitor.generators.mcf import MCFGenerator
from ModelInquisitor.parsers.bpmn import BPMNParser
from ModelInquisitor.strategies.third_party_bpmn2mcrl2 import (
    ThirdPartyBpmn2Mcrl2Strategy,
    clean_name,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC_BPMN = ROOT / "tests" / "input" / "spec.bpmn"
SPEC_MCRL2 = ROOT / "tests" / "input" / "spec.mcrl2"
THIRD_PARTY_FEATURE_BPMN = ROOT / "third-party" / "bpmn2mcrl2" / "samples" / "sample2" / "camunda" / "feature.bpmn"
THIRD_PARTY_FEATURE_MCRL2 = ROOT / "third-party" / "bpmn2mcrl2" / "samples" / "sample2" / "manual-test-output" / "feature.mcrl2"
THIRD_PARTY_PIZZA_BPMN = ROOT / "third-party" / "bpmn2mcrl2" / "samples" / "sample3" / "camunda" / "pizza-collaboration.bpmn"
THIRD_PARTY_PIZZA_MCRL2 = ROOT / "third-party" / "bpmn2mcrl2" / "samples" / "sample3" / "mcrl2" / "pizza-collaboration_output.mcrl2"


def parse_inline_bpmn(xml: str):
    return BPMNParser().parse(StringIO(xml))


def test_clean_name_matches_third_party_convention():
    assert clean_name("FFW_Send_Request") == "ffw_send_request"
    assert clean_name("Freight Forwarder (FFW)") == "freight_forwarder__ffw"
    assert clean_name("") == "unnamed_action"


def test_parser_keeps_collaboration_metadata():
    model = BPMNParser().parse(SPEC_BPMN)
    assert set(model.processes) == {"Process_FFW", "Process_SAG"}
    assert model.node("Task_FFW_Send").name == "FFW_Send_Request"
    assert model.processes["Process_FFW"].to_networkx().has_edge("Task_FFW_Send", "ParallelGateway_1")
    assert len(model.message_flows) == 3
    assert model.message_flows[0].source_process_id == "Process_FFW"
    assert model.message_flows[0].target_process_id == "Process_SAG"


def test_third_party_strategy_resolves_sample_actions_in_mcrl2():
    model = BPMNParser().parse(SPEC_BPMN)
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    mcrl2_text = SPEC_MCRL2.read_text(encoding="utf-8")

    task_action = strategy.action_for_node(model.node("Task_FFW_Send"))
    recv_action = strategy.action_for_node(model.node("ReceiveTask_3"))
    assert task_action == "s_send_request"
    assert recv_action == "r_send_request"
    assert strategy.auxiliary_actions_for_node(model.node("Task_FFW_Send")) == ("s_send_request",)
    assert strategy.observable_actions_for_node(model.node("Task_FFW_Send")) == ("c_send_request",)
    assert "c_send_request" in strategy.all_claim_actions(model)
    assert "s_send_request" not in strategy.all_claim_actions(model)
    assert "r_send_request" not in strategy.all_claim_actions(model)
    assert "c_start_gw_1" not in strategy.all_claim_actions(model)
    assert "gw_1_branch_0" in strategy.sync_actions_for_parallel_gateway("ParallelGateway_1", 2)["branch_processes"]

    for action in sorted(strategy.all_claim_actions(model)):
        assert action in mcrl2_text


def test_strategy_matches_third_party_feature_sample():
    model = BPMNParser().parse(THIRD_PARTY_FEATURE_BPMN)
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    mcrl2_text = THIRD_PARTY_FEATURE_MCRL2.read_text(encoding="utf-8")

    assert sorted(strategy.all_claim_actions(model)) == [
        "accept_feature_request",
        "handle_feature_request",
        "reject_feature_request",
    ]
    for action in strategy.all_claim_actions(model):
        assert action in mcrl2_text


def test_message_catch_event_prefers_communicated_message_action():
    model = BPMNParser().parse(THIRD_PARTY_PIZZA_BPMN)
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    generator = MCFGenerator(strategy)
    mcrl2_text = THIRD_PARTY_PIZZA_MCRL2.read_text(encoding="utf-8")

    catch_node = model.node("CatchEvent_PizzaReceived")
    assert strategy.action_for_node(catch_node) == "r_pizza"
    assert strategy.observable_actions_for_node(catch_node) == ("c_pizza",)
    assert "event_pizza_received" not in strategy.all_claim_actions(model)

    claim = next(
        claim for claim in extract_claims(model)
        if claim.kind == ClaimKind.CAUSALITY
        and claim.source_node_id == "CatchEvent_PizzaReceived"
        and claim.target_node_id == "Task_PayPizza"
    )
    formula = generator.generate(claim, model)

    assert "c_pizza(oid)" in formula
    assert "event_pizza_received" not in formula
    for action in strategy.all_claim_actions(model):
        assert action in mcrl2_text


def test_extract_claims_and_generate_mcf_formulas():
    model = BPMNParser().parse(SPEC_BPMN)
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    generator = MCFGenerator(strategy)
    claims = extract_claims(model)

    assert any(claim.kind.value == "deadlock_freedom" for claim in claims)
    assert any(claim.kind.value == "causality" for claim in claims)

    formulas = [generator.generate(claim, model) for claim in claims]
    assert any("endevent_1" in formula for formula in formulas)
    assert any("c_send_request" in formula for formula in formulas)


def test_message_flows_extract_synchronization_claims():
    model = BPMNParser().parse(SPEC_BPMN)
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    generator = MCFGenerator(strategy)

    claims = [
        claim for claim in extract_claims(model)
        if claim.kind == ClaimKind.MESSAGE_SYNCHRONIZATION
    ]

    assert len(claims) == 3
    assert any(
        claim.source_node_id == "Task_FFW_Send"
        and claim.target_node_id == "ReceiveTask_3"
        for claim in claims
    )
    formula = generator.generate(claims[0], model)
    assert "c_send_" in formula
    assert "s_send_" not in formula
    assert "r_send_" not in formula


def test_interrupting_boundary_event_extracts_absolute_mutex():
    model = parse_inline_bpmn(
        """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_Boundary" isExecutable="true">
    <bpmn:startEvent id="Start" />
    <bpmn:task id="OriginalTask" name="Original" />
    <bpmn:task id="NormalTask" name="Normal" />
    <bpmn:boundaryEvent id="TimeoutBoundary" attachedToRef="OriginalTask">
      <bpmn:timerEventDefinition />
    </bpmn:boundaryEvent>
    <bpmn:task id="RecoveryTask" name="Recover" />
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start" targetRef="OriginalTask" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="OriginalTask" targetRef="NormalTask" />
    <bpmn:sequenceFlow id="Flow_3" sourceRef="NormalTask" targetRef="End" />
    <bpmn:sequenceFlow id="Flow_4" sourceRef="TimeoutBoundary" targetRef="RecoveryTask" />
    <bpmn:sequenceFlow id="Flow_5" sourceRef="RecoveryTask" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
""",
    )

    claims = [
        claim for claim in extract_claims(model)
        if claim.kind == ClaimKind.MUTEX
        and claim.metadata.get("source") == "interrupting_boundary_event"
    ]

    assert len(claims) == 1
    assert claims[0].node_id == "TimeoutBoundary"
    assert claims[0].branch_node_ids == ("RecoveryTask", "NormalTask")


def test_necessary_response_uses_post_dominators():
    model = parse_inline_bpmn(
        """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_Response" isExecutable="true">
    <bpmn:startEvent id="Start" />
    <bpmn:task id="A" name="A" />
    <bpmn:exclusiveGateway id="Split" />
    <bpmn:task id="B" name="B" />
    <bpmn:task id="C" name="C" />
    <bpmn:exclusiveGateway id="Join" />
    <bpmn:task id="D" name="D" />
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start" targetRef="A" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="A" targetRef="Split" />
    <bpmn:sequenceFlow id="Flow_3" sourceRef="Split" targetRef="B" />
    <bpmn:sequenceFlow id="Flow_4" sourceRef="Split" targetRef="C" />
    <bpmn:sequenceFlow id="Flow_5" sourceRef="B" targetRef="Join" />
    <bpmn:sequenceFlow id="Flow_6" sourceRef="C" targetRef="Join" />
    <bpmn:sequenceFlow id="Flow_7" sourceRef="Join" targetRef="D" />
    <bpmn:sequenceFlow id="Flow_8" sourceRef="D" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
""",
    )
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    generator = MCFGenerator(strategy)

    claims = [
        claim for claim in extract_claims(model)
        if claim.kind == ClaimKind.NECESSARY_RESPONSE
    ]

    assert any(
        claim.source_node_id == "A" and claim.target_node_id == "D"
        for claim in claims
    )
    assert not any(
        claim.source_node_id == "A" and claim.target_node_id == "B"
        for claim in claims
    )
    formula = generator.generate(
        next(
            claim for claim in claims
            if claim.source_node_id == "A" and claim.target_node_id == "D"
        ),
        model,
    )
    assert "nu X" in formula
    assert "target reachable" in formula
    assert "a(oid)" in formula
    assert "d(oid)" in formula


def test_necessary_response_ignores_no_exit_loop_regions():
    model = parse_inline_bpmn(
        """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_Loop" isExecutable="true">
    <bpmn:startEvent id="Start" />
    <bpmn:parallelGateway id="Split" />
    <bpmn:task id="LoopA" name="Loop A" />
    <bpmn:task id="LoopB" name="Loop B" />
    <bpmn:task id="MainA" name="Main A" />
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start" targetRef="Split" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Split" targetRef="LoopA" />
    <bpmn:sequenceFlow id="Flow_3" sourceRef="LoopA" targetRef="LoopB" />
    <bpmn:sequenceFlow id="Flow_4" sourceRef="LoopB" targetRef="LoopA" />
    <bpmn:sequenceFlow id="Flow_5" sourceRef="Split" targetRef="MainA" />
    <bpmn:sequenceFlow id="Flow_6" sourceRef="MainA" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
""",
    )

    claims = [
        claim for claim in extract_claims(model)
        if claim.kind == ClaimKind.NECESSARY_RESPONSE
    ]

    assert any(
        claim.source_node_id == "MainA" and claim.target_node_id == "End"
        for claim in claims
    )
    assert not any(claim.source_node_id == "LoopA" for claim in claims)
    assert not any(claim.source_node_id == "LoopB" for claim in claims)


# -- LTS & trace equivalence tests --


def test_strip_data_params():
    assert strip_data_params("c_send_request(order_id(1))") == "c_send_request"
    assert strip_data_params("endevent_1") == "endevent_1"
    assert strip_data_params("tau") == "tau"


def test_parse_aut():
    aut_text = "des (0, 21, 16)\n(0, \"c_send_request\", 1)\n(1, \"c_start_gw_1\", 2)\n(2, \"endevent_1\", 3)"
    lts = parse_aut(aut_text)
    assert lts.initial_state == 0
    assert len(lts.transitions) == 3
    assert lts.outgoing(0) == [LTSTransition(0, "c_send_request", 1)]
    assert lts.is_terminal(3)


def test_parse_aut_with_data_params():
    aut_text = "des(0, 1, 2)\n(0, \"c_send_request(order_id(1))\", 1)"
    lts = parse_aut(aut_text)
    assert strip_data_params(lts.transitions[0].label) == "c_send_request"


def test_interleave_sequences_basic():
    result = interleave_sequences(("a",), ("b",))
    assert result == {("a", "b"), ("b", "a")}


def test_interleave_sequences_preserves_order():
    result = interleave_sequences(("a1", "a2"), ("b1",))
    assert ("a1", "a2", "b1") in result
    assert ("a1", "b1", "a2") in result
    assert ("b1", "a1", "a2") in result
    assert len(result) == 3


def test_interleave_sequences_empty():
    assert interleave_sequences(("a",), ()) == {("a",)}
    assert interleave_sequences((), ("b",)) == {("b",)}
    assert interleave_sequences((), ()) == {()}


def test_interleave_multi_two_branches():
    result, truncated = interleave_multi(
        [frozenset({("a",)}), frozenset({("b",)})],
        max_count=100,
    )
    assert result == frozenset({("a", "b"), ("b", "a")})
    assert not truncated


def test_interleave_trace_sets_truncation():
    big_set = frozenset({(f"a{i}",) for i in range(20)})
    result, truncated = interleave_trace_sets(big_set, big_set, max_count=10)
    assert truncated
    assert len(result) <= 10


def test_trace_comparison_equivalent():
    common = frozenset({("a", "b"), ("a", "c")})
    comp = TraceComparison(bpmn_only=frozenset(), mcrl2_only=frozenset(), common=common)
    assert comp.is_equivalent


def test_trace_comparison_not_equivalent():
    comp = TraceComparison(
        bpmn_only=frozenset({("a", "b")}),
        mcrl2_only=frozenset({("x", "y")}),
        common=frozenset({("a", "c")}),
    )
    assert not comp.is_equivalent


def test_bpmn_traces_linear_process():
    model = parse_inline_bpmn(
        """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="Start" />
    <bpmn:serviceTask id="TaskA" name="A" />
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="F1" sourceRef="Start" targetRef="TaskA" />
    <bpmn:sequenceFlow id="F2" sourceRef="TaskA" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
""",
    )
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    extractor = TraceExtractor(strategy)
    traces = extractor.bpmn_traces_for_process(model, model.processes["P"])
    assert traces == frozenset({("a", "end")})


def test_bpmn_traces_exclusive_gateway():
    model = parse_inline_bpmn(
        """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="Start" />
    <bpmn:task id="A" name="A" />
    <bpmn:exclusiveGateway id="Split" />
    <bpmn:task id="B" name="B" />
    <bpmn:task id="C" name="C" />
    <bpmn:exclusiveGateway id="Join" />
    <bpmn:task id="D" name="D" />
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="F1" sourceRef="Start" targetRef="A" />
    <bpmn:sequenceFlow id="F2" sourceRef="A" targetRef="Split" />
    <bpmn:sequenceFlow id="F3" sourceRef="Split" targetRef="B" />
    <bpmn:sequenceFlow id="F4" sourceRef="Split" targetRef="C" />
    <bpmn:sequenceFlow id="F5" sourceRef="B" targetRef="Join" />
    <bpmn:sequenceFlow id="F6" sourceRef="C" targetRef="Join" />
    <bpmn:sequenceFlow id="F7" sourceRef="Join" targetRef="D" />
    <bpmn:sequenceFlow id="F8" sourceRef="D" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
""",
    )
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    extractor = TraceExtractor(strategy)
    traces = extractor.bpmn_traces_for_process(model, model.processes["P"])
    # Two exclusive branches: A->B->D->end and A->C->D->end
    assert ("a", "b", "d", "end") in traces
    assert ("a", "c", "d", "end") in traces
    assert len(traces) == 2


def test_bpmn_traces_parallel_gateway():
    model = BPMNParser().parse(SPEC_BPMN)
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    extractor = TraceExtractor(strategy)
    ffw_traces = extractor.bpmn_traces_for_process(model, model.processes["Process_FFW"])
    # FFW: c_send_request -> (c_send_manifest, c_send_eir interleaved) -> endevent_1
    assert ("c_send_request", "c_send_manifest", "c_send_eir", "endevent_1") in ffw_traces
    assert ("c_send_request", "c_send_eir", "c_send_manifest", "endevent_1") in ffw_traces
    assert len(ffw_traces) == 2


def test_mcrl2_traces_from_handbuilt_lts():
    # Simple linear LTS: c_send_request -> c_send_manifest -> endevent_1
    adj = {
        0: [LTSTransition(0, "c_send_request", 1)],
        1: [LTSTransition(1, "c_start_gw_1", 2)],  # tau for trace purposes
        2: [LTSTransition(2, "c_send_manifest", 3)],
        3: [LTSTransition(3, "c_send_eir", 4)],
        4: [LTSTransition(4, "c_sync_join_1", 5)],  # tau
        5: [LTSTransition(5, "endevent_1", 6)],
    }
    lts = LTS(initial_state=0, states={0, 1, 2, 3, 4, 5, 6}, transitions=[], _adj=adj)
    claim_actions = {"c_send_request", "c_send_manifest", "c_send_eir", "endevent_1"}
    extractor = TraceExtractor(ThirdPartyBpmn2Mcrl2Strategy())
    traces = extractor.mcrl2_traces(lts, claim_actions)
    assert ("c_send_request", "c_send_manifest", "c_send_eir", "endevent_1") in traces


def test_mcrl2_traces_with_branching_lts():
    # LTS that branches after c_send_request
    adj = {
        0: [LTSTransition(0, "c_send_request", 1)],
        1: [
            LTSTransition(1, "c_start_gw_1", 2),  # tau
            LTSTransition(1, "c_start_gw_1", 3),  # tau to different branch
        ],
        2: [LTSTransition(2, "c_send_manifest", 4)],
        3: [LTSTransition(3, "c_send_eir", 4)],
        4: [LTSTransition(4, "endevent_1", 5)],
    }
    lts = LTS(initial_state=0, states={0, 1, 2, 3, 4, 5}, transitions=[], _adj=adj)
    claim_actions = {"c_send_request", "c_send_manifest", "c_send_eir", "endevent_1"}
    extractor = TraceExtractor(ThirdPartyBpmn2Mcrl2Strategy())
    traces = extractor.mcrl2_traces(lts, claim_actions)
    assert ("c_send_request", "c_send_manifest", "endevent_1") in traces
    assert ("c_send_request", "c_send_eir", "endevent_1") in traces


def test_trace_main_standalone_equivalence_check():
    """End-to-end test of trace extraction + comparison without mCRL2 toolchain."""
    model = BPMNParser().parse(SPEC_BPMN)
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    claim_actions = strategy.all_claim_actions(model)
    extractor = TraceExtractor(strategy)

    # Build a synthetic LTS that models FFW parallel interleavings
    # state 0: c_send_request → 1
    # state 1: tau (c_start_gw_1) → 2
    # state 2: c_send_manifest → 3, c_send_eir → 4  (interleaving start)
    # state 3: c_send_eir → 5  (manifest first, then eir)
    # state 4: c_send_manifest → 5  (eir first, then manifest)
    # state 5: tau (c_sync_join_1) → 6, endevent_1 → 7
    adj = {
        0: [LTSTransition(0, "c_send_request", 1)],
        1: [LTSTransition(1, "c_start_gw_1", 2)],
        2: [
            LTSTransition(2, "c_send_manifest", 3),
            LTSTransition(2, "c_send_eir", 4),
        ],
        3: [LTSTransition(3, "c_send_eir", 5)],
        4: [LTSTransition(4, "c_send_manifest", 5)],
        5: [LTSTransition(5, "c_sync_join_1", 6)],
        6: [LTSTransition(6, "endevent_1", 7)],
    }
    lts = LTS(initial_state=0, states={0, 1, 2, 3, 4, 5, 6, 7}, transitions=[], _adj=adj)

    mcrl2_traces = extractor.mcrl2_traces(lts, claim_actions)
    bpmn_traces = extractor.bpmn_traces_for_process(model, model.processes["Process_FFW"])
    comp = extractor.compare_traces(bpmn_traces, mcrl2_traces)

    assert comp.is_equivalent


def test_interleave_multi_truncation_preserves_all_branches():
    """When truncation occurs, all branch actions must still appear in results."""
    branch_a = frozenset({("a1", "a2")})
    branch_b = frozenset({("b1",)})
    branch_c = frozenset({("c1",)})
    # With a very low max_count, truncation will happen,
    # but every resulting trace must contain actions from all three branches.
    result, truncated = interleave_multi(
        [branch_a, branch_b, branch_c],
        max_count=3,
    )
    assert truncated  # truncation is expected for the 6-way shuffle of 3 branches
    # Before the fix, break would skip branch_c entirely,
    # producing traces that only interleave a and b (missing c actions).
    for trace in result:
        has_a = "a1" in trace and "a2" in trace
        has_b = "b1" in trace
        has_c = "c1" in trace
        assert has_a and has_b and has_c, (
            f"Trace {trace} is missing branch actions "
            f"(has_a={has_a}, has_b={has_b}, has_c={has_c})"
        )


def test_mcrl2_traces_records_empty_trace_on_terminal_initial_state():
    """If the LTS initial state is terminal with no outgoing transitions,
    the empty trace () must be recorded so it matches the BPMN side."""
    adj = {}  # state 0 has no outgoing transitions
    lts = LTS(initial_state=0, states={0}, transitions=[], _adj=adj)
    claim_actions = {"a", "b"}
    extractor = TraceExtractor(ThirdPartyBpmn2Mcrl2Strategy())
    traces = extractor.mcrl2_traces(lts, claim_actions)
    assert () in traces


def test_mcrl2_traces_empty_trace_via_tau_to_terminal():
    """Tau transitions to a terminal state should produce the empty trace."""
    adj = {
        0: [LTSTransition(0, "tau", 1)],  # tau (not a claim action) to terminal
    }
    lts = LTS(initial_state=0, states={0, 1}, transitions=[], _adj=adj)
    claim_actions = {"a", "b"}
    extractor = TraceExtractor(ThirdPartyBpmn2Mcrl2Strategy())
    traces = extractor.mcrl2_traces(lts, claim_actions)
    assert () in traces
