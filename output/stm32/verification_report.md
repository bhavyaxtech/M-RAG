# STM32 collection verification - September 8, 2026

## Verdict

The collection is operational. This is not a completed human-graded accuracy benchmark.
The live app can retrieve across PDFs and open the actual cited document/page.
Broader technical questions still expose retrieval omissions and citation-quality limits.

## Verified artifacts

- 20 PDFs, 1,837 physical pages; every PDF SHA-256 and page count matches the saved source manifest.
- 3,289 multimodal vectors and 1,675 text-only vectors, 3,072 dimensions.
- All vectors finite and normalized; the baseline vectors are byte-identical to the shared text portion of the multimodal index.
- 563 figures and 1,051 tables: all 1,614 indexed crop files successfully decoded.
- HTTP checks: all 20 documents listed, 40 first/last-page PNGs served, 20 sampled crops byte-identical to disk.
- Original hardware indexes and scored evaluation were not rebuilt.

Evidence: `live_validation/integrity.json`, `app_verification.json`.

## Live application checks

- Collection query comparing AN2594 with AN2557 completed with eight displayed sources, including unused evidence.
- Citations opened AN2557 physical pages 1 and 12, and AN2594 physical page 5, independently of the selected PDF.
- The table page viewer exposed the evidence-region overlay.
- A real pinout question displayed all five retrieved crops, all loaded with positive image dimensions; no horizontal page overflow was detected at the tested browser size.
- Invalid-page handling was tested through the UI after the repair and returned an empty evidence panel.
- These are browser interaction/DOM checks, not a complete human visual-layout audit.

## Answer review

Six existing candidate questions plus a package-specific pinout question were run through both modes; missing-page and wrong-component checks added two requests (16 initial requests). Seven affected requests were repeated after the retrieval repair. All completed without transport/model errors. Raw events, answers, citations, and request payloads are saved under `live_validation/` and `live_validation/after-fix/`.

This review was performed by Codex against the saved PDFs, not by a human grader. No aggregate accuracy or multimodal-superiority score is justified by this small, selected sample.

| Case | Source-backed finding |
|---|---|
| LQFP48 PA9/PA10 | M-RAG correctly gives pin 30 / USART1_TX and pin 31 / USART1_RX, supported by DS5319 physical pages 26 and 31. Text-only explicitly could not verify the mapping. This is one observed multimodal advantage, not a benchmark result. |
| Oscillator design | Both modes give useful general guidance but omit the device-specific numerical characteristics in DS5319 Table 22, physical page 52. M-RAG retrieved the neighboring circuit figure rather than that table. |
| Flash EEPROM emulation | Main two-page mechanism is supported by AN2594 p.7; HSI and stalls by PM0075 p.10. The response is not a complete implementation checklist: PM0075 p.14's erased-location check / PGERR exception was not retrieved. |
| ADC and DMA | The overview is supported by AN2548 p.11, RM0008 p.216, and ES096 p.13. Complete register-level configuration and each chip's applicability were not independently validated. |
| Timer linking | Initial citations included contents pages instead of technical detail. After filtering, AN2592 p.9's output-compare explanation is retrieved and cited. Exact inter-timer selection remains unverified in the answer. |
| I2C errata | Device/revision qualification is appropriately distinguished from examples. Initial retrieval included a revision-history table. The repair removes it, but the actual I2C limitation matrix and workarounds are still missing from the context. |
| USART boot mode | The interface/protocol distinction is supported by AN2606 pp.7-8 and AN3155 p.5. The requested boot-pin selection table is not retrieved, and the answer says it cannot quote the exact states. |
| Missing page / wrong part | Both decline rather than invent an answer. Missing-page evidence no longer displays unrelated pages. |

## Repairs applied during validation

1. Collection retrieval filters identifiable contents/revision-history material from ordinary technical queries. Explicit requests for navigation/history remain supported. Both methods use the same selection rule; no vectors or captions were regenerated.
2. Answer instructions distinguish navigation/history entries from technical evidence.
3. A failed exact-page lookup no longer falls through to unrelated evidence.
4. Added offline regression coverage. At this validation checkpoint: 76 Python tests and 10 frontend transport/session tests passed. Later collection-session work has its own additional tests.

## Remaining limits / next work

- Improve detail retrieval for the missing oscillator, Flash-programming, boot-selection, and errata sources before relying on answers as engineering instructions.
- Audit page-local text provenance. A confirmed legacy MinerU contents block combines multiple PDF pages under one starting-page label: `stm32-rm0008-p0011-text-chunk-003` includes the SDIO suspend/resume contents entry that is physically on p.17. Filtering keeps this navigation example out of ordinary technical collection queries, but it does not repair the underlying parse. Re-normalization using MinerU's page-local output and careful cache/index rebuilding require a separate repair/verification pass.
- The saved PDFs are historical, mirror-sourced research documents, not a verified latest-release engineering reference. Their identity checks do not prove byte equality with current manufacturer downloads.
- Deployment names are recorded; unavailable historical model snapshots for reused captions must not be invented.
- The original human-grading requirement remains open. Candidate questions still need independently reviewed ground truth and separate retrieval-hit / answer-score fields before a benchmark claim.

The monitor's COMPLETE status means automated build/check completion only.
