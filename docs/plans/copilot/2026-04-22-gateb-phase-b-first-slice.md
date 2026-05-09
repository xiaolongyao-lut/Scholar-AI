<!-- markdownlint-disable-file -->
# Plan: Gate B Phase B first slice

## Summary

Deliver the first safe Phase B slice by exporting deduplicated candidate pools for the existing 36 scaffold queries without changing the canonical goldset/qrels pair.

## Phase 1 - Offline pool export

- [x] Add the minimum offline pool-export tooling for the 36 scaffold queries.
- [x] Preserve per-source labels and include each query's original evidence docs in the pool when present.
- [x] Write a separate annotation-input artifact without mutating canonical Gate B artifacts.
- [x] Add focused regression coverage for deduplication, source labels, and canonical immutability.

