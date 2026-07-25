export interface NetworkGraphLayoutNode {
  readonly id: string;
  readonly width: number;
  readonly height: number;
}

export interface NetworkGraphLayoutEdge {
  readonly source: string;
  readonly target: string;
}

export interface NetworkGraphPosition {
  readonly x: number;
  readonly y: number;
}

interface NormalizedNode extends NetworkGraphLayoutNode {
  readonly index: number;
}

interface NormalizedEdge {
  readonly source: number;
  readonly target: number;
}

interface ComponentLayout {
  readonly nodeIndices: readonly number[];
  readonly positions: ReadonlyMap<number, NetworkGraphPosition>;
  readonly width: number;
  readonly height: number;
  readonly firstNodeId: string;
}

const DEFAULT_NODE_SIZE = 32;
const MAX_NODE_SIZE = 4_096;
const NODE_GAP = 14;
const COMPONENT_GAP = 112;
const CANVAS_PADDING = 48;
const FULL_FORCE_NODE_LIMIT = 80;
const MEDIUM_FORCE_NODE_LIMIT = 180;
const MAX_FORCE_NODE_LIMIT = 320;
const FULL_FORCE_ITERATIONS = 140;
const MEDIUM_FORCE_ITERATIONS = 100;
const LARGE_FORCE_ITERATIONS = 32;
const FULL_COLLISION_PASSES = 80;
const MEDIUM_COLLISION_PASSES = 48;
const LARGE_COLLISION_PASSES = 32;
const EXACT_CENTRALITY_CANDIDATE_LIMIT = 32;
const CENTRALITY_SAMPLE_COUNT = 9;
const MIN_EDGE_LENGTH = 92;
const MAX_EDGE_LENGTH = 180;
const EDGE_LENGTH_SCALE = 2.6;
const REPULSION_SCALE = 0.16;
const SPRING_STRENGTH = 0.08;
const CENTER_GRAVITY = 0.008;
const VELOCITY_DAMPING = 0.72;
const POSITION_PRECISION = 1_000;

function compareIds(left: string, right: string): number {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function finiteSize(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return DEFAULT_NODE_SIZE;
  return Math.min(value, MAX_NODE_SIZE);
}

function normalizeNodes(nodes: readonly NetworkGraphLayoutNode[]): NormalizedNode[] {
  const byId = new Map<string, { width: number; height: number }>();
  for (const node of nodes) {
    const width = finiteSize(node.width);
    const height = finiteSize(node.height);
    const existing = byId.get(node.id);
    byId.set(node.id, existing
      ? { width: Math.max(existing.width, width), height: Math.max(existing.height, height) }
      : { width, height });
  }

  return Array.from(byId.entries())
    .sort(([leftId], [rightId]) => compareIds(leftId, rightId))
    .map(([id, dimensions], index) => ({ id, ...dimensions, index }));
}

function normalizeEdges(
  edges: readonly NetworkGraphLayoutEdge[],
  nodeIndex: ReadonlyMap<string, number>,
): NormalizedEdge[] {
  const uniquePairs = new Map<string, NormalizedEdge>();
  for (const edge of edges) {
    const rawSource = nodeIndex.get(edge.source);
    const rawTarget = nodeIndex.get(edge.target);
    if (rawSource === undefined || rawTarget === undefined || rawSource === rawTarget) {
      continue;
    }
    const source = Math.min(rawSource, rawTarget);
    const target = Math.max(rawSource, rawTarget);
    uniquePairs.set(`${source}:${target}`, { source, target });
  }
  return Array.from(uniquePairs.values()).sort((left, right) => (
    left.source - right.source || left.target - right.target
  ));
}

function buildAdjacency(nodeCount: number, edges: readonly NormalizedEdge[]): number[][] {
  const adjacency = Array.from({ length: nodeCount }, () => new Set<number>());
  for (const edge of edges) {
    adjacency[edge.source].add(edge.target);
    adjacency[edge.target].add(edge.source);
  }
  return adjacency.map((neighbours) => Array.from(neighbours).sort((left, right) => left - right));
}

function findComponents(adjacency: readonly (readonly number[])[]): number[][] {
  const visited = new Uint8Array(adjacency.length);
  const components: number[][] = [];
  for (let start = 0; start < adjacency.length; start += 1) {
    if (visited[start] === 1) continue;
    visited[start] = 1;
    const queue = [start];
    const component: number[] = [];
    for (let cursor = 0; cursor < queue.length; cursor += 1) {
      const nodeIndex = queue[cursor];
      component.push(nodeIndex);
      for (const neighbour of adjacency[nodeIndex]) {
        if (visited[neighbour] === 1) continue;
        visited[neighbour] = 1;
        queue.push(neighbour);
      }
    }
    component.sort((left, right) => left - right);
    components.push(component);
  }
  return components;
}

function centralityScore(start: number, adjacency: readonly (readonly number[])[]): readonly [number, number] {
  const distances = new Int32Array(adjacency.length);
  distances.fill(-1);
  distances[start] = 0;
  const queue = [start];
  let distanceSum = 0;
  let eccentricity = 0;
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const nodeIndex = queue[cursor];
    const nextDistance = distances[nodeIndex] + 1;
    for (const neighbour of adjacency[nodeIndex]) {
      if (distances[neighbour] >= 0) continue;
      distances[neighbour] = nextDistance;
      distanceSum += nextDistance;
      eccentricity = Math.max(eccentricity, nextDistance);
      queue.push(neighbour);
    }
  }
  return [eccentricity, distanceSum];
}

