/* /domains: one page that opens up as you choose.
   1. the field of work (always shown, one stays selected),
   2. the kind of organization (shown when the chosen field has several),
   3. the check card with the start button (shown when a pack is chosen).
   The address hash keeps the choice, so the back button and shared links work:
   (none) = nothing chosen, #<group> = a field, #<group>/<pack> = a pack. A field with one pack goes straight to its check card. */
(function () {
  var root = document.getElementById('dc');
  if (!root) return;
  var views = [].slice.call(root.querySelectorAll('.dc-view'));
  var tiles = [].slice.call(root.querySelectorAll('.dc-tile'));
  var opts = [].slice.call(root.querySelectorAll('.dc-opt'));
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var groups = {}, packs = {};
  tiles.forEach(function (t) { groups[t.dataset.group] = { only: t.dataset.only || null }; });
  root.querySelectorAll('.dc-view[data-step="3"]').forEach(function (v) {
    packs[v.dataset.domain] = { group: v.dataset.group };
  });

  function parse() {
    var parts = decodeURIComponent(location.hash.slice(1)).split('/');
    var g = parts[0], d = parts[1];
    // A group id wins over a pack slug of the same name (justice and education are both).
    if (g && !d && !groups[g] && packs[g]) return { group: packs[g].group, domain: g };
    if (!g || !groups[g]) return {};
    if (d && packs[d] && packs[d].group === g) return { group: g, domain: d };
    if (groups[g].only) return { group: g, domain: groups[g].only };
    return { group: g };
  }

  function mark(button, on) {
    button.classList.toggle('is-selected', on);
    button.setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  function render(reveal) {
    var s = parse();
    tiles.forEach(function (t) { mark(t, t.dataset.group === s.group); });
    opts.forEach(function (o) { mark(o, Boolean(s.domain) && o.dataset.domain === s.domain); });
    var last = null;
    views.forEach(function (v) {
      var step = Number(v.dataset.step);
      var on = step === 1 ||
        (step === 2 && v.dataset.group === s.group) ||
        (step === 3 && v.dataset.domain === s.domain);
      v.hidden = !on;
      if (on) last = v; else closePanels(v);
    });
    if (reveal && last && last.dataset.step !== '1') {
      var top = last.getBoundingClientRect().top;
      var bar = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--topbar-h')) || 72;
      if (top > window.innerHeight * 0.45 || top < bar) last.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
    }
  }

  // On-demand details in the check card: at most one open at a time; pressing the open one closes it.
  function closePanels(card, except) {
    card.querySelectorAll('.dc-pbtn').forEach(function (b) {
      if (b === except) return;
      b.setAttribute('aria-expanded', 'false');
      b.classList.remove('is-open');
      var panel = document.getElementById(b.getAttribute('aria-controls'));
      if (panel) panel.hidden = true;
    });
  }
  function togglePanel(button) {
    var card = button.closest('.dc-view');
    var panel = document.getElementById(button.getAttribute('aria-controls'));
    var open = panel.hidden;
    closePanels(card, button);
    panel.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    button.classList.toggle('is-open', open);
    if (open) panel.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'nearest' });
  }

  // Organization type on the check card: pick one (press again to clear) and the start link carries it as ?org_type=,
  // so the assessment page opens with it already filled in. With none picked the link is the plain one.
  function pickOrg(chip) {
    var card = chip.closest('.dc-view');
    var on = chip.getAttribute('aria-pressed') !== 'true';
    card.querySelectorAll('[data-org]').forEach(function (c) { c.setAttribute('aria-pressed', c === chip && on ? 'true' : 'false'); });
    var cta = card.querySelector('.dc-cta[data-base]');
    if (cta) cta.setAttribute('href', cta.dataset.base + (on ? '&org_type=' + encodeURIComponent(chip.dataset.org) : ''));
  }

  function nav(hash) {
    history.pushState(null, '', location.pathname + location.search + (hash ? '#' + hash : ''));
    render(true);
  }

  root.addEventListener('click', function (e) {
    var t = e.target.closest('.dc-tile, .dc-opt, .dc-pbtn, [data-jump], [data-notice], [data-org]');
    if (!t) return;
    if (t.matches('[data-org]')) {
      pickOrg(t);
    } else if (t.matches('.dc-tile')) {
      nav(t.dataset.only ? t.dataset.group + '/' + t.dataset.only : t.dataset.group);
    } else if (t.matches('.dc-opt')) {
      nav(parse().group + '/' + t.dataset.domain);
    } else if (t.matches('.dc-pbtn')) {
      togglePanel(t);
    } else if (t.matches('[data-jump]')) {
      // an organization type that has its own pack: go to that pack's card
      var target = t.dataset.jump;
      if (packs[target]) nav(packs[target].group + '/' + target);
    } else {
      var box = document.getElementById(t.getAttribute('data-notice'));
      var open = box.hidden;
      box.hidden = !open;
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
  });
  window.addEventListener('popstate', function () { render(true); });
  render(location.hash.length > 1);
})();
