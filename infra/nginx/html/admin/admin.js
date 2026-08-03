/**
 * BidEasy Admin SPA — 라우터 + 인증 + 페이지 렌더
 *
 * 라우팅: location.hash 변경 감지. /admin#/dashboard, /admin#/users 등.
 * 인증: localStorage.access_token + GET /users/me 로 is_admin 검증.
 * 페이지: pages.dashboard(), pages.users() ... — Phase B 는 dashboard 만.
 */

const API_BASE = 'https://api.bideasy.kr/api/v1';

// ─── 유틸 ───────────────────────────────────────────────────

function getToken() {
  try {
    return localStorage.getItem('access_token') || localStorage.getItem('jwt') || null;
  } catch { return null; }
}

function clearToken() {
  try {
    localStorage.removeItem('access_token');
    localStorage.removeItem('jwt');
  } catch {}
}

function toast(message, type = 'info', duration = 3500) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = `toast show ${type}`;
  setTimeout(() => el.classList.remove('show'), duration);
}

function fmtKRW(n) {
  if (n == null) return '—';
  return n.toLocaleString('ko-KR') + '원';
}
function fmtNumber(n) {
  if (n == null) return '—';
  return n.toLocaleString('ko-KR');
}
function fmtPct(n) {
  if (n == null) return '—';
  return (n * 100).toFixed(1) + '%';
}
function fmtUSD(n) {
  if (n == null) return '—';
  return '$' + n.toFixed(2);
}
function fmtDateShort(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}
function fmtDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${y}.${m}.${day} ${hh}:${mm}`;
}
function fmtRelative(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return '방금';
  if (min < 60) return `${min}분 전`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}일 전`;
  return fmtDateTime(iso);
}

// ─── API 클라이언트 ────────────────────────────────────────

async function api(path, init = {}) {
  const token = getToken();
  if (!token) throw new Error('NO_TOKEN');
  const headers = new Headers(init.headers || {});
  headers.set('Authorization', 'Bearer ' + token);
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const resp = await fetch(API_BASE + path, { ...init, headers });
  if (resp.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (resp.status === 403) {
    throw new Error('FORBIDDEN');
  }
  if (!resp.ok) {
    const txt = await resp.text();
    let msg = `HTTP ${resp.status}`;
    try { const j = JSON.parse(txt); if (j.detail) msg = j.detail; } catch {}
    throw new Error(msg);
  }
  return resp.json();
}

// ─── 인증 흐름 ────────────────────────────────────────────

async function checkAuth() {
  const token = getToken();
  if (!token) {
    showGate('로그인이 필요해요. 운영자 계정으로 로그인해주세요.', true);
    return null;
  }
  try {
    const me = await api('/users/me');
    if (!me.is_admin) {
      showGate('관리자 권한이 없어요. 운영자 계정으로 로그인해주세요.', true);
      return null;
    }
    return me;
  } catch (err) {
    if (err.message === 'UNAUTHORIZED' || err.message === 'NO_TOKEN') {
      showGate('세션이 만료됐어요. 다시 로그인해주세요.', true);
    } else {
      showGate('인증 확인 중 오류가 발생했어요: ' + err.message, true);
    }
    return null;
  }
}

function showGate(message, withActions) {
  document.getElementById('gate').classList.remove('hidden');
  document.getElementById('app').classList.add('hidden');
  document.getElementById('gate-msg').textContent = message;
  document.getElementById('gate-actions').classList.toggle('hidden', !withActions);
}

function showApp(me) {
  document.getElementById('gate').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  document.getElementById('user-email').textContent = me.email || me.id;
}

// ─── 라우터 ────────────────────────────────────────────────

const PAGE_TITLES = {
  dashboard: '대시보드',
  users: '사용자',
  payments: '결제',
  autocalibrate: '자가보정',
  system: '시스템',
  simulation: '백테스트 (과거 데이터)',
  mockbidding: '모의투찰 (사전 등록·채점)',
};

function getCurrentRoute() {
  const h = (location.hash || '#/dashboard').replace(/^#\//, '');
  const r = h.split(/[?/]/)[0] || 'dashboard';
  return PAGE_TITLES[r] ? r : 'dashboard';
}

async function renderRoute() {
  const route = getCurrentRoute();
  // sidebar active
  document.querySelectorAll('.nav-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.route === route);
  });
  document.getElementById('page-title').textContent = PAGE_TITLES[route];

  const content = document.getElementById('page-content');
  content.innerHTML = '<div class="skel" style="margin: 12px 0;"></div>'.repeat(3);

  try {
    const renderer = pages[route] || pages.dashboard;
    await renderer(content);
  } catch (err) {
    if (err.message === 'UNAUTHORIZED' || err.message === 'NO_TOKEN') {
      showGate('세션이 만료됐어요.', true);
      return;
    }
    content.innerHTML = `<div class="card"><h3>오류</h3><p>${err.message}</p></div>`;
  }
}

// ─── 페이지 정의 ───────────────────────────────────────────

const pages = {};

// 대시보드 (Phase B)
pages.dashboard = async function(content) {
  const [rev, users, ai, sys, calib, daily] = await Promise.all([
    api('/admin/stats/revenue?days=30'),
    api('/admin/stats/users?days=30'),
    api('/admin/stats/ai-cost?days=30'),
    api('/admin/stats/system-health'),
    api('/admin/stats/autocalibrate-status'),
    api('/admin/daily-report').catch(() => null),  // 일일 리포트 (실패해도 무시)
  ]);

  // 일일 리포트 카드 (있을 때만)
  const dailyReportCard = daily ? `
    <div class="card" style="margin-bottom:24px;">
      <h3 style="display:flex;align-items:center;gap:8px;">
        📊 어제의 운영 리포트
        <span style="font-size:12px;font-weight:500;color:#8B95A1;">(${daily.target_date})</span>
        ${daily.anomalies.length > 0 ? `<span style="background:#FFF0F0;color:#E53935;font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;">이상 ${daily.anomalies.length}건</span>` : ''}
      </h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-top:14px;">
        <div><div style="font-size:12px;color:#8B95A1;">어제 매출</div><div style="font-size:18px;font-weight:700;color:#191F28;margin-top:4px;">${fmtKRW(daily.revenue.yesterday_amount)}</div><div style="font-size:11px;color:#8B95A1;">${daily.revenue.yesterday_count}건</div></div>
        <div><div style="font-size:12px;color:#8B95A1;">신규 가입</div><div style="font-size:18px;font-weight:700;color:#191F28;margin-top:4px;">${daily.users.new_signups}명</div><div style="font-size:11px;color:#8B95A1;">누적 ${daily.users.total}명</div></div>
        <div><div style="font-size:12px;color:#8B95A1;">Trial 전환</div><div style="font-size:18px;font-weight:700;color:#191F28;margin-top:4px;">${daily.conversion.conversion_rate_pct}%</div><div style="font-size:11px;color:#8B95A1;">${daily.conversion.yday_converted}/${daily.conversion.yday_trial_expired}명</div></div>
        <div><div style="font-size:12px;color:#8B95A1;">AI 사용</div><div style="font-size:18px;font-weight:700;color:#191F28;margin-top:4px;">${fmtNumber(daily.ai_usage.yday_count)}회</div><div style="font-size:11px;color:#8B95A1;">~${fmtKRW(daily.ai_usage.estimated_krw)}</div></div>
      </div>
      ${daily.anomalies.length > 0 ? `
        <div style="margin-top:14px;padding:12px 14px;background:#FFF0F0;border-left:3px solid #E53935;border-radius:8px;">
          ${daily.anomalies.map(a => `<div style="font-size:13px;color:#C62828;margin:2px 0;">${a}</div>`).join('')}
        </div>
      ` : ''}
    </div>
  ` : '';

  content.innerHTML = `
    ${dailyReportCard}
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">오늘 매출</div>
        <div class="kpi-value">${fmtKRW(rev.today.revenue)}</div>
        <div class="kpi-sub">${rev.today.orders}건</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">이번 달 매출</div>
        <div class="kpi-value">${fmtKRW(rev.this_month.revenue)}</div>
        <div class="kpi-sub">MRR ${fmtKRW(rev.mrr)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">총 사용자</div>
        <div class="kpi-value">${fmtNumber(users.total)}</div>
        <div class="kpi-sub">Trial ${users.by_status.trial_active}명 활성</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">AI 비용 (월)</div>
        <div class="kpi-value">${fmtUSD(ai.this_month.estimated_usd)}</div>
        <div class="kpi-sub">${fmtNumber(ai.this_month.calls)}회 분석</div>
      </div>
    </div>

    <div class="chart-grid">
      <div class="card">
        <h3>매출 추이 (30일)</h3>
        <div class="chart-wrap"><canvas id="ch-revenue"></canvas></div>
      </div>
      <div class="card">
        <h3>Tier 분포</h3>
        <div class="chart-wrap"><canvas id="ch-tier"></canvas></div>
      </div>
    </div>

    <div class="chart-grid-2">
      <div class="card">
        <h3>신규 가입 추이 (30일)</h3>
        <div class="chart-wrap"><canvas id="ch-signup"></canvas></div>
      </div>
      <div class="card">
        <h3>AI 토큰 사용 (30일)</h3>
        <div class="chart-wrap"><canvas id="ch-ai"></canvas></div>
      </div>
    </div>

    <div class="chart-grid">
      <div class="card">
        <h3>자가보정 상태</h3>
        ${calib.active ? `
          <div class="calib-active">
            <div class="status-row">
              <span class="status-label">Active 버전</span>
              <span class="calib-active-version">${calib.active.version_id}</span>
            </div>
            <div class="status-row">
              <span class="status-label">채택일</span>
              <span class="status-value">${fmtDateTime(calib.active.created_at)}</span>
            </div>
            ${calib.active.metrics ? `
              <div class="status-row">
                <span class="status-label">낙찰률 / 탈락률</span>
                <span class="status-value">
                  ${(calib.active.metrics.win_rate ?? 0).toFixed(2)}% /
                  ${(calib.active.metrics.dropout_rate ?? 0).toFixed(2)}%
                </span>
              </div>
            ` : ''}
            <div class="status-row">
              <span class="status-label">다음 자동 실행</span>
              <span class="status-value">${fmtDateTime(calib.next_scheduled)}</span>
            </div>
          </div>
        ` : '<p style="color:var(--color-text-muted);">active 버전 없음</p>'}
        <h3 style="margin-top:16px;">최근 이력</h3>
        ${calib.recent_history.slice(0, 5).map(h => `
          <div class="status-row">
            <span class="status-label">${fmtRelative(h.at)} · ${h.event}</span>
            <span class="status-value" style="font-family:monospace;font-size:12px;">${h.version_id || '—'}</span>
          </div>
        `).join('') || '<p style="color:var(--color-text-muted);">기록 없음</p>'}
      </div>

      <div class="card">
        <h3>시스템 헬스</h3>
        <div class="status-row">
          <span class="status-label">DB</span>
          <span class="status-value">
            <span class="status-dot ${sys.db.ok ? 'status-ok' : 'status-bad'}"></span>
            ${sys.db.ok ? '정상' : '오류'}
            ${sys.db.detail ? `<small style="color:var(--color-text-muted);"> · ${sys.db.detail}</small>` : ''}
          </span>
        </div>
        <div class="status-row">
          <span class="status-label">Redis</span>
          <span class="status-value">
            <span class="status-dot ${sys.redis.ok ? 'status-ok' : 'status-bad'}"></span>
            ${sys.redis.ok ? '정상' : '오류'}
          </span>
        </div>
        <div class="status-row">
          <span class="status-label">Celery</span>
          <span class="status-value">
            <span class="status-dot ${sys.celery.ok ? 'status-ok' : 'status-bad'}"></span>
            ${sys.celery.workers}명 워커
          </span>
        </div>
        <div class="status-row">
          <span class="status-label">마지막 크롤</span>
          <span class="status-value">${fmtRelative(sys.last_crawl_at)}</span>
        </div>
        <div class="status-row">
          <span class="status-label">마지막 자가보정 채택</span>
          <span class="status-value">${fmtRelative(sys.last_calibration_at)}</span>
        </div>
        <div class="status-row">
          <span class="status-label">PENDING 결제 (24h+)</span>
          <span class="status-value">
            ${sys.pending_payments_24h > 0
              ? `<span class="status-dot status-warn"></span>${sys.pending_payments_24h}건`
              : `<span class="status-dot status-ok"></span>0건`}
          </span>
        </div>
      </div>
    </div>
  `;

  // 차트 렌더 (모두 Chart.js 4.x)
  const chartDefaults = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } };

  new Chart(document.getElementById('ch-revenue'), {
    type: 'line',
    data: {
      labels: rev.series.map((p) => fmtDateShort(p.date)),
      datasets: [{
        data: rev.series.map((p) => p.amount),
        borderColor: '#3182F6',
        backgroundColor: 'rgba(49, 130, 246, 0.1)',
        tension: 0.3,
        fill: true,
      }],
    },
    options: {
      ...chartDefaults,
      scales: { y: { ticks: { callback: (v) => v.toLocaleString() + '원' } } },
    },
  });

  new Chart(document.getElementById('ch-tier'), {
    type: 'doughnut',
    data: {
      labels: ['Free', 'Pro', 'Pro+'],
      datasets: [{
        data: [users.by_tier.free, users.by_tier.pro, users.by_tier.pro_plus],
        backgroundColor: ['#B0B8C1', '#3182F6', '#FF8A00'],
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } },
    },
  });

  new Chart(document.getElementById('ch-signup'), {
    type: 'bar',
    data: {
      labels: users.signups_series.map((p) => fmtDateShort(p.date)),
      datasets: [{
        data: users.signups_series.map((p) => p.count),
        backgroundColor: '#22A06B',
      }],
    },
    options: chartDefaults,
  });

  new Chart(document.getElementById('ch-ai'), {
    type: 'line',
    data: {
      labels: ai.series.map((p) => fmtDateShort(p.date)),
      datasets: [{
        data: ai.series.map((p) => p.tokens),
        borderColor: '#C77700',
        backgroundColor: 'rgba(199, 119, 0, 0.1)',
        tension: 0.3,
        fill: true,
      }],
    },
    options: {
      ...chartDefaults,
      scales: { y: { ticks: { callback: (v) => v.toLocaleString() } } },
    },
  });
};

