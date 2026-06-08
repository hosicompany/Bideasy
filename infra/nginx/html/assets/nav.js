/* BidEasy 공통 네비게이션 바
 * - DOMContentLoaded 시 body 시작 직후 자동 삽입
 * - localStorage 토큰 확인 → GET /users/me 로 로그인 상태·is_admin 분기
 * - 햄버거 토글 + 현재 페이지 active 표시 + 로그아웃 처리
 *
 * 사용: <script src="/assets/nav.js" defer></script>
 * (HTML 에 mount point 불요 — 자동 삽입)
 */
(function () {
  const API_BASE = 'https://api.bideasy.kr/api/v1';

  const NAV_HTML = `
    <nav class="bd-nav" id="bd-nav">
      <div class="bd-nav-container">
        <a href="/" class="bd-nav-logo">BidEasy</a>
        <button class="bd-nav-toggle" id="bd-nav-toggle" aria-label="메뉴 열기">
          <span></span><span></span><span></span>
        </button>
        <div class="bd-nav-menu" id="bd-nav-menu">
          <ul class="bd-nav-links">
            <li><a href="/search" class="bd-nav-link" data-path="/search">공고 검색</a></li>
            <li><a href="/calculator" class="bd-nav-link" data-path="/calculator">계산기</a></li>
            <li><a href="/guide" class="bd-nav-link" data-path="/guide">사용 가이드</a></li>
            <li><a href="/pricing" class="bd-nav-link" data-path="/pricing">요금제</a></li>
          </ul>
          <div class="bd-nav-cta" id="bd-nav-cta">
            <!-- 로그인 상태에 따라 동적 -->
          </div>
        </div>
      </div>
    </nav>
  `;

  function getToken() {
    try {
      return (
        localStorage.getItem('access_token') ||
        localStorage.getItem('jwt') ||
        null
      );
    } catch {
      return null;
    }
  }

  function clearToken() {
    try {
      localStorage.removeItem('access_token');
      localStorage.removeItem('jwt');
    } catch {}
  }

  async function fetchMe(token) {
    try {
      const resp = await fetch(API_BASE + '/users/me', {
        headers: { Authorization: 'Bearer ' + token },
      });
      if (!resp.ok) return null;
      return await resp.json();
    } catch {
      return null;
    }
  }

  function renderCTA(user) {
    const cta = document.getElementById('bd-nav-cta');
    if (!cta) return;

    if (!user) {
      // 비로그인
      cta.innerHTML = `
        <a href="/login" class="bd-nav-link" data-path="/login">로그인</a>
        <a href="/signup" class="bd-nav-btn">14일 체험 시작</a>
      `;
    } else {
      // 로그인됨
      const adminLink = user.is_admin
        ? `<a href="/admin" class="bd-nav-link" data-path="/admin">Admin<span class="bd-nav-admin-badge">★</span></a>`
        : '';
      cta.innerHTML = `
        ${adminLink}
        <a href="/dashboard" class="bd-nav-link" data-path="/dashboard">대시보드</a>
        <a href="/favorites" class="bd-nav-link" data-path="/favorites">관심공고</a>
        <a href="/account" class="bd-nav-link" data-path="/account">마이페이지</a>
        <a href="#" class="bd-nav-link" id="bd-nav-logout">로그아웃</a>
      `;
      const logoutBtn = document.getElementById('bd-nav-logout');
      if (logoutBtn) {
        logoutBtn.addEventListener('click', (e) => {
          e.preventDefault();
          if (confirm('로그아웃하시겠어요?')) {
            clearToken();
            window.location.href = '/';
          }
        });
      }
    }

    // 현재 페이지 active 다시 적용 (CTA 안 링크 포함)
    markActive();
  }

  function markActive() {
    const path = window.location.pathname.replace(/\/$/, '') || '/';
    document.querySelectorAll('.bd-nav-link[data-path]').forEach((link) => {
      const p = link.dataset.path;
      if (p && (p === path || (p !== '/' && path.startsWith(p)))) {
        link.classList.add('active');
      }
    });
  }

  function setupHamburger() {
    const toggle = document.getElementById('bd-nav-toggle');
    const menu = document.getElementById('bd-nav-menu');
    if (!toggle || !menu) return;

    toggle.addEventListener('click', () => {
      menu.classList.toggle('active');
      toggle.classList.toggle('active');
      toggle.setAttribute(
        'aria-label',
        menu.classList.contains('active') ? '메뉴 닫기' : '메뉴 열기'
      );
    });

    // 모바일에서 링크 클릭 시 메뉴 자동 닫힘
    menu.addEventListener('click', (e) => {
      if (e.target.tagName === 'A' && menu.classList.contains('active')) {
        menu.classList.remove('active');
        toggle.classList.remove('active');
      }
    });
  }

  function init() {
    // 이미 nav 가 있으면 중복 삽입 방지 (개발 hot reload 대비)
    if (document.getElementById('bd-nav')) return;

    // body 시작 직후 삽입
    document.body.insertAdjacentHTML('afterbegin', NAV_HTML);

    setupHamburger();
    markActive();

    // 로그인 상태 확인 → CTA 렌더
    const token = getToken();
    if (token) {
      fetchMe(token).then((user) => renderCTA(user));
    } else {
      renderCTA(null);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
