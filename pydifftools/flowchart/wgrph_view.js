// Matplotlib-style pan/zoom for the wgrph preview page.
//
// svg-pan-zoom (vendored next to this file) handles wheel zoom and drag pan
// inside the embedded SVG. This script adds the "home" view (whole graph fit
// and pinned to the top), a zoom-to-rectangle mode, a guard so that a drag
// ending on a task link does not navigate, and restoration of the current
// view when the watcher swaps in a rebuilt SVG.
(function () {
  const embed = document.getElementById('svg-view');
  const boxButton = document.getElementById('wgrph-box-zoom');
  // Last view seen on this page; null until the first SVG is shown, so only
  // live reloads (same page, new src) restore it.
  let savedView = null;
  let boxMode = false;
  let panZoom = null;
  let initializedDoc = null;
  const searchButton = document.getElementById('wgrph-search');
  const searchPanel = document.getElementById('wgrph-search-panel');
  const searchInput = document.getElementById('wgrph-search-input');
  const searchStatus = document.getElementById('wgrph-search-status');
  const searchPrev = document.getElementById('wgrph-search-prev');
  const searchNext = document.getElementById('wgrph-search-next');
  let searchIndex = [];
  let matches = [];
  let matchIndex = 0;

  // {{{ Find literal text, including phrases across Graphviz line breaks

  function showMatch(step, focus = true) {
    const svgDoc = initializedDoc;
    if (svgDoc === null) {
      return;
    }
    const oldHighlight = svgDoc.getElementById('wgrph-search-highlight');
    if (oldHighlight) {
      oldHighlight.remove();
    }
    searchPrev.disabled = searchNext.disabled = matches.length === 0;
    if (matches.length === 0) {
      searchStatus.textContent = searchInput.value.trim() ? 'No matches' : '';
      return;
    }
    matchIndex = (matchIndex + step + matches.length) % matches.length;
    searchStatus.textContent = `${matchIndex + 1} of ${matches.length}`;
    const sizes = panZoom.getSizes();
    const viewport = svgDoc.querySelector('.svg-pan-zoom_viewport');
    // DOM ranges reflect the last rendered frame, which can lag behind the
    // pan/zoom state while typing. Use that frame's matrix for highlights.
    const matrix = viewport.getScreenCTM();
    const highlight = svgDoc.createElementNS(
      'http://www.w3.org/2000/svg', 'g'
    );
    highlight.id = 'wgrph-search-highlight';
    highlight.setAttribute('pointer-events', 'none');
    const match = matches[matchIndex];
    match.ranges.forEach(function (range) {
      const bounds = range.getBoundingClientRect();
      const box = {
        x: (bounds.x - matrix.e) / matrix.a,
        y: (bounds.y - matrix.f) / matrix.d,
        width: bounds.width / matrix.a,
        height: bounds.height / matrix.d,
      };
      const rect = svgDoc.createElementNS('http://www.w3.org/2000/svg', 'rect');
      for (const key of ['x', 'y', 'width', 'height']) {
        rect.setAttribute(key, box[key]);
      }
      rect.setAttribute('fill', '#ffd54f');
      rect.setAttribute('fill-opacity', '0.4');
      rect.setAttribute('stroke', '#b77900');
      rect.setAttribute('vector-effect', 'non-scaling-stroke');
      highlight.appendChild(rect);
    });
    viewport.appendChild(highlight);
    if (focus) {
      // Center the containing task while keeping the user's chosen scale.
      const bounds = match.node.getBBox();
      const point = svgDoc.documentElement.createSVGPoint();
      point.x = bounds.x + bounds.width / 2;
      point.y = bounds.y + bounds.height / 2;
      const center = point.matrixTransform(
        matrix.inverse().multiply(match.node.getScreenCTM())
      );
      panZoom.pan({
        x: sizes.width / 2 - center.x * sizes.realZoom,
        y: sizes.height / 2 - center.y * sizes.realZoom,
      });
    }
  }

  function search(reset = true) {
    const query = searchInput.value.trim().replace(/\s+/g, ' ').toLowerCase();
    matches = [];
    if (reset) {
      matchIndex = 0;
    }
    if (query) {
      for (const entry of searchIndex) {
        let start = entry.text.indexOf(query);
        while (start !== -1) {
          const ranges = [];
          for (const position of entry.positions.slice(start, start + query.length)) {
            if (position === null) {
              continue;
            }
            const last = ranges[ranges.length - 1];
            if (last && last.endContainer === position.leaf) {
              last.setEnd(position.leaf, position.end);
            } else {
              const range = initializedDoc.createRange();
              range.setStart(position.leaf, position.offset);
              range.setEnd(position.leaf, position.end);
              ranges.push(range);
            }
          }
          if (ranges.length) {
            matches.push({ ranges, node: entry.node });
          }
          start = entry.text.indexOf(query, start + query.length);
        }
      }
    }
    showMatch(0, reset);
  }

  function openSearch() {
    searchPanel.hidden = false;
    searchButton.setAttribute('aria-expanded', 'true');
    searchInput.focus();
    searchInput.select();
  }

  function closeSearch() {
    searchPanel.hidden = true;
    searchButton.setAttribute('aria-expanded', 'false');
    searchInput.value = '';
    search();
    searchButton.focus();
  }

  searchButton.addEventListener('click', function () {
    if (searchPanel.hidden) {
      openSearch();
    } else {
      closeSearch();
    }
  });
  searchInput.addEventListener('input', function () { search(); });
  searchInput.addEventListener('keydown', function (evt) {
    if (evt.key === 'Tab' || evt.key === 'Enter') {
      evt.preventDefault();
      showMatch(evt.shiftKey ? -1 : 1);
    }
  });
  searchPrev.addEventListener('click', function () { showMatch(-1); });
  searchNext.addEventListener('click', function () { showMatch(1); });
  // }}}

  function handleKeys(evt) {
    if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === 'f') {
      evt.preventDefault();
      openSearch();
    }
    if (evt.key === 'Escape') {
      setBoxMode(false);
      if (!searchPanel.hidden) {
        closeSearch();
      }
    }
  }

  function saveView() {
    savedView = {
      realZoom: panZoom.getSizes().realZoom,
      pan: panZoom.getPan(),
    };
  }

  function home() {
    // Fit the whole graph, pinned to the top and centered horizontally.
    panZoom.resize();
    panZoom.reset();
    const sizes = panZoom.getSizes();
    panZoom.panBy({
      x: (sizes.width - sizes.viewBox.width * sizes.realZoom) / 2,
      y: 0,
    });
  }

  function setBoxMode(enabled) {
    boxMode = enabled;
    boxButton.classList.toggle('active', enabled);
    if (panZoom === null) {
      return;
    }
    if (enabled) {
      panZoom.disablePan();
    } else {
      panZoom.enablePan();
    }
  }

  function init() {
    const svgDoc = embed.getSVGDocument();
    if (
      svgDoc === null ||
      svgDoc.readyState !== 'complete' ||
      svgDoc.documentElement === null ||
      svgDoc === initializedDoc
    ) {
      return;
    }
    initializedDoc = svgDoc;
    const svg = svgDoc.documentElement;
    // Let the SVG fill the embed box; svg-pan-zoom then moves the viewBox
    // scaling onto its viewport group.
    svg.setAttribute('width', '100%');
    svg.setAttribute('height', '100%');
    panZoom = svgPanZoom(embed, {
      fit: true,
      center: false,
      dblClickZoomEnabled: false,
      zoomScaleSensitivity: 0.2,
      minZoom: 0.1,
      maxZoom: 50,
      onZoom: saveView,
      onPan: saveView,
    });
    window.wgrphPanZoom = panZoom;
    if (savedView === null) {
      home();
    } else {
      const restore = savedView;
      const zoom = (restore.realZoom / panZoom.getSizes().realZoom) *
        panZoom.getZoom();
      panZoom.setMinZoom(Math.min(0.1, zoom));
      panZoom.setMaxZoom(Math.max(50, zoom));
      panZoom.zoom(zoom);
      panZoom.pan(restore.pan);
    }
    saveView();
    setBoxMode(boxMode);
    // {{{ Index the visible SVG text after each load
    searchIndex = Array.from(svgDoc.querySelectorAll('g.node'), function (node) {
      let text = '';
      const positions = [];
      for (const element of node.querySelectorAll('text')) {
        if (text && !text.endsWith(' ')) {
          text += ' ';
          positions.push(null);
        }
        const walker = svgDoc.createTreeWalker(element, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
          const leaf = walker.currentNode;
          for (let offset = 0; offset < leaf.length;) {
            const char = String.fromCodePoint(leaf.data.codePointAt(offset));
            const normalized = /\s/.test(char) ? ' ' : char.toLowerCase();
            if (normalized !== ' ' || !text.endsWith(' ')) {
              text += normalized;
              for (let i = 0; i < normalized.length; i++) {
                positions.push({ leaf, offset, end: offset + char.length });
              }
            }
            offset += char.length;
          }
        }
      }
      return { text, positions, node };
    });
    // }}}
    search(false);

    // {{{ Suppress link clicks that end a pan or a box selection
    let downPoint = null;
    let dragged = false;
    svgDoc.addEventListener(
      'mousedown',
      function (evt) {
        downPoint = { x: evt.clientX, y: evt.clientY };
        dragged = false;
      },
      true
    );
    svgDoc.addEventListener(
      'mousemove',
      function (evt) {
        if (
          downPoint !== null &&
          Math.hypot(evt.clientX - downPoint.x, evt.clientY - downPoint.y) > 4
        ) {
          dragged = true;
        }
      },
      true
    );
    svgDoc.addEventListener(
      'click',
      function (evt) {
        if (dragged || boxMode) {
          evt.preventDefault();
          evt.stopPropagation();
        }
        downPoint = null;
        dragged = false;
      },
      true
    );
    svgDoc.addEventListener(
      'contextmenu',
      function (evt) {
        const node = evt.target.closest
          ? evt.target.closest('g.node[data-source-name]')
          : null;
        if (!node) {
          return;
        }
        evt.preventDefault();
        const bounds = embed.getBoundingClientRect();
        window.parent.document.dispatchEvent(
          new window.parent.CustomEvent('pydifft-source-context', {
            detail: {
              phrase: node.getAttribute('data-source-name'),
              clientX: bounds.left + evt.clientX,
              clientY: bounds.top + evt.clientY,
            },
          })
        );
      },
      true
    );
    // }}}

    // {{{ Zoom-to-rectangle mode
    let boxStart = null;
    let boxRect = null;
    svg.addEventListener('mousedown', function (evt) {
      if (!boxMode || evt.button !== 0) {
        return;
      }
      boxStart = { x: evt.clientX, y: evt.clientY };
      // The rectangle lives on the root <svg>, outside the pan/zoom
      // viewport group, so its coordinates are plain screen pixels.
      boxRect = svgDoc.createElementNS('http://www.w3.org/2000/svg', 'rect');
      boxRect.setAttribute('fill', 'rgba(70,130,180,0.15)');
      boxRect.setAttribute('stroke', 'steelblue');
      boxRect.setAttribute('stroke-dasharray', '4 3');
      boxRect.setAttribute('pointer-events', 'none');
      svg.appendChild(boxRect);
    });
    svg.addEventListener('mousemove', function (evt) {
      if (boxStart === null) {
        return;
      }
      boxRect.setAttribute('x', Math.min(boxStart.x, evt.clientX));
      boxRect.setAttribute('y', Math.min(boxStart.y, evt.clientY));
      boxRect.setAttribute('width', Math.abs(evt.clientX - boxStart.x));
      boxRect.setAttribute('height', Math.abs(evt.clientY - boxStart.y));
    });
    svgDoc.addEventListener('mouseup', function (evt) {
      if (boxStart === null) {
        return;
      }
      const width = Math.abs(evt.clientX - boxStart.x);
      const height = Math.abs(evt.clientY - boxStart.y);
      const center = {
        x: (evt.clientX + boxStart.x) / 2,
        y: (evt.clientY + boxStart.y) / 2,
      };
      boxRect.remove();
      boxRect = null;
      boxStart = null;
      if (width <= 5 || height <= 5) {
        return;
      }
      const sizes = panZoom.getSizes();
      panZoom.zoomAtPointBy(
        Math.min(sizes.width / width, sizes.height / height),
        center
      );
      panZoom.panBy({
        x: sizes.width / 2 - center.x,
        y: sizes.height / 2 - center.y,
      });
    });
    // }}}
    svgDoc.addEventListener('keydown', handleKeys);
  }

  embed.addEventListener('load', init);
  // The SVG may already be loaded by the time this script runs.
  init();
  window.addEventListener('resize', function () {
    if (panZoom !== null) {
      // Keep the same magnification relative to the whole-graph fit.
      const before = panZoom.getSizes();
      const pan = panZoom.getPan();
      const zoom = panZoom.getZoom();
      const atHome = Math.abs(zoom - 1) < 1e-6 &&
        Math.abs(pan.x + before.viewBox.x * before.realZoom -
          (before.width - before.viewBox.width * before.realZoom) / 2) < 0.5 &&
        Math.abs(pan.y + before.viewBox.y * before.realZoom) < 0.5;
      panZoom.resize();
      if (atHome) {
        home();
      } else {
        panZoom.zoom(zoom);
        const after = panZoom.getSizes();
        const factor = after.realZoom / before.realZoom;
        panZoom.pan({
          x: after.width / 2 + (pan.x - before.width / 2) * factor,
          y: after.height / 2 + (pan.y - before.height / 2) * factor,
        });
      }
      saveView();
    }
  });
  document.addEventListener('keydown', handleKeys);
  document.getElementById('wgrph-home').addEventListener('click', home);
  document.getElementById('wgrph-actual-size').addEventListener('click', function () {
    // Graphviz may scale its graph group before viewer zoom is applied.
    const viewport = initializedDoc.querySelector('.svg-pan-zoom_viewport');
    const text = initializedDoc.querySelector('g.node text');
    const matrix = text ? viewport.getScreenCTM().inverse().multiply(
      text.getScreenCTM()
    ) : { a: 1, b: 0 };
    const zoom = panZoom.getZoom() / panZoom.getSizes().realZoom /
      Math.hypot(matrix.a, matrix.b);
    panZoom.setMinZoom(Math.min(0.1, zoom));
    panZoom.setMaxZoom(Math.max(50, zoom));
    panZoom.zoom(zoom);
  });
  document
    .getElementById('wgrph-zoom-in')
    .addEventListener('click', function () {
      panZoom.zoomBy(1.25);
    });
  document
    .getElementById('wgrph-zoom-out')
    .addEventListener('click', function () {
      panZoom.zoomBy(0.8);
    });
  boxButton.addEventListener('click', function () {
    setBoxMode(!boxMode);
  });
})();
