/* 투찰가 계산기 — /calculator 와 홈(/)이 함께 쓴다.
 * 마크업(id: seg·basic·tcl·tcl-label·tcl-hint·presets·aval·aval-wrap·aval-badge·result·banner)은 두 페이지에
 * 같이 있어야 한다 — backend/tests/test_calculator_markup_sync.py 가 감시한다.
 * 하한율은 assets/lower-limits.js(정본 lower_limits.py 미러), 기초금액 입력이라 fromBasis() 를 쓴다. */
(function () {
  var BD = window.BD;
  if (!document.getElementById('result')) return;
    var API_BASE = BD.API_BASE;
    var fbl = document.getElementById('from-bid-link');
    if (fbl) fbl.querySelector('span').insertAdjacentHTML('afterbegin', BD.icon('search', 14));

    // 공사는 금액대별 티어(assets/lower-limits.js — 정본: backend lower_limits.py 미러).
    // 용역·물품은 기존 정책 유지(계약유형별 상이 — 도메인 재검토 전 변경 금지).
    var LOWER = { SERVICE: 87.995, GOODS: 87.995 };
    var CT_KO = { CONSTRUCTION: '공사', SERVICE: '용역', GOODS: '물품' };

    // 기본 5억 공사 하한율 89.745% 위에서 시작 — 첫 화면이 '위반' 상태로 열리지 않게
    var st = { ct: 'CONSTRUCTION', basic: 500000000, tcl: 90.3, aval: 12400000, copied: false, aSrc: '' };
    // 공유 링크·참고 페이지에서 온 값 (?ct=&basic=&tcl=&a=&a_src=median)
    var qp = new URLSearchParams(location.search);
    if (['CONSTRUCTION', 'SERVICE', 'GOODS'].indexOf((qp.get('ct') || '').toUpperCase()) >= 0) st.ct = qp.get('ct').toUpperCase();
    var qn = function (k) { var v = qp.get(k); return v === null || v === '' ? NaN : Number(v); };
    if (Number.isFinite(qn('basic')) && qn('basic') > 0 && qn('basic') <= 1e13) st.basic = Math.round(qn('basic'));
    if (Number.isFinite(qn('tcl')) && qn('tcl') >= 85 && qn('tcl') <= 92) st.tcl = Math.round(qn('tcl') * 1000) / 1000;
    if (Number.isFinite(qn('llr')) && qn('llr') >= 50 && qn('llr') <= 100) st.noticeRate = qn('llr');
    if (Number.isFinite(qn('a')) && qn('a') >= 0 && qn('a') < st.basic) { st.aval = Math.round(Number(qp.get('a'))); st.aSrc = qp.get('a_src') === 'median' ? 'median' : ''; }

    function shareUrl() {
      return 'https://bideasy.kr/s/calc?ct=' + st.ct + '&basic=' + st.basic + '&tcl=' + st.tcl.toFixed(3) + '&a=' + (st.ct === 'GOODS' ? 0 : st.aval) + (st.aSrc === 'median' ? '&a_src=median' : '') + (st.noticeRate ? '&llr=' + st.noticeRate : '');
    }

    function num(el) { return Number(document.getElementById(el).value.replace(/[^\d]/g, '')) || 0; }

    function render() {
      var a = st.ct === 'GOODS' ? 0 : st.aval;
      var lb = st.ct === 'CONSTRUCTION'
        ? (st.noticeRate ? { rate: st.noticeRate, ambiguous: false } : window.BD_LOWER.fromBasis(st.basic))
        : { rate: LOWER[st.ct], ambiguous: false };
      var rate = lb.rate;
      var predicted = Math.floor(((st.basic - a) * (st.tcl / 100) + a) / 10) * 10;
      // 하한선도 A값 보정 — 백엔드 calculator.py 와 동일 공식: (기초 − A) × 하한율 + A
      var lower = Math.round(a > 0 ? (st.basic - a) * rate / 100 + a : st.basic * rate / 100);
      var diff = st.basic ? ((predicted - lower) / st.basic) * 100 : 0;
      var level = predicted < lower ? 'DANGER' : (diff < 0.5 ? 'WARN' : 'SAFE');
      var danger = level === 'DANGER';
      var pos = Math.max(0.05, Math.min(0.96, (diff + 1.5) / 4));
      var meta = { SAFE: ['하한선 이상', 'safe', '입력값 기준 계산 결과가 낙찰하한선보다 높습니다. 최종 투찰 전 공고 원문과 입력값을 확인하세요.'], WARN: ['하한선 근접 — 주의', 'warn', '입력값 기준 계산 결과가 하한선과 가깝습니다. 공고 원문과 투찰률을 다시 확인하세요.'], DANGER: ['하한선 미달', 'danger', '입력값 기준 계산 결과가 낙찰하한선 아래입니다. 공고 원문을 확인하도록 복사를 막았어요.'] }[level];

      document.getElementById('tcl-label').textContent = '투찰률 — 현재 ' + st.tcl.toFixed(2) + '%';
      document.getElementById('aval-badge').style.display = st.aSrc === 'median' ? 'block' : 'none';
      document.getElementById('tcl-hint').textContent = '낙찰하한선(' + rate + '%) 아래는 무효 구간입니다. 슬라이더로 입력값에 따른 계산 결과를 확인하세요.' +
        (lb.ambiguous ? ' ⚠️ 하한율 구간은 추정가격(부가세 제외) 기준이에요. 이 기초금액이면 공고의 추정가격이 경계 아래일 수 있어 높은 쪽(' + rate + '%)으로 계산했어요 — 공고문의 추정가격을 확인하세요.' : '');
      document.getElementById('tcl').style.accentColor = danger ? 'var(--danger)' : 'var(--accent)';

      var presets = [rate - 0.25, rate, rate + 0.45, rate + 1.05, rate + 2.05];
      document.getElementById('presets').innerHTML = presets.map(function (r) {
        var on = Math.abs(st.tcl - r) < 0.005, isL = Math.abs(r - rate) < 0.005;
        return '<button class="btn btn-ghost btn-sm preset" data-r="' + r.toFixed(3) + '" style="flex:1;padding:7px 0;font-family:var(--font-mono);font-weight:500;border-color:' + (on ? 'var(--accent)' : isL ? 'var(--danger)' : 'var(--line-2)') + ';color:' + (on ? 'var(--accent)' : isL ? 'var(--danger)' : 'var(--muted)') + ';">' + r.toFixed(2) + '</button>';
      }).join('');
      document.querySelectorAll('.preset').forEach(function (b) { b.addEventListener('click', function () { st.tcl = Number(b.getAttribute('data-r')); document.getElementById('tcl').value = st.tcl; render(); }); });

      var gauge = '<div style="position:relative;height:8px;border-radius:4px;overflow:hidden;background:linear-gradient(90deg,var(--danger-soft) 0 37.5%,var(--safe-soft) 37.5% 100%);"></div>' +
        '<div style="position:relative;height:0;"><div style="position:absolute;left:37.5%;top:-14px;width:2px;height:16px;background:var(--ink);border-radius:1px;"></div>' +
        '<div style="position:absolute;left:' + (pos * 100) + '%;top:-13px;transform:translateX(-50%);width:14px;height:14px;border-radius:50%;background:var(--surface);border:3px solid var(--' + (danger ? 'danger' : 'safe') + ');box-shadow:var(--shadow-sm);"></div></div>' +
        '<div style="display:flex;justify-content:space-between;margin-top:9px;"><span class="micro" style="font-size:9.5px;letter-spacing:1px;">낙찰하한선</span><span class="micro" style="font-size:9.5px;letter-spacing:1px;color:var(--' + (danger ? 'danger' : 'safe') + ');">내 투찰가</span></div>';

      document.getElementById('result').style.borderColor = danger ? 'var(--danger)' : 'var(--line)';
      document.getElementById('result').innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center;"><span class="micro">예상 투찰가</span><span class="chip chip-' + meta[1] + '"><span class="dot" style="background:var(--' + meta[1] + ');"></span>' + meta[0] + '</span></div>' +
        '<div style="display:flex;align-items:baseline;gap:7px;margin-top:12px;"><span class="num" style="font-size:22px;font-weight:500;color:var(--muted);">₩</span><span class="num" style="font-size:40px;font-weight:600;letter-spacing:-1.5px;color:var(--' + (danger ? 'danger' : 'ink') + ');">' + BD.won(predicted) + '</span></div>' +
        '<div class="panel" style="padding:18px;margin-top:18px;">' + gauge + '</div>' +
        '<div style="margin-top:10px;"><div class="drow"><span class="k">낙찰하한선 · ' + rate + '%</span><span class="v">' + BD.fmt(lower) + '</span></div>' +
        '<div class="drow"><span class="k">하한 대비 여유</span><span class="v" style="color:var(--' + (danger ? 'danger' : 'safe') + ');font-weight:700;">' + (diff >= 0 ? '+' : '') + diff.toFixed(2) + ' %p</span></div>' +
        (a > 0 ? '<div class="drow"><span class="k">A값 (투찰률 미적용)</span><span class="v">' + BD.fmt(a) + '</span></div>' : '') + '</div>' +
        '<div style="display:flex;gap:9px;margin-top:14px;padding:12px 14px;border-radius:11px;background:var(--' + meta[1] + '-soft);"><span style="color:var(--' + meta[1] + ');flex-shrink:0;margin-top:1px;">' + BD.icon(danger ? 'alert' : level === 'WARN' ? 'alert' : 'shield', 15, 1.8) + '</span><span style="font-size:13px;color:var(--ink-2);line-height:1.55;">사장님, ' + meta[2] + '</span></div>' +
        '<button id="copy" class="btn btn-block ' + (danger ? 'btn-ghost' : 'btn-primary') + '" style="margin-top:16px;' + (danger ? 'opacity:.5;cursor:not-allowed;' : '') + '"' + (danger ? ' disabled' : '') + '>' + BD.icon(st.copied ? 'check' : 'copy', 15) + ' ' + (danger ? '하한선 미달 — 복사 불가' : st.copied ? '복사됐어요' : '이 금액 복사하기') + '</button>' +
        '<button id="share" class="btn btn-ghost btn-block" style="margin-top:8px;">' + BD.icon('send', 15) + ' 계산 결과 링크 복사 <span style="font-size:11.5px;color:var(--muted);font-weight:500;">카톡·카페에 붙이면 숫자 카드로 보여요</span></button>';

      var cp = document.getElementById('copy');
      if (cp && !danger) cp.addEventListener('click', function () {
        var val = String(predicted);
        if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(val).catch(function () {}); }
        if (!st.copied && window.BD && BD.trackGrowth) BD.trackGrowth('free_value_completed', { tool: 'web_calculator' });
        st.copied = true; BD.toast('이 금액을 복사했어요'); render();
      });
    }

    document.getElementById('result').addEventListener('click', function (e) {
      if (!e.target.closest('#share')) return;
      var u = shareUrl();
      if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(u).catch(function () {}); }
      if (window.gtag) gtag('event', 'calc_share_link', { contract_type: st.ct });
      BD.toast('계산 결과 링크를 복사했어요');
    });

    document.querySelectorAll('#seg button').forEach(function (b) {
      b.addEventListener('click', function () {
        document.querySelectorAll('#seg button').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active'); st.ct = b.getAttribute('data-ct'); st.noticeRate = null;
        document.getElementById('aval-wrap').style.display = st.ct === 'GOODS' ? 'none' : 'block';
        st.copied = false; render();
      });
    });
    document.getElementById('basic').addEventListener('input', function (e) { st.basic = num('basic'); st.copied = false; render(); });
    document.getElementById('aval').addEventListener('input', function () { st.aval = num('aval'); st.aSrc = ''; st.copied = false; render(); });
    document.getElementById('tcl').addEventListener('input', function (e) { st.tcl = Number(e.target.value); st.copied = false; render(); });
    document.getElementById('basic').value = BD.won(st.basic);
    document.getElementById('aval').value = BD.won(st.aval);
    document.getElementById('tcl').value = st.tcl;
    document.querySelectorAll('#seg button').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-ct') === st.ct); });
    document.getElementById('aval-wrap').style.display = st.ct === 'GOODS' ? 'none' : 'block';
    render();

    // ?no= 프리필 — 실제 공고 컨텍스트(GET /bids/{no}/context)로 기초금액·종류 자동 입력
    var no = new URLSearchParams(location.search).get('no');
    if (no) {
      fetch(API_BASE + '/bids/' + encodeURIComponent(no) + '/context').then(function (r) { return r.ok ? r.json() : null; }).then(function (ctx) {
        if (!ctx || ctx.found === false) return;
        // 기초금액 칸에는 확인된 기초금액만 넣는다 — 추정가격(estimated_price)을 넣으면 하한선이 약 9% 낮아진다(함정 22)
        st.noticeRate = (ctx.lower_limit_rate >= 50 && ctx.lower_limit_rate <= 100) ? ctx.lower_limit_rate : null;
        if (ctx.basis_amount) { st.basic = Math.round(ctx.basis_amount); document.getElementById('basic').value = BD.won(st.basic); }
        else { st.basic = 0; document.getElementById('basic').value = ''; }
        if (ctx.contract_type) {
          st.ct = ctx.contract_type;
          document.querySelectorAll('#seg button').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-ct') === st.ct); });
          document.getElementById('aval-wrap').style.display = st.ct === 'GOODS' ? 'none' : 'block';
        }
        var nm = ctx.title || ('공고 ' + no);
        document.getElementById('banner').innerHTML = '<div class="card" style="margin-top:16px;padding:12px 16px;display:flex;align-items:center;gap:12px;border-color:var(--accent);background:var(--accent-soft);flex-wrap:wrap;"><span style="color:var(--accent);display:flex;flex-shrink:0;">' + BD.icon('doc', 15) + '</span><span style="font-size:13.5px;color:var(--ink-2);"><b style="color:var(--ink);">' + BD.esc(nm) + '</b> 기준 · ' + (ctx.basis_amount ? '기초금액·종류 자동 입력됨' : '<b style="color:var(--danger);">기초금액 미확인</b> — 공고문의 기초금액을 직접 입력하세요') + (st.noticeRate ? ' · 공고 하한율 ' + st.noticeRate + '% 적용' : '') + '</span><a class="btn btn-quiet btn-sm" style="margin-left:auto;color:var(--accent);" href="/bid.html?no=' + encodeURIComponent(no) + '">공고 상세 →</a></div>';
        st.copied = false; render();
      }).catch(function () {});
    }
})();
