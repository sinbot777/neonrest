# P1 closeout and advertising readiness — October 22, 2026

## Completed engineering

- T40 publication: four HelpLine posts prepared for Fresh Starts. Production HelpLine has no age setup and publication there remains blocked; Sandbox is age-ready. Ordinary public posts retain current age restrictions; the guide is the age-neutral onboarding surface. No changes to HelpLine roles, authentication or age information.
- Direct placements: at most four cards and one banner on Feed/Vibe pages; independent random selections on navigation. No timed refresh, behavioral ranking or private-Circle placement.
- Campaign controls: paused creation, scheduled eligibility, CSRF/staff/fresh-authorization checks, sponsor-review acknowledgments recorded in management history, bounded IDs and validated destinations/local raster assets.
- Disclosure: /advertising sets mixed-age sponsor standards, no endorsement/moderation privileges, no personal ad profiles, and coarse sponsor-reporting rules. Direct event records have no account/session/IP identifiers; selection counts are not verified views. No external sponsor reporting interface exists.
- Provider readiness: Production /ads.txt uses the account publisher ID verified in AdSense; Sandbox has no seller record and no provider meta tag. https://support.google.com/adsense/answer/12171612 documents the record format. No Google ad script, unit or Auto Ads activation is part of this release.

## Still external or owner acceptance

AdSense remains Getting ready with review requested October 17, 2026. Approval is Google's decision. Live paid-delivery acceptance requires approved inventory, a separately verified provider configuration and appropriate notices/choices. No sponsor creative was supplied, so no real campaign was invented or activated. Owner product walkthrough remains owner acceptance; engineering tests do not stand in for it. These boundaries remain explicit in the roadmap rather than declaring all of P1 commercially active.

## Publication and rollback

Run onboarding_guidance.publish only for the explicitly authorized owner maintenance batch, inside a transaction after a fresh backup. It preserves originals and avoids duplicates; differing existing post settings fail for review. It never adds staff announcements or changes roles. Keep resulting public references in the private release acceptance record. Source rollback is separate from removing legitimately published content; do not restore a live database over newer user activity.
