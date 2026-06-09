import { WikiWorkbench } from '@/pages/WikiWorkbench';

/**
 * Render the curated knowledge implementation under the product name 知识库.
 *
 * Why:
 * Wiki remains the durable implementation boundary, while the workbench presents
 * a stable user-facing knowledge-library section.
 */
export function KnowledgeLibraryPanel() {
  return <WikiWorkbench embedded />;
}
