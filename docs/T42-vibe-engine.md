# T42 — Vibe Engine specification

Status: specified October 22, 2026. This document does not enable location collection or geographic ranking.

## Chronology and choice

The default remains All posts, newest first with ID tie-breaking. Friends, Followed, selected Vibes, joined Circles and Bookmarks remain explicit views. A saved default changes only the initial view. No popularity, reaction, engagement or inferred-location score changes ordering. Profile views independently select all profile posts, authored posts or incoming guestbook messages. Signed pagination is scoped to the chosen view; edits, deleted content and revoked permissions are rechecked.

## Optional proximity

A future opt-in Nearby view accepts a manually selected area, separate from public profile city and birthday timezone. Default is Off. No IP geolocation, browser GPS permission, address, precise coordinates, background tracking or automatic reuse of profile location. No collection is needed for the current release.

Use a vetted city/region directory with stable area IDs and approximate city centroids. Disambiguate city/region/country before saving. Store only selected area ID and chosen radius (25, 100 or 500 km) in a private preference; offer Clear area, include it in own export and future erasure cleanup. Public display is separately opt-in, coarse city/region only. A private nearby preference must never make a private profile city searchable or visible. Do not infer distance to a particular user or show exact distances, coordinates, member counts or map pins.

## Nearby weighting and distant discovery

Nearby is a user-chosen filter for eligible explicitly area-tagged public Vibe activity, not a change to personal Friends/Followed feeds. Nearby results remain chronological within the selected radius. Eligibility and coarse-area opt-in precede any geographic calculation. Nearby is not offered to minors in the first implementation; their existing age-safe views remain available. A future youth design requires a separate safety review.

Always offer an All places link and ordinary Explore Vibes; never silently widen the radius or suppress distant Vibes in the default views. No nearby results means an honest empty state with All places, rather than invented local results. Disabling or clearing the area immediately restores the ordinary view.

## Implementation gate and acceptance

Future implementation must first add a reviewed area data source, bounded spatial candidates/indexes and an additive preference schema. No remote geocoding or location-bearing provider requests without an explicit decision. Enforce current audience, age, block, mute, Circle, moderation, archived/pending Vibe and field-privacy rules on every result and direct URL. Area changes reset signed cursors and invalidate relevant caches. Anonymous viewers cannot infer private preferences.

Tests must cover Off/clear/export, duplicate city names, radius boundaries, no-area and stale-area cases, cross-region discovery, private city leakage, eligibility changes between pages, minor exclusion, forged/cross-view cursors and large candidate sets. Product acceptance must verify that default and Friends/Followed chronology remain unchanged. This specification completes T42's specification scope; geographic implementation remains future work and requires its own authorized scope.
