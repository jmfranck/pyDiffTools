// Map positions into existing text nodes so selection and copy stay native.
(() => {
  const normalize = text => text.replace(/[ \t\r\n\f]+/g, ' ').replace(/^ /, '');
  const ignored = '.math, math, mjx-container';
  const entries = [];
  document.addEventListener('DOMContentLoaded', () => {
    const map = document.getElementById('pydifft-line-map');
    if (!map) return;
    for (const [path, source, positions] of JSON.parse(map.textContent)) {
      const block = path.reduce((node, index) => node?.children[index], document.body);
      if (block) entries.push({block, source, positions});
    }
  });

  let glow;
  function glowAt(block, rect) {
    glow?.remove();
    glow = document.createElement('div');
    glow.id = 'pydifft-line-glow';
    glow.setAttribute('aria-hidden', 'true');
    const bounds = block.getBoundingClientRect();
    const left = Math.max(0, bounds.left);
    const right = Math.min(document.documentElement.clientWidth, bounds.right);
    glow.style.cssText =
      'position:absolute;pointer-events:none;user-select:none;z-index:2147483646;' +
      'border-radius:5px;background:rgba(255,45,45,.19);' +
      'box-shadow:0 0 9px 3px rgba(240,25,25,.44);';
    Object.assign(glow.style, {
      left: `${left + scrollX}px`,
      top: `${rect.top + scrollY}px`,
      width: `${Math.max(0, right - left)}px`,
      height: `${Math.max(1, rect.height)}px`,
    });
    document.documentElement.appendChild(glow);
    const current = glow;
    current.animate(
      [{opacity: 1}, {opacity: 1, offset: 0.7}, {opacity: 0}],
      {duration: 3800, fill: 'forwards'}
    ).onfinish = () => current.remove();
  }

  window.pydifftForwardLine = (source, line) => {
    let best;
    for (const entry of entries) {
      if (source !== entry.source || !entry.block.getClientRects().length) continue;
      for (const [offset, number] of entry.positions) {
        const distance = Math.abs(number - line);
        if (!best || distance < best.distance ||
            (distance === best.distance && number < best.number)) {
          best = {block: entry.block, offset, number, distance};
        }
      }
    }
    if (!best || best.distance > 12) return false;
    const walker = document.createTreeWalker(best.block, NodeFilter.SHOW_TEXT);
    let text = '';
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.parentElement.closest(ignored)) continue;
      const previous = text;
      text += node.data;
      if (normalize(text).length <= best.offset) continue;
      let index = 0;
      while (normalize(previous + node.data.slice(0, index)).length <= best.offset) {
        index++;
      }
      const range = document.createRange();
      range.setStart(node, index - 1);
      range.setEnd(node, index);
      window.scrollBy(0, range.getBoundingClientRect().top - innerHeight / 3);
      glowAt(best.block, range.getBoundingClientRect());
      return true;
    }
    best.block.scrollIntoView({block: 'center'});
    glowAt(best.block, best.block.getBoundingClientRect());
    return true;
  };

  const menu = document.createElement('button');
  menu.textContent = 'Jump to source';
  menu.style.cssText =
    'display:none;position:fixed;z-index:2147483647;background:white;cursor:pointer';
  let location;
  const hide = () => { menu.style.display = 'none'; };
  document.addEventListener('click', hide);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') hide();
  });
  document.addEventListener('contextmenu', event => {
    hide();
    const entry = entries.find(({block}) => block.contains(event.target));
    if (!entry) return;
    const range = document.caretRangeFromPoint?.(event.clientX, event.clientY);
    let offset = 0;
    if (range && entry.block.contains(range.startContainer)) {
      const prefix = document.createRange();
      prefix.selectNodeContents(entry.block);
      prefix.setEnd(range.startContainer, range.startOffset);
      const fragment = prefix.cloneContents();
      fragment.querySelectorAll(ignored).forEach(node => node.remove());
      offset = normalize(fragment.textContent).length;
    }
    let line = entry.positions[0][1];
    for (const [start, number] of entry.positions) {
      if (start > offset) break;
      line = number;
    }
    location = {source: entry.source, line};
    event.preventDefault();
    if (!menu.isConnected) document.body.appendChild(menu);
    menu.style.left = Math.min(event.clientX, innerWidth - 120) + 'px';
    menu.style.top = Math.min(event.clientY, innerHeight - 30) + 'px';
    menu.style.display = 'block';
  });
  menu.addEventListener('click', () => {
    hide();
    const endpoint = window.pydifftSourceJumpEndpoint;
    fetch(endpoint, {
      method: 'POST',
      mode: 'no-cors',
      body: JSON.stringify(endpoint.startsWith('/') ? location : location.line),
    }).catch(() => {});
  });
})();