// ─── 공통 모달 / 폼 헬퍼 ──────────────────────────────────

function openModal(title, bodyHtml, onConfirm, confirmLabel = '확인', confirmClass = 'btn-primary') {
  const existing = document.getElementById('modal-backdrop');
  if (existing) existing.remove();
  const wrap = document.createElement('div');
  wrap.id = 'modal-backdrop';
  wrap.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:8000;display:flex;align-items:center;justify-content:center;padding:16px;';
  wrap.innerHTML = `
    <div class="card" style="max-width:480px;width:100%;max-height:90vh;overflow:auto;">
      <h3 style="margin-bottom:14px;">${title}</h3>
      <div id="modal-body" style="margin-bottom:18px;font-size:14px;color:var(--color-text-sub);line-height:1.6;">${bodyHtml}</div>
      <div style="display:flex;gap:10px;justify-content:flex-end;">
        <button id="modal-cancel" class="btn btn-ghost">취소</button>
        <button id="modal-ok" class="btn ${confirmClass}">${confirmLabel}</button>
      </div>
    </div>
  `;
  document.body.appendChild(wrap);
  document.getElementById('modal-cancel').addEventListener('click', () => wrap.remove());
  document.getElementById('modal-ok').addEventListener('click', async () => {
    const ok = await onConfirm(wrap);
    if (ok !== false) wrap.remove();
  });
}

// ─── 사용자 페이지 (Phase C) ──────────────────────────────

