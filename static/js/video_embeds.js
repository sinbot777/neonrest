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
    const id = card.dataset.youtubeId;
    if (!/^[A-Za-z0-9_-]{11}$/.test(id || "") || player.childElementCount) return;
    const start = Math.min(86400, Math.max(0, Number(card.dataset.videoStart) || 0));
    const frame = document.createElement("iframe");
    frame.title = "YouTube video player";
    frame.src = "https://www.youtube-nocookie.com/embed/" + id + "?playsinline=1&autoplay=0&start=" + Math.floor(start);
    frame.referrerPolicy = "strict-origin";
    frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    frame.allowFullscreen = true;
    player.replaceChildren(frame);
    load.hidden = true;
    close.hidden = false;
    frame.focus();
  });
})();
