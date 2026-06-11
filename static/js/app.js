/* ═══ WebSettle2 메인 앱 ═══════════════════════════════════════ */
(function () {
  'use strict';

  const token = localStorage.getItem('ws2_token');
  if (!token) { location.href = '/login'; return; }

  const user = {
    name: localStorage.getItem('ws2_name') || '',
    role: localStorage.getItem('ws2_role') || 'user',
  };

  async function api(path, opts = {}) {
    const resp = await fetch(path, {
      ...opts,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
        ...(opts.headers || {}),
      },
    });
    if (resp.status === 401) { logout(); return null; }
    return resp;
  }

  window.logout = function () {
    localStorage.removeItem('ws2_token');
    document.cookie = 'ws2_token=;path=/;max-age=0';
    location.href = '/login';
  };

  // ── 페이지 정의 ────────────────────────────────────────────
  const PAGES = {
    dashboard: { label: '대시보드', icon: 'layout-grid' },
    // 추후: branch, payroll, attendance, upload, settings
  };
  let currentPage = 'dashboard';

  // ── 셸 렌더 ────────────────────────────────────────────────
  function renderShell() {
    const nav = Object.entries(PAGES).map(([k, c]) => `
      <div class="sb-item ${k === currentPage ? 'on' : ''}" onclick="nav('${k}')">
        <i data-lucide="${c.icon}"></i><span>${c.label}</span>
      </div>`).join('');

    document.getElementById('app-root').innerHTML = `
      <div class="app">
        <nav class="sidebar">
          <div class="sb-logo">LAON<span>SPORTS</span></div>
          <div class="sb-nav">
            <div class="sb-sec">WORKSPACE</div>
            ${nav}
          </div>
          <div class="sb-foot">
            ${user.name} (${user.role === 'admin' ? '관리자' : '사용자'})<br>
            <a onclick="logout()">🚪 로그아웃</a>
          </div>
        </nav>
        <main class="main" id="page-content"></main>
        <nav class="bnav">
          ${Object.entries(PAGES).map(([k, c]) => `
            <div class="${k === currentPage ? 'on' : ''}" onclick="nav('${k}')">
              <i data-lucide="${c.icon}"></i><span>${c.label}</span>
            </div>`).join('')}
        </nav>
      </div>`;
    if (window.lucide) lucide.createIcons();
    renderPage();
  }

  window.nav = function (page) {
    currentPage = page;
    renderShell();
  };

  function renderPage() {
    const el = document.getElementById('page-content');
    if (currentPage === 'dashboard') renderDashboard(el);
    else el.innerHTML = '<div class="empty">준비 중인 페이지입니다</div>';
  }

  // ── 대시보드 ───────────────────────────────────────────────
  const now = new Date();
  let selYear  = now.getFullYear();
  let selMonth = now.getMonth() + 1;

  const fmtWon = (v) => (v || 0).toLocaleString();

  async function renderDashboard(el) {
    const yrs = [];
    for (let y = now.getFullYear(); y >= now.getFullYear() - 3; y--) yrs.push(y);

    el.innerHTML = `
      <div class="ph">
        <div class="ph-title">대시보드</div>
        <div class="ph-sub">연·월을 선택하면 지점별 손익이 표시됩니다</div>
      </div>
      <div class="filter-bar">
        <select id="f-yr">${yrs.map(y => `<option value="${y}" ${y === selYear ? 'selected' : ''}>${y}년</option>`).join('')}</select>
        <select id="f-mn">${Array.from({length:12},(_,i)=>i+1).map(m => `<option value="${m}" ${m === selMonth ? 'selected' : ''}>${m}월</option>`).join('')}</select>
      </div>
      <div id="dash-body"><div class="empty">데이터 로드 중…</div></div>`;

    document.getElementById('f-yr').addEventListener('change', e => { selYear  = +e.target.value; loadDashboard(); });
    document.getElementById('f-mn').addEventListener('change', e => { selMonth = +e.target.value; loadDashboard(); });
    loadDashboard();
  }

  async function loadDashboard() {
    const body = document.getElementById('dash-body');
    body.innerHTML = '<div class="empty">데이터 로드 중…</div>';
    try {
      const resp = await api(`/api/summary?year=${selYear}&month=${selMonth}`);
      if (!resp) return;
      const data = await resp.json();
      const { rows = [], totals = {} } = data;

      if (!rows.length) {
        body.innerHTML = '<div class="empty">📭 해당 월 데이터가 없습니다</div>';
        return;
      }

      const pnl = totals['손익'] || 0;
      body.innerHTML = `
        <div class="kpi-grid">
          <div class="kpi"><div class="kpi-lbl">총매출</div><div class="kpi-val">${fmtWon(totals['총매출'])}원</div></div>
          <div class="kpi"><div class="kpi-lbl">총지출</div><div class="kpi-val">${fmtWon(totals['총지출'])}원</div></div>
          <div class="kpi"><div class="kpi-lbl">손익</div><div class="kpi-val ${pnl >= 0 ? 'pos' : 'neg'}">${pnl >= 0 ? '+' : ''}${fmtWon(pnl)}원</div></div>
          <div class="kpi"><div class="kpi-lbl">이익률</div><div class="kpi-val ${(totals['이익률']||0) >= 0 ? 'pos' : 'neg'}">${totals['이익률'] || 0}%</div></div>
        </div>
        <div class="card">
          <div class="card-head">${selYear}년 ${selMonth}월 · 지점별 손익</div>
          <div style="overflow-x:auto;padding:8px 0 4px">
            <table class="tbl">
              <thead><tr>
                <th>지점</th><th>총매출</th><th>총지출</th><th>손익</th><th>이익률</th>
              </tr></thead>
              <tbody>
                ${rows.map(r => {
                  const p = Math.round(r['손익'] || 0);
                  const rt = r['이익률'] || 0;
                  return `<tr>
                    <td>${r.branch}</td>
                    <td>${fmtWon(Math.round(r['총매출']))}</td>
                    <td>${fmtWon(Math.round(r['총지출']))}</td>
                    <td><span class="bdg ${p >= 0 ? 'pos' : 'neg'}">${p >= 0 ? '▲' : '▼'} ${fmtWon(Math.abs(p))}</span></td>
                    <td style="color:${rt >= 0 ? 'var(--pos)' : 'var(--red)'};font-weight:700">${rt >= 0 ? '+' : ''}${rt}%</td>
                  </tr>`;
                }).join('')}
              </tbody>
            </table>
          </div>
        </div>`;
    } catch (err) {
      body.innerHTML = `<div class="empty">오류: ${err.message}</div>`;
    }
  }

  renderShell();
})();
