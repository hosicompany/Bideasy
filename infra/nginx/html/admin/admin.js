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
  simulation: '시뮬레이션',
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
  const [rev, users, ai, sys, calib] = await Promise.all([
    api('/admin/stats/revenue?days=30'),
    api('/admin/stats/users?days=30'),
    api('/admin/stats/ai-cost?days=30'),
    api('/admin/stats/system-health'),
    api('/admin/stats/autocalibrate-status'),
  ]);

  content.innerHTML = `
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

// 미완성 페이지 placeholder (Phase D~E 에서 구현)
['autocalibrate', 'system', 'simulation'].forEach((name) => {
  pages[name] = function(content) {
    const phase = { autocalibrate: 'D', system: 'D', simulation: 'E' }[name];
    content.innerHTML = `
      <div class="card" style="text-align:center;padding:60px 20px;">
        <h3 style="color:var(--color-text-muted);">${PAGE_TITLES[name]} 페이지</h3>
        <p style="color:var(--color-text-muted);margin-top:10px;">Phase ${phase} 에서 구현 예정</p>
      </div>
    `;
  };
});

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
