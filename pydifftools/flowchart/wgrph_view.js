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
      panZoom.zoom(
        (restore.realZoom / panZoom.getSizes().realZoom) * panZoom.getZoom()
      );
      panZoom.pan(restore.pan);
    }
    saveView();
    setBoxMode(boxMode);

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
    svgDoc.addEventListener('keydown', function (evt) {
      if (evt.key === 'Escape') {
        setBoxMode(false);
      }
    });
  }

  embed.addEventListener('load', init);
  // The SVG may already be loaded by the time this script runs.
  init();
  window.addEventListener('resize', function () {
    if (panZoom !== null) {
      panZoom.resize();
    }
  });
  document.addEventListener('keydown', function (evt) {
    if (evt.key === 'Escape') {
      setBoxMode(false);
    }
  });
  document.getElementById('wgrph-home').addEventListener('click', home);
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
