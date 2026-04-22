# How to archive the old repos

Two previous repos should point to IntellCluster:

- `wtsaleksandr-lang/ai-orchestrator` → IntellCluster Synthesis
- `wtsaleksandr-lang/decision-intelligence-tool` → IntellCluster Phronesis

## Steps (per repo)

1. **Replace the README** with the matching file from this folder:
   - `ai-orchestrator-README.md` → becomes `README.md` in `ai-orchestrator`
   - `decision-intelligence-tool-README.md` → becomes `README.md` in `decision-intelligence-tool`

   ```bash
   # from the old repo's working copy
   cp /path/to/intellcluster/docs/archive-readmes/ai-orchestrator-README.md README.md
   git add README.md
   git commit -m "chore: archive — moved to intellcluster monorepo"
   git push
   ```

2. **Archive the repo on GitHub:**
   - Go to repo → Settings → scroll to bottom → "Archive this repository"
   - This makes it read-only; existing stars/forks/issues are preserved

3. **Optional but recommended — update the GitHub "About" section:**
   - Description: `Archived — moved to intellcluster`
   - Website: `https://intellcluster.com`
   - Uncheck all topic tags (to avoid polluting search)

4. **Optional — enable repository-wide redirect in the About:**
   - There is no official GitHub redirect, but archived repos display a prominent banner linking to the README, and the README is now the first thing visitors see.

## Why both READMEs live here

Keeping the archive READMEs inside IntellCluster means:
- We can update them if the monorepo layout or URLs change
- The git history for the move lives with the successor, not the archives
- Deleting the old repos is never necessary (preserves history + any inbound links)
