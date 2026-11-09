# Service identities and HelpLine

Service is a reusable identity category stored separately from personal accounts. It has no birthday and cannot sign in independently. A verified, eligible adult human with two-factor authentication is accountable for each service. Administrators with role-management permission provision services and grant or revoke the initial public-guidance capability. Every configuration and publication action records its human actor.

## Initial scope

- New identities, or explicit conversion of a verified unused identity without a birthday, content or delegated authority. Existing welcome-friend links are retained but confer no contact authority.
- Dedicated public Service profile and Service labels on posts.
- Protected human operators publish bounded text through the Service workspace. No attachments, private audiences, Circle posting, messaging, automation tokens, or moderation authority are provided.
- All-age reading applies only to explicitly recorded public guidance whose author, destination and text hash still match. Blocks, mutes, account restrictions and moderation remain authoritative. Disabling a service or its accountable owner removes ordinary public access.
- Existing human accounts cannot switch themselves into Service. Service identities cannot read member content or participate in contacts. Staff evidence access remains staff-only.
- Publication references are repeat-safe. Ownership/operator/action dependencies are retained for export and block unreviewed erasure. Permanent erasure remains disabled.

## T40 closeout

HelpLine is the first intended conversion. Its existing verified account has no birthday and no posts. Owner authorization is required for the four approved Fresh Starts onboarding posts. The batch remains transactional and repeat-safe, with each Service publication attributed privately to its human actor. No fabricated date of birth or staff-announcement exemption is used.

## Validation and release boundary

The private candidate passes 71 Service checks plus 55 existing Page fixture checks. Coverage includes management authorization, CSRF/fresh authentication, owner/operator eligibility, all-age public reading, publication attribution/idempotency/rollback, blocks/mutes, altered/private content refusal, direct-login/session denial, operator revocation, service/owner suspension, exports and a second reusable Service identity. Fixture-only account and publication writes never affect the live database. Provider calls and mail are disabled.

Candidate tests: `tests/verify_service_accounts.py`. Hosting receipt directory: `/home/sinbot/releases/T40-service-20261108` (private, not web-mounted). The management, composer and public-profile templates render successfully. Related regressions passed: 39 growth-query checks, seven request-cache tests and 25 privacy-workflow tests. Candidate source hashes and remaining deployment evidence must be recorded before marking the release complete. Public source upload and Production deployment are not implied by this candidate document.

Future capabilities such as inbox access, automation credentials, moderation, owner transfer and accepted operator invitations require separate design and permissions; they are not silently granted by the category.
