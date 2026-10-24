/* BiblioFlow – mouvement fluide (principes Apple traduits pour le web)
   - suivi 1:1 du doigt, avec le décalage de saisie respecté
   - lâcher : l'animation reprend à la vitesse exacte du geste
   - projection de l'élan (décélération exponentielle) pour choisir l'arrivée
   - résistance élastique aux bords
   - interruptible : on peut ressaisir l'étagère en plein vol */
(function () {
  'use strict';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)');

  /* ---- Barres translucides : la séparation n'apparaît qu'au défilement ---- */
  var bars = document.querySelectorAll('.pub-nav, .topbar');
  if (bars.length) {
    var ticking = false;
    var update = function () {
      var on = window.scrollY > 8;
      bars.forEach(function (b) { b.classList.toggle('is-scrolled', on); });
      ticking = false;
    };
    window.addEventListener('scroll', function () {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  /* ---- Outils de physique ---- */
  // Projection de l'arrivée d'un geste (fonction du code d'exemple d'Apple)
  function project(v, rate) { rate = rate || 0.998; return (v / 1000) * rate / (1 - rate); }
  // Plus on dépasse la limite, moins l'élément suit
  function rubber(over, dim, c) { c = c || 0.55; return (over * dim * c) / (dim + c * Math.abs(over)); }
  // Ressort défini par amortissement (0–1) et réponse (secondes)
  function spring(from, to, velocity, damping, response, onFrame, onDone) {
    var w = 2 * Math.PI / response, k = w * w, c = 2 * damping * w;
    var x = from, v = velocity, last = performance.now(), raf;
    function step(now) {
      var dt = Math.min((now - last) / 1000, 1 / 30); last = now;
      var a = -k * (x - to) - c * v;
      v += a * dt; x += v * dt;
      if (Math.abs(v) < 0.5 && Math.abs(x - to) < 0.3) { onFrame(to); onDone && onDone(); return; }
      onFrame(x); raf = requestAnimationFrame(step);
    }
    raf = requestAnimationFrame(step);
    return function cancel() { cancelAnimationFrame(raf); };
  }

  /* ---- Étagère de livres ---- */
  var wrap = document.querySelector('.shelf-wrap');
  var track = wrap && wrap.querySelector('.shelf');
  if (wrap && track) {
    var x = 0, cancel = null, dragging = false, startX = 0, grab = 0, hist = [], moved = false, pid = null;
    function bounds() {
      var cs = getComputedStyle(wrap);
      var inner = wrap.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      return { min: Math.min(0, inner - track.offsetWidth), max: 0, dim: inner };
    }
    function render(v) { x = v; track.style.transform = 'translate3d(' + v + 'px,0,0)'; }
    function stop() { if (cancel) { cancel(); cancel = null; } }
    // position réelle à l'écran (présentation), jamais la cible logique
    function live() { var m = new DOMMatrixReadOnly(getComputedStyle(track).transform); return m.m41; }

    wrap.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      stop(); x = live(); render(x);
      startX = e.clientX; grab = e.clientX - x; moved = false; dragging = false; pid = e.pointerId;
      hist = [{ t: e.timeStamp, x: e.clientX }];
    });
    wrap.addEventListener('pointermove', function (e) {
      if (pid !== e.pointerId) return;
      if (!dragging) {
        if (Math.abs(e.clientX - startX) < 10) return;          // hystérésis ~10px
        dragging = true; moved = true; wrap.classList.add('is-dragging');
        try { wrap.setPointerCapture(e.pointerId); } catch (_) {}
        grab = e.clientX - x;                                    // pas de saut au démarrage
      }
      var b = bounds(), raw = e.clientX - grab, v = raw;
      if (raw > b.max) v = b.max + rubber(raw - b.max, b.dim);
      else if (raw < b.min) v = b.min - rubber(b.min - raw, b.dim);
      render(v);
      hist.push({ t: e.timeStamp, x: e.clientX });
      while (hist.length > 2 && e.timeStamp - hist[0].t > 100) hist.shift();
    });
    function release(e) {
      if (pid !== e.pointerId) return;
      pid = null;
      if (!dragging) return;
      dragging = false; wrap.classList.remove('is-dragging');
      var a = hist[0], z = hist[hist.length - 1];
      var dt = (z.t - a.t) / 1000, v = dt > 0.005 ? (z.x - a.x) / dt : 0;
      var b = bounds();
      var target = Math.max(b.min, Math.min(b.max, x + project(v)));
      if (reduce.matches) { render(target); return; }
      var outside = x > b.max || x < b.min;
      // un peu de rebond seulement si le geste portait de l'élan
      var damping = outside ? 1 : (Math.abs(v) > 300 ? 0.82 : 1);
      cancel = spring(x, target, v, damping, 0.42, render, function () { cancel = null; });
    }
    wrap.addEventListener('pointerup', release);
    wrap.addEventListener('pointercancel', release);
    // un glissé ne doit pas ouvrir un livre
    wrap.addEventListener('click', function (e) { if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; } }, true);
    wrap.addEventListener('dragstart', function (e) { e.preventDefault(); });
    // clavier : le livre focalisé reste visible
    wrap.addEventListener('focusin', function (e) {
      var el = e.target.closest('.spine'); if (!el) return;
      var b = bounds(), left = el.offsetLeft + x, right = left + el.offsetWidth, t = x;
      if (left < 0) t = x - left + 12; else if (right > b.dim) t = x - (right - b.dim) - 12;
      t = Math.max(b.min, Math.min(b.max, t));
      stop(); if (reduce.matches) render(t); else cancel = spring(x, t, 0, 1, 0.4, render, function () { cancel = null; });
    });
    window.addEventListener('resize', function () { var b = bounds(); stop(); render(Math.max(b.min, Math.min(b.max, x))); });
  }
})();
