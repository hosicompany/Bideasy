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
  mockbidding: '모의투찰 결과',
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

// ─── 활성화 계측 (#101 후속) ──────────────────────────────
pages.activation = async function(content) {
  content.innerHTML = '<div class="card">불러오는 중...</div>';
  let d;
  try { d = await api('/admin/stats/activation?days=30'); }
  catch (err) { content.innerHTML = `<div class="card"><h3>오류</h3><p>${err.message}</p></div>`; return; }
  // daily 는 이벤트 발생일이 아니라 **가입일 코호트** 기준이다 — 8/1 가입자가 8/20 에
  // 활성화하면 8/1 행이 소급해서 오른다. 서버 키가 cohort_* 인 이유이고, 헤더도 그렇게 읽히게 쓴다.
  const rows = (d.daily || []).filter(r => r.signups || r.cohort_profile_complete || r.cohort_activated).map(r =>
    `<tr><td>${r.date}</td><td>${r.signups}</td><td>${r.cohort_profile_complete}</td><td>${r.cohort_activated}</td></tr>`).join('');
  content.innerHTML = `
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">계측 대상 가입자</div>
        <div class="kpi-value">${fmtNumber(d.with_created_at)}</div>
        <div class="kpi-sub">총 사용자 ${fmtNumber(d.total_users)}명 · 계측 도입 이전 가입자는 분모에서 제외</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">프로필 완성</div>
        <div class="kpi-value">${d.profile_complete_pct}%</div>
        <div class="kpi-sub">${fmtNumber(d.profile_complete)}명 — 면허·소재지 입력</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">첫 안전 판정</div>
        <div class="kpi-value">${d.activated_pct}%</div>
        <div class="kpi-sub">${fmtNumber(d.activated)}명 — 계산기/AI 분석 첫 사용</div>
      </div>
    </div>
    <div class="card">
      <h3>최근 30일 — 가입일 코호트</h3>
      <p style="font-size:12px;color:var(--color-text-muted);margin:-4px 0 10px;">각 행은 <b>그날 가입한 사람들</b>이 지금까지 얼마나 전환했는지를 뜻해요 (전환한 날이 아니라 가입한 날 기준).</p>
      <table style="width:100%;font-size:13px;">
        <thead><tr><th style="text-align:left;">가입일</th><th style="text-align:left;">가입</th><th style="text-align:left;">그중 프로필 완성</th><th style="text-align:left;">그중 첫 안전 판정</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4" style="color:var(--color-text-muted);">아직 계측된 가입자가 없어요 — 계측 배포 이후의 신규 가입부터 집계됩니다.</td></tr>'}</tbody>
      </table>
    </div>`;
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
    } catch (e) { r.innerHTML = '<div class="card">오류: ' + esc(e.message) + '</div>'; }
  });
  $('sim-whatif').addEventListener('click', async () => {
    const r = $('sim-result'); r.innerHTML = '<div class="card">민감도 분석 중...</div>';
    try {
      const d = await api('/admin/simulation/whatif', { method: 'POST', body: JSON.stringify(params()) });
      const rows = (d.results || []).map(x => `<tr><td>${x.margin_delta > 0 ? '+' : ''}${x.margin_delta}%p</td><td>${x.win_rate}%</td><td>${x.pass_rate}%</td><td>${x.dropout_rate}%</td></tr>`).join('');
      r.innerHTML = `<div class="card"><h3>여유분 민감도 (margin ±)</h3><p style="color:var(--color-text-muted);font-size:13px;">여유분을 늘리면 통과율↑·낙찰률↓ 트레이드오프를 봅니다.</p>
        <table style="width:100%;font-size:13px;margin-top:10px;"><thead><tr><th style="text-align:left;">여유분 가산</th><th style="text-align:left;">낙찰률</th><th style="text-align:left;">통과율</th><th style="text-align:left;">탈락률</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    } catch (e) { r.innerHTML = '<div class="card">오류: ' + esc(e.message) + '</div>'; }
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
      armBox.innerHTML = '<div class="card">5-arm 비교: ' + esc(d.reason || '데이터 없음') + '</div>';
    } else {
      renderArms(armBox, d);
    }
  } catch (e) {
    armBox.innerHTML = '<div class="card">5-arm 비교 오류: ' + esc(e.message) + '</div>';
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
  'A값': '국민연금·건강보험·산재·고용보험 등 법정 고정비 합계. 투찰가 공식에서 사정률을 적용하지 않고 그대로 더합니다. 2026-08부터 기초금액 API 구성요소 합계(tier0)로 자동 수집하며, 결측인 공고는 0으로 계산합니다.',
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


// ─── 모의투찰 결과 ───────────────────────────────────────────
// 설계·게이트 정본: docs/MOCK_BIDDING_DESIGN.md
const MB_ARM_ORDER = ['standard', 'active', 'frontier_c5', 'frontier_c10', 'aggressive'];
let mockBidHistoryRequestSeq = 0;

function mbPct(v) { return v === null || v === undefined ? '—' : v + '%'; }
function mbGateLabel(status) {
  return ({
    PASS: '통과', FAIL: '미통과', OBSERVING: '관찰 중', NOT_READY: '표본 대기',
    BLOCKED_G_A: 'G-A 차단', LOCKED_G_B: 'G-B 잠금',
  })[status] || status || '—';
}

function mbChartEmpty(canvasId, msg) {
  const cv = document.getElementById(canvasId);
  if (!cv || !cv.parentElement) return;
  cv.parentElement.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#8B95A1;font-size:13px;">' + esc(msg) + '</div>';
}


// 운영 연구 지표는 보존하되 첫 화면은 공고 1건 = 카드 1개, 현재 추천(active)의
// 가상 등수와 실제 개찰가 비교를 중심으로 보여준다.

const MB_ARM_FRIENDLY = {
  active: '현재 추천',
  standard: '기본값',
  frontier_c5: '안전 탐색',
  frontier_c10: '도전 탐색',
  aggressive: '공격적 탐색',
};

function mbDateText(iso) {
  if (!iso) return '—';
  return String(iso).replace('T', ' ').slice(0, 16);
}

function mbRateText(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(4).replace(/0+$/, '').replace(/\.$/, '') + '%' : '—';
}

function mbOutcomeMeta(outcome) {
  return ({
    WIN: { label: '낙찰 가능 범위', tone: 'good' },
    LOST: { label: '유효 · 낙찰가보다 높음', tone: 'neutral' },
    DROPOUT: { label: '하한선 미달', tone: 'danger' },
    VOID: { label: '판정 제외', tone: 'neutral' },
    NO_RESULT: { label: '개찰 결과 대기', tone: 'waiting' },
  })[outcome] || { label: '개찰 결과 대기', tone: 'waiting' };
}

function mbResultInsight(primary) {
  if (!primary || !primary.outcome || primary.outcome === 'NO_RESULT') {
    return '개찰 결과가 수집되면 실제 낙찰가와 가상 순위를 자동으로 계산해요.';
  }
  if (primary.outcome === 'DROPOUT') {
    const gap = primary.actual_lower_limit == null
      ? null : Number(primary.price) - Number(primary.actual_lower_limit);
    return gap === null
      ? '실제 하한선보다 낮아 유효하지 않았을 가능성이 커요.'
      : `실제 하한선보다 ${fmtNumber(Math.abs(Math.round(gap)))}원 낮았어요. 이 금액으로는 유효하지 않았을 가능성이 커요.`;
  }
  const amount = primary.gap_to_winner_amount;
  if (amount === null || amount === undefined) {
    return '유효 범위는 지켰지만 실제 낙찰가와의 차이는 아직 계산 중이에요.';
  }
  if (amount > 0) {
    return `실제 낙찰가보다 ${fmtNumber(amount)}원 높았어요. 더 낮은 가격을 쓴 업체가 앞섰습니다.`;
  }
  return `실제 낙찰가보다 ${fmtNumber(Math.abs(amount))}원 낮고 하한선은 지킨 가격이었어요.`;
}

function mbHistoryArmRows(arms) {
  return (arms || []).map((arm) => {
    const meta = mbOutcomeMeta(arm.outcome);
    const rank = arm.estimated_rank == null
      ? '—' : `가상 ${fmtNumber(arm.estimated_rank)}위`;
    return `<tr>
      <td><b>${esc(MB_ARM_FRIENDLY[arm.arm] || arm.arm || '—')}</b><small>${esc(arm.arm || '')}</small></td>
      <td>${fmtNumber(arm.price)}원<small>${mbRateText(arm.bid_rate)}</small></td>
      <td><span class="mb-result-badge ${meta.tone}">${esc(meta.label)}</span></td>
      <td>${rank}<small>${arm.participants_count == null ? '참가자 집계 전' : `실제 참가 ${fmtNumber(arm.participants_count)}곳`}</small></td>
      <td>${arm.gap_to_winner_amount == null ? '—' : `${arm.gap_to_winner_amount > 0 ? '+' : '−'}${fmtNumber(Math.abs(arm.gap_to_winner_amount))}원`}</td>
    </tr>`;
  }).join('');
}

function mbHistoryItem(item) {
  const primary = item.primary_arm || {};
  const meta = mbOutcomeMeta(primary.outcome);
  const completed = item.state === 'COMPLETED';
  const rankReady = primary.estimated_rank !== null && primary.estimated_rank !== undefined;
  const rankText = rankReady ? `가상 ${fmtNumber(primary.estimated_rank)}위` : '집계 중';
  const participantText = primary.participants_count == null
    ? '참가자 데이터 대기' : `실제 참가 ${fmtNumber(primary.participants_count)}곳 기준`;
  const title = item.title || '공고명 정보 없음';
  return `<article class="mb-history-item">
    <div class="mb-history-head">
      <div>
        <div class="mb-history-kicker">
          <span class="mb-result-badge ${meta.tone}">${esc(meta.label)}</span>
          <span>${esc(item.bid_no || '—')}</span>
        </div>
        <h4>${esc(title)}</h4>
        <p>${esc(item.organization || '발주처 정보 없음')} · 마감 ${esc(mbDateText(item.deadline_at))}</p>
      </div>
      <div class="mb-history-date">${completed ? `개찰 ${esc(mbDateText(item.opened_at))}` : '결과 자동 확인 중'}</div>
    </div>
    <div class="mb-history-highlight">
      <div class="mb-history-metric">
        <span>우리가 기록한 현재 추천가</span>
        <strong>${fmtNumber(primary.price)}원</strong>
        <small>${mbRateText(primary.bid_rate)}</small>
      </div>
      <div class="mb-history-metric rank">
        <span>실제로 제출했다면</span>
        <strong>${rankText}</strong>
        <small>${participantText}</small>
      </div>
      <div class="mb-history-metric">
        <span>실제 낙찰가</span>
        <strong>${primary.actual_winner_price == null ? '—' : fmtNumber(primary.actual_winner_price) + '원'}</strong>
        <small>${completed ? '개찰 결과 기준' : '결과가 나오면 표시'}</small>
      </div>
    </div>
    <p class="mb-history-insight">${esc(mbResultInsight(primary))}</p>
    <details class="mb-strategy-details">
      <summary>함께 기록한 5가지 가격 비교</summary>
      <div class="mb-table-scroll"><table class="mb-history-table">
        <thead><tr><th>가격안</th><th>기록한 금액</th><th>판정</th><th>가상 순위</th><th>낙찰가 차이</th></tr></thead>
        <tbody>${mbHistoryArmRows(item.arms)}</tbody>
      </table></div>
    </details>
  </article>`;
}

function mbHistoryEmpty(state) {
  const text = state === 'completed'
    ? '아직 개찰 결과가 확인된 공고가 없어요.'
    : state === 'waiting'
      ? '현재 결과를 기다리는 공고가 없어요.'
      : '조건에 맞는 모의투찰 기록이 없어요.';
  return `<div class="mb-empty"><b>${text}</b><span>공고번호 검색 조건을 바꿔보세요.</span></div>`;
}

async function loadMockBidHistory(historyState) {
  const list = document.getElementById('mb-history-list');
  const pager = document.getElementById('mb-history-pager');
  if (!list || !pager) return;
  const requestSeq = ++mockBidHistoryRequestSeq;
  const requestedState = historyState.state;
  list.innerHTML = '<div class="mb-empty">결과를 불러오는 중...</div>';
  pager.innerHTML = '';

  const params = new URLSearchParams({
    state: requestedState,
    page: String(historyState.page),
    page_size: '10',
  });
  if (historyState.search) params.set('search', historyState.search);

  try {
    const data = await api('/admin/mock-bidding/history?' + params.toString());
    if (requestSeq !== mockBidHistoryRequestSeq) return;
    const summary = data.summary || {};
    const setSummary = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = fmtNumber(value || 0);
    };
    setSummary('mb-summary-registered', summary.registered);
    setSummary('mb-summary-completed', summary.completed);
    setSummary('mb-summary-waiting', summary.waiting);
    setSummary('mb-summary-ranked', summary.rank_ready);

    list.innerHTML = (data.items || []).length
      ? data.items.map(mbHistoryItem).join('')
      : mbHistoryEmpty(requestedState);
    pager.innerHTML = `<span>전체 ${fmtNumber(data.total)}공고 · ${fmtNumber(data.page)} / ${fmtNumber(data.total_pages || 1)}페이지</span>
      <div><button class="btn btn-outline" data-mb-page="${data.page - 1}" ${data.has_previous ? '' : 'disabled'}>이전</button>
      <button class="btn btn-outline" data-mb-page="${data.page + 1}" ${data.has_next ? '' : 'disabled'}>다음</button></div>`;
    pager.querySelectorAll('[data-mb-page]').forEach((button) => {
      button.addEventListener('click', () => {
        if (button.disabled) return;
        historyState.page = Number(button.dataset.mbPage);
        loadMockBidHistory(historyState);
        document.getElementById('mb-history')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  } catch (e) {
    if (requestSeq !== mockBidHistoryRequestSeq) return;
    list.innerHTML = `<div class="mb-empty"><b>결과를 불러오지 못했어요.</b><span>${esc(e.message)}</span></div>`;
  }
}

function mbAdvancedTables(sum) {
  const arms = sum.arms || {};
  const armRows = MB_ARM_ORDER.filter((arm) => arms[arm]).map((arm) => {
    const row = arms[arm];
    return `<tr><td><b>${esc(MB_ARM_FRIENDLY[arm] || arm)}</b><small>${esc(arm)}</small></td>
      <td>${fmtNumber(row.judged)}</td><td>${mbPct(row.dropout_rate)}</td>
      <td>${mbPct(row.win_rate)}</td><td>${row.mean_ratio_error ?? '—'}</td></tr>`;
  }).join('');
  const tags = sum.failure_tags || {};
  const tagRows = Object.keys(tags).map((tag) => {
    const row = tags[tag];
    return `<tr><td>${esc(tag)}</td><td>${fmtNumber(row.total)}</td><td>${mbPct(row.dropout_rate)}</td></tr>`;
  }).join('');
  return { armRows, tagRows };
}

pages.mockbidding = async function (content) {
  content.innerHTML = '<div class="card">모의투찰 결과를 불러오는 중...</div>';
  let sum;
  let charts;
  try {
    [sum, charts] = await Promise.all([
      api('/admin/mock-bidding/summary'),
      api('/admin/mock-bidding/charts').catch(() => null),
    ]);
  } catch (e) {
    content.innerHTML = `<div class="card">오류: ${esc(e.message)}</div>`;
    return;
  }

  const gates = sum.gates || {};
  const reach = gates.g_a || sum.scoring_reach || {};
  const gateB = gates.g_b || {};
  const gateC = gates.g_c || {};
  const queue = sum.queue_health || {};
  const validity = sum.sample_validity || {};
  const active = (sum.arms || {}).active || {};
  const safeRate = active.dropout_rate == null ? null : Math.max(0, 100 - active.dropout_rate);
  const rd = ((charts || {}).rank_distribution || {}).active || {};
  const ranked = Object.values(rd).reduce((acc, value) => acc + Number(value || 0), 0);
  const top3 = Number(rd['1'] || 0) + Number(rd['2'] || 0) + Number(rd['3'] || 0);
  const top3Rate = ranked ? Math.round(top3 / ranked * 1000) / 10 : null;
  const advanced = mbAdvancedTables(sum);

  content.innerHTML = `
    <section class="mb-hero">
      <div>
        <span class="mb-eyebrow">실제 돈은 쓰지 않는 사전 실험</span>
        <h2>그때 이 가격을 썼다면 몇 위였을까요?</h2>
        <p>마감 전에 기록한 가격을 실제 개찰 결과와 비교해요. 결과가 나오면 가상 순위와 낙찰가 차이를 자동으로 알려드립니다.</p>
      </div>
      <div class="mb-hero-note"><b>읽는 순서</b><span>공고 선택 → 가상 순위 확인 → 필요할 때만 5가지 가격 비교</span></div>
    </section>

    <section class="mb-summary-grid" aria-label="모의투찰 진행 요약">
      <div class="mb-summary-card"><span>기록한 공고</span><strong id="mb-summary-registered">${fmtNumber(reach.registered || 0)}</strong><small>공고 기준</small></div>
      <div class="mb-summary-card good"><span>개찰 확인 완료</span><strong id="mb-summary-completed">${fmtNumber(reach.scored || 0)}</strong><small>실제 결과와 비교 가능</small></div>
      <div class="mb-summary-card waiting"><span>결과 기다리는 중</span><strong id="mb-summary-waiting">${fmtNumber(Math.max(0, (reach.registered || 0) - (reach.scored || 0)))}</strong><small>매일 자동 재확인</small></div>
      <div class="mb-summary-card rank"><span>가상 등수 확인</span><strong id="mb-summary-ranked">—</strong><small>참가자 데이터 확보</small></div>
    </section>

    <section class="card mb-history-card" id="mb-history">
      <div class="mb-section-head">
        <div><span class="mb-section-kicker">전체 이력</span><h3>공고별 모의투찰 결과</h3>
          <p>전략 5줄을 공고 하나로 묶었습니다. 지난 결과도 페이지를 넘겨 모두 확인할 수 있어요.</p></div>
      </div>
      <div class="mb-history-controls">
        <div class="mb-tabs" role="tablist">
          <button class="active" data-mb-state="completed">개찰 완료</button>
          <button data-mb-state="waiting">결과 대기</button>
          <button data-mb-state="all">전체</button>
        </div>
        <form id="mb-history-search" class="mb-search">
          <input id="mb-history-query" maxlength="100" placeholder="공고번호로 찾기" aria-label="공고번호 검색">
          <button class="btn btn-primary" type="submit">찾기</button>
        </form>
      </div>
      <div id="mb-history-list"></div>
      <div id="mb-history-pager" class="mb-pager"></div>
    </section>

    <section class="card mb-easy-analysis">
      <div class="mb-section-head"><div><span class="mb-section-kicker">한눈에 보기</span><h3>현재 추천 가격은 이렇게 움직이고 있어요</h3>
        <p>복잡한 실험 용어 대신 안전성·가상 순위·낙찰가와의 거리만 먼저 보여드립니다.</p></div></div>
      <div class="mb-easy-kpis">
        <div><span>하한선을 지킨 비율</span><strong>${safeRate == null ? '표본 대기' : safeRate.toFixed(1) + '%'}</strong><small>현재 추천 가격 기준</small></div>
        <div><span>가상 3위 안에 든 비율</span><strong>${top3Rate == null ? '표본 대기' : top3Rate + '%'}</strong><small>등수 확인 ${fmtNumber(ranked)}공고</small></div>
        <div><span>결과 해석 상태</span><strong>${esc(mbGateLabel(reach.status))}</strong><small>${reach.interpretation_allowed ? '누적 경향을 참고할 수 있어요' : '아직 개별 결과 위주로 보세요'}</small></div>
      </div>
      <div class="mb-simple-charts">
        <div><h4>가상 순위는 어디에 모였나요?</h4><p>현재 추천 가격을 실제 참가자 사이에 넣어 계산했습니다.</p><div class="chart-wrap"><canvas id="mb-ch-rank-simple"></canvas></div></div>
        <div><h4>실제 낙찰가와 얼마나 달랐나요?</h4><p>0에 가까울수록 실제 낙찰가에 가까운 가격입니다.</p><div class="chart-wrap"><canvas id="mb-ch-gap-simple"></canvas></div></div>
      </div>
    </section>

    <details class="card mb-advanced">
      <summary><div><b>운영·연구용 상세 분석</b><span>게이트, 전략별 성적, 표본 품질을 확인할 때 펼치세요.</span></div><span>펼치기</span></summary>
      <div class="mb-advanced-body">
        <div class="mb-gate-grid">
          <div><span>데이터 수집 상태</span><b>${esc(mbGateLabel(reach.status))}</b><small>${fmtNumber(reach.scored)} / ${fmtNumber(reach.registered)}공고 채점</small></div>
          <div><span>추천 전략 비교</span><b>${esc(mbGateLabel(gateB.status))}</b><small>적격심사제 ${fmtNumber(gateB.sample_notices)} / ${fmtNumber(gateB.minimum_notices || 400)}공고</small></div>
          <div><span>고위험 전략 검토</span><b>${esc(mbGateLabel(gateC.status))}</b><small>선행 조건 충족 후 판단</small></div>
          <div><span>채점 대기</span><b>${fmtNumber(queue.due_notices)}공고</b><small>개찰 결과 도착분부터 처리</small></div>
        </div>
        <p class="mb-validity-note">유효 표본 ${fmtNumber(validity.valid_judged_notices)}공고 · 기초금액 기준 불일치 제외 ${fmtNumber(validity.excluded_base_mismatch)}공고 · 판정 불가 제외 ${fmtNumber(validity.excluded_base_unknown)}공고</p>
        <div class="mb-advanced-grid">
          <div><h4>5가지 가격안 누적 비교</h4><div class="mb-table-scroll"><table class="mb-history-table">
            <thead><tr><th>가격안</th><th>채점</th><th>무효율</th><th>적중률</th><th>사정률 오차</th></tr></thead>
            <tbody>${advanced.armRows || '<tr><td colspan="5">데이터 없음</td></tr>'}</tbody>
          </table></div></div>
          <div><h4>자주 나타난 주의 요소</h4><div class="mb-table-scroll"><table class="mb-history-table">
            <thead><tr><th>요소</th><th>등장</th><th>무효율</th></tr></thead>
            <tbody>${advanced.tagRows || '<tr><td colspan="3">데이터 없음</td></tr>'}</tbody>
          </table></div></div>
        </div>
        <div><h4>사정률 예측 오차 추이</h4><p class="mb-chart-note">등수 백필 날짜가 아니라 공고 마감일 기준으로 묶습니다.</p><div class="chart-wrap"><canvas id="mb-ch-err-advanced"></canvas></div></div>
        <div><h4>입찰방법 × 금액대</h4><div id="mb-seg-advanced" class="mb-table-scroll">—</div></div>
      </div>
    </details>
    ${glossaryCard(['무효', '무효율', '적중', '밀림', '사전 등록', '예정가격', '사정률', '낙찰하한선', 'A값'])}`;

  const historyState = { state: 'completed', page: 1, search: '' };
  document.querySelectorAll('[data-mb-state]').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('[data-mb-state]').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      historyState.state = button.dataset.mbState;
      historyState.page = 1;
      loadMockBidHistory(historyState);
    });
  });
  document.getElementById('mb-history-search').addEventListener('submit', (event) => {
    event.preventDefault();
    historyState.search = document.getElementById('mb-history-query').value.trim();
    historyState.page = 1;
    loadMockBidHistory(historyState);
  });

  renderMockBiddingOverviewCharts(charts);
  loadMockBidHistory(historyState);
};

function renderMockBiddingOverviewCharts(charts) {
  const noData = '등수를 계산할 표본이 아직 없습니다.';
  if (!charts) {
    ['mb-ch-rank-simple', 'mb-ch-gap-simple', 'mb-ch-err-advanced']
      .forEach((id) => mbChartEmpty(id, '차트 데이터를 불러오지 못했습니다.'));
    return;
  }

  const rank = (charts.rank_distribution || {}).active || {};
  const rankGroups = [
    Number(rank['1'] || 0),
    Number(rank['2'] || 0) + Number(rank['3'] || 0),
    ['4', '5', '6', '7', '8', '9', '10'].reduce((sum, key) => sum + Number(rank[key] || 0), 0),
    Number(rank['11+'] || 0),
  ];
  if (!rankGroups.some(Boolean)) {
    mbChartEmpty('mb-ch-rank-simple', noData);
  } else {
    new Chart(document.getElementById('mb-ch-rank-simple'), {
      type: 'bar',
      data: { labels: ['1위', '2~3위', '4~10위', '11위 밖'], datasets: [{ data: rankGroups, backgroundColor: ['#3182F6', '#6BA6FA', '#A8C9F8', '#D7E5F7'], borderRadius: 8 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
    });
  }

  const gap = (charts.gap_distribution || {}).active || {};
  const gapBuckets = charts.gap_buckets || [];
  if (!gapBuckets.length || !gapBuckets.some((key) => gap[key])) {
    mbChartEmpty('mb-ch-gap-simple', '낙찰가와 비교할 표본이 아직 없습니다.');
  } else {
    const friendly = ['5%+ 낮음', '2~5% 낮음', '0.5~2% 낮음', '0~0.5% 낮음', '0~0.5% 높음', '0.5~1% 높음', '1~2% 높음', '2~5% 높음', '5%+ 높음'];
    new Chart(document.getElementById('mb-ch-gap-simple'), {
      type: 'bar',
      data: { labels: friendly, datasets: [{ data: gapBuckets.map((key) => gap[key] || 0), backgroundColor: gapBuckets.map((_, index) => index <= 3 ? '#34C759' : '#FFB45C'), borderRadius: 6 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { maxRotation: 45, minRotation: 20 } }, y: { beginAtZero: true, ticks: { precision: 0 } } } },
    });
  }

  const trend = charts.ratio_error_trend || [];
  if (!trend.length) {
    mbChartEmpty('mb-ch-err-advanced', '사정률 오차 표본이 아직 없습니다.');
  } else {
    new Chart(document.getElementById('mb-ch-err-advanced'), {
      type: 'line',
      data: { labels: trend.map((row) => String(row.date || '').slice(5)), datasets: [{ data: trend.map((row) => row.mean_error), borderColor: '#3182F6', backgroundColor: 'rgba(49,130,246,.08)', fill: true, tension: .3 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });
  }

  const segmentEl = document.getElementById('mb-seg-advanced');
  const segments = charts.segments || [];
  if (segmentEl) {
    if (!segments.length) {
      segmentEl.textContent = '세그먼트 표본이 아직 없습니다.';
    } else {
      segmentEl.innerHTML = `<table class="mb-history-table"><thead><tr><th>입찰방법</th><th>금액대</th><th>채점</th><th>무효율</th></tr></thead><tbody>${segments.map((row) => `<tr><td>${esc(row.bid_method || '—')}</td><td>${esc(row.bracket || '—')}</td><td>${fmtNumber(row.judged)}</td><td>${mbPct(row.dropout_rate)}</td></tr>`).join('')}</tbody></table>`;
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
