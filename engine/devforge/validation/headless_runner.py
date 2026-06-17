"""Headless Runner — validates GDScript files via Godot headless.

Reimplements gen-1's headless validation with the corrected approach:
uses a custom Godot script (``tools/validate_scripts.gd``) that iterates
``.gd`` files and forces parsing via ``ResourceLoader.load()`` with
``CACHE_MODE_IGNORE``.  The subprocess pattern is copied from
WorldForge's ``gate2._run_godot_determinism()``.

Usage::

    runner = HeadlessRunner(godot_bin="godot", project_path="./game")
    report = runner.validate()

    if not report.passed:
        for err in report.errors:
            print(f"{err.file}:{err.line}: {err.message}")
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from devforge.reasoning.ai.repair.error_parser import ErrorParser, ParsedError
from devforge.reasoning.ai.repair.repair_planner import RepairPlanner, RepairPlan
from devforge.infrastructure.logger import logger


# ── Constants ────────────────────────────────────────────────────

DEFAULT_GODOT_BIN = "godot"
DEFAULT_TIMEOUT_SECONDS = 120
VALIDATION_SCRIPT = "tools/validate_scripts.gd"

# Pattern for structured error lines emitted by validate_scripts.gd
# Matches: FILE:res://path/to/file.gd:<line> - <message>
FILE_ERROR_PATTERN = re.compile(
    r"FILE:(?P<file>.*?\.gd):(?P<line>-?\d+)\s*-\s*(?P<message>.+)"
)

# Godot startup lines to filter from error detection.
# NOTE: ^WARNING: and ^ERROR: patterns match engine-level log messages.
# Godot parse errors use the format "res://path:line - message" without
# a log-level prefix, so these filters won't mask real parse errors.
GODOT_STARTUP_PATTERNS = [
    re.compile(r"Godot Engine"),
    re.compile(r"OpenGL"),
    re.compile(r"Vulkan"),
    re.compile(r"\[DevForge\]"),
    re.compile(r"^\s*$"),  # blank lines
    re.compile(r"^WARNING:"),
    re.compile(r"^ERROR:"),
]

# Pattern for FILES_CHECKED summary from the Godot script
FILES_CHECKED_PATTERN = re.compile(r"FILES_CHECKED:(\d+)")


# ── Data structures ──────────────────────────────────────────────

@dataclass
class ValidationError:
    """A single validation error from the headless check."""

    file: str
    line: int
    message: str
    error_type: str = "parse_error"
    symbol: str | None = None

    @classmethod
    def from_parsed(cls, pe: ParsedError) -> "ValidationError":
        return cls(
            file=pe.file,
            line=pe.line,
            message=pe.message,
            error_type=pe.error_type,
            symbol=pe.symbol,
        )


@dataclass
class ValidationReport:
    """Complete result of a headless validation run."""

    passed: bool
    errors: List[ValidationError] = field(default_factory=list)
    repair_plans: List[RepairPlan] = field(default_factory=list)
    files_checked: int = 0
    elapsed_ms: int = 0
    raw_stdout: str = ""
    raw_stderr: str = ""

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "error_count": self.error_count,
            "files_checked": self.files_checked,
            "elapsed_ms": self.elapsed_ms,
            "errors": [
                {"file": e.file, "line": e.line, "message": e.message,
                 "type": e.error_type}
                for e in self.errors
            ],
            "repair_plans": len(self.repair_plans),
        }

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"Headless Validation: {status}",
            f"  Files checked: {self.files_checked}",
            f"  Errors: {self.error_count}",
            f"  Repair plans: {len(self.repair_plans)}",
            f"  Elapsed: {self.elapsed_ms}ms",
        ]
        if self.errors:
            lines.append("  Errors:")
            for e in self.errors:
                lines.append(f"    {e.file}:{e.line}: {e.message}")
        return "\n".join(lines)


# ── Headless Runner ──────────────────────────────────────────────

class HeadlessRunner:
    """Runs Godot headless with the validation script.

    Copies the production-tested subprocess pattern from
    WorldForge ``gate2._run_godot_determinism()``:

    1. Invoke ``godot --headless --path <project> -s tools/validate_scripts.gd``
    2. Parse stdout for structured error lines (``FILE:...``)
    3. Feed parsed errors through ``ErrorParser`` → ``RepairPlanner``
    4. Return a ``ValidationReport``.

    Success is determined by absence of error lines in stdout,
    NOT by Godot's exit code (which is unreliable).
    """

    def __init__(
        self,
        godot_bin: str = DEFAULT_GODOT_BIN,
        project_path: str | Path = ".",
        *,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self._godot_bin = godot_bin
        self._project_path = Path(project_path)
        self._timeout = timeout
        self._error_parser = ErrorParser()
        self._repair_planner = RepairPlanner()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def validate(self) -> ValidationReport:
        """Run the headless validation.

        Returns:
            ValidationReport with errors and (if applicable) repair plans.
        """
        start = time.time()

        script_path = self._project_path / VALIDATION_SCRIPT
        if not script_path.exists():
            return ValidationReport(
                passed=False,
                errors=[
                    ValidationError(
                        file="", line=0,
                        message=f"Validation script not found: {script_path}",
                        error_type="config_error",
                    )
                ],
                elapsed_ms=int((time.time() - start) * 1000),
            )

        logger.info("headless", f"Running validation: {script_path}")

        try:
            raw_stdout, raw_stderr = self._run_godot(script_path)
        except Exception as exc:
            elapsed = int((time.time() - start) * 1000)
            logger.error("headless", f"Validation failed: {exc}")
            return ValidationReport(
                passed=False,
                errors=[
                    ValidationError(
                        file="", line=0,
                        message=f"Godot process error: {exc}",
                        error_type="process_error",
                    )
                ],
                elapsed_ms=elapsed,
            )

        # Parse structured errors from stdout
        parsed_errors, files_checked = self._parse_stdout(raw_stdout)

        # Also feed raw stderr through ErrorParser for Godot compiler errors
        stderr_parsed = self._error_parser.parse_report_from_text(raw_stderr)
        for pe in stderr_parsed:
            parsed_errors.append(pe)

        # Deduplicate by (file, line, message)
        seen = set()
        unique_errors: List[ParsedError] = []
        for pe in parsed_errors:
            key = (pe.file, pe.line, pe.message)
            if key not in seen:
                seen.add(key)
                unique_errors.append(pe)

        # Convert to ValidationError
        errors = [ValidationError.from_parsed(pe) for pe in unique_errors]

        # files_checked already parsed from FILES_CHECKED in _parse_stdout

        # Generate repair plans for each error
        repair_plans: List[RepairPlan] = []
        for pe in unique_errors:
            try:
                file_path = self._project_path / pe.file
                if file_path.exists():
                    content = file_path.read_text()
                    plan = self._repair_planner.plan_repair(pe, content, step=None)
                    if plan:
                        repair_plans.append(plan)
                        logger.info("headless",
                                     f"Repair plan for {pe.file}:{pe.line}",
                                     steps=len(plan.steps))
            except Exception as exc:
                logger.warn("headless",
                            f"Could not generate repair plan for {pe.file}: {exc}")

        elapsed = int((time.time() - start) * 1000)

        report = ValidationReport(
            passed=len(errors) == 0,
            errors=errors,
            repair_plans=repair_plans,
            files_checked=files_checked,
            elapsed_ms=elapsed,
            raw_stdout=raw_stdout,
            raw_stderr=raw_stderr,
        )

        logger.info(
            "headless",
            f"Validation {'PASSED' if report.passed else 'FAILED'}: "
            f"{files_checked} files, {len(errors)} errors, {elapsed}ms",
        )

        return report

    # ------------------------------------------------------------------
    # Godot subprocess (copied from WorldForge gate2)
    # ------------------------------------------------------------------

    def _run_godot(self, script_path: Path) -> tuple[str, str]:
        """Invoke Godot headless with the validation script.

        Returns (stdout, stderr) tuple.
        """
        cmd = [
            self._godot_bin,
            "--headless",
            "--path", str(self._project_path),
            "-s", str(script_path),
        ]

        logger.info("headless", f"Running: {' '.join(cmd)}")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""

            # Log exit code for diagnostics (but don't rely on it)
            if proc.returncode != 0:
                logger.warn(
                    "headless",
                    f"Godot exited with code {proc.returncode} "
                    f"(exit codes are unreliable; checking output for errors)",
                )

            return stdout, stderr

        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Godot validation timed out ({self._timeout}s)"
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"Godot binary not found: {self._godot_bin}. "
                f"Install Godot or set GODOT_BIN environment variable."
            )

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def _parse_stdout(self, raw_stdout: str) -> tuple[List[ParsedError], int]:
        """Extract structured errors from the validation script's stdout.

        The validation script emits lines in the format:
            FILE:<path>:<line> - <message>
            FILES_CHECKED:<count>

        We filter out Godot startup noise (version banners, OpenGL info, etc.).

        Returns (parsed_errors, files_checked_count).
        """
        errors: List[ParsedError] = []
        files_checked = 0
        file_matched_lines: set[str] = set()

        for line in raw_stdout.splitlines():
            # Parse FILES_CHECKED summary
            fc_match = FILES_CHECKED_PATTERN.search(line)
            if fc_match:
                files_checked = int(fc_match.group(1))
                continue

            # Skip known noise lines
            if self._is_startup_noise(line):
                continue

            match = FILE_ERROR_PATTERN.search(line)
            if match:
                file = match.group("file")
                line_number = int(match.group("line"))
                # -1 means "unknown line" from the Godot script
                if line_number == -1:
                    line_number = 0
                message = match.group("message")

                errors.append(ParsedError(
                    file=file,
                    line=line_number,
                    message=message,
                    error_type="parse_error",
                ))
                file_matched_lines.add(line)

        # Feed remaining (non-FILE-matched) lines through ErrorParser
        # to catch Godot-native error lines like "res://path:42 - Parse error: ..."
        remaining_lines = [
            l for l in raw_stdout.splitlines()
            if l not in file_matched_lines and not self._is_startup_noise(l)
        ]
        if remaining_lines:
            std_errors = self._error_parser.parse_report_from_text(
                "\n".join(remaining_lines)
            )
            errors.extend(std_errors)

        return errors, files_checked

    @staticmethod
    def _is_startup_noise(line: str) -> bool:
        """Check if a line is Godot startup output, not a validation error."""
        for pattern in GODOT_STARTUP_PATTERNS:
            if pattern.search(line):
                return True
        return False
