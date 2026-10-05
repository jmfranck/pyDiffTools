// Add a small local-only source jump action to cpb and flowchart previews.
(function () {
  const endpoint = window.pydifftSourceJumpEndpoint;
  if (!endpoint) {
    return;
  }
  const excludedSourceElements =
    '.math,.MathJax,mjx-container,.katex,math,' +
    'script[type^="math/tex"],' +
    'a[href*="#fig:"],a[href*="#fig-"],a[href*="#fig%3A"]';

  const menu = document.createElement('div');
  menu.id = 'pydifft-source-jump-menu';
  menu.style.cssText =
    'display:none;position:fixed;z-index:2147483647;background:#fff;' +
    'border:1px solid #777;border-radius:3px;padding:3px;' +
    'box-shadow:0 2px 6px #555;font:14px sans-serif;';
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = 'Jump to source';
  button.style.cssText =
    'border:0;background:transparent;padding:6px 10px;cursor:pointer;' +
    'font:inherit;';
  menu.appendChild(button);
  document.addEventListener('DOMContentLoaded', function () {
    document.body.appendChild(menu);
  });

  let phrase = '';

  function hideMenu() {
    menu.style.display = 'none';
  }

  function showMenu(event, text) {
    phrase = (text || '').replace(/\s+/g, ' ').trim();
    if (!phrase) {
      hideMenu();
      return;
    }
    if (menu.parentNode !== document.body && document.body) {
      document.body.appendChild(menu);
    }
    event.preventDefault();
    menu.style.left = Math.min(event.clientX, window.innerWidth - 170) + 'px';
    menu.style.top = Math.min(event.clientY, window.innerHeight - 42) + 'px';
    menu.style.display = 'block';
  }

  function sentenceAtPoint(event) {
    let range = null;
    if (document.caretRangeFromPoint) {
      range = document.caretRangeFromPoint(event.clientX, event.clientY);
    } else if (document.caretPositionFromPoint) {
      const position = document.caretPositionFromPoint(
        event.clientX,
        event.clientY
      );
      if (position) {
        range = document.createRange();
        range.setStart(position.offsetNode, position.offset);
      }
    }
    const target = event.target.nodeType === Node.TEXT_NODE
      ? event.target.parentElement
      : event.target;
    const targetElement = target && target.closest ? target : document.body;
    if (targetElement.closest(excludedSourceElements)) {
      return '';
    }
    const block = targetElement.closest(
      'p,li,blockquote,h1,h2,h3,h4,h5,h6,dt,dd,td,th'
    ) || targetElement;
    // Drop rendered math and cross-reference links so the phrase resembles
    // the searchable Markdown source, where mfs removes those constructs.
    let text = '';
    let clickedOffset = 0;
    let found = false;
    function collectText(node) {
      if (node.nodeType === Node.TEXT_NODE) {
        if (range && node === range.startContainer) {
          clickedOffset = text.length + range.startOffset;
          found = true;
        }
        text += node.textContent;
        return;
      }
      if (
        node.nodeType === Node.ELEMENT_NODE &&
        node !== block &&
        node.matches(excludedSourceElements)
      ) {
        text += ' ';
        return;
      }
      node.childNodes.forEach(collectText);
    }
    collectText(block);
    const rawText = text;
    text = rawText.replace(/\s+/g, ' ').trim();
    if (!text) {
      return '';
    }
    if (!range || !found) {
      return text;
    }

    // The raw DOM offset is used to find sentence bounds before whitespace is
    // collapsed. Recompute its visible offset after normalization.
    const normalizedPrefix = rawText
      .slice(0, clickedOffset)
      .replace(/\s+/g, ' ')
      .replace(/^\s+/, '');
    clickedOffset = normalizedPrefix.length;
    const before = text.slice(0, clickedOffset);
    const after = text.slice(clickedOffset);
    const start = Math.max(
      before.lastIndexOf('.'),
      before.lastIndexOf('!'),
      before.lastIndexOf('?')
    ) + 1;
    const endMatch = after.match(/[.!?](?:\s|$)/);
    const end = endMatch ? clickedOffset + endMatch.index + 1 : text.length;
    return text.slice(start, end).trim() || text;
  }

  button.addEventListener('click', function () {
    hideMenu();
    fetch(endpoint, {
      method: 'POST',
      mode: 'no-cors',
      body: phrase,
    }).catch(function () {
      // The preview may be closing while the local editor request is sent.
    });
  });
  document.addEventListener('click', hideMenu);
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      hideMenu();
    }
  });
  document.addEventListener('contextmenu', function (event) {
    showMenu(event, sentenceAtPoint(event));
  });
  document.addEventListener('pydifft-source-context', function (event) {
    showMenu(
      {
        clientX: event.detail.clientX,
        clientY: event.detail.clientY,
        preventDefault: function () {
          event.preventDefault();
        },
      },
      event.detail.phrase
    );
  });
})();
