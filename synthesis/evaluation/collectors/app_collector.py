"""
Collect outputs from our multi-AI orchestration app.
Uses the internal API (POST /api/run + SSE stream) to run prompts and capture results.
"""

import asyncio
import json
import time
import httpx

from synthesis.evaluation.pipeline_logger import PipelineExecutionLog


async def collect_app_output(
    prompt: str,
    category: str,
    mode: str = "standard",
    base_url: str = "http://localhost:8080",
    timeout: int = 600,
    pipeline_log: PipelineExecutionLog | None = None,
) -> dict:
    """Run a prompt through the app and collect the full output.

    Returns:
        {
            "system": "orchestrator",
            "prompt_id": str,
            "refined_prompt": str,
            "final_output": str,
            "strategist_output": str,
            "model_outputs": [{model, status, latency_ms}],
            "metadata": {mode, tier, models_used, phases, ...},
            "runtime_ms": int,
            "cost_estimate": float | None,
        }
    """
    start = time.time()

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=float(timeout))) as client:
        # Start the run
        resp = await client.post(f"{base_url}/api/run", json={
            "category": category,
            "prompt": prompt,
            "mode": mode,
        })
        resp.raise_for_status()
        run_id = resp.json()["run_id"]

        # Collect SSE events
        refined_prompt = ""
        final_output = ""
        strategist_parts = []
        model_outputs = []
        metadata = {"mode": mode, "run_id": run_id}

        async with client.stream("GET", f"{base_url}/api/stream/{run_id}") as stream:
            async for line in stream.aiter_lines():
                if not line.startswith("data: "):
                    if line.startswith("event: "):
                        current_event = line[7:]
                    continue

                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                # Feed to pipeline logger
                if pipeline_log:
                    pipeline_log.process_sse_event(current_event, data)

                if current_event == "step":
                    if data.get("step") == "prompt_engineer" and data.get("status") == "done":
                        refined_prompt = data.get("result", "")
                elif current_event == "model_result":
                    model_outputs.append({
                        "model": data.get("model"),
                        "status": data.get("status"),
                        "latency_ms": data.get("latency_ms"),
                    })
                elif current_event == "strategist":
                    strategist_parts.append(data.get("result", ""))
                elif current_event == "decision":
                    final_output = data.get("result", "")
                elif current_event == "phases_info":
                    metadata["total_phases"] = data.get("total")
                    metadata["phase_names"] = data.get("names")
                elif current_event == "research_info":
                    metadata["models_used"] = data.get("scheduled")
                    metadata["tier"] = data.get("tier")
                elif current_event == "debug_context":
                    metadata["tier"] = data.get("tier")
                elif current_event in ("done", "error"):
                    if current_event == "error":
                        metadata["error"] = data.get("message")
                    break

    runtime_ms = int((time.time() - start) * 1000)

    # Finalize pipeline log
    if pipeline_log:
        pipeline_log.mode = mode
        pipeline_log.finalize(runtime_ms)

    # Try to get cost from history
    cost = None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/api/history/{run_id}")
            if resp.status_code == 200:
                run_data = resp.json()
                cost = run_data.get("cost_estimate")
    except Exception:
        pass

    return {
        "system": "orchestrator",
        "refined_prompt": refined_prompt,
        "final_output": final_output,
        "strategist_output": "\n\n".join(strategist_parts),
        "model_outputs": model_outputs,
        "metadata": metadata,
        "runtime_ms": runtime_ms,
        "cost_estimate": cost,
    }
