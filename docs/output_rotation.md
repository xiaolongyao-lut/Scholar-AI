# Output File Rotation

## Cost Tracking File Rotation

The `scripts/rotate_output.py` script archives cost tracking files when they exceed 64 MB to prevent unbounded growth.

### Files Managed

- `output/llm_cost.jsonl` — LLM API call costs and token usage
- `output/rerank_cost.jsonl` — Reranking service costs and token usage

### Archive Location

Files are archived to `output/archive/YYYY-MM/` with timestamp:

```
output/archive/2026-04/llm_cost_20260421_153045.jsonl
output/archive/2026-04/rerank_cost_20260421_153045.jsonl
```

### Manual Rotation Schedule

**Operations team runs rotation manually every Monday:**

```powershell
python scripts/rotate_output.py
```

### Behavior

- Files **above 64 MB**: Moved to archive
- Files **at or below 64 MB**: Preserved in place
- Non-existent files: Skipped gracefully

### Example Output

```
Checking files for rotation (threshold: 64 MB)...
  llm_cost.jsonl: 87.45 MB > 64 MB, rotating...
    Archived to: output/archive/2026-04/llm_cost_20260421_153045.jsonl
  rerank_cost.jsonl: 23.12 MB ≤ 64 MB, skipping

Rotation complete: 1 file(s) archived
```
