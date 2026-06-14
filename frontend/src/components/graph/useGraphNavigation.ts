import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

import { locateChunk, type ChunkLocator } from '@/services/resourcesApi';
import { encodePdfBboxParam, type PdfBboxUnit } from '@/lib/pdfAnchor';
import type { GraphNavigateTarget } from './GraphPayloadViewer';
import { resolveMaterialTarget, type GraphNode, type MaterialTarget } from './payloadToRf';

/**
 * 图谱导航共享逻辑。维度图谱与关系图谱共用同一套「解析定位 → chunk 补全 →
 * 跳转 PDF/材料」管线，避免两份 viewer 各写一遍出现行为漂移。
 *
 * 输入：
 * - projectId: 当前项目；chunk locator 需要它来补 page/bbox。
 * - onNavigateTarget: 宿主页提供时，跳转交给宿主（嵌入式 PDF）；否则走路由。
 *
 * 输出：
 * - navigateNode(node): 解析节点 → 若有材料定位则跳转，返回是否成功跳转。
 * - resolveTarget(node): 仅解析，不跳转（供详情面板判断「打开原文」是否可用）。
 */

// 跨组件实例共享 locator 缓存，避免重复请求同一 chunk 的定位。
const graphLocatorCache = new Map<string, ChunkLocator | null>();

function locatorCacheKey(projectId: string, chunkId: string): string {
  return `${projectId}::${chunkId}`;
}

/** @internal — 测试用，清空 locator 缓存。 */
export function __resetGraphNavigationCacheForTests(): void {
  graphLocatorCache.clear();
}

export interface UseGraphNavigationOptions {
  projectId?: string | null;
  onNavigateTarget?: (target: GraphNavigateTarget) => void;
}

export interface UseGraphNavigation {
  resolveTarget: (node: GraphNode) => MaterialTarget | null;
  navigateNode: (node: GraphNode) => Promise<boolean>;
}

export function useGraphNavigation({
  projectId,
  onNavigateTarget,
}: UseGraphNavigationOptions): UseGraphNavigation {
  const navigate = useNavigate();

  const navigateToMaterialTarget = useCallback(
    async (target: MaterialTarget): Promise<boolean> => {
      let page = typeof target.page === 'number' && target.page > 0 ? target.page : null;
      let bbox = Array.isArray(target.bbox) && target.bbox.length === 4 ? target.bbox : null;
      let bboxUnit: PdfBboxUnit | null = target.bbox_unit ?? null;
      const normalizedProjectId = typeof projectId === 'string' ? projectId.trim() : '';

      // 缺 page/bbox 时，靠 chunk locator 在当前项目里补全锚点。
      if (target.chunk_id && normalizedProjectId && (!page || !bbox)) {
        const key = locatorCacheKey(normalizedProjectId, target.chunk_id);
        let locator = graphLocatorCache.get(key);
        if (locator === undefined) {
          locator = await locateChunk(target.chunk_id, normalizedProjectId);
          graphLocatorCache.set(key, locator);
        }
        if (locator?.material_id === target.material_id) {
          if (!page && typeof locator.page === 'number' && locator.page > 0) {
            page = locator.page;
          }
          if (!bbox && Array.isArray(locator.bbox) && locator.bbox.length === 4) {
            bbox = locator.bbox;
            bboxUnit = locator.bbox_unit ?? null;
          }
        }
      }

      if (onNavigateTarget) {
        onNavigateTarget({
          material_id: target.material_id,
          page,
          chunk_id: target.chunk_id ?? null,
          bbox,
          bbox_unit: bboxUnit,
        });
        return true;
      }

      const params = new URLSearchParams();
      if (page) params.set('page', String(page));
      if (target.chunk_id) params.set('chunk', target.chunk_id);
      const bboxParam = encodePdfBboxParam(bbox, bboxUnit);
      if (bboxParam) params.set('bbox', bboxParam);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      navigate(`/workbench/paper/${encodeURIComponent(target.material_id)}${suffix}`);
      return true;
    },
    [navigate, onNavigateTarget, projectId],
  );

  const navigateNode = useCallback(
    async (node: GraphNode): Promise<boolean> => {
      const target = resolveMaterialTarget(node);
      if (!target) return false;
      return navigateToMaterialTarget(target);
    },
    [navigateToMaterialTarget],
  );

  const resolveTarget = useCallback((node: GraphNode) => resolveMaterialTarget(node), []);

  return { resolveTarget, navigateNode };
}
