from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ModelInquisitor.core.traces import TraceComparison, TraceConfig, TraceExtractor
from ModelInquisitor.parsers.bpmn import BPMNParser
from ModelInquisitor.runners.trace_verifier import TraceVerificationResult, TraceVerificationRunner
from ModelInquisitor.strategies.third_party_bpmn2mcrl2 import ThirdPartyBpmn2Mcrl2Strategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check trace equivalence between a BPMN model and its mCRL2 translation.",
    )
    parser.add_argument("bpmn", type=Path, help="Path to the source BPMN XML file.")
    parser.add_argument("mcrl2", type=Path, help="Path to the translated mCRL2 file.")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Directory for generated LPS/LTS artifacts.",
    )
    parser.add_argument(
        "--max-trace-length",
        type=int,
        default=50,
        help="Maximum observable actions per trace (state explosion mitigation).",
    )
    parser.add_argument(
        "--max-trace-count",
        type=int,
        default=1000,
        help="Maximum traces per side (state explosion mitigation).",
    )
    parser.add_argument(
        "--show-traces",
        action="store_true",
        help="Print all traces for each process.",
    )
    return parser.parse_args()


def render_trace_comparison(console: Console, result: TraceVerificationResult) -> None:
    if result.status in {"not_run", "model_error"}:
        console.print(Panel(
            f"[yellow]Trace equivalence could not be run.[/yellow]\n{result.output}",
            title="Trace equivalence", expand=False,
        ))
        return

    verdict = (
        "[green]EQUIVALENT[/green]" if result.status == "equivalent"
        else "[red]NOT EQUIVALENT[/red]" if result.status == "not_equivalent"
        else "[yellow]BOUNDED (incomplete)[/yellow]"
    )
    console.print(Panel(f"Per-process trace equivalence: {verdict}", title="Trace equivalence verdict", expand=False))

    table = Table(title="Per-process trace comparison")
    table.add_column("Process")
    table.add_column("BPMN traces")
    table.add_column("mCRL2 traces")
    table.add_column("Common")
    table.add_column("BPMN-only")
    table.add_column("mCRL2-only")
    table.add_column("Equivalent?")

    for process_id, comp in result.per_process.items():
        eq = "[green]yes[/green]" if comp.is_equivalent else "[red]no[/red]"
        table.add_row(
            process_id,
            str(len(comp.common) + len(comp.bpmn_only)),
            str(len(comp.common) + len(comp.mcrl2_only)),
            str(len(comp.common)),
            str(len(comp.bpmn_only)),
            str(len(comp.mcrl2_only)),
            eq,
        )
    console.print(table)

    for process_id, comp in result.per_process.items():
        if comp.is_equivalent:
            continue
        diff_lines = []
        if comp.bpmn_only:
            diff_lines.append("[bold]BPMN traces missing from mCRL2:[/bold]")
            for trace in sorted(comp.bpmn_only)[:5]:
                diff_lines.append(f"  {', '.join(trace) or '(empty)'}")
            if len(comp.bpmn_only) > 5:
                diff_lines.append(f"  ... and {len(comp.bpmn_only) - 5} more")
        if comp.mcrl2_only:
            diff_lines.append("[bold]mCRL2 traces missing from BPMN:[/bold]")
            for trace in sorted(comp.mcrl2_only)[:5]:
                diff_lines.append(f"  {', '.join(trace) or '(empty)'}")
            if len(comp.mcrl2_only) > 5:
                diff_lines.append(f"  ... and {len(comp.mcrl2_only) - 5} more")
        if diff_lines:
            console.print(Panel("\n".join(diff_lines), title=f"Trace differences: {process_id}", expand=False))


def render_trace_detail(console: Console, result: TraceVerificationResult) -> None:
    for process_id, comp in result.per_process.items():
        lines = []
        lines.append(f"[bold]BPMN traces ({len(comp.common) + len(comp.bpmn_only)}):[/bold]")
        for trace in sorted(comp.common | comp.bpmn_only):
            lines.append(f"  {', '.join(trace) or '(empty)'}")
        lines.append(f"[bold]mCRL2 traces ({len(comp.common) + len(comp.mcrl2_only)}):[/bold]")
        for trace in sorted(comp.common | comp.mcrl2_only):
            lines.append(f"  {', '.join(trace) or '(empty)'}")
        console.print(Panel("\n".join(lines), title=f"Traces: {process_id}", expand=False))


def main() -> int:
    args = parse_args()
    console = Console()

    if not args.bpmn.exists():
        console.print(f"[red]BPMN file does not exist:[/red] {args.bpmn}")
        return 2
    if not args.mcrl2.exists():
        console.print(f"[red]mCRL2 file does not exist:[/red] {args.mcrl2}")
        return 2

    config = TraceConfig(
        max_trace_length=args.max_trace_length,
        max_trace_count=args.max_trace_count,
    )
    runner = TraceVerificationRunner(config=config)
    result = runner.verify(args.bpmn, args.mcrl2, work_dir=args.work_dir)

    render_trace_comparison(console, result)
    if args.show_traces:
        render_trace_detail(console, result)

    if result.status in {"model_error", "not_run"}:
        return 3
    if result.status == "bounded":
        return 3
    return 0 if result.is_equivalent else 1


if __name__ == "__main__":
    raise SystemExit(main())