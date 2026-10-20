(() => {
  "use strict";
  document.addEventListener("click", (event) => {
    const button = event.target.closest(".neon-video-load, .neon-video-close");
    if (!button) return;
    const card = button.closest(".neon-video-card");
    if (!card) return;
    const player = card.querySelector(".neon-video-player");
    const load = card.querySelector(".neon-video-load");
    const close = card.querySelector(".neon-video-close");
    if (button === close) {
      player.replaceChildren();
      close.hidden = true;
      load.hidden = false;
      load.focus();
      return;
    }
    const provider = card.dataset.videoProvider || "youtube";
    const id = card.dataset.videoId || card.dataset.youtubeId;
    if (player.childElementCount) return;
    let source;
    const frame = document.createElement("iframe");
    if (provider === "youtube") {
      if (!/^[A-Za-z0-9_-]{11}$/.test(id || "")) return;
      const start = Math.min(86400, Math.max(0, Number(card.dataset.videoStart) || 0));
      frame.title = "YouTube video player";
      source = "https://www.youtube-nocookie.com/embed/" + id + "?playsinline=1&autoplay=0&start=" + Math.floor(start);
    } else if (provider === "instagram" || provider === "facebook") {
      let original;
      try { original = new URL(card.dataset.videoUrl); } catch (_) { return; }
      if (original.protocol !== "https:" || original.username || original.password || original.port || original.hash) return;
      frame.dataset.provider = provider;
      if (provider === "instagram") {
        if (original.hostname !== "www.instagram.com" || !/^\/(p|reel|tv)\/[A-Za-z0-9_-]{5,64}\/$/.test(original.pathname) || original.search) return;
        source = original.href + "embed/";
        frame.title = "Instagram embedded post";
      } else {
        const validWatch = original.hostname === "www.facebook.com" && original.pathname === "/watch/" && /^\?v=[0-9]{3,30}$/.test(original.search);
        const validReel = original.hostname === "www.facebook.com" && /^\/reel\/[0-9]{3,30}\/$/.test(original.pathname) && !original.search;
        const validShare = original.hostname === "www.facebook.com" && /^\/share\/[vr]\/[A-Za-z0-9_-]{3,128}\/$/.test(original.pathname) && !original.search;
        const validShort = original.hostname === "fb.watch" && /^\/[A-Za-z0-9_-]{3,128}\/$/.test(original.pathname) && !original.search;
        if (!(validWatch || validReel || validShare || validShort)) return;
        source = "https://www.facebook.com/plugins/video.php?href=" + encodeURIComponent(original.href) + "&show_text=false&autoplay=false&width=500";
        frame.title = "Facebook video player";
        if (card.dataset.videoPortrait === "true") frame.classList.add("neon-video-portrait");
      }
    } else { return; }
    frame.src = source;
    frame.referrerPolicy = "strict-origin";
    frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    frame.allowFullscreen = true;
    player.replaceChildren(frame);
    load.hidden = true;
    close.hidden = false;
    frame.focus();
  });
})();
