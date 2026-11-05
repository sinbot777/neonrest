# Collaborative Zines release status

Status: 5 November 2026. Released on Production.

Zines is live at https://www.neonrest.com/zines . The public [Make Your First Zine field guide](https://www.neonrest.com/zines/V5tIzOh9ygRnYIgq/issues/OLIA4lVr146ZS9Sc) introduces the toolsets, artwork, composition, reading, sharing and printing.

Zines supports Standard, Custom and Advanced toolsets; inline and wrapped artwork; linked stories; styles and master elements; single-page, two-page and continuous reading; grouped atmosphere presets; sharing previews; and reading, booklet and mini-eight PDF output.

[PR #118](https://github.com/sinbot777/neonrest/pull/118) was merged as `f0c214145afe1143e38998d5ec236bb903ad0219`. The verified r7 package was deployed, with all 57 source and 552 runtime files checked after installation. Fresh Production data and source/configuration backups were taken before deployment. Sandbox content was not copied into Production.

Production checks passed issue creation, page save/reload, artwork upload and cover persistence, wrapped artwork composition, publishing, reader modes and access boundaries. The existing signed-in session remained usable without additional MFA. A fresh credential/2FA login was not repeated; the login route loaded and anonymous editing was denied.

All six live PDF exports passed: reading, booklet and mini-eight, each on Letter and A4, with correct page counts, dimensions and retained text. The user successfully downloaded and physically printed both booklet and eight-panel editions. No printing defect was reported. Facebook's actual share composer displayed the public guide's title and artwork; no post was published.

Earlier Sandbox validation included a confirmed 390 × 740 browser check of Custom Save/Cancel, page save/reload and reader modes without horizontal overflow. Application, security, authoring, sharing, appearance, folding, sizing, recovery and PDF regression checks passed during release preparation; overlapping suite counts are not unique test totals.

Advanced has substantial composition tools but is not yet equivalent to a mature professional publishing suite. Rich typography, live linked-text reflow, professional prepress, live coediting and other planned capabilities remain incomplete.
