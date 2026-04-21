"""
Pipeline Execution Logger for benchmark validation.
Captures structured per-run execution data from SSE events.
Detects silent failures and assigns validity flags.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LOGS_DIR = Path("evaluation/pipeline_logs")


class PipelineExecutionLog:
    """Captures and validates a single orchestrator benchmark run."""

    def __init__(self, prompt_id: str, prompt_title: str, category: str):
        self.prompt_id = prompt_id
        self.prompt_title = prompt_title
        self.category = category
        self.timestamp = datetime.now(timezone.utc).isoformat()

        # Routing
        self.mode = None
        self.tier = None
        self.complexity = None

        # Research models
        self.models_selected = []     # what was requested
        self.models_scheduled = []    # what actually got a provider
        self.models_skipped = []      # requested but not scheduled
        self.model_results = {}       # model -> {status, runtime_ms, output_length, retries}

        # Synthesis
        self.strategist_model = None
        self.strategist_completed = False
        self.strategist_runtime_ms = 0
        self.strategist_output_length = 0

        self.decision_maker_model = None
        self.decision_maker_completed = False
        self.decision_maker_runtime_ms = 0
        self.decision_maker_output_length = 0

        # Phases
        self.total_phases = 0
        self.phase_names = []
        self.phases_completed = 0

        # Final
        self.final_output_generated = False
        self.final_output_length = 0
        self.total_runtime_ms = 0
        self.total_cost_estimate = None

        # PE
        self.pe_completed = False
        self.pe_model = None

        # Freshness
        self.freshness_level = None
        self.web_search_enabled = False

        # Warnings
        self.warnings = []
        self.errors = []

    def process_sse_event(self, event_type: str, data: dict):
        """Process a single SSE event and update the log."""

        if event_type == "step":
            step = data.get("step")
            status = data.get("status")

            if step == "prompt_engineer":
                if status == "done":
                    self.pe_completed = True
                    self.pe_model = data.get("provider")
                elif status == "error":
                    self.errors.append("Prompt engineer failed")

            elif step == "research":
                if status == "error":
                    self.errors.append("Research stage failed")

            elif step == "strategist":
                if status == "done":
                    self.strategist_completed = True
                elif status == "error":
                    self.errors.append("Strategist failed")

            elif step == "decision_maker":
                if status == "done":
                    self.decision_maker_completed = True
                elif status == "error":
                    self.errors.append("Decision maker failed")

        elif event_type == "research_info":
            self.models_selected = data.get("requested", [])
            self.models_scheduled = data.get("scheduled", [])
            self.models_skipped = data.get("skipped", [])
            self.tier = data.get("tier")
            # Initialize model tracking
            for m in self.models_scheduled:
                if m not in self.model_results:
                    self.model_results[m] = {
                        "status": "scheduled",
                        "started": False,
                        "completed": False,
                        "failed": False,
                        "runtime_ms": 0,
                        "output_length": 0,
                    }

        elif event_type == "model_status":
            model = data.get("model")
            status = data.get("status")
            if model not in self.model_results:
                self.model_results[model] = {
                    "status": status,
                    "started": False,
                    "completed": False,
                    "failed": False,
                    "runtime_ms": 0,
                    "output_length": 0,
                }
            if status == "running":
                self.model_results[model]["started"] = True
            elif status == "queued":
                self.model_results[model]["status"] = "queued"

        elif event_type == "model_result":
            model = data.get("model")
            status = data.get("status")
            if model not in self.model_results:
                self.model_results[model] = {"started": True, "completed": False, "failed": False, "runtime_ms": 0, "output_length": 0}
            mr = self.model_results[model]
            mr["status"] = status
            mr["runtime_ms"] = data.get("latency_ms", 0)
            mr["started"] = True
            if status == "success":
                mr["completed"] = True
                response = data.get("response", "")
                mr["output_length"] = len(response) if response else 0
            else:
                mr["failed"] = True
                mr["error"] = data.get("error", "")

        elif event_type == "phases_info":
            self.total_phases = data.get("total", 1)
            self.phase_names = data.get("names", [])

        elif event_type == "phase_progress":
            pass  # tracked via phases_info total

        elif event_type == "debug_context":
            self.tier = data.get("tier", self.tier)
            if data.get("models"):
                self.models_scheduled = data["models"]

        elif event_type == "freshness":
            self.freshness_level = data.get("level")
            self.web_search_enabled = data.get("web_search", False)

        elif event_type == "strategist":
            self.phases_completed += 1
            self.strategist_output_length += len(data.get("result", ""))

        elif event_type == "decision":
            result = data.get("result", "")
            self.final_output_generated = bool(result)
            self.final_output_length = len(result)
            self.decision_maker_completed = True

        elif event_type == "done":
            pass  # final status set in finalize()

        elif event_type == "error":
            self.errors.append(data.get("message", "Unknown error"))

    def finalize(self, total_runtime_ms: int):
        """Run after all events processed. Detects silent failures."""
        self.total_runtime_ms = total_runtime_ms

        # Detect silent failures
        for model, mr in self.model_results.items():
            if not mr.get("started"):
                self.warnings.append(f"Model {model} was selected but never started")
            if mr.get("status") == "success" and mr.get("output_length", 0) == 0:
                self.warnings.append(f"Model {model} returned success but empty output")
            if mr.get("status") == "timeout":
                self.warnings.append(f"Model {model} timed out")

        if not self.pe_completed:
            self.warnings.append("Prompt Engineer did not complete")

        if not self.strategist_completed:
            self.warnings.append("Strategist did not complete")

        if not self.decision_maker_completed:
            self.warnings.append("Decision Maker did not complete")

        if self.total_phases > 1 and self.phases_completed < self.total_phases:
            self.warnings.append(
                f"Only {self.phases_completed}/{self.total_phases} phases completed"
            )

        if not self.final_output_generated:
            self.errors.append("No final output was generated")

        if self.models_skipped:
            self.warnings.append(f"Models skipped (no provider): {self.models_skipped}")

    @property
    def validity(self) -> str:
        """Assign validity flag based on execution state."""
        if self.errors:
            # Check if critical
            critical = any(
                "final output" in e.lower() or "decision maker" in e.lower()
                for e in self.errors
            )
            if critical:
                return "INVALID"
            return "DEGRADED"

        failed_models = sum(1 for mr in self.model_results.values() if mr.get("failed"))
        total_models = len(self.model_results)
        success_models = sum(1 for mr in self.model_results.values() if mr.get("completed"))

        if total_models > 0 and success_models == 0:
            return "INVALID"

        if self.warnings:
            return "VALID_WITH_WARNINGS"

        if (self.pe_completed and self.strategist_completed and
                self.decision_maker_completed and self.final_output_generated):
            return "VALID"

        return "VALID_WITH_WARNINGS"

    def to_dict(self) -> dict:
        """Export as structured dict."""
        return {
            "prompt_id": self.prompt_id,
            "prompt_title": self.prompt_title,
            "category": self.category,
            "timestamp": self.timestamp,
            "validity": self.validity,
            "routing": {
                "mode": self.mode,
                "tier": self.tier,
                "complexity": self.complexity,
                "freshness": self.freshness_level,
                "web_search": self.web_search_enabled,
            },
            "prompt_engineer": {
                "model": self.pe_model,
                "completed": self.pe_completed,
            },
            "research": {
                "models_selected": self.models_selected,
                "models_scheduled": self.models_scheduled,
                "models_skipped": self.models_skipped,
                "per_model": self.model_results,
                "total_models": len(self.model_results),
                "successful": sum(1 for m in self.model_results.values() if m.get("completed")),
                "failed": sum(1 for m in self.model_results.values() if m.get("failed")),
            },
            "synthesis": {
                "strategist_completed": self.strategist_completed,
                "strategist_output_length": self.strategist_output_length,
                "decision_maker_completed": self.decision_maker_completed,
                "decision_maker_output_length": self.decision_maker_output_length,
            },
            "phases": {
                "total": self.total_phases,
                "completed": self.phases_completed,
                "names": self.phase_names,
            },
            "final": {
                "output_generated": self.final_output_generated,
                "output_length": self.final_output_length,
                "total_runtime_ms": self.total_runtime_ms,
                "cost_estimate": self.total_cost_estimate,
            },
            "warnings": self.warnings,
            "errors": self.errors,
        }

    def summary_line(self) -> str:
        """One-line summary for console output."""
        models_ok = sum(1 for m in self.model_results.values() if m.get("completed"))
        models_total = len(self.model_results)
        return (
            f"[{self.validity}] {self.prompt_id} | "
            f"tier={self.tier} | "
            f"models={models_ok}/{models_total} | "
            f"phases={self.phases_completed}/{self.total_phases} | "
            f"PE={'ok' if self.pe_completed else 'FAIL'} | "
            f"Strat={'ok' if self.strategist_completed else 'FAIL'} | "
            f"DM={'ok' if self.decision_maker_completed else 'FAIL'} | "
            f"output={'ok' if self.final_output_generated else 'FAIL'} | "
            f"{len(self.warnings)}w {len(self.errors)}e"
        )


def save_pipeline_logs(logs: list[PipelineExecutionLog], output_dir: str = None):
    """Save all pipeline logs to JSON."""
    if output_dir is None:
        output_dir = str(LOGS_DIR)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_runs": len(logs),
        "valid": sum(1 for l in logs if l.validity == "VALID"),
        "valid_with_warnings": sum(1 for l in logs if l.validity == "VALID_WITH_WARNINGS"),
        "degraded": sum(1 for l in logs if l.validity == "DEGRADED"),
        "invalid": sum(1 for l in logs if l.validity == "INVALID"),
        "runs": [l.to_dict() for l in logs],
    }

    path = Path(output_dir) / f"pipeline_log_{ts}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def generate_integrity_summary(logs: list[PipelineExecutionLog]) -> str:
    """Generate markdown Pipeline Integrity Summary for reports."""
    total = len(logs)
    valid = sum(1 for l in logs if l.validity == "VALID")
    warnings = sum(1 for l in logs if l.validity == "VALID_WITH_WARNINGS")
    degraded = sum(1 for l in logs if l.validity == "DEGRADED")
    invalid = sum(1 for l in logs if l.validity == "INVALID")

    lines = [
        "\n## Pipeline Integrity Summary\n",
        f"| Status | Count | % |",
        f"|--------|-------|---|",
        f"| VALID | {valid} | {valid/total*100:.0f}% |" if total else "",
        f"| VALID_WITH_WARNINGS | {warnings} | {warnings/total*100:.0f}% |" if total else "",
        f"| DEGRADED | {degraded} | {degraded/total*100:.0f}% |" if total else "",
        f"| INVALID | {invalid} | {invalid/total*100:.0f}% |" if total else "",
        "",
    ]

    # Collect all warnings/errors
    all_warnings = []
    all_errors = []
    for l in logs:
        for w in l.warnings:
            all_warnings.append(f"{l.prompt_id}: {w}")
        for e in l.errors:
            all_errors.append(f"{l.prompt_id}: {e}")

    if all_errors:
        lines.append("**Errors:**")
        for e in all_errors:
            lines.append(f"- {e}")
        lines.append("")

    if all_warnings:
        lines.append("**Warnings:**")
        for w in all_warnings[:10]:  # cap at 10
            lines.append(f"- {w}")
        if len(all_warnings) > 10:
            lines.append(f"- ... and {len(all_warnings) - 10} more")
        lines.append("")

    # Model reliability
    model_stats = {}  # model -> {runs, successes, failures, timeouts}
    for l in logs:
        for model, mr in l.model_results.items():
            if model not in model_stats:
                model_stats[model] = {"runs": 0, "success": 0, "failed": 0, "timeout": 0}
            model_stats[model]["runs"] += 1
            if mr.get("completed"):
                model_stats[model]["success"] += 1
            if mr.get("failed"):
                model_stats[model]["failed"] += 1
            if mr.get("status") == "timeout":
                model_stats[model]["timeout"] += 1

    if model_stats:
        lines.append("**Model Reliability:**")
        lines.append("| Model | Runs | Success | Failed | Timeout | Rate |")
        lines.append("|-------|------|---------|--------|---------|------|")
        for model, stats in sorted(model_stats.items()):
            rate = stats["success"] / stats["runs"] * 100 if stats["runs"] else 0
            lines.append(
                f"| {model} | {stats['runs']} | {stats['success']} | "
                f"{stats['failed']} | {stats['timeout']} | {rate:.0f}% |"
            )
        lines.append("")

    # Benchmark trustworthiness
    usable = valid + warnings
    lines.append(f"**Benchmark trustworthiness:** {usable}/{total} runs usable ({usable/total*100:.0f}%)" if total else "")
    if invalid > 0:
        lines.append(f"**WARNING:** {invalid} runs are INVALID and should be excluded from scoring.")

    return "\n".join(l for l in lines if l is not None)
