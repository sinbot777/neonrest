# T24 Last.fm acceptance

Profiles render before a single asynchronous Last.fm request. No timed polling or new feature toggle. Provider fixtures verify current versus last-played metadata, absent artwork, empty/malformed responses and provider failure. Client fixtures verify safe text/links/art, asynchronous loading and error handling (19 assertions). Music and available artwork stay in the Details row; art is bounded to 160px and its container width and clears on image failure. The existing live owner profile confirmed track detection; final hosted acceptance is recorded in the roadmap.