function chooseHub(
  component: readonly number[],
  adjacency: readonly (readonly number[])[],
  nodes: readonly NormalizedNode[],
): number {
  let maximumDegree = -1;
  for (const nodeIndex of component) {
    maximumDegree = Math.max(maximumDegree, adjacency[nodeIndex].length);
  }
  const candidates = component.filter((nodeIndex) => adjacency[nodeIndex].length === maximumDegree);
  if (candidates.length === 1 || maximumDegree === component.length - 1) {
    return candidates[0];
  }
  const scoredCandidates = candidates.length <= EXACT_CENTRALITY_CANDIDATE_LIMIT
    ? candidates
    : Array.from({ length: CENTRALITY_SAMPLE_COUNT }, (_, sampleIndex) => (
        candidates[Math.round(sampleIndex * (candidates.length - 1) / (CENTRALITY_SAMPLE_COUNT - 1))]
      )).filter((candidate, index, sampled) => index === 0 || candidate !== sampled[index - 1]);
  let selected = scoredCandidates[0];
  let selectedScore = centralityScore(selected, adjacency);
  for (let index = 1; index < scoredCandidates.length; index += 1) {
    const candidate = scoredCandidates[index];
    const score = centralityScore(candidate, adjacency);
    const isBetter = score[0] < selectedScore[0]
      || (score[0] === selectedScore[0] && score[1] < selectedScore[1])
      || (score[0] === selectedScore[0]
        && score[1] === selectedScore[1]
        && compareIds(nodes[candidate].id, nodes[selected].id) < 0);
    if (isBetter) {
      selected = candidate;
      selectedScore = score;
    }
  }
  return selected;
}

interface RadialSeed {
  readonly x: Float64Array;
  readonly y: Float64Array;
  readonly hubLocalIndex: number;
}

