(function () {
  'use strict';

  // Заявки уходят на почту через FormSubmit (formsubmit.co). Первая заявка присылает на почту письмо
  // для активации — после нажатия «Activate» все следующие заявки приходят письмами.
  var FORM_ENDPOINT = 'https://formsubmit.co/ajax/hrexpert63@gmail.com';
  var START = Date.parse('2026-10-15T00:00:00+03:00');

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var fmt = function (n) { return Math.round(n).toLocaleString('ru-RU').replace(/[ ,]/g, ' ') + ' ₽'; };
  var pad = function (n) { return String(n).padStart(2, '0'); };

  /* Menu */
  var menu = $('#menu');
  var menuBtn = $('.menu__btn', menu);
  function setMenu(open) {
    menu.classList.toggle('is-open', open);
    menuBtn.setAttribute('aria-expanded', String(open));
    $('.menu__label', menu).textContent = open ? 'Закрыть' : 'Меню';
  }
  menuBtn.addEventListener('click', function () { setMenu(!menu.classList.contains('is-open')); });
  $$('.menu__panel a').forEach(function (a) { a.addEventListener('click', function () { setMenu(false); }); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setMenu(false); });
  document.addEventListener('click', function (e) { if (!menu.contains(e.target)) setMenu(false); });

  /* Tabs (pains + modules) */
  function tabs(btnSel, attr, panelAttr) {
    var btns = $$(btnSel);
    btns.forEach(function (b) {
      b.addEventListener('click', function () {
        var i = b.getAttribute(attr);
        btns.forEach(function (x) { var on = x === b; x.classList.toggle('is-active', on); x.setAttribute('aria-selected', String(on)); });
        $$('[' + panelAttr + ']').forEach(function (p) { p.hidden = p.getAttribute(panelAttr) !== i; });
      });
    });
  }
  tabs('.tab', 'data-tab', 'data-panel');
  tabs('.mod-tab', 'data-mod', 'data-modpanel');

  /* USP cards: hover on desktop, tap on touch */
  var usps = $$('.usp');
  usps.forEach(function (u) {
    u.addEventListener('mouseenter', function () { u.classList.add('is-on'); });
    u.addEventListener('mouseleave', function () { u.classList.remove('is-on'); });
    u.addEventListener('focus', function () { u.classList.add('is-on'); });
    u.addEventListener('blur', function () { u.classList.remove('is-on'); });
    u.addEventListener('click', function (e) {
      if (matchMedia('(hover: hover)').matches) return;
      var on = !u.classList.contains('is-on');
      usps.forEach(function (x) { x.classList.remove('is-on'); });
      u.classList.toggle('is-on', on);
    });
  });

  /* Matrix of calling */
  var secData = [
    ['Окружение', 'Люди, культура, ценности коллег — в какой среде клиент раскрывается.'],
    ['Условия труда', 'Формат и режим работы, код Голланда (RIASEC).'],
    ['Навыки', 'Способности и перенос навыков из прошлого опыта.'],
    ['Знания и интересы', 'Что клиент знает и что хочет изучать дальше.'],
    ['Финансы', 'Реалистичный уровень дохода и финансовые ожидания.'],
    ['География', 'Офис, удалёнка или релокация.'],
    ['Цель / призвание', 'Точка сборки: сюда сходятся шесть сфер, а Big Five проверяет итоговую формулировку призвания.']
  ];
  var shades = ['#0A3D3A', '#0F4F4A', '#15625B', '#1B766C', '#25897D', '#3AA697'];
  var matrix = $('#matrix');
  var gSec = $('.matrix__sectors', matrix);
  var center = $('.matrix__center', matrix);
  var NS = 'http://www.w3.org/2000/svg';
  var C = 220, R1 = 80, R2 = 212, GAP = 1.2;
  var pt = function (r, a) { return [C + r * Math.cos(a * Math.PI / 180), C + r * Math.sin(a * Math.PI / 180)].map(function (v) { return v.toFixed(2); }); };
  var paths = [], labels = [];
  for (var i = 0; i < 6; i++) {
    var a0 = -120 + i * 60 + GAP, a1 = -120 + (i + 1) * 60 - GAP, am = (a0 + a1) / 2;
    var p1 = pt(R2, a0), p2 = pt(R2, a1), p3 = pt(R1, a1), p4 = pt(R1, a0), l = pt(148, am).map(Number);
    var path = document.createElementNS(NS, 'path');
    path.setAttribute('d', 'M' + p1.join(' ') + ' A' + R2 + ' ' + R2 + ' 0 0 1 ' + p2.join(' ') + ' L' + p3.join(' ') + ' A' + R1 + ' ' + R1 + ' 0 0 0 ' + p4.join(' ') + ' Z');
    path.setAttribute('data-sector', i);
    path.setAttribute('tabindex', '0');
    path.setAttribute('role', 'button');
    path.setAttribute('aria-label', secData[i][0]);
    gSec.appendChild(path);
    paths.push(path);
    var lab = document.createElement('span');
    lab.className = 'matrix__label';
    lab.style.left = (l[0] / 440 * 100).toFixed(2) + '%';
    lab.style.top = (l[1] / 440 * 100).toFixed(2) + '%';
    lab.textContent = secData[i][0];
    matrix.appendChild(lab);
    labels.push(lab);
  }
  function selectSector(n) {
    paths.forEach(function (p, j) {
      var on = j === n;
      p.style.fill = on ? '#C9A227' : shades[j];
      p.style.stroke = on ? '#FAF9F6' : '#0E211F';
      labels[j].classList.toggle('is-on', on);
    });
    center.classList.toggle('is-on', n === 6);
    $('#sector-n').textContent = n + 1;
    $('#sector-t').textContent = secData[n][0];
    $('#sector-d').textContent = secData[n][1];
  }
  $$('[data-sector]', matrix).forEach(function (el) {
    var n = +el.getAttribute('data-sector');
    el.addEventListener('click', function () { selectSector(n); });
    el.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectSector(n); } });
  });
  selectSector(6);

  /* Income calculator */
  var calc = { clients: 6, sessions: 3, price: 5000 };
  function renderCalc() {
    var m = calc.clients * calc.sessions * calc.price;
    $('[data-out=clients]').textContent = calc.clients;
    $('[data-out=sessions]').textContent = calc.sessions;
    $('[data-out=price]').textContent = fmt(calc.price);
    $('#inc-m').textContent = fmt(m);
    $('#inc-y').textContent = fmt(m * 12);
  }
  $$('[data-in]').forEach(function (inp) {
    inp.addEventListener('input', function () { calc[inp.getAttribute('data-in')] = +inp.value; renderCalc(); });
  });
  renderCalc();

  /* Countdown */
  var cellBoxes = $$('[data-countdown=cells]');
  var inline = $('[data-countdown=inline]');
  var cellEls = cellBoxes.map(function (box) {
    return ['дней', 'часов', 'минут', 'секунд'].map(function (lbl) {
      var d = document.createElement('div'), b = document.createElement('b'), s = document.createElement('span');
      s.textContent = lbl; d.appendChild(b); d.appendChild(s); box.appendChild(d); return b;
    });
  });
  function tick() {
    var diff = Math.max(0, START - Date.now());
    if (diff === 0) { $$('.js-timer-block').forEach(function (el) { el.hidden = true; el.style.display = 'none'; }); return false; }
    var v = [Math.floor(diff / 864e5), pad(Math.floor(diff / 36e5) % 24), pad(Math.floor(diff / 6e4) % 60), pad(Math.floor(diff / 1e3) % 60)];
    inline.textContent = v[0] + 'д ' + v[1] + ':' + v[2] + ':' + v[3];
    cellEls.forEach(function (els) { els.forEach(function (b, k) { b.textContent = v[k]; }); });
    return true;
  }
  if (tick()) { var timer = setInterval(function () { if (!tick()) clearInterval(timer); }, 1000); }

  /* Animated stats */
  var stats = $('#stats');
  var nums = $$('[data-count]', stats);
  function drawCount(p) {
    nums.forEach(function (b) { b.textContent = Math.round(+b.getAttribute('data-count') * p) + (b.getAttribute('data-suffix') || ''); });
  }
  if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    drawCount(0);
    var io = new IntersectionObserver(function (es) {
      if (!es[0].isIntersecting) return;
      io.disconnect();
      var s = performance.now();
      (function step(t) { var p = Math.min(1, (t - s) / 1600); drawCount(1 - Math.pow(1 - p, 3)); if (p < 1) requestAnimationFrame(step); })(s);
    }, { threshold: 0.3 });
    io.observe(stats);
  }

  /* FAQ accordion (one open at a time) */
  var faqItems = $$('.faq__item');
  faqItems.forEach(function (item) {
    $('button', item).addEventListener('click', function () {
      var open = !item.classList.contains('is-open');
      faqItems.forEach(function (x) { x.classList.remove('is-open'); $('button', x).setAttribute('aria-expanded', 'false'); });
      item.classList.toggle('is-open', open);
      $('button', item).setAttribute('aria-expanded', String(open));
    });
  });

  /* Plan buttons remember the chosen plan */
  var form = $('#apply-form');
  $$('[data-plan]').forEach(function (a) {
    a.addEventListener('click', function () { form.elements.plan.value = a.getAttribute('data-plan'); });
  });

  /* Application form */
  var err = $('.form__err', form);
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var f = form.elements;
    var msg = !f.name.value.trim() ? 'Укажите имя' : !f.contact.value.trim() ? 'Укажите телефон или Telegram' : !f.agree.checked ? 'Нужно согласие на обработку персональных данных' : '';
    err.hidden = !msg; err.textContent = msg;
    if (msg) return;
    var done = function () { form.hidden = true; $('.form__done').hidden = false; };
    if (!FORM_ENDPOINT) { done(); return; }
    var btn = $('.form__submit', form);
    btn.disabled = true;
    fetch(FORM_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({
        'Имя': f.name.value.trim(), 'Контакт': f.contact.value.trim(), 'Деятельность': f.role.value || '—',
        'Тариф': f.plan.value || '—', 'Страница': location.href,
        _subject: 'Заявка на «Карьерный стратег»: ' + f.name.value.trim(), _template: 'table', _captcha: 'false'
      })
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (String(j.success) !== 'true') throw new Error(j.message);
      done();
    }).catch(function () {
      btn.disabled = false;
      err.hidden = false;
      err.textContent = 'Не удалось отправить заявку. Попробуйте ещё раз или напишите нам в Telegram.';
    });
  });
})();
