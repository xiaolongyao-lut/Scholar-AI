import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";

describe("writing resource export types", () => {
  it("aliases academic export appendix types from generated OpenAPI schemas", () => {
    const source = readFileSync("src/types/resources.ts", "utf8");

    expect(source).toMatch(
      /export type ProjectExportEvidenceRow\s*=\s*components\["schemas"\]\["ProjectExportEvidenceRowPayload"\]/,
    );
    expect(source).toMatch(
      /export type ProjectExportCitationChainRow\s*=\s*components\["schemas"\]\["ProjectExportCitationChainPayload"\]/,
    );
    expect(source).toMatch(
      /export type ProjectExportReviewFinding\s*=\s*components\["schemas"\]\["ProjectExportReviewFindingPayload"\]/,
    );
    expect(source).toMatch(
      /export type ProjectExportResult\s*=\s*components\["schemas"\]\["ProjectExportPayload"\]/,
    );
  });
});
