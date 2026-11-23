# ATmega revision-grounding pilot

Collected September 8, 2026. No paid inference, MinerU parsing, embedding, index changes, corpus registration, or application changes were performed.

## Corpus

| Document | Revision | Pages | Location |
|---|---|---:|---|
| Family datasheet DS40002061 | A, October 2018 | 662 | `datasheet-rev-a.pdf` |
| Family datasheet DS40002061 | B, 2020 | 653 | Existing `../hardware/atmega328p.pdf` (not duplicated) |
| Silicon Errata and Data Sheet Clarifications DS80000855 | C, April 2024 | 19 | `errata.pdf` |

The downloaded documents came directly from Microchip. Exact source URLs, SHA-256 hashes, document IDs, and provenance are in manifest.json. The existing revision B file was identified from its contents; its original download URL was not established in this task.

## Concrete evidence anchors

1. **Cross-document correction:** DS40002061B page 39, Table 9-4, lists 14 CK for the additional reset delay of the crystal-oscillator/BOD-enabled row. DS80000855C page 5, section 3.1.1/Table 9-4, explicitly replaces 14 CK with 19 CK for ATmega328P. The startup-from-power-down column remains a separate quantity (16K CK for that row). This is a correction-document retrieval test, not merely semantic similarity.
2. **Revision-specific table content:** Both datasheet revisions have Table 30-1 on page 323. Revision B adds two low-input-voltage comparator-offset rows, with additional conditions and a characterization caveat in footnote 5, absent from that page in revision A. Do not claim absence from the entire older document without a full audit.
3. **Silicon-revision scope:** Errata C pages 2-3 mark the unstable 32 kHz oscillator issue for ATmega328/P silicon A and B, not D. Document revision C is not silicon revision C. Page 2 says ATmega328/P silicon C was never released to production.
4. **Linked-document provenance:** Errata C page 1 explicitly references DS40002061. Page 15 dates errata revision C to April 2024 and says its initial revision moved content out of the datasheet.

## Source anomalies and limits

- Revision B contents page 11 dates B to August 2020; its revision-history page 646 dates B to September 2020. Preserve both; use document ID/revision as the primary key.
- Revision A page 657 says the previous document number was 8227 rev. J, while nearby revision headings and revision B use 8271J. Do not silently normalize this historical identifier.
- These three files are a verified starter collection, not a verified archive of every release.
- A preview montage was rendered to output/atmega_revision_study/evidence-overview.png, but the image-view tool was unavailable in this session. Evidence checks used PDF text extraction; visual column alignment still needs human review before locking numeric ground truth.
- Tables expose selectable text. Do not label these questions visual-required without checking whether your text baseline can answer them.

## Next implementation step (not performed)

Use a separate corpus/index and version-qualified document IDs. Store document revision, device variant, and silicon applicability separately. Retrieve each requested revision explicitly; follow the errata relationship when corrections are in scope. Preserve provenance for historical-only answers rather than always overriding old documents with newer corrections.

Start with the candidate questions below. They are evidence-anchored drafts, not hand-scored evaluation results. Confirm table layouts visually and finalize ground truth before running paid processing.

- For ATmega328P, crystal oscillator with BOD enabled at VCC=5.0 V, what additional reset delay does datasheet B state, and how does errata C correct it? Cite both documents.
- What low-input-voltage comparator-offset rows and qualification were added to Table 30-1 page 323 in B compared with A? Cite both versions and keep operating conditions attached to values.
- Is the unstable 32 kHz oscillator issue applicable to ATmega328/P silicon D? How does this differ from silicon A/B? Cite errata C, not the document revision letter as a silicon identifier.
- When asked only what datasheet B originally says about the clock delay, can the system report 14 CK as the historical statement while separately identifying the later correction if permitted by the question?
