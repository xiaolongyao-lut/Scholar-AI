import dagre from '@dagrejs/dagre';
import type { Edge, Node } from '@xyflow/react';

export interface LayoutOptions {
  // Node box size hint for dagre. React Flow renders fixed-size boxes
  // for now; if we add dynamic sizing later, measure first then re-layout.
  nodeWidth?: number;
  nodeHeight?: number;
  rankdir?: 'TB' | 'LR' | 'BT' | 'RL';
  ranksep?: number;
  nodesep?: number;
  staggerRankSiblings?: boolean;
}

const DEFAULTS: Required<LayoutOptions> = {
  nodeWidth: 160,
  nodeHeight: 48,
  rankdir: 'LR',
  ranksep: 110,
  nodesep: 44,
  staggerRankSiblings: true,
};

interface NodeBox {
  width: number;
  height: number;
}

function readCssSize(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value;
  if (typeof value === 'string') {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  return fallback;
}

function nodeBox(node: Node, options: Required<LayoutOptions>): NodeBox {
  const width = readCssSize(node.style?.width, options.nodeWidth);
  const height = readCssSize(node.style?.height, readCssSize(node.style?.minHeight, options.nodeHeight));
  return { width, height };
}

function staggerOffset(index: number): number {
  const lane = index % 3;
  if (lane === 0) return -28;
  if (lane === 2) return 28;
  return 0;
}

function applyRankStagger(nodes: Node[], rankdir: Required<LayoutOptions>['rankdir']): Node[] {
  const rankKey = (node: Node): string => {
    const axis = rankdir === 'LR' || rankdir === 'RL' ? node.position.x : node.position.y;
    return String(Math.round(axis / 10) * 10);
  };
  const groups = new Map<string, Node[]>();
  for (const node of nodes) {
    const key = rankKey(node);
    const group = groups.get(key) ?? [];
    group.push(node);
    groups.set(key, group);
  }
  const offsets = new Map<string, number>();
  for (const group of groups.values()) {
    if (group.length < 4) continue;
    group.forEach((node, index) => offsets.set(node.id, staggerOffset(index)));
  }
  return nodes.map((node) => {
    const offset = offsets.get(node.id);
    if (offset === undefined) return node;
    return {
      ...node,
      position: rankdir === 'LR' || rankdir === 'RL'
        ? { x: node.position.x + offset, y: node.position.y }
        : { x: node.position.x, y: node.position.y + offset },
    };
  });
}

/**
 * Run dagre over a set of React Flow nodes + edges and return new nodes
 * with `position` filled in. Edges are returned as-is; dagre only positions
 * vertices.
 *
 * Pure function — same input always produces the same output, which makes
 * it cheap to unit-test without a DOM.
 */
export function layoutWithDagre(
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions = {},
): { nodes: Node[]; edges: Edge[] } {
  const opts = { ...DEFAULTS, ...options };
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: opts.rankdir, ranksep: opts.ranksep, nodesep: opts.nodesep });
  g.setDefaultEdgeLabel(() => ({}));
  const boxes = new Map<string, NodeBox>();

  for (const node of nodes) {
    const box = nodeBox(node, opts);
    boxes.set(node.id, box);
    g.setNode(node.id, { width: box.width, height: box.height });
  }
  for (const edge of edges) {
    // dagre rejects edges with unknown endpoints; the GraphPayload adapter
    // already drops such edges, but guard so a stale payload can't crash.
    if (g.hasNode(edge.source) && g.hasNode(edge.target)) {
      g.setEdge(edge.source, edge.target);
    }
  }

  dagre.layout(g);

  const positioned = nodes.map((node) => {
    const laid = g.node(node.id);
    if (!laid) return node;
    const box = boxes.get(node.id) ?? { width: opts.nodeWidth, height: opts.nodeHeight };
    return {
      ...node,
      // dagre gives the centre of the box; React Flow positions by top-left.
      position: { x: laid.x - box.width / 2, y: laid.y - box.height / 2 },
    };
  });

  return { nodes: opts.staggerRankSiblings ? applyRankStagger(positioned, opts.rankdir) : positioned, edges };
}
