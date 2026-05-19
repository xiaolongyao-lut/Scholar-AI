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
}

const DEFAULTS: Required<LayoutOptions> = {
  nodeWidth: 160,
  nodeHeight: 48,
  rankdir: 'LR',
  ranksep: 80,
  nodesep: 28,
};

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

  for (const node of nodes) {
    g.setNode(node.id, { width: opts.nodeWidth, height: opts.nodeHeight });
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
    return {
      ...node,
      // dagre gives the centre of the box; React Flow positions by top-left.
      position: { x: laid.x - opts.nodeWidth / 2, y: laid.y - opts.nodeHeight / 2 },
    };
  });

  return { nodes: positioned, edges };
}