function seedRadialPositions(
  component: readonly number[],
  adjacency: readonly (readonly number[])[],
  nodes: readonly NormalizedNode[],
  edgeLength: number,
): RadialSeed {
  const componentLookup = new Map(component.map((nodeIndex, localIndex) => [nodeIndex, localIndex]));
  const hubNodeIndex = chooseHub(component, adjacency, nodes);
  const hubLocalIndex = componentLookup.get(hubNodeIndex) ?? 0;
  const levels = new Int32Array(component.length);
  const parents = new Int32Array(component.length);
  levels.fill(-1);
  parents.fill(-1);
  levels[hubLocalIndex] = 0;
  const queue = [hubNodeIndex];
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const nodeIndex = queue[cursor];
    const localIndex = componentLookup.get(nodeIndex);
    if (localIndex === undefined) continue;
    for (const neighbour of adjacency[nodeIndex]) {
      const neighbourLocalIndex = componentLookup.get(neighbour);
      if (neighbourLocalIndex === undefined || levels[neighbourLocalIndex] >= 0) continue;
      levels[neighbourLocalIndex] = levels[localIndex] + 1;
      parents[neighbourLocalIndex] = localIndex;
      queue.push(neighbour);
    }
  }

  const x = new Float64Array(component.length);
  const y = new Float64Array(component.length);
  const angleByLocalIndex = new Float64Array(component.length);
  const angularOrder = new Int32Array(component.length);
  const maximumLevel = Math.max(0, ...levels);
  let previousRadius = 0;
  let previousMaximumNodeRadius = Math.hypot(
    nodes[hubNodeIndex].width,
    nodes[hubNodeIndex].height,
  ) / 2;
  for (let level = 1; level <= maximumLevel; level += 1) {
    const ring = component
      .map((_, localIndex) => localIndex)
      .filter((localIndex) => levels[localIndex] === level)
      .sort((left, right) => {
        const leftParent = parents[left];
        const rightParent = parents[right];
        const parentOrder = angularOrder[leftParent] - angularOrder[rightParent];
        if (parentOrder !== 0) return parentOrder;
        const degreeOrder = adjacency[component[right]].length - adjacency[component[left]].length;
        if (degreeOrder !== 0) return degreeOrder;
        return compareIds(nodes[component[left]].id, nodes[component[right]].id);
      });
    const maximumNodeRadius = Math.max(...ring.map((localIndex) => {
      const node = nodes[component[localIndex]];
      return Math.hypot(node.width, node.height) / 2;
    }));
    const circumferenceRadius = ring.length <= 1
      ? 0
      : (maximumNodeRadius * 2 + NODE_GAP) / (2 * Math.sin(Math.PI / ring.length));
    const radialSeparation = previousRadius
      + previousMaximumNodeRadius
      + maximumNodeRadius
      + NODE_GAP;
    const radius = Math.max(
      level * edgeLength * 0.92,
      circumferenceRadius,
      radialSeparation,
      edgeLength * 0.72,
    );
    const phase = -Math.PI / 2 + (level % 2 === 0 ? Math.PI / Math.max(2, ring.length) : 0);
    ring.forEach((localIndex, order) => {
      let angle = phase + (Math.PI * 2 * order) / Math.max(1, ring.length);
      if (ring.length === 1 && level > 1) {
        angle = angleByLocalIndex[parents[localIndex]];
      }
      x[localIndex] = Math.cos(angle) * radius;
      y[localIndex] = Math.sin(angle) * radius;
      angleByLocalIndex[localIndex] = angle;
      angularOrder[localIndex] = order;
    });
    previousRadius = radius;
    previousMaximumNodeRadius = maximumNodeRadius;
  }
  return { x, y, hubLocalIndex };
}

function forceIterationsForNodeCount(nodeCount: number): number {
  if (nodeCount <= FULL_FORCE_NODE_LIMIT) return FULL_FORCE_ITERATIONS;
  if (nodeCount <= MEDIUM_FORCE_NODE_LIMIT) return MEDIUM_FORCE_ITERATIONS;
  if (nodeCount <= MAX_FORCE_NODE_LIMIT) return LARGE_FORCE_ITERATIONS;
  return 0;
}

function collisionPassesForNodeCount(nodeCount: number): number {
  if (nodeCount <= FULL_FORCE_NODE_LIMIT) return FULL_COLLISION_PASSES;
  if (nodeCount <= MEDIUM_FORCE_NODE_LIMIT) return MEDIUM_COLLISION_PASSES;
  return LARGE_COLLISION_PASSES;
}

