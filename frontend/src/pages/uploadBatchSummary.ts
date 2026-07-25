export interface UploadBatchSummaryInput {
  accepted_files?: number;
  completed_files?: number;
  successful_files?: number;
  queued_files?: number;
  duplicate_files?: number;
  skipped_files?: number;
  failed_files?: number;
  total_chunks?: number;
}

export interface UploadBatchSummaryCounts {
  accepted: number;
  completed: number;
  queued: number;
  duplicate: number;
  skipped: number;
  failed: number;
  chunks: number;
}

function boundedCount(value: number | undefined): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.trunc(value));
}

export function summarizeUploadBatch(result: UploadBatchSummaryInput): UploadBatchSummaryCounts {
  const queued = boundedCount(result.queued_files);
  const completed = boundedCount(result.completed_files ?? result.successful_files);
  const accepted = boundedCount(result.accepted_files ?? completed + queued);

  return {
    accepted,
    completed,
    queued,
    duplicate: boundedCount(result.duplicate_files),
    skipped: boundedCount(result.skipped_files),
    failed: boundedCount(result.failed_files),
    chunks: boundedCount(result.total_chunks),
  };
}
