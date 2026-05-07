import shutil
from pathlib import Path

import pytest

from ModelInquisitor.extractors import extract_claims
from ModelInquisitor.generators.mcf import MCFGenerator
from ModelInquisitor.parsers.bpmn import BPMNParser
from ModelInquisitor.runners.verifier import VerificationRunner
from ModelInquisitor.strategies.third_party_bpmn2mcrl2 import (
    ThirdPartyBpmn2Mcrl2Strategy,
    clean_name,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC_BPMN = ROOT / "tests" / "input" / "spec.bpmn"
SPEC_MCRL2 = ROOT / "tests" / "input" / "spec.mcrl2"
THIRD_PARTY_FEATURE_BPMN = ROOT / "third-party" / "bpmn2mcrl2" / "samples" / "sample2" / "camunda" / "feature.bpmn"
THIRD_PARTY_FEATURE_MCRL2 = ROOT / "third-party" / "bpmn2mcrl2" / "samples" / "sample2" / "manual-test-output" / "feature.mcrl2"


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
    assert "c_send_request" in strategy.all_claim_actions(model)
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


def test_extract_claims_and_generate_mcf_formulas():
    model = BPMNParser().parse(SPEC_BPMN)
    strategy = ThirdPartyBpmn2Mcrl2Strategy()
    strategy.prepare(model)
    generator = MCFGenerator(strategy)
    claims = extract_claims(model)

    assert any(claim.kind.value == "deadlock_freedom" for claim in claims)
    assert any(claim.kind.value == "action_preservation" for claim in claims)
    assert any(claim.kind.value == "message_synchronization" for claim in claims)
    assert any(claim.kind.value == "causality" for claim in claims)
    assert sum(claim.kind.value == "action_preservation" for claim in claims) == 8
    assert sum(claim.kind.value == "message_synchronization" for claim in claims) == 3

    formulas = [generator.generate(claim, model) for claim in claims]
    assert any("endevent_1" in formula for formula in formulas)
    assert any("c_send_request" in formula for formula in formulas)
    assert any("s_send_request" in formula and "r_send_request" in formula for formula in formulas)
    assert any("Observable node Task_FFW_Send" in formula for formula in formulas)


def test_mcrl2_toolchain_verifies_sample_claims(tmp_path):
    required_tools = ("mcrl22lps", "lps2pbes", "pbes2bool")
    missing_tools = [tool for tool in required_tools if shutil.which(tool) is None]
    if missing_tools:
        pytest.skip(f"mCRL2 toolchain not available: {', '.join(missing_tools)}")

    results = VerificationRunner().verify(SPEC_BPMN, SPEC_MCRL2, work_dir=tmp_path)

    assert len(results) == 19
    assert sum(result.claim.kind.value == "action_preservation" for result in results) == 8
    assert sum(result.claim.kind.value == "message_synchronization" for result in results) == 3
    assert all(result.status == "passed" for result in results)
    assert all(result.truth is True for result in results)
    assert (tmp_path / "model.lps").exists()