function simulateComponent(
  component: readonly number[],
  componentEdges: readonly NormalizedEdge[],
  adjacency: readonly (readonly number[])[],
  nodes: readonly NormalizedNode[],
): RadialSeed {
  const averageDiameter = component.reduce((sum, nodeIndex) => (
    sum + Math.max(nodes[nodeIndex].width, nodes[nodeIndex].height)
  ), 0) / component.length;
  const edgeLength = Math.min(
    MAX_EDGE_LENGTH,
    Math.max(MIN_EDGE_LENGTH, averageDiameter * EDGE_LENGTH_SCALE),
  );
  const seed = seedRadialPositions(component, adjacency, nodes, edgeLength);
  const forceIterations = forceIterationsForNodeCount(component.length);
  if (component.length === 1 || forceIterations === 0) return seed;

  const localIndexByNode = new Map(component.map((nodeIndex, localIndex) => [nodeIndex, localIndex]));
  const localEdges = componentEdges.map((edge) => ({
    source: localIndexByNode.get(edge.source) ?? -1,
    target: localIndexByNode.get(edge.target) ?? -1,
  })).filter((edge) => edge.source >= 0 && edge.target >= 0);
  const velocityX = new Float64Array(component.length);
  const velocityY = new Float64Array(component.length);
  const forceX = new Float64Array(component.length);
  const forceY = new Float64Array(component.length);
  const repulsionConstant = edgeLength * edgeLength * REPULSION_SCALE;

  for (let iteration = 0; iteration < forceIterations; iteration += 1) {
    forceX.fill(0);
    forceY.fill(0);
    for (let left = 0; left < component.length; left += 1) {
      for (let right = left + 1; right < component.length; right += 1) {
        let deltaX = seed.x[right] - seed.x[left];
        let deltaY = seed.y[right] - seed.y[left];
        let distance = Math.hypot(deltaX, deltaY);
        if (distance < 1e-6) {
          const direction = (left + right) % 2 === 0 ? 1 : -1;
          deltaX = direction;
          deltaY = direction * 0.5;
          distance = Math.hypot(deltaX, deltaY);
        }
        const unitX = deltaX / distance;
        const unitY = deltaY / distance;
        const repulsion = repulsionConstant / Math.max(distance, edgeLength * 0.12);
        forceX[left] -= unitX * repulsion;
        forceY[left] -= unitY * repulsion;
        forceX[right] += unitX * repulsion;
        forceY[right] += unitY * repulsion;

        const leftNode = nodes[component[left]];
        const rightNode = nodes[component[right]];
        const overlapX = (leftNode.width + rightNode.width) / 2 + NODE_GAP - Math.abs(deltaX);
        const overlapY = (leftNode.height + rightNode.height) / 2 + NODE_GAP - Math.abs(deltaY);
        if (overlapX > 0 && overlapY > 0) {
          if (overlapX <= overlapY) {
            const sign = deltaX >= 0 ? 1 : -1;
            forceX[left] -= sign * overlapX * 0.75;
            forceX[right] += sign * overlapX * 0.75;
          } else {
            const sign = deltaY >= 0 ? 1 : -1;
            forceY[left] -= sign * overlapY * 0.75;
            forceY[right] += sign * overlapY * 0.75;
          }
        }
      }
    }

    for (const edge of localEdges) {
      const deltaX = seed.x[edge.target] - seed.x[edge.source];
      const deltaY = seed.y[edge.target] - seed.y[edge.source];
      const distance = Math.max(1e-6, Math.hypot(deltaX, deltaY));
      const sourceNode = nodes[component[edge.source]];
      const targetNode = nodes[component[edge.target]];
      const nodeRadius = (
        Math.max(sourceNode.width, sourceNode.height)
        + Math.max(targetNode.width, targetNode.height)
      ) / 4;
      const restLength = edgeLength + nodeRadius;
      const attraction = (distance - restLength) * SPRING_STRENGTH;
      const unitX = deltaX / distance;
      const unitY = deltaY / distance;
      forceX[edge.source] += unitX * attraction;
      forceY[edge.source] += unitY * attraction;
      forceX[edge.target] -= unitX * attraction;
      forceY[edge.target] -= unitY * attraction;
    }

    const progress = iteration / Math.max(1, forceIterations - 1);
    const temperature = edgeLength * (0.62 * (1 - progress) + 0.018);
    for (let localIndex = 0; localIndex < component.length; localIndex += 1) {
      if (localIndex === seed.hubLocalIndex) {
        seed.x[localIndex] = 0;
        seed.y[localIndex] = 0;
        velocityX[localIndex] = 0;
        velocityY[localIndex] = 0;
        continue;
      }
      forceX[localIndex] -= seed.x[localIndex] * CENTER_GRAVITY;
      forceY[localIndex] -= seed.y[localIndex] * CENTER_GRAVITY;
      velocityX[localIndex] = (velocityX[localIndex] + forceX[localIndex]) * VELOCITY_DAMPING;
      velocityY[localIndex] = (velocityY[localIndex] + forceY[localIndex]) * VELOCITY_DAMPING;
      const speed = Math.hypot(velocityX[localIndex], velocityY[localIndex]);
      if (speed > temperature) {
        velocityX[localIndex] = velocityX[localIndex] / speed * temperature;
        velocityY[localIndex] = velocityY[localIndex] / speed * temperature;
      }
      seed.x[localIndex] += velocityX[localIndex];
      seed.y[localIndex] += velocityY[localIndex];
    }
  }
  return seed;
}

