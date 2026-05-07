from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LTSGenerationResult:
    status: str  # "success", "model_error", "not_run"
    lts_path: Path | None = None
    lps_path: Path | None = None
    output: str = ""
    command: tuple[str, ...] = ()


class LTSGenerator:
    """Generate an LTS .aut file from an mCRL2 specification."""

    def has_toolchain(self) -> bool:
        return all(
            shutil.which(cmd)
            for cmd in ("mcrl22lps", "lps2lts")
        )

    def generate(
        self,
        mcrl2_path: str | Path,
        *,
        work_dir: str | Path | None = None,
    ) -> LTSGenerationResult:
        """Run mcrl22lps -> lps2lts to produce an .aut file."""
        mcrl2_path = Path(mcrl2_path)

        if not self.has_toolchain():
            return LTSGenerationResult(
                status="not_run",
                output="mCRL2 command-line tools (mcrl22lps, lps2lts) were not found on PATH.",
            )

        artifact_dir = Path(work_dir) if work_dir else Path(".verify-artifacts")
        artifact_dir.mkdir(parents=True, exist_ok=True)

        lps_path = artifact_dir / "model.lps"
        aut_path = artifact_dir / "model.aut"

        # Step 1: mcrl22lps
        lps_cmd = ("mcrl22lps", str(mcrl2_path), str(lps_path))
        lps_proc = self._run(lps_cmd)
        if lps_proc.returncode != 0:
            return LTSGenerationResult(
                status="model_error",
                lps_path=lps_path,
                output=self._proc_output(lps_proc),
                command=lps_cmd,
            )

        # Step 2: lps2lts (output in .aut format)
        lts_cmd = ("lps2lts", str(lps_path), str(aut_path))
        lts_proc = self._run(lts_cmd)
        if lts_proc.returncode != 0:
            return LTSGenerationResult(
                status="model_error",
                lps_path=lps_path,
                lts_path=aut_path,
                output=self._proc_output(lts_proc),
                command=lts_cmd,
            )

        return LTSGenerationResult(
            status="success",
            lps_path=lps_path,
            lts_path=aut_path,
            output=self._proc_output(lts_proc),
            command=lts_cmd,
        )

    def _run(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, check=False, capture_output=True, text=True)

    def _proc_output(self, proc: subprocess.CompletedProcess[str]) -> str:
        return (proc.stdout or "") + (proc.stderr or "")