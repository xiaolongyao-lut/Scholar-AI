/**
 * Convert a Discussion run result into a GraphPayload v0 subgraph.
 *
 * L1 scope (per plan §4.11):
 *   - agent node per unique agent_id (success or failed; failed gets
 *     metadata.status = "failed")
 *   - evidence node per unique snippet, deduped by material_id +
 *     chunk_id (fallback: source + sha1(text) when material_id is
 *     missing — wiki/manual snippets)
 *   - agent → evidence edge with relation = "uses", deduped by
 *     (agent_id, evidence_id).
 *   - **G5 (2026-05-15) per-agent attribution**: when at least one
 *     successful agent in the run has a non-empty `cited_evidence_ids`,
 *     edges connect each successful agent only to the evidence it
 *     actually cited (E-id mapped through the per-run snippet position
 *     to the deduped graph node). Edges carry
 *     metadata.via = "citation".
 *   - **Run-level fallback**: when all successful agents have empty
 *     `cited_evidence_ids` (legacy payloads from before G2, or runs
 *     where no agent emitted markers), every successful agent links
 *     to every evidence node — preserving the pre-G5 viewer behavior.
 *     Fallback edges carry metadata.via = "run_level".
 *   - no claim node, no supports/contradicts edges
 *   - empty snippets is valid: returns agent-only graph
 */
import type { components } from '@/generated/openapi';
import type { DiscussionRunResult } from '@/services/discussionApi';

type GraphPayloadV0 = components['schemas']['GraphPayloadV0'];
type GraphNode = components['schemas']['GraphNode'];
type GraphEdge = components['schemas']['GraphEdge'];

/**
 * Runtime shape of a snippet inside DiscussionEvidencePackPayload.
 * Backend types these as Record<string, unknown>; here we narrow to
 * the contract the orchestrator emits today
 * (chunk_id / content / source / score / material_id / section_path /
 * source_labels — no page field).
 */
interface DiscussionSnippet {
  chunk_id?: unknown;
  content?: unknown;
  source?: unknown;
  score?: unknown;
  material_id?: unknown;
  section_path?: unknown;
  source_labels?: unknown;
}

function pickString(v: unknown): string | undefined {
  return typeof v === 'string' && v.length > 0 ? v : undefined;
}

function pickNumber(v: unknown): number | undefined {
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
}

/** Cheap, deterministic fingerprint for snippets without material_id. */
function hashText(text: string): string {
  let h = 0;
  for (let i = 0; i < text.length; i += 1) {
    h = (h * 31 + text.charCodeAt(i)) | 0;
  }
  // Unsigned hex; 8 chars is enough for L1 dedup.
  return (h >>> 0).toString(16).padStart(8, '0');
}

function evidenceIdOf(snippet: DiscussionSnippet, fallbackIndex: number): string {
  const materialId = pickString(snippet.material_id);
  const chunkId = pickString(snippet.chunk_id);
  if (materialId && chunkId) return `ev:${materialId}:${chunkId}`;
  if (materialId) return `ev:${materialId}:${fallbackIndex}`;
  const source = pickString(snippet.source) ?? 'unknown';
  const content = pickString(snippet.content) ?? '';
  return `ev:${source}:${hashText(content)}`;
}

function evidenceLabel(snippet: DiscussionSnippet, index: number): string {
  const content = pickString(snippet.content);
  if (content) {
    return content.length > 60 ? `${content.slice(0, 57)}…` : content;
  }
  const materialId = pickString(snippet.material_id);
  if (materialId) return `evidence ${materialId}`;
  return `evidence #${index + 1}`;
}

