# Linked video playback

YouTube watch, youtu.be, Shorts, live and embed links become click-to-load cards in the shared post renderer (profile, feed, Vibe and individual post views). Original post text stays intact. Existing posts work without a migration. Up to three distinct videos are recognized per post; fenced/inline code is skipped. Start timestamps are supported and bounded to 24 hours.

Recognition is local and performs no network fetches. Only exact recognized hostnames and 11-character IDs are accepted; user-info URLs and unexpected ports are rejected. Canonical fallback URLs contain only the validated ID and timestamp. No user-supplied HTML is inserted. Before a click, there are no provider images, scripts, frames, preconnects or metadata calls.

Clicking Load uses the YouTube privacy-enhanced iframe host with autoplay disabled. strict-origin referrers supply the site origin required by YouTube without sending private post paths or query strings. Close removes the iframe and returns focus to Load. Provider playback restrictions can still apply. The original-video link remains available without JavaScript and when embedding fails. Facebook/Instagram links remain ordinary links pending a separately verified integration.

The public, noindex /static/video-demo.html page uses the same card markup and player assets for a demonstration without creating user posts. Full-app fixture checks cover URL handling, hidden posts, profiles and individual post pages.

References: https://developers.google.com/youtube/player_parameters and https://support.google.com/youtube/answer/171780 .