function resolveNodeCollisions(
  component: readonly number[],
  nodes: readonly NormalizedNode[],
  x: Float64Array,
  y: Float64Array,
  hubLocalIndex: number,
): void {
  const collisionPasses = collisionPassesForNodeCount(component.length);
  for (let pass = 0; pass < collisionPasses; pass += 1) {
    let collisionFound = false;
    for (let left = 0; left < component.length; left += 1) {
      const leftNode = nodes[component[left]];
      for (let right = left + 1; right < component.length; right += 1) {
        const rightNode = nodes[component[right]];
        const deltaX = x[right] - x[left];
        const deltaY = y[right] - y[left];
        const overlapX = (leftNode.width + rightNode.width) / 2 + NODE_GAP - Math.abs(deltaX);
        const overlapY = (leftNode.height + rightNode.height) / 2 + NODE_GAP - Math.abs(deltaY);
        if (overlapX <= 0 || overlapY <= 0) continue;
        collisionFound = true;
        const separateHorizontally = overlapX <= overlapY;
        const overlap = separateHorizontally ? overlapX : overlapY;
        const rawDelta = separateHorizontally ? deltaX : deltaY;
        const sign = rawDelta === 0 ? ((left + right) % 2 === 0 ? 1 : -1) : Math.sign(rawDelta);
        const leftShare = left === hubLocalIndex ? 0 : (right === hubLocalIndex ? 1 : 0.5);
        const rightShare = right === hubLocalIndex ? 0 : (left === hubLocalIndex ? 1 : 0.5);
        if (separateHorizontally) {
          x[left] -= sign * overlap * leftShare;
          x[right] += sign * overlap * rightShare;
        } else {
          y[left] -= sign * overlap * leftShare;
          y[right] += sign * overlap * rightShare;
        }
      }
    }
    if (!collisionFound) return;
  }
}

function layoutComponent(
  component: readonly number[],
  edges: readonly NormalizedEdge[],
  adjacency: readonly (readonly number[])[],
  nodes: readonly NormalizedNode[],
): ComponentLayout {
  const componentSet = new Set(component);
  const componentEdges = edges.filter((edge) => (
    componentSet.has(edge.source) && componentSet.has(edge.target)
  ));
  const simulated = simulateComponent(component, componentEdges, adjacency, nodes);
  if (component.length <= MAX_FORCE_NODE_LIMIT) {
    resolveNodeCollisions(component, nodes, simulated.x, simulated.y, simulated.hubLocalIndex);
  }

  let minimumX = Number.POSITIVE_INFINITY;
  let minimumY = Number.POSITIVE_INFINITY;
  let maximumX = Number.NEGATIVE_INFINITY;
  let maximumY = Number.NEGATIVE_INFINITY;
  for (let localIndex = 0; localIndex < component.length; localIndex += 1) {
    const node = nodes[component[localIndex]];
    minimumX = Math.min(minimumX, simulated.x[localIndex] - node.width / 2);
    minimumY = Math.min(minimumY, simulated.y[localIndex] - node.height / 2);
    maximumX = Math.max(maximumX, simulated.x[localIndex] + node.width / 2);
    maximumY = Math.max(maximumY, simulated.y[localIndex] + node.height / 2);
  }
  const positions = new Map<number, NetworkGraphPosition>();
  for (let localIndex = 0; localIndex < component.length; localIndex += 1) {
    const nodeIndex = component[localIndex];
    const node = nodes[nodeIndex];
    positions.set(nodeIndex, {
      x: simulated.x[localIndex] - node.width / 2 - minimumX,
      y: simulated.y[localIndex] - node.height / 2 - minimumY,
    });
  }
  return {
    nodeIndices: component,
    positions,
    width: Math.max(1, maximumX - minimumX),
    height: Math.max(1, maximumY - minimumY),
    firstNodeId: nodes[component[0]].id,
  };
}

