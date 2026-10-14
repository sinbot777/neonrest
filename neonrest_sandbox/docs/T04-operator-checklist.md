# T04 Sandbox operator checklist — October 11, 2026 (Pacific)

Verified: 475 age/account checks + 36 retention checks. Test copies isolate the live database and uploads; email sends are stubbed.

## Existing accounts
No missing DOB values remain, but a stored DOB is not proof of verified age. Nine accounts lack a saved timezone. Let each account confirm its birthday timezone once under Age and safety; approved parents may confirm their minor child's clock in Family Settings. Do not assign guessed DOBs or guardian approvals.

The existing child @Ang-morpork has a stored DOB and an approved signed-consent-form link. No uploaded letter is recorded. The operator must resolve any missing genuine consent/guardian evidence; this audit does not fabricate or independently validate it. Existing access was not changed by this audit.

## Data review and deletion
Review private requests at /sandbox/manage/family/requests with manage_roles and renewed authorization. Check current guardian authority independently; the form checkbox records that work rather than performing identity verification. Record a minimal case reference, not identity documents in notes. Approval releases only the requested child's account data, requires parent reauthorization, and expires after 24 hours. Revoked consent does not automatically remove applicable parent request rights, but current authority must be reviewed before release.

Reviewed deletion hides the child account, revokes sessions and enters the existing 30-day grace process. Automatic permanent processing is disabled. Staff cancellation requires reviewed guardian authority; it restores the previous inactive state and does not reinstate revoked consent. If a child turns 18, parent-only privileges stop; the adult manages their own requests. Closed/declined/completed-access records are eligible after 90 days from review, only when retention is activated. Unresolved/scheduled requests are not blindly aged out.

DOB review requests leave the stored date immutable. A robust correction verification process is not provisioned, so staff must not promise or bypass a DOB correction. Public signup is 13+; new under-13 enrollment is disabled.

## Production readiness
Production lacks age_policy, community_features, age_clock and family_data. Copying one module is not a valid rollout. Prepare a full reviewed migration of the Sandbox dependencies, production database migrations, email settings, permission configuration and media guards. Back up production database/media and verify restore before rollout. Rehearse against a disposable production copy, keep retention disabled, then run the full age/permission/retention suite and signed-out/live smoke checks. Define rollback for both code and schema; verify pending sessions, guardian records, timezones and protected historical posts after migration. No production promotion is authorized by this Sandbox checklist.

Future Circles, messaging, search and previews must use the shared age/audience gates when implemented.
