# Service identities and HelpLine

**Production release completed — November 8, 2026 (Pacific).** [PR #132](https://github.com/sinbot777/neonrest/pull/132) merged as `6f83452f797e43ad2c4035c506676975fa3ab64e`. [HelpLine](https://www.neonrest.com/@HelpLine) is active as a Service without a birthday. Its four approved Fresh Starts posts are published, attributed to the accountable human operator and repeat-safe.

Published guidance:

- [Welcome to Neonrest](https://www.neonrest.com/posts/82wj5LKUYwnwzkki)
- [Your welcome friend and Top 9](https://www.neonrest.com/posts/Uq8eM5Iiinh59Htr)
- [Vibes, Circles and audiences](https://www.neonrest.com/posts/WMvSph73EbZdLoQW)
- [Find your pace and get help](https://www.neonrest.com/posts/GDwWxwTSAddTILfm)


Service is a reusable identity category stored separately from personal accounts. It has no birthday and cannot sign in independently. A verified, eligible adult human with two-factor authentication is accountable for each service. Administrators with role-management permission provision services and grant or revoke the initial public-guidance capability. Every configuration and publication action records its human actor.

## Initial scope

- New identities, or explicit conversion of a verified unused identity without a birthday, content or delegated authority. Existing welcome-friend links are retained but confer no contact authority.
- Dedicated public Service profile and Service labels on posts.
- Protected human operators publish bounded text through the Service workspace. No attachments, private audiences, Circle posting, messaging, automation tokens, or moderation authority are provided.
- All-age reading applies only to explicitly recorded public guidance whose author, destination and text hash still match. Blocks, mutes, account restrictions and moderation remain authoritative. Disabling a service or its accountable owner removes ordinary public access.
- Existing human accounts cannot switch themselves into Service. Service identities cannot read member content or participate in contacts. Staff evidence access remains staff-only.
- Publication references are repeat-safe. Ownership/operator/action dependencies are retained for export and block unreviewed erasure. Permanent erasure remains disabled.

## T40 closeout

HelpLine is the first activated Service. The owner completed the protected controls and authorized the four approved Fresh Starts onboarding posts. The batch remains transactional and repeat-safe, with each Service publication attributed privately to its human actor. No fabricated date of birth or staff-announcement exemption is used.

## Validation and release boundary

The release passed 71 isolated Service checks plus 55 existing Page fixture checks. Coverage includes management authorization, CSRF/fresh authentication, owner/operator eligibility, all-age public reading, publication attribution/idempotency/rollback, blocks/mutes, altered/private content refusal, direct-login/session denial, operator revocation, service/owner suspension, exports and a second reusable Service identity. Fixture-only account and publication writes never affect the live database. Provider calls and mail are disabled.


Future capabilities such as inbox access, automation credentials, moderation, owner transfer and accepted operator invitations require separate design and permissions; they are not silently granted by the category.

The regression suite is `tests/verify_service_accounts.py`. Management, composer and public-profile templates rendered successfully. Production checks verified all four anonymous public post links, all four profile topics, no anonymous operator controls, repeat-safe publication and healthy database integrity. Desktop and 390px checks passed without horizontal overflow; actual-device and broader assistive-technology acceptance remain separate.

## Production / repository reconciliation

The November 8 audit aligned all 500 tracked files with the merged release. The existing Last.fm key now comes from private owner-only configuration through `LASTFM_API_KEY`; no key belongs in source. Four provider fixtures passed and the live profile showed Last Played after reload. Sandbox source was preserved. Release backups and operator audit records are private; no database, credentials or user uploads were published to GitHub.
