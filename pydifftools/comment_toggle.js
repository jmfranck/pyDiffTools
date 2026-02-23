// comment_toggle.js
(function () {
  const SELECTOR_BUBBLE =
    "div.comment-left, div.comment-right, " +
    "span.comment-pin > span.comment-left, span.comment-pin > span.comment-right, " +
    "div.comment-overlay.comment-left, div.comment-overlay.comment-right";

  const SELECTOR_OVERLAY = "div.comment-overlay[data-comment-id]";
  const SELECTOR_ANCHOR = 'span.comment-pin-block[data-comment-id]';
  const SELECTOR_INLINE =
    "span.comment-pin > span.comment-right, span.comment-pin > span.comment-left";

  function clamp(x, lo, hi) {
    return Math.max(lo, Math.min(hi, x));
  }

  function cssLengthToPx(value, fallbackPx) {
    // Convert css lengths (px/rem/etc.) into pixel numbers for geometry math.
    if (!value) return fallbackPx;
    const probe = document.createElement("div");
    probe.style.position = "absolute";
    probe.style.visibility = "hidden";
    probe.style.width = value.trim();
    document.body.appendChild(probe);
    const pixels = probe.getBoundingClientRect().width;
    document.body.removeChild(probe);
    if (!Number.isFinite(pixels) || pixels <= 0) return fallbackPx;
    return pixels;
  }

  function cssVariableLengthPx(name, fallbackPx) {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(name);
    return cssLengthToPx(raw, fallbackPx);
  }

  function positionComments() {
    // Inline comment bubbles are absolutely positioned relative to a zero-width
    // pin. We nudge overlapping bubbles so adjacent <comment> tags visibly
    // separate, and we raise the bubbles so the pointer aims at the source point.
    const inlineBubbles = document.querySelectorAll(SELECTOR_INLINE);
    if (inlineBubbles.length) {
      const inlineRise = cssVariableLengthPx("--comment-inline-rise", 0);
      const overlapShift = cssVariableLengthPx("--comment-overlap-shift", 0);
      const placedInline = [];

      inlineBubbles.forEach((bubble) => {
        bubble.style.transform = "";

        const bubbleRect = bubble.getBoundingClientRect();
        let shiftX = 0;

        if (overlapShift > 0) {
          for (let j = 0; j < placedInline.length; j += 1) {
            const prior = placedInline[j];
            const verticalOverlap =
              bubbleRect.top < prior.bottom && bubbleRect.bottom > prior.top;
            const horizontalOverlap =
              bubbleRect.left + shiftX < prior.right &&
              bubbleRect.right + shiftX > prior.left;
            if (verticalOverlap && horizontalOverlap) {
              if (bubble.classList.contains("comment-left")) {
                shiftX -= overlapShift;
              } else {
                shiftX += overlapShift;
              }
            }
          }
        }

        bubble.style.transform = `translate(${shiftX}px, ${-inlineRise}px)`;
        const shiftedRect = bubble.getBoundingClientRect();
        placedInline.push({
          left: shiftedRect.left,
          right: shiftedRect.right,
          top: shiftedRect.top,
          bottom: shiftedRect.bottom,
        });
      });
    }

    const overlays = document.querySelectorAll(SELECTOR_OVERLAY);
    if (!overlays.length) return;

    const viewportLeft = window.scrollX;
    const viewportRight = window.scrollX + window.innerWidth;
    const overlapShift = cssVariableLengthPx("--comment-overlap-shift", 0);
    const overlayRise = cssVariableLengthPx("--comment-overlay-rise", 6);
    const overlayRightShift = cssVariableLengthPx("--comment-overlay-right-shift", 0);
    const placed = [];

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
      const gap = cssVariableLengthPx("--comment-gap", 8);

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
        // default right; add configurable shift so the arrow points back to
        // the intended source location instead of aligning bubble top-left.
        left = ax + gap + overlayRightShift;
      }

      // Clamp within viewport so it doesn't go off-screen
      left = clamp(left, viewportLeft + 4, viewportRight - ow - 4);

      // Raise overlay so the arrow points toward the source anchor.
      const top = ay - overlayRise;

      let shiftedLeft = left;
      if (overlapShift > 0) {
        for (let j = 0; j < placed.length; j += 1) {
          const prior = placed[j];
          const verticalOverlap = top < prior.bottom && top + oh > prior.top;
          const horizontalOverlap =
            shiftedLeft < prior.right && shiftedLeft + ow > prior.left;
          if (verticalOverlap && horizontalOverlap) {
            shiftedLeft += overlapShift;
          }
        }
        shiftedLeft = clamp(
          shiftedLeft,
          viewportLeft + 4,
          viewportRight - ow - 4
        );
      }

      ov.style.left = `${shiftedLeft}px`;
      ov.style.top = `${top}px`;
      ov.style.visibility = "";
      placed.push({
        left: shiftedLeft,
        right: shiftedLeft + ow,
        top: top,
        bottom: top + oh,
      });
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
  window.addEventListener("load", positionComments, { passive: true });
  window.addEventListener("resize", positionComments, { passive: true });
  window.addEventListener("scroll", positionComments, { passive: true });
  document.addEventListener("DOMContentLoaded", positionComments, { passive: true });

  // If fonts/images load after DOMContentLoaded, do one more pass shortly after
  window.setTimeout(positionComments, 50);
  window.setTimeout(positionComments, 250);
})();
