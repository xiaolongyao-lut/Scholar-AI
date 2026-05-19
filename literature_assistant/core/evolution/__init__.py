"""
Literature Evolution Layer — incremental self-evolution capability around the
existing literature assistant. See:
  docs/plans/active/2026-05-17-literature-evolution-agent-incremental-upgrade-plan.md

Slice 2 (this module) provides:
  - models.evolution.ExperienceCandidate (single source of truth contract)
  - evolution.state_machine (pure-function transition rules + D-EVO-P0-8 guards)
  - evolution.secret_scan (fail-closed wrapper over wiki.evaluation scanner)
  - evolution.store.EvolutionCandidateStore (SQLite, dedupe, online backup)
  - evolution.service.EvolutionService (orchestration facade + singleton)
  - routers.evolution_router (`/evolution/*` REST endpoints)

Slices 3+ add capture from inspiration / discussion / runtime / skill paths,
the review UI, promotion to MemPalace + skill drafts, and the curator.
"""

from evolution._capture_args import CaptureCandidateArgs
from evolution.background import run_capture_in_background
from evolution.config import (
    is_candidate_capture_enabled,
    is_curator_enabled,
    is_curator_llm_judge_enabled,
    is_promotion_enabled,
    is_recall_enabled,
    load_evolution_config,
)
from evolution.curator import CuratorRunResult, EvolutionCurator
from evolution.curator_llm_judge import (
    JudgeVerdict,
    MAX_CLAIMS_PER_BUCKET,
    call_curator_llm_judge,
)
from evolution.discussion_capture import extract_from_discussion_result
from evolution.inspiration_capture import (
    extract_from_spark,
    extract_from_sparks,
)
from evolution.promotion import EvolutionPromoter, PromotionResult
from evolution.rag_capture import extract_from_rag_result
from evolution.runtime_capture import extract_from_job
from evolution.skill_capture import extract_from_skill_run
from evolution.service import (
    EvolutionService,
    PromotionOutcome,
    compute_dedupe_hash,
    get_evolution_service,
    reset_evolution_service_for_tests,
)
from evolution.state_machine import (
    TERMINAL_STATES,
    TransitionResult,
    evaluate_transition,
    is_terminal,
)
from evolution.store import (
    DEFAULT_DB_FILENAME,
    EvolutionCandidateStore,
    StoreWriteResult,
    default_db_path,
)
from evolution.secret_scan import (
    SecretScanVerdict,
    fields_to_scan,
    scan_candidate_fields,
)

__all__ = [
    "EvolutionService",
    "compute_dedupe_hash",
    "get_evolution_service",
    "reset_evolution_service_for_tests",
    "TERMINAL_STATES",
    "TransitionResult",
    "evaluate_transition",
    "is_terminal",
    "DEFAULT_DB_FILENAME",
    "EvolutionCandidateStore",
    "StoreWriteResult",
    "default_db_path",
    "SecretScanVerdict",
    "fields_to_scan",
    "scan_candidate_fields",
    "is_candidate_capture_enabled",
    "is_curator_enabled",
    "is_curator_llm_judge_enabled",
    "is_promotion_enabled",
    "is_recall_enabled",
    "load_evolution_config",
    "CuratorRunResult",
    "EvolutionCurator",
    "JudgeVerdict",
    "MAX_CLAIMS_PER_BUCKET",
    "call_curator_llm_judge",
    "CaptureCandidateArgs",
    "run_capture_in_background",
    "extract_from_spark",
    "extract_from_sparks",
    "extract_from_discussion_result",
    "extract_from_job",
    "extract_from_rag_result",
    "extract_from_skill_run",
    "EvolutionPromoter",
    "PromotionOutcome",
    "PromotionResult",
]