export function discussionToGraphPayload(result: DiscussionRunResult): GraphPayloadV0 {
  // --- evidence nodes (deduped) ---
  const evidenceNodes: GraphNode[] = [];
  const evidenceIds: string[] = []; // preserve order of first appearance
  const seenEvidence = new Set<string>();
  // Map per-run E-id (E1, E2, …) to the deduped graph node id so the
  // G5 per-agent attribution path can resolve cited_evidence_ids[] back
  // to actual node ids. Index is 1-based to match the backend's
  // build_evidence_ids contract (snippet position -> "E{i+1}").
  const evidenceIdByEId = new Map<string, string>();
  const snippets = (result.evidence?.snippets ?? []) as DiscussionSnippet[];
  const declaredEvidenceIds = result.evidence?.evidence_ids ?? [];
  snippets.forEach((snippet, index) => {
    const id = evidenceIdOf(snippet, index);
    const eid = declaredEvidenceIds[index] ?? `E${index + 1}`;
    evidenceIdByEId.set(eid, id);
    if (seenEvidence.has(id)) return;
    seenEvidence.add(id);
    evidenceIds.push(id);

    const materialId = pickString(snippet.material_id);
    const chunkId = pickString(snippet.chunk_id);
    const content = pickString(snippet.content);
    const score = pickNumber(snippet.score);
    const sectionPath = pickString(snippet.section_path);
    const source = pickString(snippet.source);

    const evidenceRefs = materialId
      ? [
          {
            material_id: materialId,
            chunk_id: chunkId ?? null,
            page: null, // Discussion snippets do not carry page (per
            // confirmed schema 2026-05-14); KnowledgeBase falls back
            // to page 1 on deep-link.
            text: content ?? '',
            score: score ?? null,
          },
        ]
      : null;

    const metadata: Record<string, unknown> = {};
    if (sectionPath) metadata.section_path = sectionPath;
    if (source) metadata.source = source;
    if (!materialId && content) metadata.content_hash = hashText(content);

    evidenceNodes.push({
      id,
      label: evidenceLabel(snippet, index),
      type: 'evidence',
      material_id: materialId ?? null,
      evidence_refs: evidenceRefs,
      confidence: score ?? null,
      metadata: Object.keys(metadata).length > 0 ? metadata : null,
      source_ref: null,
    });
  });

  // --- agent nodes (dedup by agent_id; carry status) ---
  const agentNodes: GraphNode[] = [];
  const agentSuccess = new Map<string, boolean>();
  // Per-agent union of cited evidence node ids across all turns. Empty
  // set => no citation captured for this agent => fallback path.
  const agentCitedNodes = new Map<string, Set<string>>();
  for (const turn of result.turns) {
    for (const trace of turn.agent_traces) {
      const prev = agentSuccess.get(trace.agent_id);
      // A run may produce one trace per agent per turn. Treat the agent
      // as successful if *any* turn succeeded; failed only if all
      // turns failed.
      agentSuccess.set(trace.agent_id, (prev ?? false) || trace.success);
      if (trace.success && trace.cited_evidence_ids && trace.cited_evidence_ids.length > 0) {
        let set = agentCitedNodes.get(trace.agent_id);
        if (!set) {
          set = new Set<string>();
          agentCitedNodes.set(trace.agent_id, set);
        }
        for (const eid of trace.cited_evidence_ids) {
          const nodeId = evidenceIdByEId.get(eid);
          if (nodeId) set.add(nodeId);
        }
      }
    }
  }
  for (const turn of result.turns) {
    for (const trace of turn.agent_traces) {
      if (agentNodes.some((n) => n.id === trace.agent_id)) continue;
      const overallSuccess = agentSuccess.get(trace.agent_id) ?? false;
      const metadata: Record<string, unknown> = {
        provider: trace.provider,
        model: trace.model,
        role: trace.role,
      };
      if (trace.role_label) metadata.role_label = trace.role_label;
      if (!overallSuccess) metadata.status = 'failed';
      agentNodes.push({
        id: trace.agent_id,
        label: trace.role_label || trace.agent_id,
        type: 'agent',
        metadata,
        material_id: null,
        source_ref: null,
        evidence_refs: null,
        confidence: null,
      });
    }
  }

  // --- edges: per-agent attribution when any agent cited; run-level
  // fallback when nobody did (legacy payloads or no-marker runs). ---
  const edges: GraphEdge[] = [];
  const seenEdge = new Set<string>();
  const someoneCited = Array.from(agentCitedNodes.values()).some((s) => s.size > 0);

  function emitEdge(agentId: string, evidenceId: string, via: 'citation' | 'run_level'): void {
    const key = `${agentId}|${evidenceId}`;
    if (seenEdge.has(key)) return;
    seenEdge.add(key);
    edges.push({
      id: `edge:${key}`,
      source: agentId,
      target: evidenceId,
      relation: 'uses',
      material_id: null,
      source_ref: null,
      evidence_refs: null,
      confidence: null,
      metadata: { via },
    });
  }

  for (const agentNode of agentNodes) {
    if (agentSuccess.get(agentNode.id) !== true) continue;
    if (someoneCited) {
      // Per-agent attribution: only edges to actually cited evidence.
      // Agents that didn't cite (empty / undefined set) get no edges.
      const cited = agentCitedNodes.get(agentNode.id);
      if (!cited || cited.size === 0) continue;
      for (const evidenceId of evidenceIds) {
        if (!cited.has(evidenceId)) continue;
        emitEdge(agentNode.id, evidenceId, 'citation');
      }
    } else {
      // Run-level fallback: every successful agent → every evidence.
      for (const evidenceId of evidenceIds) {
        emitEdge(agentNode.id, evidenceId, 'run_level');
      }
    }
  }

  return {
    version: 'v0',
    scope: { kind: 'question', ref: result.run_id },
    updated_at: new Date().toISOString(),
    nodes: [...agentNodes, ...evidenceNodes],
    edges,
  };
}
