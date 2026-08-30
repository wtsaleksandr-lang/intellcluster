---
name: Long-running ingestion execution
description: How to keep resumable data ingestion running across workspace restarts.
---

Long-running ingestion should run as a managed console workflow rather than a shell background task; the ingestion checkpoints make restarts safe.

**Why:** Background shell processes are terminated when the workspace restarts, while the persisted ingestion checkpoint allows a managed workflow to continue without replaying prior records.

**How to apply:** Use the resumable module command in a managed console workflow for extended ingestion jobs. Use the status command to verify the saved position before restarting.