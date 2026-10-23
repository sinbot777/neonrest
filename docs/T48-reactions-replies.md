# T48 — reaction queries and reply recipients

Prepared October 22, 2026 (Pacific). Deployment and full app acceptance pending.

Feed/profile/timeline hydration uses one grouped query for visible posts, with a
covering `(post_id, emoji, user_id)` index. It returns counts and the viewer's
own choices without eagerly loading every reactor handle. Multiple reactions
and independent toggle-off behavior are preserved. Existing aggregate counts
retain their meaning; hidden people are omitted from the people listing.

“Who reacted?” opens an audience-checked page with an emoji selector and at most
50 visible people per window. Next links seek by user ID, with signed tokens
scoped to the post, emoji and viewer. Audience and member visibility are checked
again on every request. This adds no comment reactions.

Reply headers show author → recipient even when the parent is outside the
current comment window. Missing, moderated, blocked, age-ineligible and cross-post
parents do not disclose their handle. The existing indentation cap remains.

Local fictional-fixture validation:

- 14 reaction checks, including multiple choices, toggle-off, anonymous state,
  hidden reactors, complete seek windows and malformed boundaries.
- With 100,000 unrelated reactions, SQLite VM work for the same visible page
  fell from 402,906 to 1,932 instructions after adding the index.
- 39 timeline/comment-window checks, including hidden parent recipients and
  visible recipients across target windows.
- 33 index installation/query-plan/rollback checks.
- Shared reaction JavaScript add/remove, duplicate controls, CSRF and retry checks.

Exact counting still scales with the number of reactions on the selected posts;
this is not a constant-time counter cache or a hosting capacity claim.

Before rollout: run disposable-copy app integration checks in both environments,
including private/age/blocked reactor access, cursor isolation, Feed/profile/
Vibe/Circle rendering, comment editing and deep reply rendering. Verify live
source baselines, take backups, install additively and reload normally. Edge was
unavailable during preparation. Keep T48 open until these checks pass.
