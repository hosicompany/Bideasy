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
    chat: 'M3 3.5h10a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-.5.5H6.5L4 13v-2H3a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5z',
    send: 'M2 8.2l11.6-5.2-4.2 11-2.3-4.4z',
    x: 'M4 4l8 8 M12 4l-8 8',
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

  // ── 고객 문의 챗봇 위젯 (전 페이지 자동 마운트) ──────────────
  function mountSupportChat() {
    if (document.getElementById('bd-chat-fab')) return;
    var API = 'https://api.bideasy.kr/api/v1';
    var sid = '';
    try { sid = localStorage.getItem('bideasy_chat_session') || ''; } catch (e) {}
    if (!sid) { sid = 'web-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7); try { localStorage.setItem('bideasy_chat_session', sid); } catch (e) {} }
    var history = [], busy = false;

    var fab = document.createElement('button');
    fab.id = 'bd-chat-fab'; fab.className = 'bd-chat-fab'; fab.setAttribute('aria-label', '문의 챗봇 열기');
    fab.innerHTML = icon('chat', 24);
    var panel = document.createElement('div');
    panel.className = 'bd-chat-panel';
    panel.innerHTML =
      '<div class="bd-chat-head"><span style="width:30px;height:30px;border-radius:9px;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center;">' + icon('chat', 16) + '</span>' +
      '<div style="flex:1;min-width:0;"><div style="font-size:14.5px;font-weight:800;">BidEasy 도우미</div><div style="font-size:11.5px;color:var(--muted);">요금제·사용법·결제 등 무엇이든</div></div>' +
      '<button id="bd-chat-ticket" class="btn btn-quiet btn-sm" style="padding:6px 9px;font-size:12px;" title="사람에게 문의">문의</button>' +
      '<button id="bd-chat-x" class="btn btn-quiet btn-sm" style="padding:6px;" aria-label="닫기">' + icon('x', 15) + '</button></div>' +
      '<div class="bd-chat-body" id="bd-chat-body"></div>' +
      '<div class="bd-chat-foot" id="bd-chat-foot"><textarea id="bd-chat-in" class="bd-chat-input" rows="1" placeholder="메시지를 입력하세요"></textarea>' +
      '<button id="bd-chat-send" class="btn btn-primary" style="padding:9px 12px;" aria-label="전송">' + icon('send', 16) + '</button></div>';
    document.body.appendChild(fab); document.body.appendChild(panel);

    var body = panel.querySelector('#bd-chat-body');
    var input = panel.querySelector('#bd-chat-in');

    function bubble(role, text) {
      var d = document.createElement('div');
      d.className = 'bd-chat-msg ' + (role === 'user' ? 'u' : 'a');
      d.textContent = text;
      body.appendChild(d); body.scrollTop = body.scrollHeight;
    }
    function openPanel() {
      panel.classList.add('open');
      if (!history.length) bubble('assistant', '안녕하세요 사장님! BidEasy 도우미예요. 요금제·A값·자격 매칭·결제·설치 방법 등 무엇이든 편하게 물어보세요. 🙂');
      setTimeout(function () { input.focus(); }, 60);
    }
    function closePanel() { panel.classList.remove('open'); }
    fab.addEventListener('click', function () { panel.classList.contains('open') ? closePanel() : openPanel(); });
    panel.querySelector('#bd-chat-x').addEventListener('click', closePanel);

    input.addEventListener('input', function () { input.style.height = 'auto'; input.style.height = Math.min(92, input.scrollHeight) + 'px'; });
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
    panel.querySelector('#bd-chat-send').addEventListener('click', send);

    async function send() {
      if (busy) return;
      var msg = (input.value || '').trim(); if (!msg) return;
      input.value = ''; input.style.height = 'auto';
      bubble('user', msg); history.push({ role: 'user', content: msg }); busy = true;
      var typing = document.createElement('div'); typing.className = 'bd-chat-typing'; typing.textContent = '입력 중…';
      body.appendChild(typing); body.scrollTop = body.scrollHeight;
      try {
        var headers = { 'Content-Type': 'application/json' }; var tk = getToken(); if (tk) headers['Authorization'] = 'Bearer ' + tk;
        var resp = await fetch(API + '/support/chat', { method: 'POST', headers: headers, body: JSON.stringify({ message: msg, session_id: sid, history: history.slice(-6) }) });
        var data = resp.ok ? await resp.json() : null;
        if (typing.parentNode) body.removeChild(typing);
        var ans = (data && data.answer) || 'support@bideasy.kr 로 문의해 주시면 빠르게 답변드릴게요.';
        if (data && data.session_id) { sid = data.session_id; try { localStorage.setItem('bideasy_chat_session', sid); } catch (e) {} }
        bubble('assistant', ans); history.push({ role: 'assistant', content: ans });
      } catch (e) {
        if (typing.parentNode) body.removeChild(typing);
        bubble('assistant', '연결에 문제가 있어요. 잠시 후 다시 시도하시거나 support@bideasy.kr 로 문의해 주세요.');
      } finally { busy = false; }
    }

    // ── 사람에게 문의 남기기 (티켓) ──
    panel.querySelector('#bd-chat-ticket').addEventListener('click', function () {
      panel.classList.add('open');
      body.innerHTML = '';
      var wrap = document.createElement('div');
      wrap.style.cssText = 'padding:4px;';
      wrap.innerHTML = '<p style="font-size:13.5px;color:var(--muted);line-height:1.6;margin:0 0 12px;">자동 답변으로 해결되지 않으면 여기에 남겨주세요. 확인하고 이메일로 답변드릴게요.</p>' +
        '<label class="field-label">문의 내용</label><textarea id="tk-msg" class="bd-chat-input" rows="4" style="width:100%;max-height:none;margin-bottom:12px;"></textarea>' +
        '<label class="field-label">답변받을 이메일</label><input id="tk-email" class="bd-chat-input" style="width:100%;font-family:var(--font-sans);" placeholder="name@company.kr">' +
        '<div id="tk-err" style="display:none;color:var(--danger);font-size:12.5px;font-weight:600;margin-top:10px;"></div>' +
        '<div style="display:flex;gap:8px;margin-top:14px;"><button id="tk-cancel" class="btn btn-ghost btn-block btn-sm">취소</button><button id="tk-send" class="btn btn-primary btn-block btn-sm">문의 보내기</button></div>';
      body.appendChild(wrap);
      var tkTok = getToken();
      if (tkTok) { fetch(API + '/users/me', { headers: { Authorization: 'Bearer ' + tkTok } }).then(function (r) { return r.ok ? r.json() : null; }).then(function (u) { if (u && u.email) { var e = document.getElementById('tk-email'); if (e && !e.value) e.value = u.email; } }).catch(function () {}); }
      document.getElementById('tk-cancel').addEventListener('click', function () { body.innerHTML = ''; history = []; openPanel(); });
      document.getElementById('tk-send').addEventListener('click', async function () {
        var m = (document.getElementById('tk-msg').value || '').trim();
        var em = (document.getElementById('tk-email').value || '').trim();
        var err = document.getElementById('tk-err');
        if (!m) { err.textContent = '문의 내용을 입력해주세요'; err.style.display = 'block'; return; }
        var btn = this; btn.disabled = true; btn.textContent = '보내는 중...';
        try {
          var headers = { 'Content-Type': 'application/json' }; if (tkTok) headers['Authorization'] = 'Bearer ' + tkTok;
          await fetch(API + '/support/ticket', { method: 'POST', headers: headers, body: JSON.stringify({ message: m, email: em || null, session_id: sid }) });
          body.innerHTML = ''; history = [];
          bubble('assistant', '문의가 접수됐어요! 확인하고 ' + (em ? em : '등록된 이메일') + '로 답변드릴게요. 감사합니다. 🙏');
        } catch (e) { err.textContent = '전송에 실패했어요. support@bideasy.kr 로 보내주세요.'; err.style.display = 'block'; btn.disabled = false; btn.textContent = '문의 보내기'; }
      });
    });
  }

  window.BD = { icon: icon, won: won, fmt: fmt, mountNav: mountNav, toast: toast, getFavs: getFavs, toggleFav: toggleFav, getTheme: getTheme, setTheme: setTheme, getToken: getToken, mountSupportChat: mountSupportChat, API_BASE: 'https://api.bideasy.kr/api/v1' };
  // 전 페이지 자동 마운트 (auth/checkout 등 모두 — 문의 접점 극대화)
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { try { mountSupportChat(); } catch (e) {} });
  else { try { mountSupportChat(); } catch (e) {} }
})();
