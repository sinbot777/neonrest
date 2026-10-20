# Linked media playback

The shared post renderer recognizes YouTube, Facebook video and Instagram post/Reel links locally. Existing posts work without migrations. A post gets at most three distinct cards across all providers, preserving URL order and skipping inline/fenced code. No metadata requests, redirects, provider scripts, thumbnails, iframes or preconnects are made before the reader clicks Load. The server never fetches user-supplied URLs.

Exact provider host allowlists, validated IDs/path shapes and canonical URLs strip tracking queries and reject user-info URLs and unexpected ports. JavaScript independently validates Meta URLs before constructing a fixed provider iframe URL. Untrusted HTML is never inserted. strict-origin referrers send the site origin without private post paths or query strings. Close removes the iframe and returns focus to Load. Original links remain available without JavaScript and when providers refuse embedding.

YouTube watch/youtu.be/Shorts/live/embed links retain bounded start timestamps. Facebook watch, numeric page/video and Reel links use the official video plugin with autoplay disabled. Facebook fb.watch and share/v/share/r links are passed to the same plugin; if a short/share link is not accepted by Meta, use its full original video URL. Instagram p/reel/reels/tv links use the same canonical /embed/ URL pattern constructed by Instagram's official embed.js, inside a cross-origin iframe, without loading that script into Neonrest's parent document. Instagram frames retain a fixed readable height and can scroll. Private content, disabled embeds, removed posts and provider sign-in restrictions remain controlled by the provider.

YouTube remains privacy-enhanced and does not request autoplay. No video files, metadata caches, new account credentials or API tokens are stored by Neonrest. Existing Circle, age and moderation visibility checks run before rendering any cards.

Noindex demos: /static/video-demo.html and /static/meta-video-demo.html. Meta examples use the official developer video and NASA/JPL's public Reel; demos do not create user posts. Browser preview verified Facebook playback through the end and Instagram decoded, active playback, plus lazy creation and Close cleanup.

References:
- https://developers.google.com/youtube/player_parameters
- https://developers.facebook.com/docs/plugins/embedded-video-player/
- https://developers.facebook.com/documentation/instagram-platform/oembed
- https://www.instagram.com/embed.js (official URL construction inspected during implementation)