function roundPosition(value: number): number {
  const rounded = Math.round(value * POSITION_PRECISION) / POSITION_PRECISION;
  return Object.is(rounded, -0) ? 0 : rounded;
}

function packComponents(
  layouts: readonly ComponentLayout[],
  nodes: readonly NormalizedNode[],
): ReadonlyMap<string, NetworkGraphPosition> {
  const orderedLayouts = [...layouts].sort((left, right) => (
    right.width * right.height - left.width * left.height
    || right.nodeIndices.length - left.nodeIndices.length
    || compareIds(left.firstNodeId, right.firstNodeId)
  ));
  const paddedArea = orderedLayouts.reduce((sum, layout) => (
    sum + (layout.width + COMPONENT_GAP) * (layout.height + COMPONENT_GAP)
  ), 0);
  const widestLayout = Math.max(0, ...orderedLayouts.map((layout) => layout.width));
  const targetRowWidth = Math.max(widestLayout, Math.sqrt(paddedArea) * 1.35);
  const packedByIndex = new Map<number, NetworkGraphPosition>();
  let cursorX = CANVAS_PADDING;
  let cursorY = CANVAS_PADDING;
  let rowHeight = 0;
  for (const layout of orderedLayouts) {
    if (cursorX > CANVAS_PADDING && cursorX + layout.width > CANVAS_PADDING + targetRowWidth) {
      cursorX = CANVAS_PADDING;
      cursorY += rowHeight + COMPONENT_GAP;
      rowHeight = 0;
    }
    for (const nodeIndex of layout.nodeIndices) {
      const localPosition = layout.positions.get(nodeIndex);
      if (!localPosition) continue;
      packedByIndex.set(nodeIndex, {
        x: cursorX + localPosition.x,
        y: cursorY + localPosition.y,
      });
    }
    cursorX += layout.width + COMPONENT_GAP;
    rowHeight = Math.max(rowHeight, layout.height);
  }

  const result = new Map<string, NetworkGraphPosition>();
  for (const node of nodes) {
    const position = packedByIndex.get(node.index) ?? { x: CANVAS_PADDING, y: CANVAS_PADDING };
    result.set(node.id, { x: roundPosition(position.x), y: roundPosition(position.y) });
  }
  return result;
}

/**
 * Computes a bounded, one-shot force layout for dense read-only networks.
 * Edges are treated as undirected layout constraints; duplicate, self, and
 * dangling edges are ignored. Returned coordinates use top-left node origins.
 */
export function layoutNetworkGraph(
  inputNodes: readonly NetworkGraphLayoutNode[],
  inputEdges: readonly NetworkGraphLayoutEdge[],
): ReadonlyMap<string, NetworkGraphPosition> {
  const nodes = normalizeNodes(inputNodes);
  if (nodes.length === 0) return new Map<string, NetworkGraphPosition>();
  const nodeIndex = new Map(nodes.map((node) => [node.id, node.index]));
  const edges = normalizeEdges(inputEdges, nodeIndex);
  const adjacency = buildAdjacency(nodes.length, edges);
  const components = findComponents(adjacency);
  const layouts = components.map((component) => layoutComponent(component, edges, adjacency, nodes));
  return packComponents(layouts, nodes);
}
