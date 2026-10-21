# T16 — Following and private friend labels

Sandbox implementation, October 21, 2026. Production rollout is separate.

Following stays one-way. An account can disable follows, remove an individual follower, or explicitly allow a removed follower to try again. Disabling revokes existing follows; enabling never resurrects them. A removed follower cannot immediately re-follow. Following does not create a friendship, grant Circle membership, reveal private profile fields or bypass age, parent-contact, block, inactive/disabled-account or moderation restrictions. Comment preferences no longer accidentally govern following. Re-following after a voluntary unfollow reactivates the existing unique relationship row.

Existing post audiences remain unchanged. New “Friends and followers” includes current eligible followers and the established Friends/family audience. Choosing “Friends” excludes follower-only access. Public remains public to eligible visitors; removing a follower does not hide public content. Author-only posts and Circle visibility retain their existing rules. Post-audience defaults apply to new posts, not historical posts.

Private friend labels are custom categories, separate from Circles and the later nickname feature. Owners can create, rename, archive and restore up to 32 labels of 1–40 characters, assign accepted eligible Friends and remove assignments. Names are normalized and escaped. Only the owner sees label names and assignments. A label can target a post audience, but current friendship, assignment, author ownership and safety checks are all required. Unfriending/blocking clears assignments. Archiving fails closed; restoring explicitly restores label audience access. An archived audience remains selected when editing its post, preventing accidental fallback to Public. Label IDs are stable and never reused.

Own account exports include the owner's follow preferences, exclusions, labels and assignments. Another person's labels are excluded. Newly added private labels are not silently added to reviewed guardian export payloads. Related-user preservation discovery includes label memberships and follower exclusions. Future erasure cleanup includes these records; permanent account erasure remains disabled. No automatic user/file cleanup is activated.

Changes use additive tables and an incoming-follower index. No existing post audience, account field, Circle membership or relationship row is rewritten by migration. Follow opt-out/removal takes effect only when its owner submits the corresponding action. New forms use CSRF, verified sessions and bounded mutation rates. Connection lists are paginated; no invitations, follow alerts or SMTP messages are sent.

Rollback restores source only, retaining the additive tables and newer user records. Posts using the new audiences fail closed under older code. Never rewind a user database to undo a code deployment.
