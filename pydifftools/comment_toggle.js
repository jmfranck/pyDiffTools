// comment_toggle.js
(function () {
  const SELECTOR_BUBBLE =
    "div.comment-left, div.comment-right, " +
    "span.comment-pin > span.comment-left, span.comment-pin > span.comment-right, " +
    "div.comment-overlay.comment-left, div.comment-overlay.comment-right";

  const SELECTOR_OVERLAY = "div.comment-overlay[data-comment-id]";
  const SELECTOR_ANCHOR = 'span.comment-pin-block[data-comment-id]';

  function clamp(x, lo, hi) {
    return Math.max(lo, Math.min(hi, x));
  }

  function positionOverlays() {
    const overlays = document.querySelectorAll(SELECTOR_OVERLAY);
    if (!overlays.length) return;

    const viewportLeft = window.scrollX;
    const viewportRight = window.scrollX + window.innerWidth;

    overlays.forEach((ov) => {
      const id = ov.getAttribute("data-comment-id");
      if (!id) return;

      const anchor = document.querySelector(
        `${SELECTOR_ANCHOR}[data-comment-id="${CSS.escape(id)}"]`
      );
      if (!anchor) return;

      // Ensure measurable
      ov.style.position = "absolute";
      ov.style.visibility = "hidden";
      ov.style.left = "0px";
      ov.style.top = "0px";

      const a = anchor.getBoundingClientRect();
      const gap = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--comment-gap")) || 8;

      // Measure overlay
      // (temporarily visible for accurate width/height)
      ov.style.visibility = "hidden";
      const ow = ov.offsetWidth;
      const oh = ov.offsetHeight;

      // Anchor point in document coords
      const ax = a.left + window.scrollX;
      const ay = a.top + window.scrollY;

      let left;
      if (ov.classList.contains("comment-left")) {
        left = ax - gap - ow;
      } else {
        // default right
        left = ax + gap;
      }

      // Clamp within viewport so it doesn't go off-screen
      left = clamp(left, viewportLeft + 4, viewportRight - ow - 4);

      // Put it slightly above the anchor line (tweakable)
      const top = ay - 6;

      ov.style.left = `${left}px`;
      ov.style.top = `${top}px`;
      ov.style.visibility = "";
    });
  }

  // Click-to-hide (keeps your behavior, now includes overlays too)
  document.addEventListener("click", function (e) {
    const bubble = e.target.closest(SELECTOR_BUBBLE);
    if (!bubble) return;
    e.stopPropagation();
    bubble.classList.toggle("comment-hidden");
  });

  // Reposition overlays on layout changes
  window.addEventListener("load", positionOverlays, { passive: true });
  window.addEventListener("resize", positionOverlays, { passive: true });
  window.addEventListener("scroll", positionOverlays, { passive: true });
  document.addEventListener("DOMContentLoaded", positionOverlays, { passive: true });

  // If fonts/images load after DOMContentLoaded, do one more pass shortly after
  window.setTimeout(positionOverlays, 50);
  window.setTimeout(positionOverlays, 250);
})();