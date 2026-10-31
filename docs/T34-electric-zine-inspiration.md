# Electric Zine Maker-inspired feature intake

## Implemented locally: fold-and-print foundation

- Eight-panel, single-sided mini-zine on landscape Letter or A4.
- Reading order mapped to panels with a rotated upper row. The existing front/back covers remain adjacent; issues of 2–8 pages are padded with blank panels before the back cover. Longer issues use the existing saddle-stitch booklet.
- Dashed fold guides and a solid center cut. Guides are optional in artwork PDFs. Existing booklets can add a center fold line. Standard reading-order PDFs stay clean.
- Independent preview guide visibility, sheet proportions, panel labels and orientation indicators.
- A numbered test sheet substitutes labels for art. Proofs retain publication visibility and download admission checks.
- Panel safe inset 0–12.7 mm. Insets reduce content inside fixed physical panels; they never shift fold/cut coordinates. Custom issue trim dimensions remain separate from the Letter/A4 sheet format.
- Assembly steps for creasing, the center slit and collapsing the sheet. No staples needed for this format.

Validation: 88 new checks covering 2–8-page padding, ordering, real PDF transforms, landscape dimensions, Letter/A4, clean versus guided exports, invalid options and protected download access; eight DOM checks for option visibility and independent preview guides; existing 54 component checks. Two rendered proofs were inspected. Actual home-printer, physical folding, hosted full-app and live browser acceptance remain open. The code remains in an isolated side copy; no deployment occurred.

## Onboarded follow-on scope (not implemented)

1. Other formats: eight-page Z-fold, square accordion, 16-page mini-booklet. Each needs its own verified panel map, cut/fold directions, duplex behavior, paper constraints and assembly proof; no guessed generic rearrangement.
2. Print production: trim/crop marks, bleed and safe-area overlays, printer-margin calibration, duplex orientation test sheet, reversible front/back sheet views and assembly previews.
3. Drawing: pen, brush, eraser, fill, stamps and freehand annotations. Keep drawings in an artwork layer; retain selectable text and ordinary composition objects.
4. DIY effects: photocopy grain, halftone, paper/torn-edge treatments, ink textures and collage assets. Preserve originals and apply effects to an editable duplicate or generated artwork asset.
5. Experimental effects: smudge, distortion, channel shifts, pixel/glitch treatments and blend modes. Preview parameters before applying; Undo is required.
6. Toolset integration: simple formats and guided instructions in Standard; optional chosen art/production groups in Custom; complete implemented controls in Advanced. Keep them in task panels or dedicated overlays, without scattering controls around the page.

No inactive buttons or unimplemented tools are presented as working features. Existing limitations remain: composition uses the original fixed logical board and may letterbox on different trim aspect ratios; freeform page-coordinate adaptation, linked text, bleed and professional color management are separate work.

## Research and design references

- Electric Zine Maker overview: https://alienmelon.itch.io/electric-zine-maker
- Official tool site: https://unicornycopia.com/ezm/
- Mini-booklet and Z-fold announcement: https://alienmelon.itch.io/electric-zine-maker/devlog/169744/two-new-templates-mini-booklets-are-here
- Accordion format: https://alienmelon.itch.io/electric-zine-maker/devlog/166588/breaking-news-new-template-the-square-accordion-fold
- Artwork effects: https://alienmelon.itch.io/electric-zine-maker/devlog/90240/electric-zine-maker-fuzzy-update-with-ascii-power-goo-like-tools-displacement-color-management-and-more
- Eight-page physical panel map and assembly reference: https://chandra.si.edu/make/images/Zine_folding.pdf
- Additional folding reference: https://guides.loc.gov/ld.php?content_id=67687837

This is an original implementation of the requested behavior. No Electric Zine Maker source code, interface artwork or bundled assets were imported.
