from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ModelInquisitor.core.models import Claim, ClaimKind
from ModelInquisitor.runners.verifier import VerificationResult, VerificationRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify BPMN-derived semantic claims against an mCRL2 translation."
    )
    parser.add_argument("bpmn", type=Path, help="Path to the source BPMN XML file.")
    parser.add_argument("mcrl2", type=Path, help="Path to the translated mCRL2 file.")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Directory for generated LPS/MCF/PBES artifacts.",
    )
    parser.add_argument(
        "--show-formulas",
        action="store_true",
        help="Print generated MCF formulas for each claim.",
    )
    return parser.parse_args()


def explain_claim(claim: Claim) -> str:
    if claim.kind == ClaimKind.DEADLOCK_FREEDOM:
        return (
            f"Process {claim.process_id} should be able to reach an end event. "
            "A false result means the translated model may contain a path that cannot terminate normally."
        )
    if claim.kind == ClaimKind.ACTION_PRESERVATION:
        return (
            f"Observable BPMN node {claim.node_id} should still be visible as a reachable action "
            "in the translated mCRL2 model."
        )
    if claim.kind == ClaimKind.MESSAGE_SYNCHRONIZATION:
        return (
            f"Message flow {claim.node_id} should be synchronized as a communicated action. "
            "A false result means communication may be missing or raw send/receive actions may be exposed."
        )
    if claim.kind == ClaimKind.CAUSALITY:
        return (
            f"Node {claim.source_node_id} should be a necessary predecessor of {claim.target_node_id}. "
            "The check asks whether the target action can be observed before the source action."
        )
    if claim.kind == ClaimKind.MUTEX:
        branches = ", ".join(claim.branch_node_ids)
        return (
            f"Branches {branches} under exclusive gateway {claim.node_id} should not both appear "
            "in the same execution trace."
        )
    return claim.description or "Unnamed claim."


def short_claim_text(claim: Claim) -> str:
    if claim.kind == ClaimKind.DEADLOCK_FREEDOM:
        return f"{claim.process_id} reaches an end event"
    if claim.kind == ClaimKind.ACTION_PRESERVATION:
        return f"{claim.node_id} remains reachable"
    if claim.kind == ClaimKind.MESSAGE_SYNCHRONIZATION:
        return f"{claim.node_id} synchronizes send/receive"
    if claim.kind == ClaimKind.CAUSALITY:
        return f"{claim.source_node_id} before {claim.target_node_id}"
    if claim.kind == ClaimKind.MUTEX:
        return f"{' / '.join(claim.branch_node_ids)} are mutually exclusive"
    return claim.description or claim.kind.value


def status_text(result: VerificationResult) -> str:
    if result.status == "passed":
        return "[green]passed[/green]"
    if result.status == "failed":
        return "[red]failed[/red]"
    if result.status == "formula_error":
        return "[yellow]formula error[/yellow]"
    if result.status == "model_error":
        return "[yellow]model error[/yellow]"
    if result.status == "solver_error":
        return "[yellow]solver error[/yellow]"
    if result.status == "not_run":
        return "[yellow]not run[/yellow]"
    return f"[dim]{result.status}[/dim]"


def render_summary(console: Console, results: list[VerificationResult]) -> None:
    counts = Counter(result.status for result in results)
    summary = ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))
    table = Table(title=f"ModelInquisitor verification results ({summary})")
    table.add_column("#", justify="right")
    table.add_column("Claim")
    table.add_column("Status")
    table.add_column("Check")

    for index, result in enumerate(results, 1):
        table.add_row(
            str(index),
            result.claim.kind.value,
            status_text(result),
            short_claim_text(result.claim),
        )
    console.print(table)


def render_claim_explanations(console: Console, results: list[VerificationResult]) -> None:
    grouped: dict[ClaimKind, list[VerificationResult]] = defaultdict(list)
    for result in results:
        grouped[result.claim.kind].append(result)

    lines = []
    for kind, group in grouped.items():
        if kind == ClaimKind.DEADLOCK_FREEDOM:
            processes = ", ".join(result.claim.process_id or "unknown" for result in group)
            lines.append(f"[bold]Deadlock freedom[/bold]: each listed process should still be able to terminate ({processes}).")
        elif kind == ClaimKind.ACTION_PRESERVATION:
            nodes = ", ".join(result.claim.node_id or "unknown" for result in group)
            lines.append(f"[bold]Action preservation[/bold]: each observable BPMN node should remain reachable in mCRL2 ({nodes}).")
        elif kind == ClaimKind.MESSAGE_SYNCHRONIZATION:
            flows = ", ".join(result.claim.node_id or "unknown" for result in group)
            lines.append(f"[bold]Message synchronization[/bold]: each BPMN message flow should appear as synchronized communication, without raw send/receive exposure ({flows}).")
        elif kind == ClaimKind.CAUSALITY:
            pairs = "; ".join(
                f"{result.claim.source_node_id} -> {result.claim.target_node_id}"
                for result in group
            )
            lines.append(f"[bold]Causality[/bold]: the source action must be observed before the target action ({pairs}).")
        elif kind == ClaimKind.MUTEX:
            gateways = ", ".join(result.claim.node_id or "unknown" for result in group)
            lines.append(f"[bold]Mutex[/bold]: exclusive gateway branches must not both occur in one trace ({gateways}).")
        else:
            lines.append(f"[bold]{kind.value}[/bold]: {len(group)} claim(s).")

    if lines:
        console.print(Panel("\n".join(lines), title="What was checked", expand=False))


def render_details(console: Console, results: list[VerificationResult], show_formulas: bool) -> None:
    needs_details = show_formulas or any(
        result.status not in {"passed", "failed"} or result.truth is False
        for result in results
    )
    if not needs_details:
        return

    for index, result in enumerate(results, 1):
        if not show_formulas and result.status == "passed":
            continue
        lines = [
            f"[bold]Claim:[/bold] {result.claim.description}",
            f"[bold]Meaning:[/bold] {explain_claim(result.claim)}",
            f"[bold]Status:[/bold] {status_text(result)}",
        ]
        if result.command:
            lines.append(f"[bold]Last command:[/bold] {' '.join(result.command)}")
        if show_formulas:
            lines.append("[bold]MCF:[/bold]")
            lines.append(result.formula)
        if result.output.strip() and result.status not in {"passed", "failed"}:
            lines.append("[bold]Tool output:[/bold]")
            lines.append(result.output.strip())
        console.print(Panel("\n".join(lines), title=f"Claim {index}", expand=False))


def main() -> int:
    args = parse_args()
    console = Console()

    if not args.bpmn.exists():
        console.print(f"[red]BPMN file does not exist:[/red] {args.bpmn}")
        return 2
    if not args.mcrl2.exists():
        console.print(f"[red]mCRL2 file does not exist:[/red] {args.mcrl2}")
        return 2

    runner = VerificationRunner()
    results = runner.verify(args.bpmn, args.mcrl2, work_dir=args.work_dir)

    render_summary(console, results)
    render_claim_explanations(console, results)
    render_details(console, results, args.show_formulas)

    if any(result.status in {"model_error", "formula_error", "solver_error", "not_run"} for result in results):
        return 3
    return 0 if all(result.truth for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