pages.users = async function(content) {
  // 쿼리 파라미터 파싱
  const params = new URLSearchParams((location.hash.split('?')[1] || ''));
  const page = parseInt(params.get('page') || '1', 10);
  const search = params.get('search') || '';
  const tier = params.get('tier') || '';
  const trial = params.get('trial') || '';

  const qs = new URLSearchParams({ page, size: 20 });
  if (search) qs.set('search', search);
  if (tier) qs.set('tier', tier);
  if (trial) qs.set('trial', trial);

  const data = await api('/admin/users?' + qs.toString());

  content.innerHTML = `
    <div class="card" style="margin-bottom:16px;">
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
        <input id="user-search" type="text" value="${search}" placeholder="이메일·회사명·대표자명"
               style="flex:1;min-width:200px;padding:10px 14px;border:1px solid var(--color-border);border-radius:10px;font-family:inherit;font-size:14px;">
        <select id="user-tier" style="padding:10px 14px;border:1px solid var(--color-border);border-radius:10px;font-family:inherit;font-size:14px;">
          <option value="">전체 tier</option>
          <option value="free" ${tier==='free'?'selected':''}>Free</option>
          <option value="pro" ${tier==='pro'?'selected':''}>Pro</option>
          <option value="pro_plus" ${tier==='pro_plus'?'selected':''}>Pro+</option>
        </select>
        <select id="user-trial" style="padding:10px 14px;border:1px solid var(--color-border);border-radius:10px;font-family:inherit;font-size:14px;">
          <option value="">Trial 전체</option>
          <option value="active" ${trial==='active'?'selected':''}>활성</option>
          <option value="expired" ${trial==='expired'?'selected':''}>만료</option>
          <option value="none" ${trial==='none'?'selected':''}>없음</option>
        </select>
        <button id="user-search-btn" class="btn btn-primary">검색</button>
      </div>
    </div>

    <div class="card" style="padding:0;overflow:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <thead>
          <tr style="background:var(--color-bg);">
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">ID</th>
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">이메일</th>
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">회사</th>
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">Tier</th>
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">Trial</th>
            <th style="text-align:right;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">포인트</th>
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">작업</th>
          </tr>
        </thead>
        <tbody>
          ${data.items.map(u => `
            <tr style="border-top:1px solid var(--color-border-light);">
              <td style="padding:12px;font-family:monospace;font-size:12px;color:var(--color-text-muted);">${u.id}</td>
              <td style="padding:12px;">${u.email || '—'}${u.is_admin ? ' <span style="background:#FFF6E5;color:#C77700;padding:2px 6px;border-radius:6px;font-size:10px;font-weight:700;">ADMIN</span>' : ''}</td>
              <td style="padding:12px;color:var(--color-text-sub);">${u.company_name || '—'}</td>
              <td style="padding:12px;">
                <span style="background:${u.effective_tier === 'free' ? 'var(--color-bg)' : u.effective_tier === 'pro' ? 'var(--color-primary-bg)' : 'var(--color-warning-bg)'};color:${u.effective_tier === 'free' ? 'var(--color-text-sub)' : u.effective_tier === 'pro' ? 'var(--color-primary)' : 'var(--color-warning)'};padding:3px 9px;border-radius:6px;font-size:12px;font-weight:600;">
                  ${u.effective_tier.toUpperCase()}
                </span>
              </td>
              <td style="padding:12px;">
                ${u.is_trial_active ? `<span style="color:var(--color-primary);font-weight:600;">${u.trial_days_remaining}일 남음</span>` : '<span style="color:var(--color-text-muted);">—</span>'}
              </td>
              <td style="padding:12px;text-align:right;font-weight:600;">${fmtNumber(u.points)}</td>
              <td style="padding:12px;">
                <button class="btn btn-ghost" data-action="detail" data-id="${u.id}" style="padding:6px 10px;font-size:12px;">상세</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      ${data.items.length === 0 ? '<div style="padding:40px;text-align:center;color:var(--color-text-muted);">검색 결과 없음</div>' : ''}
    </div>

    ${renderPagination(data, '#/users')}
  `;

  // 이벤트 바인딩
  document.getElementById('user-search-btn').addEventListener('click', () => {
    const newQs = new URLSearchParams();
    const s = document.getElementById('user-search').value.trim();
    const t = document.getElementById('user-tier').value;
    const tr = document.getElementById('user-trial').value;
    if (s) newQs.set('search', s);
    if (t) newQs.set('tier', t);
    if (tr) newQs.set('trial', tr);
    location.hash = '#/users' + (newQs.toString() ? '?' + newQs.toString() : '');
  });
  document.getElementById('user-search').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('user-search-btn').click();
  });
  document.querySelectorAll('button[data-action="detail"]').forEach(btn => {
    btn.addEventListener('click', () => showUserDetail(parseInt(btn.dataset.id, 10)));
  });
};

async function showUserDetail(userId) {
  const user = await api(`/admin/users/${userId}`);
  const bodyHtml = `
    <div class="status-row"><span class="status-label">ID</span><span class="status-value">${user.id}</span></div>
    <div class="status-row"><span class="status-label">이메일</span><span class="status-value">${user.email || '—'}</span></div>
    <div class="status-row"><span class="status-label">회사</span><span class="status-value">${user.company_name || '—'}</span></div>
    <div class="status-row"><span class="status-label">현재 Tier</span><span class="status-value">${user.effective_tier.toUpperCase()}${user.is_trial_active ? ' (Trial)' : ''}</span></div>
    <div class="status-row"><span class="status-label">포인트</span><span class="status-value">${fmtNumber(user.points)}</span></div>
    <div class="status-row"><span class="status-label">총 결제</span><span class="status-value">${fmtKRW(user.total_paid)}</span></div>
    <div class="status-row"><span class="status-label">총 환불</span><span class="status-value">${fmtKRW(user.total_refunded)}</span></div>
    <div class="status-row"><span class="status-label">입찰 횟수</span><span class="status-value">${user.bids_count}</span></div>
    ${user.trial_expires_at ? `<div class="status-row"><span class="status-label">Trial 만료</span><span class="status-value">${fmtDateTime(user.trial_expires_at)}</span></div>` : ''}
    ${user.subscription_expires_at ? `<div class="status-row"><span class="status-label">구독 만료</span><span class="status-value">${fmtDateTime(user.subscription_expires_at)}</span></div>` : ''}
    <div style="margin-top:14px;display:flex;flex-wrap:wrap;gap:6px;">
      <button class="btn btn-outline" id="act-tier" style="padding:6px 12px;font-size:12px;">Tier 변경</button>
      <button class="btn btn-outline" id="act-extend" style="padding:6px 12px;font-size:12px;">Trial 연장</button>
      <button class="btn btn-outline" id="act-expire" style="padding:6px 12px;font-size:12px;">Trial 만료</button>
      <button class="btn btn-outline" id="act-points" style="padding:6px 12px;font-size:12px;">포인트 지급</button>
      <button class="btn btn-danger" id="act-delete" style="padding:6px 12px;font-size:12px;">삭제</button>
    </div>
    ${user.recent_payments.length ? `
      <h4 style="margin-top:18px;margin-bottom:8px;font-size:13px;color:var(--color-text-sub);">최근 결제 (${user.recent_payments.length})</h4>
      ${user.recent_payments.map(p => `
        <div style="font-size:12px;padding:6px 0;border-top:1px solid var(--color-border-light);">
          <div style="font-family:monospace;color:var(--color-text-muted);">${p.order_id}</div>
          <div style="display:flex;justify-content:space-between;">
            <span>${fmtKRW(p.amount)} · ${p.status}</span>
            <span style="color:var(--color-text-muted);">${fmtDateShort(p.confirmed_at || p.created_at)}</span>
          </div>
        </div>
      `).join('')}
    ` : ''}
  `;
  openModal(`사용자 ${user.id} 상세`, bodyHtml, () => true, '닫기', 'btn-ghost');

  // 버튼 이벤트
  setTimeout(() => {
    const $ = id => document.getElementById(id);
    $('act-tier')?.addEventListener('click', () => showTierChangeModal(user));
    $('act-extend')?.addEventListener('click', () => showExtendTrialModal(user));
    $('act-expire')?.addEventListener('click', () => showExpireTrialModal(user));
    $('act-points')?.addEventListener('click', () => showGrantPointsModal(user));
    $('act-delete')?.addEventListener('click', () => showDeleteUserModal(user));
  }, 50);
}

function showTierChangeModal(user) {
  openModal('Tier 변경', `
    <div class="status-row"><span class="status-label">대상</span><span class="status-value">${user.email || user.id}</span></div>
    <label style="display:block;margin-top:10px;font-size:13px;font-weight:600;">새 Tier</label>
    <select id="new-tier" style="width:100%;padding:10px;margin-top:6px;border:1px solid var(--color-border);border-radius:8px;font-family:inherit;">
      <option value="free" ${user.tier==='free'?'selected':''}>Free</option>
      <option value="pro" ${user.tier==='pro'?'selected':''}>Pro</option>
      <option value="pro_plus" ${user.tier==='pro_plus'?'selected':''}>Pro+</option>
    </select>
    <label style="display:block;margin-top:10px;font-size:13px;font-weight:600;">만료일 (비우면 무기한)</label>
    <input id="new-expires" type="datetime-local" style="width:100%;padding:10px;margin-top:6px;border:1px solid var(--color-border);border-radius:8px;font-family:inherit;">
    <label style="display:block;margin-top:10px;font-size:13px;font-weight:600;">사유</label>
    <input id="tier-reason" type="text" placeholder="예: VIP 부여" style="width:100%;padding:10px;margin-top:6px;border:1px solid var(--color-border);border-radius:8px;font-family:inherit;">
  `, async () => {
    const tier = document.getElementById('new-tier').value;
    const expRaw = document.getElementById('new-expires').value;
    const reason = document.getElementById('tier-reason').value;
    const body = { tier, reason };
    if (expRaw) body.expires_at = new Date(expRaw).toISOString();
    try {
      await api(`/admin/users/${user.id}/tier`, { method: 'PATCH', body: JSON.stringify(body) });
      toast('Tier 변경 완료', 'success');
      renderRoute();
    } catch (e) { toast(e.message, 'error'); return false; }
  }, '저장');
}

function showExtendTrialModal(user) {
  openModal('Trial 연장', `
    <div class="status-row"><span class="status-label">대상</span><span class="status-value">${user.email || user.id}</span></div>
    <label style="display:block;margin-top:10px;font-size:13px;font-weight:600;">연장 일수</label>
    <input id="ext-days" type="number" value="14" min="1" max="365" style="width:100%;padding:10px;margin-top:6px;border:1px solid var(--color-border);border-radius:8px;font-family:inherit;">
  `, async () => {
    const days = parseInt(document.getElementById('ext-days').value, 10);
    try {
      await api(`/admin/users/${user.id}/extend-trial`, { method: 'POST', body: JSON.stringify({ days }) });
      toast('Trial 연장 완료', 'success');
      renderRoute();
    } catch (e) { toast(e.message, 'error'); return false; }
  }, '연장');
}

function showExpireTrialModal(user) {
  openModal('Trial 즉시 만료', `
    이 사용자의 Trial 을 지금 즉시 만료시킵니다. 진행할까요?
    <div style="margin-top:8px;font-size:12px;color:var(--color-text-muted);">대상: ${user.email || user.id}</div>
  `, async () => {
    try {
      await api(`/admin/users/${user.id}/expire-trial`, { method: 'POST' });
      toast('Trial 만료 완료', 'success');
      renderRoute();
    } catch (e) { toast(e.message, 'error'); return false; }
  }, '만료시키기', 'btn-danger');
}

function showGrantPointsModal(user) {
  openModal('포인트 지급', `
    <div class="status-row"><span class="status-label">대상</span><span class="status-value">${user.email || user.id}</span></div>
    <label style="display:block;margin-top:10px;font-size:13px;font-weight:600;">지급 포인트</label>
    <input id="pt-amount" type="number" value="1000" min="1" style="width:100%;padding:10px;margin-top:6px;border:1px solid var(--color-border);border-radius:8px;font-family:inherit;">
    <label style="display:block;margin-top:10px;font-size:13px;font-weight:600;">사유</label>
    <input id="pt-reason" type="text" placeholder="예: 사과 보상" style="width:100%;padding:10px;margin-top:6px;border:1px solid var(--color-border);border-radius:8px;font-family:inherit;">
  `, async () => {
    const amount = parseInt(document.getElementById('pt-amount').value, 10);
    const reason = document.getElementById('pt-reason').value;
    if (!reason) { toast('사유를 입력해주세요', 'error'); return false; }
    try {
      await api(`/admin/users/${user.id}/grant-points`, { method: 'POST', body: JSON.stringify({ amount, reason }) });
      toast('지급 완료', 'success');
      renderRoute();
    } catch (e) { toast(e.message, 'error'); return false; }
  }, '지급');
}

function showDeleteUserModal(user) {
  openModal('사용자 삭제', `
    <div style="color:var(--color-danger);font-weight:600;margin-bottom:8px;">⚠️ 이 작업은 되돌릴 수 없어요</div>
    <div class="status-row"><span class="status-label">대상</span><span class="status-value">${user.email || user.id}</span></div>
    <div style="margin-top:10px;font-size:13px;color:var(--color-text-sub);">
      Notification·DeviceToken·UserBid·PointTransaction 은 함께 삭제됩니다.<br>
      PaymentOrder 는 user_id=NULL 로 보존 (회계 기록).
    </div>
    <label style="display:flex;align-items:center;gap:6px;margin-top:14px;font-size:13px;">
      <input id="force-delete" type="checkbox"> 활성 구독 있어도 강제 삭제
    </label>
  `, async () => {
    const force = document.getElementById('force-delete').checked;
    try {
      const r = await api(`/admin/users/${user.id}${force ? '?force=true' : ''}`, { method: 'DELETE' });
      toast(`삭제 완료 (포인트 거래 ${r.deleted.point_transactions}건 등)`, 'success');
      location.hash = '#/users';
    } catch (e) { toast(e.message, 'error'); return false; }
  }, '삭제', 'btn-danger');
}

// ─── 결제 페이지 (Phase C) ────────────────────────────────

pages.payments = async function(content) {
  const params = new URLSearchParams((location.hash.split('?')[1] || ''));
  const page = parseInt(params.get('page') || '1', 10);
  const search = params.get('search') || '';
  const status = params.get('status') || '';

  const qs = new URLSearchParams({ page, size: 20 });
  if (search) qs.set('search', search);
  if (status) qs.set('status', status);

  const data = await api('/admin/payments?' + qs.toString());

  content.innerHTML = `
    <div class="card" style="margin-bottom:16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
      <input id="pay-search" type="text" value="${search}" placeholder="주문ID·결제키" style="flex:1;min-width:200px;padding:10px 14px;border:1px solid var(--color-border);border-radius:10px;font-family:inherit;font-size:14px;">
      <select id="pay-status" style="padding:10px 14px;border:1px solid var(--color-border);border-radius:10px;font-family:inherit;font-size:14px;">
        <option value="">전체 상태</option>
        <option value="CONFIRMED" ${status==='CONFIRMED'?'selected':''}>완료</option>
        <option value="PENDING" ${status==='PENDING'?'selected':''}>대기</option>
        <option value="FAILED" ${status==='FAILED'?'selected':''}>실패</option>
      </select>
      <button id="pay-search-btn" class="btn btn-primary">검색</button>
      <button id="cleanup-pending" class="btn btn-outline">24h+ PENDING 정리</button>
    </div>

    <div class="card" style="padding:0;overflow:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <thead>
          <tr style="background:var(--color-bg);">
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">주문ID</th>
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">유형</th>
            <th style="text-align:right;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">금액</th>
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">상태</th>
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">사용자</th>
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">결제일</th>
            <th style="text-align:left;padding:12px;font-size:12px;color:var(--color-text-muted);text-transform:uppercase;">작업</th>
          </tr>
        </thead>
        <tbody>
          ${data.items.map(p => `
            <tr style="border-top:1px solid var(--color-border-light);">
              <td style="padding:12px;font-family:monospace;font-size:12px;">${p.order_id}</td>
              <td style="padding:12px;color:var(--color-text-sub);font-size:12px;">${p.order_kind === 'subscription' ? '구독' : '포인트'}</td>
              <td style="padding:12px;text-align:right;font-weight:600;">
                ${fmtKRW(p.amount)}
                ${p.refund_amount ? `<div style="font-size:11px;color:var(--color-danger);">환불 -${fmtKRW(p.refund_amount)}</div>` : ''}
              </td>
              <td style="padding:12px;">
                <span style="background:${p.status==='CONFIRMED' ? 'var(--color-success-bg)' : p.status==='PENDING' ? 'var(--color-warning-bg)' : 'var(--color-danger-bg)'};color:${p.status==='CONFIRMED' ? 'var(--color-success)' : p.status==='PENDING' ? 'var(--color-warning)' : 'var(--color-danger)'};padding:3px 9px;border-radius:6px;font-size:12px;font-weight:600;">
                  ${p.status}
                </span>
              </td>
              <td style="padding:12px;font-size:12px;color:var(--color-text-muted);">${p.user_id ?? '(삭제됨)'}</td>
              <td style="padding:12px;font-size:12px;color:var(--color-text-muted);">${fmtDateShort(p.confirmed_at || p.created_at)}</td>
              <td style="padding:12px;">
                <button class="btn btn-ghost" data-action="payment-detail" data-id="${p.order_id}" style="padding:6px 10px;font-size:12px;">상세</button>
                ${p.status === 'CONFIRMED' && !p.refunded_at ? `<button class="btn btn-danger" data-action="refund" data-id="${p.order_id}" style="padding:6px 10px;font-size:12px;">환불</button>` : ''}
                ${p.status === 'PENDING' ? `<button class="btn btn-outline" data-action="cancel-pending" data-id="${p.order_id}" style="padding:6px 10px;font-size:12px;">취소</button>` : ''}
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      ${data.items.length === 0 ? '<div style="padding:40px;text-align:center;color:var(--color-text-muted);">검색 결과 없음</div>' : ''}
    </div>

    ${renderPagination(data, '#/payments')}
  `;

  document.getElementById('pay-search-btn').addEventListener('click', () => {
    const newQs = new URLSearchParams();
    const s = document.getElementById('pay-search').value.trim();
    const st = document.getElementById('pay-status').value;
    if (s) newQs.set('search', s);
    if (st) newQs.set('status', st);
    location.hash = '#/payments' + (newQs.toString() ? '?' + newQs.toString() : '');
  });
  document.getElementById('cleanup-pending').addEventListener('click', () => {
    if (!confirm('24시간 이상 PENDING 상태인 결제를 모두 FAILED 처리합니다. 진행할까요?')) return;
    api('/admin/payments/cleanup-pending', { method: 'POST', body: JSON.stringify({ hours: 24 }) })
      .then(r => { toast(`${r.cleaned}건 정리 완료`, 'success'); renderRoute(); })
      .catch(e => toast(e.message, 'error'));
  });
  document.querySelectorAll('button[data-action="payment-detail"]').forEach(btn => {
    btn.addEventListener('click', () => showPaymentDetail(btn.dataset.id));
  });
  document.querySelectorAll('button[data-action="refund"]').forEach(btn => {
    btn.addEventListener('click', () => showRefundModal(btn.dataset.id));
  });
  document.querySelectorAll('button[data-action="cancel-pending"]').forEach(btn => {
    btn.addEventListener('click', () => cancelPending(btn.dataset.id));
  });
};

async function cancelPending(orderId) {
  if (!confirm(`주문 ${orderId} 을 취소(FAILED) 처리할까요?\n결제 미완료 상태라 외부 영향 없습니다.`)) return;
  try {
    await api(`/admin/payments/${encodeURIComponent(orderId)}/cancel-pending`, { method: 'POST' });
    toast('PENDING 취소 완료', 'success');
    renderRoute();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function showPaymentDetail(orderId) {
  const p = await api(`/admin/payments/${encodeURIComponent(orderId)}`);
  const bodyHtml = `
    <div class="status-row"><span class="status-label">주문ID</span><span class="status-value" style="font-family:monospace;">${p.order_id}</span></div>
    <div class="status-row"><span class="status-label">유형</span><span class="status-value">${p.order_kind === 'subscription' ? '구독' : '포인트'}</span></div>
    <div class="status-row"><span class="status-label">금액</span><span class="status-value">${fmtKRW(p.amount)}</span></div>
    <div class="status-row"><span class="status-label">상태</span><span class="status-value">${p.status}</span></div>
    <div class="status-row"><span class="status-label">결제 수단</span><span class="status-value">${p.method || '—'}</span></div>
    <div class="status-row"><span class="status-label">사용자</span><span class="status-value">${p.user ? `${p.user.email} (#${p.user.id})` : '(삭제됨)'}</span></div>
    <div class="status-row"><span class="status-label">결제일</span><span class="status-value">${fmtDateTime(p.confirmed_at)}</span></div>
    ${p.refunded_at ? `
      <div class="status-row"><span class="status-label">환불 금액</span><span class="status-value" style="color:var(--color-danger);">${fmtKRW(p.refund_amount)}</span></div>
      <div class="status-row"><span class="status-label">환불 사유</span><span class="status-value">${p.refund_reason || '—'}</span></div>
      <div class="status-row"><span class="status-label">환불일</span><span class="status-value">${fmtDateTime(p.refunded_at)}</span></div>
    ` : ''}
    ${p.fail_reason ? `<div class="status-row"><span class="status-label">실패 사유</span><span class="status-value" style="color:var(--color-danger);">${p.fail_reason}</span></div>` : ''}
  `;
  openModal(`주문 ${p.order_id}`, bodyHtml, () => true, '닫기', 'btn-ghost');
}

function showRefundModal(orderId) {
  openModal('결제 환불', `
    <div class="status-row"><span class="status-label">주문</span><span class="status-value" style="font-family:monospace;">${orderId}</span></div>
    <label style="display:block;margin-top:10px;font-size:13px;font-weight:600;">환불 금액 (비우면 전액)</label>
    <input id="refund-amount" type="number" min="1" placeholder="원" style="width:100%;padding:10px;margin-top:6px;border:1px solid var(--color-border);border-radius:8px;font-family:inherit;">
    <label style="display:block;margin-top:10px;font-size:13px;font-weight:600;">환불 사유 (필수)</label>
    <input id="refund-reason" type="text" placeholder="예: 고객 단순 변심" style="width:100%;padding:10px;margin-top:6px;border:1px solid var(--color-border);border-radius:8px;font-family:inherit;">
    <label style="display:flex;align-items:center;gap:6px;margin-top:12px;font-size:13px;">
      <input id="revoke-tier" type="checkbox"> 사용자 tier=free 회수 (전액 환불 시)
    </label>
  `, async () => {
    const amountRaw = document.getElementById('refund-amount').value;
    const reason = document.getElementById('refund-reason').value.trim();
    const revoke_tier = document.getElementById('revoke-tier').checked;
    if (!reason) { toast('환불 사유 입력', 'error'); return false; }
    const body = { reason, revoke_tier };
    if (amountRaw) body.amount = parseInt(amountRaw, 10);
    try {
      const r = await api(`/admin/payments/${encodeURIComponent(orderId)}/refund`, { method: 'POST', body: JSON.stringify(body) });
      toast(`환불 완료 (${fmtKRW(r.refund_amount)})`, 'success');
      renderRoute();
    } catch (e) { toast(e.message, 'error'); return false; }
  }, '환불 실행', 'btn-danger');
}

// ─── 페이지네이션 공통 ────────────────────────────────────

function renderPagination(data, baseHash) {
  if (data.total_pages <= 1) return '';
  const params = new URLSearchParams((location.hash.split('?')[1] || ''));
  const cur = data.page;
  const total = data.total_pages;
  const links = [];
  const makeLink = (p, label) => {
    const newParams = new URLSearchParams(params);
    newParams.set('page', String(p));
    const active = p === cur ? 'style="background:var(--color-primary);color:#fff;border-color:var(--color-primary);"' : '';
    return `<a href="${baseHash}?${newParams.toString()}" class="btn btn-outline" ${active} style="padding:6px 12px;font-size:12px;${p===cur?'background:var(--color-primary);color:#fff;border-color:var(--color-primary);':''}">${label}</a>`;
  };
  if (cur > 1) links.push(makeLink(cur - 1, '이전'));
  const start = Math.max(1, cur - 3);
  const end = Math.min(total, cur + 3);
  for (let p = start; p <= end; p++) links.push(makeLink(p, String(p)));
  if (cur < total) links.push(makeLink(cur + 1, '다음'));
  return `<div style="display:flex;gap:6px;justify-content:center;flex-wrap:wrap;margin-top:14px;">
    ${links.join('')}
    <span style="margin-left:8px;color:var(--color-text-muted);font-size:12px;line-height:32px;">총 ${fmtNumber(data.total)}건</span>
  </div>`;
}

// ─── 공통: Celery 작업 폴링 ───────────────────────────────
async function pollTask(taskId, onState, maxMs = 180000) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    let s;
    try { s = await api('/admin/system/tasks/' + encodeURIComponent(taskId)); } catch { return null; }
    if (onState) onState(s);
    if (s.state === 'SUCCESS' || s.state === 'FAILURE') return s;
    await new Promise(r => setTimeout(r, 2500));
  }
  return null;
}
function metricChips(m) {
  if (!m) return '<span style="color:var(--color-text-muted);">지표 없음</span>';
  const item = (k, v, suf) => `<span style="display:inline-block;margin-right:14px;"><b>${k}</b> ${v == null ? '—' : v}${suf || ''}</span>`;
  return item('낙찰률', m.win_rate, '%') + item('통과율', m.pass_rate, '%') + item('탈락률', m.dropout_rate, '%') + (m.rate_error != null ? item('사정률오차', m.rate_error, '%p') : '');
}

// ─── 자가보정 (Phase D) ───────────────────────────────────
pages.autocalibrate = async function(content) {
  content.innerHTML = '<div class="card">불러오는 중...</div>';
  let status = {}, versions = { items: [] };
  try { status = await api('/admin/stats/autocalibrate-status'); } catch {}
  try { versions = await api('/admin/autocalibrate/versions'); } catch {}
  const a = status.active;
  const histRows = (status.recent_history || []).map(h =>
    `<tr><td>${fmtDateTime(h.at)}</td><td><span class="badge">${h.event}</span></td><td style="font-family:monospace;font-size:12px;">${h.version_id || '—'}</td></tr>`).join('');
  const verRows = (versions.items || []).map(v =>
    `<tr><td style="font-family:monospace;font-size:12px;">${v.version_id}</td><td>${fmtDateTime(v.created_at)}</td><td>${v.status}</td><td>${metricChips(v.metrics)}</td>
      <td><button class="ac-rollback" data-v="${v.version_id}" style="font-size:12px;padding:5px 10px;border:1px solid var(--color-border,#E5E8EB);border-radius:8px;background:#fff;cursor:pointer;">롤백</button></td></tr>`).join('');
  content.innerHTML = `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
        <h3>현재 전략 ${a ? '<span style="font-family:monospace;font-size:13px;">' + a.version_id + '</span>' : '(없음)'}</h3>
        <button id="ac-run" style="background:#3182F6;color:#fff;border:none;border-radius:10px;padding:10px 18px;font-weight:700;cursor:pointer;">재보정 실행</button>
      </div>
      <p style="margin-top:8px;">${a ? metricChips(a.metrics) : '활성 전략 정보가 없어요.'}</p>
      <p style="color:var(--color-text-muted);font-size:13px;margin-top:6px;">다음 자동 실행: ${fmtDateTime(status.next_scheduled)}</p>
      <div id="ac-run-out" style="margin-top:10px;font-size:13px;"></div>
    </div>
    <div class="card"><h3>버전 이력</h3><table style="width:100%;font-size:13px;"><tbody>${verRows || '<tr><td>버전 없음</td></tr>'}</tbody></table></div>
    <div class="card"><h3>변경 로그</h3><table style="width:100%;font-size:13px;"><tbody>${histRows || '<tr><td>이력 없음</td></tr>'}</tbody></table></div>`;

  document.getElementById('ac-run').addEventListener('click', async (e) => {
    e.target.disabled = true; e.target.textContent = '실행 중...';
    const out = document.getElementById('ac-run-out');
    try {
      const r = await api('/admin/autocalibrate/run', { method: 'POST' });
      out.textContent = '작업 시작 (' + r.task_id.slice(0, 8) + ')... 수십 초 소요됩니다.';
      const fin = await pollTask(r.task_id, s => { out.textContent = '상태: ' + s.state; });
      if (fin && fin.state === 'SUCCESS') { toast('자가보정 완료', 'success'); pages.autocalibrate(content); }
      else { out.textContent = '결과: ' + (fin ? (fin.error || fin.state) : '시간 초과'); toast('완료 또는 시간초과', 'info'); }
    } catch { toast('실행 실패', 'error'); e.target.disabled = false; e.target.textContent = '재보정 실행'; }
  });
  content.querySelectorAll('.ac-rollback').forEach(b => b.addEventListener('click', async () => {
    if (!confirm(b.dataset.v + ' 버전으로 롤백할까요?')) return;
    try { await api('/admin/autocalibrate/rollback/' + encodeURIComponent(b.dataset.v), { method: 'POST' }); toast('롤백 완료', 'success'); pages.autocalibrate(content); }
    catch { toast('롤백 실패', 'error'); }
  }));
};

// ─── 시스템 (Phase D) ─────────────────────────────────────
pages.system = async function(content) {
  content.innerHTML = '<div class="card">불러오는 중...</div>';
  let triggers = { tasks: [] };
  try { triggers = await api('/admin/system/triggers'); } catch {}
  const rows = (triggers.tasks || []).map(t =>
    `<tr><td>${t.desc}</td><td style="font-family:monospace;font-size:12px;color:var(--color-text-muted);">${t.name}</td>
      <td><button class="sys-run" data-name="${t.name}" style="font-size:12px;padding:6px 12px;border:none;border-radius:8px;background:#3182F6;color:#fff;cursor:pointer;">실행</button></td>
      <td class="sys-out" data-out="${t.name}" style="font-size:12px;color:var(--color-text-muted);"></td></tr>`).join('');
  content.innerHTML = `<div class="card"><h3>수동 작업 실행</h3>
    <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:12px;">Celery 작업을 즉시 트리거합니다 (정기 스케줄과 별개).</p>
    <table style="width:100%;font-size:13px;"><tbody>${rows || '<tr><td>작업 없음</td></tr>'}</tbody></table></div>`;
  content.querySelectorAll('.sys-run').forEach(b => b.addEventListener('click', async () => {
    const name = b.dataset.name; const out = content.querySelector('.sys-out[data-out="' + name + '"]');
    b.disabled = true; out.textContent = '시작...';
    try {
      const r = await api('/admin/system/tasks/' + encodeURIComponent(name) + '/trigger', { method: 'POST' });
      const fin = await pollTask(r.task_id, s => { out.textContent = s.state; });
      if (fin && fin.state === 'SUCCESS') out.textContent = '✓ ' + (JSON.stringify(fin.result) || '완료').slice(0, 60);
      else out.textContent = '✗ ' + (fin ? (fin.error || fin.state) : '시간초과');
    } catch { out.textContent = '실패'; } finally { b.disabled = false; }
  }));
};

// ─── 시뮬레이션 (Phase E) ─────────────────────────────────
pages.simulation = async function(content) {
  content.innerHTML = '<div class="card">불러오는 중...</div>';
  let ds = { by_year: {}, methods: [], total: 0 };
  try { ds = await api('/admin/simulation/datasets'); } catch {}
  const yearOpts = Object.keys(ds.by_year || {});
  const methodOpts = ds.methods || [];
  content.innerHTML = `
    <div class="card">
      <h3>모의 투찰 백테스트</h3>
      <p style="color:var(--color-text-muted);font-size:13px;">과거 개찰결과 ${fmtNumber(ds.total)}건에 현재 전략을 적용해 낙찰률·탈락률을 측정합니다.</p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;align-items:center;">
        <label style="font-size:13px;">연도 <input id="sim-yf" type="number" placeholder="from" style="width:90px;padding:7px;border:1px solid #E5E8EB;border-radius:8px;"> ~ <input id="sim-yt" type="number" placeholder="to" style="width:90px;padding:7px;border:1px solid #E5E8EB;border-radius:8px;"></label>
        <select id="sim-method" style="padding:7px;border:1px solid #E5E8EB;border-radius:8px;"><option value="">전체 입찰방법</option>${methodOpts.map(m => '<option>' + m + '</option>').join('')}</select>
        <button id="sim-run" style="background:#3182F6;color:#fff;border:none;border-radius:10px;padding:9px 18px;font-weight:700;cursor:pointer;">백테스트 실행</button>
        <button id="sim-whatif" style="background:#fff;color:#3182F6;border:1px solid #C6DCFF;border-radius:10px;padding:9px 18px;font-weight:700;cursor:pointer;">여유분 민감도</button>
      </div>
      <div style="font-size:12px;color:var(--color-text-muted);margin-top:8px;">데이터: ${yearOpts.length ? yearOpts.join(', ') + '년' : '없음'}</div>
    </div>
    <div id="sim-result"></div>`;

  function params() {
    const b = {};
    if ($('sim-yf').value) b.year_from = Number($('sim-yf').value);
    if ($('sim-yt').value) b.year_to = Number($('sim-yt').value);
    if ($('sim-method').value) b.bid_method = $('sim-method').value;
    return b;
  }
  function $(id) { return document.getElementById(id); }

  $('sim-run').addEventListener('click', async () => {
    const r = $('sim-result'); r.innerHTML = '<div class="card">백테스트 중...</div>';
    try {
      const d = await api('/admin/simulation/backtest', { method: 'POST', body: JSON.stringify(params()) });
      const m = d.metrics || {};
      const brRows = (d.by_bracket || []).map(x => `<tr><td>${x.bracket}</td><td>${fmtNumber(x.total)}</td><td>${x.win_rate}%</td><td>${x.pass_rate}%</td><td>${x.dropout_rate}%</td></tr>`).join('');
      r.innerHTML = `<div class="card"><h3>결과 (표본 ${fmtNumber(d.sample)}건)</h3><p style="margin:8px 0;">${metricChips(m)}</p>
        <table style="width:100%;font-size:13px;margin-top:10px;"><thead><tr><th style="text-align:left;">가격대</th><th style="text-align:left;">건수</th><th style="text-align:left;">낙찰률</th><th style="text-align:left;">통과율</th><th style="text-align:left;">탈락률</th></tr></thead><tbody>${brRows}</tbody></table></div>`;
    } catch (e) { r.innerHTML = '<div class="card">오류: ' + e.message + '</div>'; }
  });
  $('sim-whatif').addEventListener('click', async () => {
    const r = $('sim-result'); r.innerHTML = '<div class="card">민감도 분석 중...</div>';
    try {
      const d = await api('/admin/simulation/whatif', { method: 'POST', body: JSON.stringify(params()) });
      const rows = (d.results || []).map(x => `<tr><td>${x.margin_delta > 0 ? '+' : ''}${x.margin_delta}%p</td><td>${x.win_rate}%</td><td>${x.pass_rate}%</td><td>${x.dropout_rate}%</td></tr>`).join('');
      r.innerHTML = `<div class="card"><h3>여유분 민감도 (margin ±)</h3><p style="color:var(--color-text-muted);font-size:13px;">여유분을 늘리면 통과율↑·낙찰률↓ 트레이드오프를 봅니다.</p>
        <table style="width:100%;font-size:13px;margin-top:10px;"><thead><tr><th style="text-align:left;">여유분 가산</th><th style="text-align:left;">낙찰률</th><th style="text-align:left;">통과율</th><th style="text-align:left;">탈락률</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    } catch (e) { r.innerHTML = '<div class="card">오류: ' + e.message + '</div>'; }
  });

  // ── 5-arm 비교 (모의투찰과 같은 arm 구성으로 과거를 재평가) ──
  // 모의투찰은 표본이 쌓이는 데 시간이 걸린다. 같은 arm 을 과거에 적용해
  // 지금 당장 방향을 본다. 판정은 mock_bidding.judge 재사용이라 두 화면의
  // 정의가 갈라지지 않는다.
  const armBox = document.createElement('div');
  content.appendChild(armBox);
  armBox.innerHTML = '<div class="card">5-arm 비교 불러오는 중...</div>';

  try {
    const d = await api('/admin/simulation/arms');
    if (!d.available) {
      armBox.innerHTML = '<div class="card">5-arm 비교: ' + (d.reason || '데이터 없음') + '</div>';
    } else {
      renderArms(armBox, d);
    }
  } catch (e) {
    armBox.innerHTML = '<div class="card">5-arm 비교 오류: ' + e.message + '</div>';
  }
};

const ARM_LABEL_BT = {
  standard: 'standard', active: 'active',
  frontier_c5: 'frontier_c5', frontier_c10: 'frontier_c10', aggressive: 'aggressive',
};
const ARM_SEQ = ['standard', 'active', 'frontier_c5', 'frontier_c10', 'aggressive'];
// arm_backtest.MIN_METHOD_N 과 같은 값 — 방법별 표의 최소 표본
const MIN_METHOD_N_LABEL = 30;

function renderArms(box, d) {
  const names = ARM_SEQ.filter((a) => d.arms[a]);
  const cell = (m) => m
    ? `<td class="${m.dropout_rate > 10 ? '' : ''}" style="font-weight:700;color:${m.dropout_rate > 10 ? '#FF3B30' : 'inherit'};">${m.dropout_rate.toFixed(2)}%</td>
       <td>${m.win_rate.toFixed(2)}%<br><span style="font-size:11px;color:#8B95A1;font-weight:400;">${m.win_ci95[0].toFixed(1)}~${m.win_ci95[1].toFixed(1)}</span></td>`
    : '<td>—</td><td>—</td>';

  const rows = names.map((a) => {
    const e = d.arms[a];
    return `<tr${a === 'active' ? ' style="background:#E8F1FE;"' : ''}>
      <td style="text-align:left;"><b>${ARM_LABEL_BT[a]}</b><br>
        <span style="font-size:11px;color:#8B95A1;">${esc(e.desc || '')}</span></td>
      ${cell(e.overall)}${cell(e.holdout)}${cell(e.qualification_holdout)}
    </tr>`;
  }).join('');

  const sz = d.slice_sizes || {};
  const msz = d.method_sizes || {};
  const mNames = Object.keys(msz);

  // 방법별 표 — "전체" 한 칸이 낙찰하한 체계가 다른 방법들을 뭉갠다는 걸 드러낸다
  const methodRows = mNames.length ? names.map((a) => {
    const bm = d.arms[a].by_method || {};
    return `<tr${a === 'active' ? ' style="background:#E8F1FE;"' : ''}>
      <td style="text-align:left;"><b>${ARM_LABEL_BT[a]}</b></td>
      ${mNames.map((m) => {
        const t = bm[m];
        return t
          ? `<td style="font-weight:700;color:${t.dropout_rate > 10 ? '#FF3B30' : 'inherit'};">${t.dropout_rate.toFixed(2)}%</td>`
          : '<td>—</td>';
      }).join('')}
    </tr>`;
  }).join('') : '';

  const excluded = d.n_excluded_base_mismatch || 0;
  const exclBanner = excluded ? `
    <div style="margin-top:10px;font-size:12.5px;color:#7A2E2E;background:#FFF1F0;border:1px solid #FFC9C6;border-radius:10px;padding:10px 12px;">
      🚫 <b>${fmtNumber(excluded)}건 제외</b> — 불러온 ${fmtNumber(d.n_loaded)}건 중 기초금액과 ${gl('예정가격')}의
      기준이 어긋난 행입니다(${gl('사정률')} 0.94~1.06 밖). 개찰 크롤러가 부가세 제외 금액을 저장해 생긴 문제로,
      섞어서 집계하면 무효율이 실제보다 크게 부풀려집니다.
    </div>` : '';

  box.innerHTML = `
    <div class="card">
      <h3>5-arm 비교 — 과거 데이터</h3>
      <p style="color:var(--color-text-muted);font-size:13px;">
        모의투찰과 <b>같은 5개 ${gl('arm')}</b>을 과거 개찰 ${fmtNumber(d.n_records)}건에 적용한 결과입니다.
        1차 지표는 ${gl('무효율')}이며, ${gl('적중률')}은 내부 참고용입니다.
      </p>
      ${exclBanner}
      ${(d.caveats || []).map((c) => `<div style="margin-top:10px;font-size:12.5px;color:#4E5968;background:#FFF7E6;border:1px solid #FFE0A3;border-radius:10px;padding:10px 12px;">⚠️ ${esc(c)}</div>`).join('')}
      <div style="overflow-x:auto;margin-top:14px;">
        <table style="width:100%;font-size:13px;min-width:680px;text-align:right;">
          <thead>
            <tr><th rowspan="2" style="text-align:left;">arm</th>
              <th colspan="2">전체 (n=${fmtNumber(sz.overall)})</th>
              <th colspan="2">${gl('holdout')} 2025 (n=${fmtNumber(sz.holdout)})</th>
              <th colspan="2">${gl('적격심사제')} holdout (n=${fmtNumber(sz.qualification_holdout)})</th></tr>
            <tr><th>무효율</th><th>적중률 (${gl('신뢰구간', 'CI')})</th>
                <th>무효율</th><th>적중률 (CI)</th>
                <th>무효율</th><th>적중률 (CI)</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <p style="margin-top:10px;font-size:12px;color:#8B95A1;">
        ※ '전체' 열은 낙찰하한 체계가 서로 다른 입찰방법을 한데 모은 값입니다.
        arm 사이의 우열은 아래 방법별 표나 ${gl('적격심사제')} holdout 으로 판단하세요.
      </p>
    </div>

    ${mNames.length ? `
    <div class="card">
      <h3>입찰방법별 무효율 — active 기준선</h3>
      <p style="color:var(--color-text-muted);font-size:13px;">
        방법마다 ${gl('낙찰하한율')} 체계가 달라 같은 arm 이어도 결과가 갈립니다.
        표본 ${MIN_METHOD_N_LABEL}건 이상인 방법만 표시합니다.
      </p>
      <div style="overflow-x:auto;margin-top:12px;">
        <table style="width:100%;font-size:13px;min-width:560px;text-align:right;">
          <thead><tr><th style="text-align:left;">arm</th>
            ${mNames.map((m) => `<th>${esc(m)}<br><span style="font-size:11px;color:#8B95A1;font-weight:400;">n=${fmtNumber(msz[m])}</span></th>`).join('')}
          </tr></thead>
          <tbody>${methodRows}</tbody>
        </table>
      </div>
    </div>` : ''}

    <div class="card">
      <h3>안전 ↔ 적중 트레이드오프</h3>
      <p style="color:var(--color-text-muted);font-size:13px;">
        가로축 ${gl('무효율')}, 세로축 ${gl('적중률')} — <b>왼쪽 위가 좋은 자리</b>입니다.
        점선은 설계상의 ${gl('무효율 캡')}(5% · 10%).
      </p>
      <div class="chart-wrap" style="height:340px;"><canvas id="ch-arm-scatter"></canvas></div>
    </div>

    ${glossaryCard(['무효율', '적중률', '무효', '적중', '밀림', 'arm', 'holdout',
                    '신뢰구간', '무효율 캡', '백테스트', '과적합', '낙찰하한율',
                    '예정가격', '사정률', '적격심사제'])}`;

  // 산점도 — holdout(공정 비교) 기준. active 만 강조, 나머지는 중립.
  const pts = names.map((a) => ({
    x: d.arms[a].holdout ? d.arms[a].holdout.dropout_rate : 0,
    y: d.arms[a].holdout ? d.arms[a].holdout.win_rate : 0,
    label: a,
  }));
  new Chart(document.getElementById('ch-arm-scatter'), {
    type: 'scatter',
    data: {
      datasets: [{
        data: pts,
        pointRadius: pts.map((p) => (p.label === 'active' ? 9 : 6)),
        pointHoverRadius: 12,
        backgroundColor: pts.map((p) =>
          p.label === 'active' ? '#3182F6' : (p.x > 10 ? '#FF3B30' : '#8B95A1')),
        borderColor: '#fff', borderWidth: 2,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (c) => `${c.raw.label} — 무효 ${c.raw.x.toFixed(2)}% / 적중 ${c.raw.y.toFixed(2)}%`,
          },
        },
      },
      scales: {
        x: { title: { display: true, text: '무효율 % (낮을수록 좋음)' }, beginAtZero: true },
        y: { title: { display: true, text: '적중률 %' }, beginAtZero: true },
      },
    },
    plugins: [{
      // 캡 기준선 + 점 라벨 — 색 단독으로 식별하지 않게 이름을 직접 붙인다.
      id: 'armAnno',
      afterDatasetsDraw(chart) {
        const { ctx, scales: { x, y } } = chart;
        ctx.save();
        [5, 10].forEach((v) => {
          if (v < x.min || v > x.max) return;
          const px = x.getPixelForValue(v);
          ctx.strokeStyle = '#C6CDD5'; ctx.setLineDash([3, 4]); ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(px, y.top); ctx.lineTo(px, y.bottom); ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = '#8B95A1'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
          ctx.fillText('캡 ' + v + '%', px, y.top - 4);
        });
        const meta = chart.getDatasetMeta(0);
        ctx.textAlign = 'left'; ctx.font = '700 12px sans-serif';
        meta.data.forEach((pt, i) => {
          const p = chart.data.datasets[0].data[i];
          ctx.fillStyle = p.label === 'active' ? '#1B64DA' : '#191F28';
          ctx.fillText(p.label, pt.x + 12, pt.y + 4);
        });
        ctx.restore();
      },
    }],
  });
}

// ─── 용어집 ──────────────────────────────────────────────────
// 정본: docs/GLOSSARY_BIDDING.md — 문구를 고칠 때 그 문서도 함께 고친다.
// 공공입찰 도메인은 "예정가격이 개찰 순간 추첨으로 정해진다"는 전제를 모르면
// 아래 지표가 전부 오해된다. 그래서 지표 옆에 설명을 붙인다.

const GLOSSARY = {
  '기초금액': '발주기관이 공고에 제시하는 기준 금액. 모든 계산의 출발점입니다.',
  '복수예비가격': '기초금액 ±2~3% 범위로 만든 15개 후보 가격. 여기서 4개가 뽑혀 예정가격이 됩니다.',
  '예정가격': '개찰 때 입찰자들이 뽑은 번호로 선택된 4개 예비가격의 평균. 낙찰 판정의 기준이며 개찰 전에는 알 수 없습니다(추첨).',
  '사정률': '예정가격 ÷ 기초금액. 보통 97~103% 사이에서 움직입니다.',
  '투찰률': '우리 투찰가 ÷ 기초금액 (%).',
  '낙찰하한율': '예정가격 대비 최소 투찰 비율. 이 밑으로 쓰면 무효입니다. 공사·금액대·시행일별로 다릅니다(예: 10억 미만 공사 89.745%).',
  '낙찰하한선': '예정가격 × 낙찰하한율. 이 금액 미만으로 투찰하면 입찰이 무효가 됩니다.',
  'A값': '국민연금·건강보험·산재·고용보험 등 법정 고정비 합계. 투찰가 공식에서 사정률을 적용하지 않고 그대로 더합니다. ⚠️ 현재 공고의 99.99%에서 결측이라 0으로 계산 중입니다.',
  '무효': 'DROPOUT — 투찰가가 낙찰하한선 미만이라 입찰 자체가 없던 일이 되는 것. 가장 나쁜 결과입니다.',
  '무효율': '판정된 건 중 무효의 비율. 브랜드 KPI가 유효율이라 이것이 1차 지표입니다 — 낮을수록 좋습니다.',
  '적중': 'WIN — 투찰가가 [낙찰하한선, 실제 낙찰가] 구간에 들어간 것. 하한선을 통과하면서 낙찰자보다 낮았다는 뜻입니다. ⚠️ 1순위 낙찰 보장은 아닙니다.',
  '적중률': '판정된 건 중 적중의 비율. 내부 참고용이며 대외에 «낙찰률»로 표기하는 것은 금지입니다(전역 규칙 §4-2).',
  '밀림': 'LOST — 하한선은 통과했으나 낙찰가보다 높아 더 싼 업체에 밀린 것.',
  'arm': '동시에 시험하는 전략 하나. A/B 테스트의 각 안에 해당하며, 모의투찰은 같은 공고에 5개 arm을 동시 등록합니다.',
  '사전 등록': '결과를 보기 전에 가격·지표·판정 기준을 확정해 잠그는 것. 사후에 유리하게 고치는 것(체리피킹)을 구조적으로 막습니다.',
  '백테스트': '과거 데이터에 전략을 적용해 사후 재구성하는 것. 빠르지만 파라미터가 바뀌면 과거 수치도 함께 변합니다 — 참고용이지 증거가 아닙니다.',
  'holdout': '파라미터 학습에 쓰지 않고 남겨둔 검증용 데이터. 과적합 여부를 봅니다.',
  '과적합': '학습 데이터에만 잘 맞고 새 데이터에서는 무너지는 현상.',
  '신뢰구간': 'Wilson 95% 신뢰구간 — 비율의 불확실성 범위. 표본이 작으면 넓어지고, 두 arm의 구간이 겹치면 우열을 단정할 수 없습니다.',
  '오라클': '사후에 최적값을 골랐을 때의 상한. 어떤 알고리즘도 넘을 수 없는 천장입니다.',
  '무효율 캡': '최적화할 때 «무효율이 이 값을 넘지 않는다»는 제약. frontier_c5는 캡 5%를 뜻합니다.',
  '적격심사제': '최저가 순으로 이행능력(실적·재무·기술)을 심사해 통과한 첫 업체가 낙찰되는 방식. BidEasy의 비치헤드 시장입니다.',
  '소액수의견적': '소액 공사에서 2인 이상 견적을 받아 결정하는 방식. 건수가 가장 많습니다.',
  '채점 도달률': '등록한 건이 실제로 채점까지 도달한 비율. 개찰결과가 붙어야 채점되므로, 이 값이 낮으면 다른 지표를 해석할 수 없습니다.',
  'G-A': '파이프라인 건전성 게이트 — 채점 도달률 60% 이상. 미달이면 다른 지표를 해석하지 않습니다.',
  'G-B': '전략 우열 게이트 — 적격심사제 400건 누적 후, active가 슬라이더 기본값을 유의하게 상회하는지 판정합니다.',
  'G-C': '제품화 검토 게이트 — frontier_c10이 active를 유의하게 상회하고 무효율 11% 이하일 때 Pro+ 전략투찰 검토에 착수합니다.',
};

/** 용어에 밑줄 + 네이티브 툴팁을 붙인다. 설명이 없으면 그냥 텍스트. */
function gl(term, label) {
  const d = GLOSSARY[term];
  const text = label || term;
  if (!d) return text;
  return '<span title="' + esc(d) + '" style="border-bottom:1px dotted #8B95A1;cursor:help;">'
    + text + '</span>';
}

/** 접이식 용어집 카드 — 페이지 하단에 붙인다. */
function glossaryCard(terms) {
  const rows = terms.filter((t) => GLOSSARY[t]).map((t) =>
    '<tr><td style="white-space:nowrap;font-weight:700;vertical-align:top;">' + t + '</td>'
    + '<td style="text-align:left;color:#4E5968;">' + esc(GLOSSARY[t]) + '</td></tr>').join('');
  return `<div class="card">
    <details>
      <summary style="cursor:pointer;font-weight:700;font-size:15px;">📖 용어 설명 (${terms.length}개)</summary>
      <p style="color:var(--color-text-muted);font-size:13px;margin:10px 0;">
        정본: <code>docs/GLOSSARY_BIDDING.md</code>
      </p>
      <div style="overflow-x:auto;"><table style="width:100%;font-size:13px;">
        <tbody>${rows}</tbody>
      </table></div>
    </details>
  </div>`;
}

/** HTML 속성/본문에 넣을 텍스트 이스케이프 */
function esc(t) {
  return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}


// ─── 모의투찰 (사전 등록·채점) ───────────────────────────────
// 설계·게이트 정본: docs/MOCK_BIDDING_DESIGN.md
// ⚠️ 1차 지표는 무효율(dropout). 낙찰률이 아니다(§0.2) — 표 컬럼 순서도 그에 맞춘다.
//    낙찰률의 대외 표기는 전역 규칙 §4-2 위반이므로 화면에 주의를 명시한다.

const MB_ARM_LABEL = {
  standard: 'standard (슬라이더 기본 −2.5%)',
  active: 'active (현 자가보정)',
  frontier_c5: 'frontier_c5 (무효 캡 5%)',
  frontier_c10: 'frontier_c10 (무효 캡 10%)',
  aggressive: 'aggressive (−12%)',
};
const MB_ARM_ORDER = ['standard', 'active', 'frontier_c5', 'frontier_c10', 'aggressive'];
// arm 색은 화면 전체에서 고정 — 차트끼리 색이 다르면 비교가 안 된다.
const MB_ARM_COLOR = {
  standard: '#8B95A1',
  active: '#3182F6',
  frontier_c5: '#34C759',
  frontier_c10: '#22A06B',
  aggressive: '#FF3B30',
};

function mbPct(v) { return v === null || v === undefined ? '—' : v + '%'; }

pages.mockbidding = async function (content) {
  content.innerHTML = '<div class="card">불러오는 중...</div>';

  let sum, charts;
  try {
    // 차트 집계 실패가 성적표까지 막지 않도록 분리해서 잡는다
    [sum, charts] = await Promise.all([
      api('/admin/mock-bidding/summary'),
      api('/admin/mock-bidding/charts').catch(() => null),
    ]);
  } catch (e) {
    content.innerHTML = '<div class="card">오류: ' + e.message + '</div>';
    return;
  }

  const reach = sum.scoring_reach || {};
  const gate = reach.gate_g_a_threshold || 60;
  const reachPct = reach.reach_pct;
  const gateOk = reachPct !== null && reachPct !== undefined && reachPct >= gate;
  const gateColor = reachPct === null || reachPct === undefined ? '#8B95A1'
    : (gateOk ? '#34C759' : '#FF3B30');

  const arms = sum.arms || {};
  const armRows = MB_ARM_ORDER.filter((a) => arms[a]).map((a) => {
    const m = arms[a];
    return `<tr>
      <td style="white-space:nowrap;">${MB_ARM_LABEL[a] || a}</td>
      <td>${fmtNumber(m.judged)}</td>
      <td style="font-weight:700;color:${m.dropout_rate > 10 ? '#FF3B30' : '#191F28'};">${mbPct(m.dropout_rate)}</td>
      <td>${mbPct(m.win_rate)}</td>
      <td>${fmtNumber(m.win)} / ${fmtNumber(m.lost)} / ${fmtNumber(m.dropout)}</td>
      <td>${m.mean_ratio_error === null || m.mean_ratio_error === undefined ? '—' : m.mean_ratio_error}</td>
      <td>${fmtNumber(m.no_result)}</td>
    </tr>`;
  }).join('');

  const tags = sum.failure_tags || {};
  const tagRows = Object.keys(tags).map((t) => {
    const s = tags[t];
    return `<tr><td>${t}</td><td>${fmtNumber(s.total)}</td><td>${fmtNumber(s.dropout)}</td>
      <td style="font-weight:700;">${mbPct(s.dropout_rate)}</td><td>${fmtNumber(s.win)}</td></tr>`;
  }).join('');

  content.innerHTML = `
    <div class="card">
      <h3>G-A · 파이프라인 건전성</h3>
      <p style="color:var(--color-text-muted);font-size:13px;">
        등록한 건이 실제로 채점까지 도달하는 비율입니다. ${gl('G-A')} 기준 미달이면 다른 지표는 해석하지 않습니다.
      </p>
      <div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:12px;align-items:baseline;">
        <div><div style="font-size:12px;color:#8B95A1;">등록</div>
          <div style="font-size:24px;font-weight:800;">${fmtNumber(reach.registered)}</div></div>
        <div><div style="font-size:12px;color:#8B95A1;">채점 완료</div>
          <div style="font-size:24px;font-weight:800;">${fmtNumber(reach.scored)}</div></div>
        <div><div style="font-size:12px;color:#8B95A1;">도달률 (기준 ${gate}%)</div>
          <div style="font-size:24px;font-weight:800;color:${gateColor};">${mbPct(reachPct)}</div></div>
      </div>
    </div>

    <!-- 시각화 — 순서는 설계 §0.2 지표 우선순위 그대로: 무효율(1차·가장 크게) →
         적중률(2차) → 등수(3차) → 격차 → 사정률 오차(4차) → 오답노트 → 세그먼트 -->
    <div class="card">
      <h3>① arm 별 무효율 — 1차 지표</h3>
      <p style="color:var(--color-text-muted);font-size:13px;">
        무효(DROPOUT)는 입찰 자체가 없던 일이 됩니다. 브랜드 KPI 는 유효율 —
        이 막대가 낮을수록 좋습니다.
      </p>
      <div style="position:relative;height:300px;"><canvas id="mb-ch-dropout"></canvas></div>
    </div>

    <div class="chart-grid-2">
      <div class="card">
        <h3>② arm 별 적중률 (내부 참고)</h3>
        <p style="color:var(--color-text-muted);font-size:13px;">대외 표기 금지(전역 규칙 §4-2).</p>
        <div class="chart-wrap"><canvas id="mb-ch-win"></canvas></div>
      </div>
      <div class="card">
        <h3>③ 등수 분포 — 우리가 몇 등에 몰리는지</h3>
        <p style="color:var(--color-text-muted);font-size:13px;">
          참가자 데이터가 붙은 채점 건만. 등수는 ${gl('무효')} 참가자를 포함한 순위입니다.
        </p>
        <div class="chart-wrap"><canvas id="mb-ch-rank"></canvas></div>
      </div>
    </div>

    <div class="chart-grid-2">
      <div class="card">
        <h3>④ 낙찰가 대비 격차 분포</h3>
        <p style="color:var(--color-text-muted);font-size:13px;">
          (우리가격−낙찰가)/낙찰가. 0~0.5% 구간이 "아깝게 놓친" 건입니다.
        </p>
        <div class="chart-wrap"><canvas id="mb-ch-gap"></canvas></div>
      </div>
      <div class="card">
        <h3>⑤ 사정률 예측 오차 추이 (active)</h3>
        <p style="color:var(--color-text-muted);font-size:13px;">
          개별 승패는 ${gl('예정가격')} 추첨 노이즈가 크지만, ${gl('사정률')} 오차는 모델의 순수 신호입니다.
        </p>
        <div class="chart-wrap"><canvas id="mb-ch-err"></canvas></div>
      </div>
    </div>

    <div class="chart-grid-2">
      <div class="card">
        <h3>⑥ 오답노트 — 태그별 무효율</h3>
        <div class="chart-wrap"><canvas id="mb-ch-tags"></canvas></div>
      </div>
      <div class="card">
        <h3>⑦ 세그먼트 교차표 (입찰방법 × 금액대, active)</h3>
        <p style="color:var(--color-text-muted);font-size:13px;">셀 = 채점 건수 / 무효율.</p>
        <div id="mb-seg" style="overflow-x:auto;">—</div>
      </div>
    </div>

    <div class="card">
      <h3>arm 별 성적표</h3>
      <p style="color:var(--color-text-muted);font-size:13px;">
        <b>1차 지표는 무효율(dropout)</b>입니다 — 무효는 입찰 자체가 없던 일이 됩니다.
        낙찰률은 내부 참고용이며 <b>대외 표기 금지</b>(전역 규칙 §4-2).
      </p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin:12px 0;align-items:center;">
        <select id="mb-method" style="padding:7px;border:1px solid #E5E8EB;border-radius:8px;">
          <option value="">전체 입찰방법</option>
          <option>적격심사제</option>
          <option>소액수의견적</option>
          <option>제한적최저가(낙찰하한율)</option>
          <option>최저가낙찰제</option>
        </select>
        <button id="mb-reload" style="background:#3182F6;color:#fff;border:none;border-radius:10px;padding:9px 18px;font-weight:700;cursor:pointer;">조회</button>
      </div>
      <div style="overflow-x:auto;">
      <table style="width:100%;font-size:13px;min-width:720px;">
        <thead><tr>
          <th style="text-align:left;">arm</th>
          <th style="text-align:left;">채점</th>
          <th style="text-align:left;">무효율 ★</th>
          <th style="text-align:left;">적중률</th>
          <th style="text-align:left;">WIN/LOST/무효</th>
          <th style="text-align:left;">사정률 오차</th>
          <th style="text-align:left;">미개찰</th>
        </tr></thead>
        <tbody>${armRows || '<tr><td colspan="7" style="color:#8B95A1;">아직 채점된 건이 없습니다. 등록 후 개찰이 붙으면 표시됩니다.</td></tr>'}</tbody>
      </table>
      </div>
    </div>

    <div class="card">
      <h3>오답노트 — 태그별 무효율</h3>
      <p style="color:var(--color-text-muted);font-size:13px;">
        실패 건에 붙은 사유 태그. 여기서 나온 사실이 곧 사용자 경고 기능이 됩니다.
      </p>
      <div style="overflow-x:auto;">
      <table style="width:100%;font-size:13px;min-width:520px;">
        <thead><tr><th style="text-align:left;">태그</th><th style="text-align:left;">등장</th>
          <th style="text-align:left;">무효</th><th style="text-align:left;">무효율</th><th style="text-align:left;">WIN</th></tr></thead>
        <tbody>${tagRows || '<tr><td colspan="5" style="color:#8B95A1;">아직 데이터가 없습니다.</td></tr>'}</tbody>
      </table>
      </div>
    </div>

    <div class="card">
      <h3>최근 등록 원장</h3>
      <p style="color:var(--color-text-muted);font-size:13px;">
        등록은 <b>마감 전에만</b> 이뤄지고 이후 수정되지 않습니다(사전 등록). 스냅샷은 등록 시점에 우리가 본 값입니다.
      </p>
      <div id="mb-reg" style="overflow-x:auto;">불러오는 중...</div>
    </div>

    <div class="card">
      <h3>최근 채점 결과</h3>
      <div id="mb-res" style="overflow-x:auto;">불러오는 중...</div>
    </div>`;

  renderMockBiddingCharts(charts);

  document.getElementById('mb-reload').addEventListener('click', async () => {
    const m = document.getElementById('mb-method').value;
    location.hash = '#/mockbidding';
    const c = document.getElementById('page-content');
    c.innerHTML = '<div class="card">조회 중...</div>';
    try {
      const d = await api('/admin/mock-bidding/summary' + (m ? '?bid_method=' + encodeURIComponent(m) : ''));
      // 필터 결과만 간단 표로 다시 그린다(전체 화면 재구성 대신).
      const rows = MB_ARM_ORDER.filter((a) => (d.arms || {})[a]).map((a) => {
        const x = d.arms[a];
        return `<tr><td>${MB_ARM_LABEL[a] || a}</td><td>${fmtNumber(x.judged)}</td>
          <td style="font-weight:700;">${mbPct(x.dropout_rate)}</td><td>${mbPct(x.win_rate)}</td></tr>`;
      }).join('');
      c.innerHTML = `<div class="card"><h3>${m || '전체'} — arm 별 성적</h3>
        <table style="width:100%;font-size:13px;margin-top:10px;">
        <thead><tr><th style="text-align:left;">arm</th><th style="text-align:left;">채점</th>
        <th style="text-align:left;">무효율 ★</th><th style="text-align:left;">적중률</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4" style="color:#8B95A1;">데이터 없음</td></tr>'}</tbody></table>
        <p style="margin-top:12px;"><a href="#/mockbidding" onclick="location.reload()" class="link-muted">← 전체 보기</a></p></div>`;
    } catch (e) {
      c.innerHTML = '<div class="card">오류: ' + e.message + '</div>';
    }
  });

  // 용어집 — 도메인 용어를 모르면 위 지표가 전부 오해된다
  content.insertAdjacentHTML('beforeend', glossaryCard([
    '무효', '무효율', '적중', '적중률', '밀림', '채점 도달률',
    'G-A', 'G-B', 'G-C', 'arm', '사전 등록',
    '기초금액', '복수예비가격', '예정가격', '사정률', '투찰률',
    '낙찰하한율', '낙찰하한선', 'A값', '적격심사제', '소액수의견적',
  ]));

  // 원장·결과는 화면을 막지 않도록 뒤이어 채운다
  api('/admin/mock-bidding/registrations?limit=30').then((d) => {
    const el = document.getElementById('mb-reg');
    if (!el) return;
    if (!d.items || !d.items.length) { el.innerHTML = '<span style="color:#8B95A1;">아직 등록된 건이 없습니다. 매시 15분에 마감 임박 공고가 등록됩니다.</span>'; return; }
    el.innerHTML = `<table style="width:100%;font-size:12px;min-width:820px;">
      <thead><tr><th style="text-align:left;">공고번호</th><th style="text-align:left;">arm</th>
      <th style="text-align:left;">등록가</th><th style="text-align:left;">투찰률</th>
      <th style="text-align:left;">등록시각</th><th style="text-align:left;">마감</th>
      <th style="text-align:left;">하한율(출처)</th><th style="text-align:left;">A값</th>
      <th style="text-align:left;">상태</th></tr></thead><tbody>
      ${d.items.map((x) => `<tr>
        <td>${x.bid_no}</td><td>${x.arm}</td>
        <td>${fmtNumber(x.price)}원</td><td>${x.bid_rate}%</td>
        <td>${(x.registered_at || '').replace('T', ' ').slice(0, 16)}</td>
        <td>${(x.deadline_at || '').replace('T', ' ').slice(0, 16)}</td>
        <td>${x.snapshot.lower_limit_rate}% (${x.snapshot.llr_source})</td>
        <td>${x.snapshot.a_value ? fmtNumber(x.snapshot.a_value) : '<span style="color:#FF3B30;">없음</span>'}</td>
        <td>${x.status}</td></tr>`).join('')}
      </tbody></table>`;
  }).catch(() => {});

  api('/admin/mock-bidding/results?limit=30').then((d) => {
    const el = document.getElementById('mb-res');
    if (!el) return;
    if (!d.items || !d.items.length) { el.innerHTML = '<span style="color:#8B95A1;">아직 채점된 건이 없습니다.</span>'; return; }
    const color = { WIN: '#34C759', DROPOUT: '#FF3B30', LOST: '#8B95A1', NO_RESULT: '#8B95A1' };
    el.innerHTML = `<table style="width:100%;font-size:12px;min-width:820px;">
      <thead><tr><th style="text-align:left;">공고번호</th><th style="text-align:left;">arm</th>
      <th style="text-align:left;">판정</th><th style="text-align:left;">등수/참여</th>
      <th style="text-align:left;">우리가격</th>
      <th style="text-align:left;">낙찰가</th><th style="text-align:left;">하한선</th>
      <th style="text-align:left;">낙찰가 대비</th><th style="text-align:left;">태그</th></tr></thead><tbody>
      ${d.items.map((x) => `<tr>
        <td>${x.bid_no}</td><td>${x.arm}</td>
        <td style="font-weight:700;color:${color[x.outcome] || '#191F28'};">${x.outcome}</td>
        <td>${x.estimated_rank ? x.estimated_rank + '위 / ' + (x.participants_count ?? '?') + '명' : '—'}</td>
        <td>${fmtNumber(x.our_price)}</td>
        <td>${x.actual_winner_price ? fmtNumber(x.actual_winner_price) : '—'}</td>
        <td>${x.actual_lower_limit ? fmtNumber(Math.round(x.actual_lower_limit)) : '—'}</td>
        <td>${x.gap_to_winner_pct === null || x.gap_to_winner_pct === undefined ? '—' : x.gap_to_winner_pct + '%'}</td>
        <td style="color:#8B95A1;">${(x.failure_tags || []).join(', ') || '—'}</td></tr>`).join('')}
      </tbody></table>`;
  }).catch(() => {});
};

// ─── 모의투찰 차트 렌더 — 순서는 §0.2 지표 우선순위, 라이브러리는
//     대시보드와 동일한 Chart.js(admin.html 이 이미 로드) 재사용. CDN 추가 금지.

function mbChartEmpty(canvasId, msg) {
  const cv = document.getElementById(canvasId);
  if (!cv || !cv.parentElement) return;
  cv.parentElement.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#8B95A1;font-size:13px;">' + msg + '</div>';
}

function renderMockBiddingCharts(charts) {
  const noData = '아직 채점 데이터가 없습니다.';
  const allIds = ['mb-ch-dropout', 'mb-ch-win', 'mb-ch-rank', 'mb-ch-gap', 'mb-ch-err', 'mb-ch-tags'];
  if (!charts) {
    allIds.forEach((id) => mbChartEmpty(id, '차트 집계를 불러오지 못했습니다.'));
    return;
  }
  const base = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } };
  const legendBottom = { ...base, plugins: { legend: { display: true, position: 'bottom' } } };

  // ①② arm 별 무효율(1차)·적중률(2차) — 같은 arm 은 항상 같은 색
  const arms = MB_ARM_ORDER.filter((a) => (charts.arms || {})[a] && charts.arms[a].judged > 0);
  if (!arms.length) {
    mbChartEmpty('mb-ch-dropout', noData);
    mbChartEmpty('mb-ch-win', noData);
  } else {
    const colors = arms.map((a) => MB_ARM_COLOR[a] || '#3182F6');
    new Chart(document.getElementById('mb-ch-dropout'), {
      type: 'bar',
      data: { labels: arms, datasets: [{ data: arms.map((a) => charts.arms[a].dropout_rate ?? 0), backgroundColor: colors }] },
      options: { ...base, scales: { y: { beginAtZero: true, ticks: { callback: (v) => v + '%' } } } },
    });
    new Chart(document.getElementById('mb-ch-win'), {
      type: 'bar',
      data: { labels: arms, datasets: [{ data: arms.map((a) => charts.arms[a].win_rate ?? 0), backgroundColor: colors }] },
      options: { ...base, scales: { y: { beginAtZero: true, ticks: { callback: (v) => v + '%' } } } },
    });
  }

  // ③ 등수 분포 히스토그램 (3차 — Phase 2 산출물)
  const rd = charts.rank_distribution || {};
  const rankArms = MB_ARM_ORDER.filter((a) => rd[a]);
  if (!rankArms.length) {
    mbChartEmpty('mb-ch-rank', '참가자 데이터가 붙은 채점 건이 아직 없습니다.');
  } else {
    const cap = charts.rank_histogram_cap || 10;
    const labels = [];
    for (let i = 1; i <= cap; i++) labels.push(String(i));
    labels.push((cap + 1) + '+');
    new Chart(document.getElementById('mb-ch-rank'), {
      type: 'bar',
      data: {
        labels,
        datasets: rankArms.map((a) => ({ label: a, data: labels.map((l) => rd[a][l] || 0), backgroundColor: MB_ARM_COLOR[a] })),
      },
      options: { ...legendBottom, scales: { y: { beginAtZero: true } } },
    });
  }

  // ④ 낙찰가 대비 격차 분포
  const gd = charts.gap_distribution || {};
  const gapArms = MB_ARM_ORDER.filter((a) => gd[a]);
  if (!gapArms.length) {
    mbChartEmpty('mb-ch-gap', noData);
  } else {
    const labels = charts.gap_buckets || [];
    new Chart(document.getElementById('mb-ch-gap'), {
      type: 'bar',
      data: {
        labels,
        datasets: gapArms.map((a) => ({ label: a, data: labels.map((l) => gd[a][l] || 0), backgroundColor: MB_ARM_COLOR[a] })),
      },
      options: { ...legendBottom, scales: { y: { beginAtZero: true } } },
    });
  }

  // ⑤ 사정률 예측 오차 추이 (4차)
  const trend = charts.ratio_error_trend || [];
  if (!trend.length) {
    mbChartEmpty('mb-ch-err', noData);
  } else {
    new Chart(document.getElementById('mb-ch-err'), {
      type: 'line',
      data: {
        labels: trend.map((t) => (t.date || '').slice(5)),
        datasets: [{
          data: trend.map((t) => t.mean_error),
          borderColor: '#3182F6',
          backgroundColor: 'rgba(49, 130, 246, 0.1)',
          tension: 0.3,
          fill: true,
        }],
      },
      options: { ...base, scales: { y: { beginAtZero: true } } },
    });
  }

  // ⑥ 오답노트 태그별 무효율 (막대)
  const tags = charts.failure_tags || {};
  const tagNames = Object.keys(tags).filter((t) => tags[t].dropout_rate !== null && tags[t].dropout_rate !== undefined);
  if (!tagNames.length) {
    mbChartEmpty('mb-ch-tags', noData);
  } else {
    new Chart(document.getElementById('mb-ch-tags'), {
      type: 'bar',
      data: { labels: tagNames, datasets: [{ data: tagNames.map((t) => tags[t].dropout_rate), backgroundColor: '#FF8A00' }] },
      options: { ...base, indexAxis: 'y', scales: { x: { beginAtZero: true, ticks: { callback: (v) => v + '%' } } } },
    });
  }

  // ⑦ 세그먼트 교차표 — 금액대 경계는 autocalibrate 와 동일 어휘(small~xxlarge)
  const segEl = document.getElementById('mb-seg');
  if (segEl) {
    const seg = charts.segments || [];
    if (!seg.length) {
      segEl.innerHTML = '<span style="color:#8B95A1;">' + noData + '</span>';
    } else {
      const brackets = ['small', 'medium', 'large', 'xlarge', 'xxlarge'];
      const bracketLabel = { small: '~1억', medium: '1~5억', large: '5~10억', xlarge: '10~50억', xxlarge: '50억~' };
      const byMethod = {};
      seg.forEach((s) => { (byMethod[s.bid_method] = byMethod[s.bid_method] || {})[s.bracket] = s; });
      segEl.innerHTML = `<table style="width:100%;font-size:12px;min-width:420px;">
        <thead><tr><th style="text-align:left;">입찰방법</th>
        ${brackets.map((b) => '<th style="text-align:left;">' + bracketLabel[b] + '</th>').join('')}</tr></thead><tbody>
        ${Object.keys(byMethod).map((m) => `<tr><td style="white-space:nowrap;">${m}</td>
          ${brackets.map((b) => {
            const c = byMethod[m][b];
            if (!c) return '<td style="color:#B0B8C1;">—</td>';
            return `<td>${fmtNumber(c.judged)}건<br><span style="font-weight:700;color:${c.dropout_rate > 10 ? '#FF3B30' : '#191F28'};">${mbPct(c.dropout_rate)}</span></td>`;
          }).join('')}</tr>`).join('')}
        </tbody></table>`;
    }
  }
}

// ─── 부팅 ────────────────────────────────────────────────────

document.getElementById('btn-logout').addEventListener('click', () => {
  if (!confirm('로그아웃하시겠어요?')) return;
  clearToken();
  location.href = '/';
});

window.addEventListener('hashchange', renderRoute);

(async function init() {
  const me = await checkAuth();
  if (!me) return;
  showApp(me);
  if (!location.hash) location.hash = '#/dashboard';
  await renderRoute();
})();
