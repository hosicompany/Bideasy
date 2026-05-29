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

// 미완성 페이지 placeholder (Phase C~E 에서 구현)
['users', 'payments', 'autocalibrate', 'system', 'simulation'].forEach((name) => {
  pages[name] = function(content) {
    const phase = { users: 'C', payments: 'C', autocalibrate: 'D', system: 'D', simulation: 'E' }[name];
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
