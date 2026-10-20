# Database performance

Six additive, non-unique indexes support existing profile-author/profile-target, comment-batch, Vibe-membership, active-follow and incoming-friend-request lookups. They are installed idempotently at startup after existing schema migrations. No content, relationship constraints, visibility rules, journal settings or retention periods are changed.

The regression uses fictional in-memory data: 50,000 posts, 100,000 comments, 50,000 Vibe memberships, 20,000 follows and 20,000 friend requests. It compares results and query plans, tests repeated installation, rollback of a conflicting index and preservation of an open caller transaction. The six indexes cost roughly 8 MB at those test sizes. Timings describe selected lookups, not whole-page speed or hosting capacity.

## Growth follow-up

Profile history still needs bounded pagination. The feed and Vibe pages cap visible posts, but exact total counts and visibility callbacks can examine many rows. These deserve a separate, permission-tested query/pagination change. Offset pagination and leading-wildcard text search also merit measurement at larger sizes.

Statistics already expire old measurements on a 90-day window. Security retention respects preservation holds. Content, moderation history and held records must not be treated as disposable logs. Check expiry indexes and housekeeping frequency separately before changing retention behavior. Avoid unnecessary VACUUM operations on small databases with no free pages.
