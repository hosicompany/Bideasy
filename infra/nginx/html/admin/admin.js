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
  activation: '활성화 · 설문',
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
      <button class="btn btn-outline" id="act-feedback" style="padding:6px 12px;font-size:12px;">피드백 요청 메일</button>
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
    $('act-feedback')?.addEventListener('click', () => showFeedbackRequestModal(user));
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

function showFeedbackRequestModal(user) {
  openModal('피드백 요청 메일', `
    <div class="status-row"><span class="status-label">대상</span><span class="status-value">${esc(user.email || user.id)}</span></div>
    <div style="margin-top:10px;font-size:13px;color:var(--color-text-sub);line-height:1.6;">
      답장으로 질문 2개(알게 된 경로·아쉬운 점)를 받는 메일이에요. 답장은 support@bideasy.kr 로 와요.<br>
      광고 메일로 분류되어 <b>광고 수신을 확인한 회원에게만</b> 실제로 나가고, 한 사람에게 한 번만 보내져요.
      미리보기: <a href="#" id="fb-preview">열기</a>
    </div>
  `, async () => {
    try {
      const r = await api(`/admin/outbound/feedback-request?user_id=${user.id}`, { method: 'POST' });
      const msg = { sent: '발송 완료', dry_run: '발송 꺼짐(dry_run) — 실제로 나가지 않았어요' }[r.status]
        || (r.reason === 'no_consent' ? '광고 수신 미확인 — 발송하지 않았어요'
          : r.reason === 'duplicate' ? '이미 보낸 회원이에요' : `${r.status} (${r.reason || ''})`);
      toast(msg, r.status === 'sent' ? 'success' : 'error');
    } catch (e) { toast(e.message, 'error'); return false; }
  }, '보내기');
  setTimeout(() => document.getElementById('fb-preview')?.addEventListener('click', async (ev) => {
    ev.preventDefault();
    const p = await api('/admin/outbound/preview?template=feedback_request');
    const w = window.open('', '_blank');
    if (w) { w.document.title = p.subject; w.document.body.innerHTML = `<h3>${esc(p.subject)}</h3>` + p.html; }
  }), 50);
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
  let sv = null;
  try { [d, sv] = await Promise.all([api('/admin/stats/activation?days=30'), api('/admin/growth/micro-survey?days=90').catch(() => null)]); }
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
    </div>
    ${renderMicroSurvey(sv)}`;
};

// 1문항 설문 응답 — 문항 ID 는 backend growth.py MICRO_SURVEY_QUESTIONS 와 같다.
const SURVEY_LABELS = {
  visit_purpose: '방문 목적 (무료 진단 결과 화면)',
  monthly_bids: '월 직접 투찰 건수 (대시보드)',
  payment_hesitation: '결제를 망설인 이유 (결제 화면)',
};
function renderMicroSurvey(sv) {
  if (!sv) return '<div class="card"><h3>1문항 설문</h3><p style="color:var(--color-text-muted);">응답을 불러오지 못했어요.</p></div>';
  const blocks = Object.keys(SURVEY_LABELS).map((key) => {
    const q = sv.questions[key];
    if (!q) return `<div style="margin-top:14px;"><b>${SURVEY_LABELS[key]}</b><div style="font-size:13px;color:var(--color-text-muted);margin-top:4px;">아직 응답이 없어요</div></div>`;
    const answers = q.answers.map(([a, n]) =>
      `<tr><td>${esc(a)}</td><td style="text-align:right;">${n}</td><td style="text-align:right;color:var(--color-text-muted);">${Math.round(n * 100 / q.total)}%</td></tr>`).join('');
    const details = q.details.map((d) =>
      `<li style="margin:4px 0;">${esc(d.detail)} <span style="color:var(--color-text-muted);font-size:11px;">${d.user_id ? '회원 ' + d.user_id : '비회원'} · ${fmtDateShort(d.occurred_at)}</span></li>`).join('');
    return `<div style="margin-top:14px;"><b>${SURVEY_LABELS[key]}</b> <span style="color:var(--color-text-muted);font-size:12px;">${q.total}명</span>
      <table style="width:100%;font-size:13px;margin-top:6px;"><tbody>${answers}</tbody></table>
      ${details ? `<div style="font-size:12px;color:var(--color-text-sub);margin-top:6px;">직접 입력</div><ul style="font-size:13px;padding-left:18px;margin:4px 0 0;">${details}</ul>` : ''}</div>`;
  }).join('');
  return `<div class="card"><h3>1문항 설문 — 최근 90일</h3>
    <p style="font-size:12px;color:var(--color-text-muted);margin:-4px 0 0;">한 사람이 같은 문항에 한 번만 답해요 (회원은 계정, 비회원은 브라우저 기준).</p>${blocks}</div>`;
}

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
  'A값': '국민연금·건강보험·노인장기요양보험료, 퇴직공제부금비, 산업안전보건관리비 등 사후정산 비목 10종 합계(산재·고용보험 제외). 투찰가 공식에서 사정률을 적용하지 않고 그대로 더합니다. 2026-08부터 기초금액 API 구성요소 합계(tier0)로 자동 수집하며, 결측인 공고는 0으로 계산합니다.',
  '무효': 'DROPOUT — 투찰가가 낙찰하한선 미만이라 입찰 자체가 없던 일이 되는 것. 가장 나쁜 결과입니다.',
  '무효율': '판정된 건 중 무효의 비율. 브랜드 KPI가 유효율이라 이것이 1차 지표입니다 — 낮을수록 좋습니다.',
  '적중': 'WIN(화면 표기: 심사 순번 안) — 투찰가가 [낙찰하한선, 실제 낙찰가] 구간에 들어간 것. 가격만 본 판정이라 "실제 낙찰자보다 먼저 심사받았다"까지만 뜻합니다. ⚠️ 적격심사제는 시공경험·경영상태 등 적격심사 점수를 반영하지 않아 실제 낙찰 여부는 알 수 없습니다.',
  '적중률': '판정된 건 중 적중의 비율(가격 기준). 적격심사 점수를 반영하지 않은 내부 참고용이며 대외에 «낙찰률»로 표기하는 것은 금지입니다(전역 규칙 §4-2).',
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

// ── 이력 필터 (1단계: 기간·판정·순위·기준 가격안 / 2단계: 입찰방법·금액대·주의 요소·낙찰가 차이·정렬·CSV) ──
// 순위는 절대 순위 구간이 기본이고 상위 %는 보조다 — 관리자가 개찰조서와
// 바로 대조할 수 있는 숫자가 절대 순위이기 때문이다.
const MB_RANK_BUCKETS = {
  '1': { label: '1위', min: 1, max: 1 },
  '2-3': { label: '2~3위', min: 2, max: 3 },
  '4-10': { label: '4~10위', min: 4, max: 10 },
  '11+': { label: '11위 이하', min: 11, max: null },
};
const MB_OUTCOME_FILTERS = ['WIN', 'LOST', 'DROPOUT'];
const MB_HISTORY_STATES = ['completed', 'waiting', 'all'];
// 금액대 어휘는 서버 PRICE_BRACKETS(자가보정 세그먼트와 동일)를 따른다
const MB_BRACKET_LABELS = {
  small: '1억 미만', medium: '1억~5억', large: '5억~10억', xlarge: '10억~50억', xxlarge: '50억 이상',
};
// 낙찰가 대비 차이 구간 — 차트(gap_buckets)와 같은 키. 경계 값은 아래 구간에 포함된다.
const MB_GAP_LABELS = {
  '≤-5': '−5% 이하', '-5~-2': '−5~−2%', '-2~-0.5': '−2~−0.5%', '-0.5~0': '−0.5~0%',
  '0~0.5': '0~+0.5% (아깝게 놓침)', '0.5~1': '+0.5~1%', '1~2': '+1~2%', '2~5': '+2~5%', '>5': '+5% 초과',
};
// 서버 FAILURE_TAGS 와 같은 어휘 — facets 응답이 오면 그쪽을 쓴다
const MB_FAILURE_TAGS = ['A값_결측', '하한율_테이블폴백', '기초금액_정정', '재공고건', '예가_비표준',
  '기초금액_기준불일치', '기초금액_변경됨', '사정률_극단', '예정가격_결측'];
const MB_SORTS = {
  deadline_desc: '마감 최신순', deadline_asc: '마감 오래된순',
  rank_asc: '가상 순위순', gap_abs_asc: '낙찰가와 가까운순',
};
// 결과(판정)가 있어야 의미 있는 정렬 — 결과 대기 탭에서는 쓰지 않는다
const MB_RESULT_SORTS = ['rank_asc', 'gap_abs_asc'];
const MB_CSV_MAX_NOTICES = 5000;

function mbLocalDate(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function mbIsDate(v) { return /^\d{4}-\d{2}-\d{2}$/.test(v || ''); }

// 허용 키 검사는 자기 속성만 — `obj[v]` 로 보면 `constructor`·`__proto__` 같은
// 프로토타입 키가 통과해 링크 하나로 목록이 422 오류 상태가 된다.
function mbHas(obj, key) { return key != null && Object.prototype.hasOwnProperty.call(obj, key); }

function mbHistoryStateFromUrl(rankVerified) {
  const q = new URLSearchParams(location.hash.split('?')[1] || '');
  const pct = Number(q.get('pct'));
  const st = {
    state: MB_HISTORY_STATES.includes(q.get('state')) ? q.get('state') : 'completed',
    page: Math.max(1, parseInt(q.get('page'), 10) || 1),
    search: (q.get('q') || '').slice(0, 100),
    arm: MB_ARM_ORDER.includes(q.get('arm')) ? q.get('arm') : 'active',
    dateField: q.get('df') === 'opened' ? 'opened' : 'deadline',
    from: mbIsDate(q.get('from')) ? q.get('from') : '',
    to: mbIsDate(q.get('to')) ? q.get('to') : '',
    outcome: MB_OUTCOME_FILTERS.includes(q.get('outcome')) ? q.get('outcome') : '',
    rank: mbHas(MB_RANK_BUCKETS, q.get('rank')) ? q.get('rank') : '',
    rankPct: Number.isFinite(pct) && pct > 0 && pct <= 100 ? String(pct) : '',
    // 입찰방법은 facets 가 오기 전에도 URL 값을 유지한다(서버가 일치 검사만 한다)
    bidMethod: (q.get('method') || '').slice(0, 100),
    bracket: mbHas(MB_BRACKET_LABELS, q.get('bracket')) ? q.get('bracket') : '',
    tag: MB_FAILURE_TAGS.includes(q.get('tag')) ? q.get('tag') : '',
    gap: mbHas(MB_GAP_LABELS, q.get('gap')) ? q.get('gap') : '',
    validOnly: q.get('valid') === '1',
    sort: mbHas(MB_SORTS, q.get('sort')) ? q.get('sort') : 'deadline_desc',
  };
  // 검증 전에는 URL 로 들어온 순위 조건·순위 정렬도 버린다 — 서버도 409 로 거부한다
  if (!rankVerified) {
    st.rank = '';
    st.rankPct = '';
    if (st.sort === 'rank_asc') st.sort = 'deadline_desc';
  }
  return st;
}

function mbSyncHistoryUrl(st) {
  const q = new URLSearchParams();
  if (st.state !== 'completed') q.set('state', st.state);
  if (st.page > 1) q.set('page', String(st.page));
  if (st.search) q.set('q', st.search);
  if (st.arm !== 'active') q.set('arm', st.arm);
  if (st.dateField !== 'deadline') q.set('df', st.dateField);
  if (st.from) q.set('from', st.from);
  if (st.to) q.set('to', st.to);
  if (st.outcome) q.set('outcome', st.outcome);
  if (st.rank) q.set('rank', st.rank);
  if (st.rankPct) q.set('pct', st.rankPct);
  if (st.bidMethod) q.set('method', st.bidMethod);
  if (st.bracket) q.set('bracket', st.bracket);
  if (st.tag) q.set('tag', st.tag);
  if (st.gap) q.set('gap', st.gap);
  if (st.validOnly) q.set('valid', '1');
  if (st.sort !== 'deadline_desc') q.set('sort', st.sort);
  const qs = q.toString();
  // location.hash 를 바꾸면 hashchange 로 페이지 전체(요약·차트)를 다시 그린다.
  // 필터는 목록만 다시 부르면 되므로 replaceState 로 주소만 맞춘다.
  history.replaceState(null, '', '#/mockbidding' + (qs ? '?' + qs : ''));
}

// 실제로 요청에 실리는 조건. 결과 대기 탭에는 판정이 없으므로 결과 기반 조건
// (가격안·판정·순위·주의 요소·낙찰가 차이·유효 표본·결과 정렬)을 뺀다 — 남겨 두면
// 언제나 0건이 되어 "대기 공고가 없다"로 오독된다. 순위는 검증 통과 시에만.
function mbEffectiveHistoryFilters(st, rankVerified) {
  const eff = { ...st };
  if (st.state === 'waiting') {
    Object.assign(eff, { arm: 'active', outcome: '', rank: '', rankPct: '', tag: '', gap: '', validOnly: false });
    if (MB_RESULT_SORTS.includes(eff.sort)) eff.sort = 'deadline_desc';
  }
  if (!rankVerified) {
    eff.rank = '';
    eff.rankPct = '';
    if (eff.sort === 'rank_asc') eff.sort = 'deadline_desc';
  }
  return eff;
}

// 목록과 CSV 가 같은 조건을 쓰도록 요청 파라미터는 여기서만 만든다
function mbHistoryQuery(st, rankVerified) {
  const eff = mbEffectiveHistoryFilters(st, rankVerified);
  const params = new URLSearchParams({ state: eff.state });
  if (eff.search) params.set('search', eff.search);
  if (eff.from || eff.to) params.set('date_field', eff.dateField);
  if (eff.from) params.set('date_from', eff.from);
  if (eff.to) params.set('date_to', eff.to);
  if (eff.bidMethod) params.set('bid_method', eff.bidMethod);
  if (eff.bracket) params.set('bracket', eff.bracket);
  if (eff.state !== 'waiting') {
    params.set('arm', eff.arm);
    if (eff.outcome) params.set('outcome', eff.outcome);
    if (eff.rank) {
      const bucket = MB_RANK_BUCKETS[eff.rank];
      params.set('rank_min', String(bucket.min));
      if (bucket.max != null) params.set('rank_max', String(bucket.max));
    }
    if (eff.rankPct) params.set('rank_pct_max', eff.rankPct);
    if (eff.tag) params.set('tag', eff.tag);
    if (eff.gap) params.set('gap_bucket', eff.gap);
    if (eff.validOnly) params.set('valid_base_only', 'true');
  }
  if (eff.sort !== 'deadline_desc') params.set('sort', eff.sort);
  return params;
}

// 기준 가격안은 결과 조건이 있을 때만 결과를 바꾼다 — 혼자서는 필터가 아니다. 정렬도 필터가 아니다.
function mbHistoryHasFilter(st) {
  return Boolean(st.search || st.from || st.to || st.outcome || st.rank || st.rankPct
    || st.bidMethod || st.bracket || st.tag || st.gap || st.validOnly);
}

function mbHistoryFilterSummary(st) {
  const parts = [];
  if (st.from || st.to) {
    parts.push(`${st.dateField === 'opened' ? '개찰일' : '마감일'} ${st.from || '처음'} ~ ${st.to || '오늘'}`);
  }
  if (st.bidMethod) parts.push(st.bidMethod);
  if (st.bracket) parts.push(`기초금액 ${MB_BRACKET_LABELS[st.bracket]}`);
  const armLabel = MB_ARM_FRIENDLY[st.arm] || st.arm;
  if (st.outcome) parts.push(`${armLabel} 판정: ${mbOutcomeMeta(st.outcome).label}`);
  if (st.rank) parts.push(`${armLabel} 가상 ${MB_RANK_BUCKETS[st.rank].label}`);
  if (st.rankPct) parts.push(`${armLabel} 유효 투찰 상위 ${st.rankPct}% 이내`);
  if (st.gap) parts.push(`${armLabel} 낙찰가 차이 ${MB_GAP_LABELS[st.gap]}`);
  if (st.tag) parts.push(`주의 요소 ${st.tag}`);
  if (st.validOnly) parts.push('기초금액 검증 통과분만');
  if (st.search) parts.push(`공고번호 "${st.search}"`);
  return parts.join(' · ');
}

function mbSelectOptions(entries, selected, emptyLabel) {
  return [`<option value="">${esc(emptyLabel)}</option>`].concat(entries.map(([value, label]) =>
    `<option value="${esc(value)}" ${selected === value ? 'selected' : ''}>${esc(label)}</option>`)).join('');
}

function mbHistoryFilterPanel(st, rankVerified, facets) {
  const armOptions = MB_ARM_ORDER.map((arm) =>
    `<option value="${arm}" ${st.arm === arm ? 'selected' : ''}>${esc(MB_ARM_FRIENDLY[arm] || arm)}</option>`).join('');
  const outcomeOptions = mbSelectOptions(MB_OUTCOME_FILTERS.map((o) => [o, mbOutcomeMeta(o).label]),
    st.outcome, '전체 판정');
  const rankChips = [['', '전체']].concat(Object.entries(MB_RANK_BUCKETS).map(([k, v]) => [k, v.label]))
    .map(([k, label]) => `<button type="button" data-mb-rank="${k}" class="${st.rank === k ? 'active' : ''}" ${rankVerified ? '' : 'disabled'}>${esc(label)}</button>`).join('');
  const methods = ((facets || {}).bid_methods || []).map((m) => [m.value, `${m.value} (${fmtNumber(m.notices)})`]);
  // URL 로 들어온 입찰방법이 목록에 없어도 선택 상태를 잃지 않게 한다
  if (st.bidMethod && !methods.some(([v]) => v === st.bidMethod)) methods.unshift([st.bidMethod, st.bidMethod]);
  const tags = ((facets || {}).failure_tags || MB_FAILURE_TAGS).map((t) => [t, t]);
  const sortOptions = Object.entries(MB_SORTS).map(([k, label]) =>
    `<option value="${k}" ${st.sort === k ? 'selected' : ''} ${k === 'rank_asc' && !rankVerified ? 'disabled' : ''} ${MB_RESULT_SORTS.includes(k) ? 'data-mb-result-sort' : ''}>${esc(label)}${k === 'rank_asc' && !rankVerified ? ' (검증 후)' : ''}</option>`).join('');
  return `<div class="mb-filter-panel" id="mb-history-filters">
    <div class="mb-filter-row">
      <label class="mb-filter-field"><span>기간 기준</span>
        <select id="mb-f-datefield"><option value="deadline" ${st.dateField === 'deadline' ? 'selected' : ''}>마감일</option><option value="opened" ${st.dateField === 'opened' ? 'selected' : ''}>개찰일</option></select></label>
      <label class="mb-filter-field"><span>시작</span><input type="date" id="mb-f-from" value="${esc(st.from)}"></label>
      <label class="mb-filter-field"><span>종료</span><input type="date" id="mb-f-to" value="${esc(st.to)}"></label>
      <div class="mb-filter-quick">
        <button type="button" data-mb-range="7">최근 7일</button>
        <button type="button" data-mb-range="30">최근 30일</button>
        <button type="button" data-mb-range="month">이번 달</button>
        <button type="button" data-mb-range="">기간 전체</button>
      </div>
    </div>
    <div class="mb-filter-row">
      <label class="mb-filter-field"><span>입찰방법</span><select id="mb-f-method">${mbSelectOptions(methods, st.bidMethod, '전체 입찰방법')}</select></label>
      <label class="mb-filter-field"><span>금액대(기초금액)</span><select id="mb-f-bracket">${mbSelectOptions(Object.entries(MB_BRACKET_LABELS), st.bracket, '전체 금액대')}</select></label>
      <label class="mb-filter-field"><span>정렬</span><select id="mb-f-sort">${sortOptions}</select></label>
    </div>
    <div class="mb-filter-row">
      <label class="mb-filter-field"><span>기준 가격안</span><select id="mb-f-arm" data-mb-result-filter>${armOptions}</select></label>
      <label class="mb-filter-field"><span>판정</span><select id="mb-f-outcome" data-mb-result-filter>${outcomeOptions}</select></label>
      <div class="mb-filter-field"><span>가상 순위</span><div class="mb-tabs mb-rank-chips">${rankChips}</div></div>
      <label class="mb-filter-field mb-filter-pct"><span>유효 투찰 상위 % 이내</span>
        <input type="number" id="mb-f-pct" min="0.1" max="100" step="0.1" placeholder="예: 10" value="${esc(st.rankPct)}" ${rankVerified ? '' : 'disabled'}></label>
    </div>
    <div class="mb-filter-row">
      <label class="mb-filter-field"><span>낙찰가 대비 차이</span><select id="mb-f-gap" data-mb-result-filter>${mbSelectOptions(Object.entries(MB_GAP_LABELS), st.gap, '전체 구간')}</select></label>
      <label class="mb-filter-field"><span>주의 요소</span><select id="mb-f-tag" data-mb-result-filter>${mbSelectOptions(tags, st.tag, '전체 주의 요소')}</select></label>
      <label class="mb-filter-check"><input type="checkbox" id="mb-f-valid" data-mb-result-filter ${st.validOnly ? 'checked' : ''}><span>기초금액 검증 통과분만<small>상단 성적표·차트와 같은 유효 표본 기준 — 낙찰가 차이 차트와 건수를 맞출 때 함께 켜세요</small></span></label>
      <div class="mb-filter-actions">
        <button type="button" class="btn btn-outline" id="mb-f-reset">조건 초기화</button>
        <button type="button" class="btn btn-outline" id="mb-f-csv">조건대로 CSV 받기</button>
      </div>
    </div>
    ${rankVerified ? '' : '<p class="mb-filter-note">등수 축 검증 전이라 순위 필터·순위 정렬은 잠겨 있고, CSV 의 가상 순위 칸도 비워서 내려받아요.</p>'}
    <p class="mb-filter-note" id="mb-f-waiting-note" hidden>결과 대기 공고에는 판정이 없어서 가격안·판정·순위·낙찰가 차이·주의 요소·검증 조건은 적용하지 않아요.</p>
    <p class="mb-filter-note" id="mb-f-csv-note" hidden></p>
  </div>`;
}

const MB_FILTER_DEFAULTS = {
  search: '', arm: 'active', dateField: 'deadline', from: '', to: '', outcome: '', rank: '', rankPct: '',
  bidMethod: '', bracket: '', tag: '', gap: '', validOnly: false, sort: 'deadline_desc',
};

function mbBindHistoryFilters(historyState, rankVerified) {
  const reload = () => {
    historyState.page = 1;
    loadMockBidHistory(historyState, rankVerified);
  };
  const byId = (id) => document.getElementById(id);
  // 결과 조건이 하나라도 있을 때만 가격안 변경이 목록을 바꾼다
  const hasResultCondition = () => Boolean(historyState.outcome || historyState.rank || historyState.rankPct
    || historyState.tag || historyState.gap || historyState.validOnly || MB_RESULT_SORTS.includes(historyState.sort));
  byId('mb-f-datefield').addEventListener('change', (e) => { historyState.dateField = e.target.value; if (historyState.from || historyState.to) reload(); else mbSyncHistoryUrl(historyState); });
  byId('mb-f-from').addEventListener('change', (e) => { historyState.from = mbIsDate(e.target.value) ? e.target.value : ''; reload(); });
  byId('mb-f-to').addEventListener('change', (e) => { historyState.to = mbIsDate(e.target.value) ? e.target.value : ''; reload(); });
  document.querySelectorAll('[data-mb-range]').forEach((button) => {
    button.addEventListener('click', () => {
      const today = new Date();
      const key = button.dataset.mbRange;
      let from = '';
      if (key === 'month') from = mbLocalDate(new Date(today.getFullYear(), today.getMonth(), 1));
      else if (key) from = mbLocalDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - Number(key) + 1));
      historyState.from = from;
      historyState.to = key ? mbLocalDate(today) : '';
      byId('mb-f-from').value = historyState.from;
      byId('mb-f-to').value = historyState.to;
      reload();
    });
  });
  byId('mb-f-arm').addEventListener('change', (e) => { historyState.arm = e.target.value; if (hasResultCondition()) reload(); else mbSyncHistoryUrl(historyState); });
  const onSelect = (id, key) => byId(id).addEventListener('change', (e) => { historyState[key] = e.target.value; reload(); });
  onSelect('mb-f-outcome', 'outcome');
  onSelect('mb-f-method', 'bidMethod');
  onSelect('mb-f-bracket', 'bracket');
  onSelect('mb-f-gap', 'gap');
  onSelect('mb-f-tag', 'tag');
  byId('mb-f-sort').addEventListener('change', (e) => {
    const sort = mbHas(MB_SORTS, e.target.value) ? e.target.value : 'deadline_desc';
    historyState.sort = sort === 'rank_asc' && !rankVerified ? 'deadline_desc' : sort;
    e.target.value = historyState.sort;
    reload();
  });
  byId('mb-f-valid').addEventListener('change', (e) => { historyState.validOnly = e.target.checked; reload(); });
  document.querySelectorAll('[data-mb-rank]').forEach((button) => {
    button.addEventListener('click', () => {
      if (!rankVerified || button.disabled) return;
      historyState.rank = button.dataset.mbRank;
      document.querySelectorAll('[data-mb-rank]').forEach((b) => b.classList.toggle('active', b === button));
      reload();
    });
  });
  byId('mb-f-pct').addEventListener('change', (e) => {
    if (!rankVerified) return;
    const n = Number(e.target.value);
    historyState.rankPct = e.target.value && Number.isFinite(n) && n > 0 && n <= 100 ? String(n) : '';
    e.target.value = historyState.rankPct;
    reload();
  });
  byId('mb-f-reset').addEventListener('click', () => {
    Object.assign(historyState, MB_FILTER_DEFAULTS);
    byId('mb-history-query').value = '';
    byId('mb-f-datefield').value = 'deadline';
    ['mb-f-from', 'mb-f-to', 'mb-f-outcome', 'mb-f-pct', 'mb-f-method', 'mb-f-bracket', 'mb-f-gap', 'mb-f-tag']
      .forEach((id) => { byId(id).value = ''; });
    byId('mb-f-arm').value = 'active';
    byId('mb-f-sort').value = 'deadline_desc';
    byId('mb-f-valid').checked = false;
    document.querySelectorAll('[data-mb-rank]').forEach((b) => b.classList.toggle('active', b.dataset.mbRank === ''));
    reload();
  });
  byId('mb-f-csv').addEventListener('click', () => mbDownloadHistoryCsv(historyState, rankVerified));
}

// 결과 대기 탭에는 판정·순위가 없다 — 탭에 맞춰 결과 조건 입력을 잠근다(요청에서는
// mbEffectiveHistoryFilters 가 뺀다).
function mbToggleResultFilters(historyState, rankVerified) {
  const waiting = historyState.state === 'waiting';
  document.querySelectorAll('[data-mb-result-filter]').forEach((el) => { el.disabled = waiting; });
  document.querySelectorAll('[data-mb-rank]').forEach((el) => { el.disabled = waiting || !rankVerified; });
  document.querySelectorAll('[data-mb-result-sort]').forEach((el) => {
    el.disabled = waiting || (el.value === 'rank_asc' && !rankVerified);
  });
  const pct = document.getElementById('mb-f-pct');
  if (pct) pct.disabled = waiting || !rankVerified;
  const note = document.getElementById('mb-f-waiting-note');
  if (note) note.hidden = !waiting;
}

// CSV 는 api() 가 JSON 만 다루므로 같은 인증 헤더로 직접 받는다. 조건은 목록과
// 같은 mbHistoryQuery — 화면 건수와 파일 건수가 갈라지지 않게.
async function mbDownloadHistoryCsv(historyState, rankVerified) {
  const note = document.getElementById('mb-f-csv-note');
  const button = document.getElementById('mb-f-csv');
  const show = (text) => { if (note) { note.textContent = text; note.hidden = !text; } };
  const token = getToken();
  if (!token) { show('로그인이 필요해요.'); return; }
  const query = mbHistoryQuery(historyState, rankVerified).toString();
  // 목록이 같은 조건으로 받아 둔 건수일 때만 믿는다. 모르면 상한만 알린다.
  const known = historyState.lastTotalQuery === query;
  const total = known ? Number(historyState.lastTotal || 0) : null;
  if (button) button.disabled = true;
  show(total != null && total > MB_CSV_MAX_NOTICES
    ? `조건에 맞는 공고가 ${fmtNumber(total)}건이라 앞의 ${fmtNumber(MB_CSV_MAX_NOTICES)}공고(현재 정렬 기준)만 내려받아요.`
    : total == null
      ? `CSV 를 만드는 중이에요... (한 번에 최대 ${fmtNumber(MB_CSV_MAX_NOTICES)}공고)`
      : 'CSV 를 만드는 중이에요...');
  try {
    const resp = await fetch(API_BASE + '/admin/mock-bidding/history.csv?' + query, {
      headers: { Authorization: 'Bearer ' + token },
    });
    if (!resp.ok) {
      let msg = `HTTP ${resp.status}`;
      try { const j = JSON.parse(await resp.text()); if (j.detail) msg = j.detail; } catch {}
      throw new Error(msg);
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `mock-bidding-history-${mbLocalDate(new Date())}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    if (total == null || total <= MB_CSV_MAX_NOTICES) show(rankVerified ? '' : '등수 축 검증 전이라 가상 순위 칸은 비워서 내려받았어요.');
  } catch (e) {
    show(`CSV 를 받지 못했어요: ${e.message}`);
  } finally {
    if (button) button.disabled = false;
  }
}

