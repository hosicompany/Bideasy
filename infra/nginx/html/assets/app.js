/* app.js — shared client helpers for BidEasy static pages.
   Exposes window.BD: icon, won, fmt, mountNav, toast, getFavs, toggleFav, theme.
   In production these favorites/feed calls would hit your api(). */
(function () {
  var ICONS = {
    search: 'M7.5 7.5m-5 0a5 5 0 1 0 10 0a5 5 0 1 0 -10 0 M11 11l4 4',
    filter: 'M2.5 4h11 M4.5 8h7 M6.5 12h3',
    check: 'M3.5 8.5l3 3 6-6.5',
    alert: 'M8 3l5.5 10h-11z M8 7.2v3 M8 11.6v.01',
    chevR: 'M6 3.5l4.5 4.5L6 12.5',
    chevD: 'M3.5 6l4.5 4.5L12.5 6',
    bell: 'M5 7a4 4 0 0 1 8 0c0 4 1.5 5 1.5 5h-11S5 11 5 7 M7.2 14.5a1.8 1.8 0 0 0 3.6 0',
    doc: 'M4 2.5h5l3 3v8a.5.5 0 0 1-.5.5h-7.5a.5.5 0 0 1-.5-.5V3a.5.5 0 0 1 .5-.5z M9 2.5V5.5h3',
    bolt: 'M8.5 2.5L4 9h3.2l-.7 4.5L11 7H7.8z',
    shield: 'M8 2.5l5 1.8v3.7c0 3-2.2 4.8-5 5.7-2.8-.9-5-2.7-5-5.7V4.3z',
    chart: 'M3 13V3 M3 13h10 M5.5 10.5l2.5-3 2 1.5 3-4',
    user: 'M8 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5 M3.5 13.5c0-2.5 2-4 4.5-4s4.5 1.5 4.5 4',
    arrowR: 'M3 8h10 M9 4l4 4-4 4',
    clock: 'M8 8m-5.5 0a5.5 5.5 0 1 0 11 0a5.5 5.5 0 1 0 -11 0 M8 4.5V8l2.5 1.5',
    copy: 'M5.5 5.5V3.2A.7.7 0 0 1 6.2 2.5h6.6a.7.7 0 0 1 .7.7v6.6a.7.7 0 0 1-.7.7h-2.3 M2.5 6.2a.7.7 0 0 1 .7-.7h6.6a.7.7 0 0 1 .7.7v6.6a.7.7 0 0 1-.7.7H3.2a.7.7 0 0 1-.7-.7z',
    star: 'M8 2.5l1.7 3.5 3.8.5-2.8 2.7.7 3.8L8 11.7 4.6 13.5l.7-3.8L2.5 7l3.8-.5z',
    sun: 'M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5 M8 1.5v1.5 M8 13v1.5 M2.4 2.4l1 1 M12.6 12.6l1 1 M1.5 8h1.5 M13 8h1.5 M2.4 13.6l1-1 M12.6 3.4l1-1',
    moon: 'M13 9.5A5.5 5.5 0 0 1 6.5 3 5.5 5.5 0 1 0 13 9.5z',
  };
  function icon(name, size, sw) {
    size = size || 16; sw = sw || 1.6;
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="' + sw + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" style="flex-shrink:0;vertical-align:middle"><path d="' + ICONS[name] + '"/></svg>';
  }
  function won(n) { return Number(n).toLocaleString('ko-KR'); }
  function fmt(n) { return '\u20a9 ' + won(Math.round(n)); }

  function getTheme() { try { return localStorage.getItem('bideasy_theme') || 'light'; } catch (e) { return 'light'; } }
  function setTheme(t) {
    try { localStorage.setItem('bideasy_theme', t); } catch (e) {}
    document.body.setAttribute('data-theme', t);
    var b = document.getElementById('themebtn'); if (b) b.innerHTML = icon(t === 'dark' ? 'sun' : 'moon');
  }
  // apply persisted theme ASAP
  try { document.documentElement.setAttribute('data-theme', getTheme()); } catch (e) {}
  document.addEventListener('DOMContentLoaded', function () { document.body.setAttribute('data-theme', getTheme()); });

  function getToken() { try { return localStorage.getItem('access_token') || localStorage.getItem('jwt') || null; } catch (e) { return null; } }

  function mountNav(active) {
    var links = [['search.html', '공고 검색', 'search'], ['dashboard.html', '대시보드', 'dashboard'], ['calculator.html', '계산기', 'calculator'], ['pricing.html', '요금제', 'pricing']];
    var authed = !!getToken();
    var right = authed
      ? '<a class="navlink" href="account.html">마이</a><a class="navlink" id="navlogout" href="#">로그아웃</a>'
      : '<a class="navlink" href="login.html">로그인</a><a class="btn btn-primary btn-sm" href="signup.html">14일 체험</a>';
    var html = '<nav class="topnav"><div class="topnav-in">' +
      '<a class="brand" href="index.html"><img src="brand/bideasy-mark.svg" width="22" height="22" alt="">BidEasy</a>' +
      '<ul class="navlinks">' + links.map(function (l) { return '<li><a class="navlink' + (active === l[2] ? ' active' : '') + '"' + (active === l[2] ? ' aria-current="page"' : '') + ' href="' + l[0] + '">' + l[1] + '</a></li>'; }).join('') + '</ul>' +
      '<div style="margin-left:auto;display:flex;align-items:center;gap:10px;">' +
        '<button id="themebtn" class="btn btn-quiet btn-sm" style="padding:8px;border-radius:9px;" aria-label="라이트/다크 테마 전환" title="테마">' + icon(getTheme() === 'dark' ? 'sun' : 'moon') + '</button>' +
        right +
      '</div></div></nav>';
    var el = document.getElementById('nav'); if (el) el.outerHTML = html;
    var tb = document.getElementById('themebtn'); if (tb) tb.addEventListener('click', function () { setTheme(getTheme() === 'dark' ? 'light' : 'dark'); });
    var lo = document.getElementById('navlogout');
    if (lo) lo.addEventListener('click', function (e) { e.preventDefault(); if (confirm('로그아웃하시겠어요?')) { try { localStorage.removeItem('access_token'); localStorage.removeItem('jwt'); } catch (x) {} location.href = '/'; } });
    // skip-to-content link + focusable main heading (a11y)
    var h1 = document.querySelector('h1');
    if (h1) { if (!h1.id) h1.id = 'main-content'; h1.setAttribute('tabindex', '-1'); }
    if (!document.querySelector('.skip-link')) document.body.insertAdjacentHTML('afterbegin', '<a class="skip-link" href="#main-content">본문 바로가기</a>');
  }

  function toast(msg, tone) {
    tone = tone || 'safe';
    var host = document.querySelector('.bd-toaster');
    if (!host) { host = document.createElement('div'); host.className = 'bd-toaster'; document.body.appendChild(host); }
    var t = document.createElement('div'); t.className = 'bd-toast';
    t.innerHTML = '<span class="tdot" style="background:var(--' + tone + ')"></span>' + msg;
    host.appendChild(t); setTimeout(function () { t.remove(); }, 2400);
  }

  function getFavs() { try { return new Set(JSON.parse(localStorage.getItem('bideasy_favs') || '["20260601-003"]')); } catch (e) { return new Set(); } }
  function saveFavs(s) { try { localStorage.setItem('bideasy_favs', JSON.stringify(Array.from(s))); } catch (e) {} }
  function toggleFav(id) { var s = getFavs(); var had = s.has(id); had ? s.delete(id) : s.add(id); saveFavs(s); return !had; }

  window.BD = { icon: icon, won: won, fmt: fmt, mountNav: mountNav, toast: toast, getFavs: getFavs, toggleFav: toggleFav, getTheme: getTheme, setTheme: setTheme, getToken: getToken, API_BASE: 'https://api.bideasy.kr/api/v1' };
})();