function mbOutcomeMeta(outcome) {
  return ({
    // 가격만 본 판정이다 — 적격심사 점수를 모르므로 '낙찰'을 암시하지 않는다
    WIN: { label: '심사 순번 안(가격 기준)', tone: 'good' },
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

// 등수의 분모는 전 참가자가 아니라 **유효 투찰** 수다. 낙찰하한선 미달 투찰에는
// 개찰 API 가 순위를 주지 않으므로, 무효까지 세면 개찰조서와 다른 등수가 된다.
function mbParticipantText(arm) {
  const valid = arm.valid_participants_count;
  const total = arm.participants_count;
  // "N곳 기준"으로 쓰면 분모 선언으로 읽혀 "2곳 기준인데 3위" 같은 모순이 된다.
  // 등수는 우리를 끼워 넣은 값이라 최대 N+1 이다 — 서술형으로 적는다.
  if (valid != null) {
    return total != null && total !== valid
      ? `유효 투찰 ${fmtNumber(valid)}곳 사이 순위 · 총 참가 ${fmtNumber(total)}곳`
      : `유효 투찰 ${fmtNumber(valid)}곳 사이 순위`;
  }
  return total == null ? '참가자 집계 전' : `총 참가 ${fmtNumber(total)}곳`;
}

// 무효는 개찰 순위를 갖지 않는다. 이걸 '집계 중'으로 두면 판정이 끝난 건인데도
// 관리자가 오지 않을 숫자를 기다린다.
function mbRankText(arm, pendingLabel, rankVerified = false) {
  if (arm.outcome === 'DROPOUT') return '순위 없음(무효)';
  if (!rankVerified) return '등수 점검 중';
  return arm.estimated_rank == null
    ? pendingLabel : `가상 ${fmtNumber(arm.estimated_rank)}위`;
}

function mbHistoryArmRows(arms, rankVerified) {
  return (arms || []).map((arm) => {
    const meta = mbOutcomeMeta(arm.outcome);
    const rank = mbRankText(arm, '—', rankVerified);
    return `<tr>
      <td><b>${esc(MB_ARM_FRIENDLY[arm.arm] || arm.arm || '—')}</b><small>${esc(arm.arm || '')}</small></td>
      <td>${fmtNumber(arm.price)}원<small>${mbRateText(arm.bid_rate)}</small></td>
      <td><span class="mb-result-badge ${meta.tone}">${esc(meta.label)}</span></td>
      <td>${rank}<small>${esc(mbParticipantText(arm))}</small></td>
      <td>${arm.gap_to_winner_amount == null ? '—' : `${arm.gap_to_winner_amount > 0 ? '+' : '−'}${fmtNumber(Math.abs(arm.gap_to_winner_amount))}원`}</td>
    </tr>`;
  }).join('');
}

// 적격심사제는 하한선 이상 최저가부터 차례로 심사해 기준 점수를 넘는 첫 업체가 낙찰된다.
// 실제 낙찰가 이하 = '실제 낙찰자보다 먼저 심사받았다'까지만 사실이고, 우리 점수는 모른다.
// 밀림·무효는 점수와 무관하게 가격만으로 확정되므로 경고하지 않는다.
function mbQualificationCaveat(item, primary) {
  if (!primary || primary.outcome !== 'WIN' || !String(item.bid_method || '').includes('적격')) return '';
  return '<p class="mb-caveat">가격만 본 판정이에요. 적격심사 점수(시공경험·경영상태 등)는 반영하지 않아서, 실제로 낙찰됐을지는 알 수 없어요.</p>';
}

function mbHistoryItem(item, rankVerified, filterArm = 'active') {
  const primary = item.primary_arm || {};
  // 다른 가격안으로 걸렀다면, 이 카드가 왜 걸렸는지 첫 화면에서 보여준다
  const filtered = filterArm !== 'active'
    ? (item.arms || []).find((arm) => arm.arm === filterArm) : null;
  const filteredLine = filtered
    ? `<p class="mb-filter-hit">필터 기준 · ${esc(MB_ARM_FRIENDLY[filterArm] || filterArm)}: ${esc(mbOutcomeMeta(filtered.outcome).label)} · ${mbRankText(filtered, '—', rankVerified)}</p>`
    : '';
  const meta = mbOutcomeMeta(primary.outcome);
  const completed = item.state === 'COMPLETED';
  const rankText = mbRankText(primary, '집계 중', rankVerified);
  const participantText = (primary.participants_count == null
      && primary.valid_participants_count == null)
    ? '참가자 데이터 대기' : mbParticipantText(primary);
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
    ${mbQualificationCaveat(item, primary)}
    ${filteredLine}
    <details class="mb-strategy-details">
      <summary>함께 기록한 5가지 가격 비교</summary>
      <div class="mb-table-scroll"><table class="mb-history-table">
        <thead><tr><th>가격안</th><th>기록한 금액</th><th>판정</th><th>가상 순위</th><th>낙찰가 차이</th></tr></thead>
        <tbody>${mbHistoryArmRows(item.arms, rankVerified)}</tbody>
      </table></div>
    </details>
  </article>`;
}

function mbHistoryEmpty(state, hasFilter = false) {
  const text = hasFilter
    ? '조건에 맞는 공고가 없어요.'
    : state === 'completed'
      ? '아직 개찰 결과가 확인된 공고가 없어요.'
      : state === 'waiting'
        ? '현재 결과를 기다리는 공고가 없어요.'
        : '조건에 맞는 모의투찰 기록이 없어요.';
  const hint = hasFilter ? '기간·판정·순위 조건을 넓히거나 초기화해 보세요.' : '공고번호 검색 조건을 바꿔보세요.';
  return `<div class="mb-empty"><b>${text}</b><span>${hint}</span></div>`;
}

async function loadMockBidHistory(historyState, rankVerified) {
  const list = document.getElementById('mb-history-list');
  const pager = document.getElementById('mb-history-pager');
  if (!list || !pager) return;
  const requestSeq = ++mockBidHistoryRequestSeq;
  const requestedState = historyState.state;
  list.innerHTML = '<div class="mb-empty">결과를 불러오는 중...</div>';
  pager.innerHTML = '';

  const params = mbHistoryQuery(historyState, rankVerified);
  params.set('page', String(historyState.page));
  params.set('page_size', '10');
  const eff = mbEffectiveHistoryFilters(historyState, rankVerified);
  const filterArm = requestedState !== 'waiting' ? eff.arm : 'active';
  const hasFilter = mbHistoryHasFilter(eff);
  mbSyncHistoryUrl(historyState);
  mbToggleResultFilters(historyState, rankVerified);

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
    const rankedSummary = document.getElementById('mb-summary-ranked');
    if (rankedSummary) {
      rankedSummary.textContent = rankVerified ? fmtNumber(summary.rank_ready || 0) : '점검 중';
    }

    list.innerHTML = (data.items || []).length
      ? data.items.map((item) => mbHistoryItem(item, rankVerified, filterArm)).join('')
      : mbHistoryEmpty(requestedState, hasFilter);
    // 이 건수가 어느 조건의 것인지 함께 남긴다 — 조건을 바꾼 직후 CSV 를 누르면
    // 이전 조건의 건수로 잘림 여부를 안내하게 된다
    historyState.lastTotal = Number(data.total || 0);
    historyState.lastTotalQuery = mbHistoryQuery(historyState, rankVerified).toString();
    const filterText = hasFilter ? mbHistoryFilterSummary(eff) : '';
    const sortText = eff.sort !== 'deadline_desc' ? ` · ${MB_SORTS[eff.sort]}` : '';
    pager.innerHTML = `<span>${hasFilter ? '조건에 맞는' : '전체'} ${fmtNumber(data.total)}공고 · ${fmtNumber(data.page)} / ${fmtNumber(data.total_pages || 1)}페이지${esc(sortText)}${filterText ? `<small class="mb-filter-summary">${esc(filterText)}</small>` : ''}</span>
      <div><button class="btn btn-outline" data-mb-page="${data.page - 1}" ${data.has_previous ? '' : 'disabled'}>이전</button>
      <button class="btn btn-outline" data-mb-page="${data.page + 1}" ${data.has_next ? '' : 'disabled'}>다음</button></div>`;
    pager.querySelectorAll('[data-mb-page]').forEach((button) => {
      button.addEventListener('click', () => {
        if (button.disabled) return;
        historyState.page = Number(button.dataset.mbPage);
        loadMockBidHistory(historyState, rankVerified);
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
  let facets;
  try {
    [sum, charts, facets] = await Promise.all([
      api('/admin/mock-bidding/summary'),
      api('/admin/mock-bidding/charts').catch(() => null),
      // 선택지가 없어도 목록은 떠야 한다 — 실패하면 고정 어휘로 대체
      api('/admin/mock-bidding/history/facets').catch(() => null),
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
  // 축이 어긋난 상태에서 숫자만 살려두면, 관리자가 차트 경고를 읽고도 바로 위의
  // KPI 를 그대로 보고서에 옮긴다. 해석을 막으려면 숫자도 함께 막아야 한다.
  const axisHealth = (charts || {}).rank_axis_health || {};
  // 등수는 검증기가 명시적으로 true 를 줄 때만 노출한다. 차트 API
  // 실패나 소표본 판정 보류를 '정상'으로 해석하면 정작 감시기가 꺼진
  // 순간에 잘못된 가상 등수가 공고별 이력에 다시 노출된다.
  const rankVerified = axisHealth.healthy === true;
  const axisBroken = !rankVerified;
  // 제외 수를 숨기면 전수를 본 것처럼 읽힌다. 무효율이 높은 arm 일수록 많이
  // 빠지므로, arm 간 비교에는 반드시 무효율과 함께 봐야 한다.
  const excluded = (charts || {}).rank_excluded || {};
  const exDropout = Number((excluded.dropout || {}).active || 0);
  const exNoData = Number((excluded.no_rank_data || {}).active || 0);
  const exParts = [];
  if (exDropout) exParts.push(`무효 ${fmtNumber(exDropout)}건(순위 없음)`);
  if (exNoData) exParts.push(`참가자 데이터 미도착 ${fmtNumber(exNoData)}건`);
  const dropoutExcludedText = exParts.length
    ? `${exParts.join(' · ')}은 제외했어요(무효율은 위 지표 참조).` : '';
  const top3Rate = (ranked && !axisBroken) ? Math.round(top3 / ranked * 1000) / 10 : null;
  const top3Label = axisHealth.healthy === false ? '축 점검 중' : '축 확인 대기';
  const advanced = mbAdvancedTables(sum);
  const historyState = mbHistoryStateFromUrl(rankVerified);

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
      <div class="mb-summary-card rank"><span>등수 계산 완료</span><strong id="mb-summary-ranked">—</strong><small>무효(순위 없음) 제외</small></div>
    </section>

    <section class="card mb-history-card" id="mb-history">
      <div class="mb-section-head">
        <div><span class="mb-section-kicker">전체 이력</span><h3>공고별 모의투찰 결과</h3>
          <p>전략 5줄을 공고 하나로 묶었습니다. 지난 결과도 페이지를 넘겨 모두 확인할 수 있어요.</p></div>
      </div>
      <div class="mb-history-controls">
        <div class="mb-tabs" role="tablist">
          <button class="${historyState.state === 'completed' ? 'active' : ''}" data-mb-state="completed">개찰 완료</button>
          <button class="${historyState.state === 'waiting' ? 'active' : ''}" data-mb-state="waiting">결과 대기</button>
          <button class="${historyState.state === 'all' ? 'active' : ''}" data-mb-state="all">전체</button>
        </div>
        <form id="mb-history-search" class="mb-search">
          <input id="mb-history-query" maxlength="100" placeholder="공고번호로 찾기" aria-label="공고번호 검색" value="${esc(historyState.search)}">
          <button class="btn btn-primary" type="submit">찾기</button>
        </form>
      </div>
      ${mbHistoryFilterPanel(historyState, rankVerified, facets)}
      ${rankVerified ? '' : '<p class="mb-validity-note">등수 축을 확인하는 중이에요. 검증이 통과할 때까지 공고별 가상 등수는 숨깁니다.</p>'}
      <div id="mb-history-list"></div>
      <div id="mb-history-pager" class="mb-pager"></div>
    </section>

    <section class="card mb-easy-analysis">
      <div class="mb-section-head"><div><span class="mb-section-kicker">한눈에 보기</span><h3>현재 추천 가격은 이렇게 움직이고 있어요</h3>
        <p>복잡한 실험 용어 대신 안전성·가상 순위·낙찰가와의 거리만 먼저 보여드립니다.</p></div></div>
      <div class="mb-easy-kpis">
        <div><span>하한선을 지킨 비율</span><strong>${safeRate == null ? '표본 대기' : safeRate.toFixed(1) + '%'}</strong><small>현재 추천 가격 기준</small></div>
        <div><span>가상 3위 안에 든 비율</span><strong>${top3Rate == null ? top3Label : top3Rate + '%'}</strong><small>${rankVerified ? `등수 확인 ${fmtNumber(ranked)}공고 · 무효 제외` : '등수 축 검증 통과 전'}</small></div>
        <div><span>결과 해석 상태</span><strong>${esc(mbGateLabel(reach.status))}</strong><small>${reach.interpretation_allowed ? '누적 경향을 참고할 수 있어요' : '아직 개별 결과 위주로 보세요'}</small></div>
      </div>
      <div class="mb-simple-charts">
        <div><h4>가상 순위는 어디에 모였나요?</h4><p>현재 추천 가격을 <b>유효 투찰</b>(낙찰하한선 이상) 사이에 넣어 계산했습니다. ${dropoutExcludedText}</p><div class="chart-wrap"><canvas id="mb-ch-rank-simple"></canvas></div></div>
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
            <thead><tr><th>가격안</th><th>채점</th><th>무효율</th><th>적중률(가격 기준)</th><th>사정률 오차</th></tr></thead>
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

  document.querySelectorAll('[data-mb-state]').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('[data-mb-state]').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      historyState.state = button.dataset.mbState;
      historyState.page = 1;
      loadMockBidHistory(historyState, rankVerified);
    });
  });
  document.getElementById('mb-history-search').addEventListener('submit', (event) => {
    event.preventDefault();
    historyState.search = document.getElementById('mb-history-query').value.trim();
    historyState.page = 1;
    loadMockBidHistory(historyState, rankVerified);
  });
  mbBindHistoryFilters(historyState, rankVerified);

  // 차트가 던져도 원장(가장 중요한 데이터)은 반드시 뜨게 한다 — 장식이 본문을
  // 가리면 안 된다. Chart.js 로드 실패 한 번이 화면 전체를 비우던 구조였다.
  try {
    renderMockBiddingOverviewCharts(charts);
  } catch (error) {
    console.error('[mock-bidding] 차트 렌더 실패', error);
  }
  loadMockBidHistory(historyState, rankVerified);
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
  // 등수 축이 개찰 API 와 어긋나면 그래프를 그리는 것 자체가 거짓말이 된다.
  // Phase 2 는 축이 틀린 채 9일을 돌았고 화면은 그동안 멀쩡히 그려졌다.
  const axis = charts.rank_axis_health;
  if (!axis || axis.healthy !== true) {
    // 사유별로 다른 말을 해야 한다. 전부 "N% 어긋남"으로 쓰면 결측률 이상일 때
    // "0.0% 어긋났습니다" 같은 자기모순 문구가 나온다.
    const why = axis && axis.healthy === false ? ({
      axis_mismatch: `개찰 API 순위와 ${axis.mismatch_pct}% 어긋났습니다.`,
      null_rank_anomaly: `무효 투찰 비중이 ${axis.null_rank_pct}% 입니다(정상 범위 5~90%). `
        + 'API 가 순위를 주는 기준이 바뀌었을 수 있어요.',
      no_rank_at_all: '순위 필드가 한 건도 파싱되지 않았습니다. 필드명 변경을 의심하세요.',
    }[axis.reason] || '축 점검이 필요합니다.')
      : axis
        ? `최근 ${axis.window_days ?? 7}일 표본 ${fmtNumber(axis.sampled_notices || 0)}공고로는 아직 축을 판정할 수 없어요.`
        : '축 검증 데이터를 불러오지 못했습니다.';
    mbChartEmpty('mb-ch-rank-simple',
      `등수 축 점검이 필요해요 — ${why} 원인을 확인할 때까지 등수는 해석하지 마세요.`);
  } else if (!rankGroups.some(Boolean)) {
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
