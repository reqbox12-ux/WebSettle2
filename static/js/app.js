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
    const headers = { 'Authorization': 'Bearer ' + token, ...(opts.headers || {}) };
    if (!(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    const resp = await fetch(path, { ...opts, headers });
    if (resp.status === 401) { logout(); return null; }
    return resp;
  }

  window.logout = function () {
    localStorage.removeItem('ws2_token');
    document.cookie = 'ws2_token=;path=/;max-age=0';
    location.href = '/login';
  };

  // ── 토스트 ─────────────────────────────────────────────────
  window.showToast = function (msg, type = 'ok') {
    const old = document.getElementById('toast'); if (old) old.remove();
    const t = document.createElement('div');
    t.id = 'toast';
    t.textContent = msg;
    t.style.cssText = `position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
      background:${type === 'err' ? '#E60028' : '#1F1B1B'};color:#fff;padding:12px 22px;
      border-radius:10px;font-size:13.5px;font-weight:600;z-index:9999;
      box-shadow:0 6px 24px rgba(0,0,0,.3);max-width:90vw`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
  };

  const fmtWon = (v) => Math.round(v || 0).toLocaleString();
  const now = new Date();
  let selYear  = now.getFullYear();
  let selMonth = now.getMonth() + 1;

  // 메타 캐시 (지점/계정과목)
  let META = { branches: [], categories: [] };
  async function loadMeta() {
    if (META.branches.length) return META;
    const r = await api('/api/meta');
    if (r && r.ok) META = await r.json();
    return META;
  }

  function ymFilter(onChange) {
    const yrs = [];
    for (let y = now.getFullYear(); y >= now.getFullYear() - 3; y--) yrs.push(y);
    setTimeout(() => {
      const y = document.getElementById('f-yr'), m = document.getElementById('f-mn');
      if (y) y.addEventListener('change', e => { selYear = +e.target.value; onChange(); });
      if (m) m.addEventListener('change', e => { selMonth = +e.target.value; onChange(); });
    }, 0);
    return `
      <select id="f-yr">${yrs.map(y => `<option value="${y}" ${y === selYear ? 'selected' : ''}>${y}년</option>`).join('')}</select>
      <select id="f-mn">${Array.from({length:12},(_,i)=>i+1).map(m => `<option value="${m}" ${m === selMonth ? 'selected' : ''}>${m}월</option>`).join('')}</select>`;
  }

  // ── 페이지 정의 ────────────────────────────────────────────
  const PAGES = {
    dashboard:  { label: '대시보드',   icon: 'layout-grid',  sec: 'WORKSPACE' },
    branch:     { label: '지점',       icon: 'building-2',   sec: '관리' },
    attendance: { label: '출퇴근 현황', icon: 'clock',        sec: '관리' },
    employees:  { label: '직원',       icon: 'users',        sec: '관리' },
    upload:     { label: '데이터 업로드', icon: 'upload',     sec: '데이터' },
    settings:   { label: '설정',       icon: 'settings',     sec: '데이터' },
  };
  let currentPage = 'dashboard';

  // ── 셸 렌더 ────────────────────────────────────────────────
  function renderShell() {
    let nav = '', lastSec = '';
    for (const [k, c] of Object.entries(PAGES)) {
      if (c.sec !== lastSec) { nav += `<div class="sb-sec">${c.sec}</div>`; lastSec = c.sec; }
      nav += `<div class="sb-item ${k === currentPage ? 'on' : ''}" onclick="nav('${k}')">
        <i data-lucide="${c.icon}"></i><span>${c.label}</span></div>`;
    }
    document.getElementById('app-root').innerHTML = `
      <div class="app">
        <nav class="sidebar">
          <div class="sb-logo"><img src="/static/img/logo.png" alt="LAONSPORTS"
            style="height:34px;object-fit:contain"></div>
          <div class="sb-nav">${nav}</div>
          <div class="sb-foot">
            ${user.name} (${user.role === 'admin' ? '관리자' : '사용자'})<br>
            <a onclick="logout()">🚪 로그아웃</a>
          </div>
        </nav>
        <main class="main" id="page-content"></main>
        <nav class="bnav">
          ${Object.entries(PAGES).slice(0, 5).map(([k, c]) => `
            <div class="${k === currentPage ? 'on' : ''}" onclick="nav('${k}')">
              <i data-lucide="${c.icon}"></i><span>${c.label}</span></div>`).join('')}
        </nav>
      </div>`;
    if (window.lucide) lucide.createIcons();
    renderPage();
  }

  window.nav = function (page) { currentPage = page; renderShell(); };

  function renderPage() {
    const el = document.getElementById('page-content');
    ({ dashboard: renderDashboard, branch: renderBranch, attendance: renderAttendance,
       employees: renderEmployees, upload: renderUpload, settings: renderSettings,
    }[currentPage] || (() => { el.innerHTML = '<div class="empty">준비 중</div>'; }))(el);
  }

  /* ════ 대시보드 ════════════════════════════════════════════ */
  async function renderDashboard(el) {
    el.innerHTML = `
      <div class="ph"><div class="ph-title">대시보드</div>
        <div class="ph-sub">전월·전년 대비 및 지점별 손익</div></div>
      <div class="filter-bar">${ymFilter(loadDashboard)}
        <button class="xbtn" onclick="dlSummary()">📥 Excel</button></div>
      <div id="dash-body"><div class="empty">로드 중…</div></div>`;
    loadDashboard();
  }

  window.dlSummary = async function () {
    const r = await api(`/api/summary/excel?year=${selYear}&month=${selMonth}`);
    if (!r || !r.ok) { showToast('데이터가 없습니다', 'err'); return; }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `손익현황_${selYear}년${String(selMonth).padStart(2,'0')}월.xlsx`;
    a.click();
  };

  function deltaBadge(cur, prev, lbl) {
    if (!prev && prev !== 0) return '';
    const d = cur - prev;
    const cls = d >= 0 ? 'pos' : 'neg';
    return `<div style="font-size:11px;margin-top:6px;color:var(--ink3)">
      ${lbl} <span class="bdg ${cls}" style="font-size:10.5px;padding:1px 7px">
      ${d >= 0 ? '▲' : '▼'} ${fmtWon(Math.abs(d))}</span></div>`;
  }

  async function loadDashboard() {
    const body = document.getElementById('dash-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';
    const resp = await api(`/api/summary?year=${selYear}&month=${selMonth}`);
    if (!resp) return;
    const { rows = [], totals = {}, prev = {}, yoy = {} } = await resp.json();
    if (!rows.length) { body.innerHTML = '<div class="empty">📭 해당 월 데이터가 없습니다</div>'; return; }

    const pnl = totals['손익'] || 0;
    body.innerHTML = `
      <div class="kpi-grid">
        <div class="kpi"><div class="kpi-lbl">총매출</div>
          <div class="kpi-val">${fmtWon(totals['총매출'])}원</div>
          ${deltaBadge(totals['총매출'], prev['총매출'], '전월')}
          ${deltaBadge(totals['총매출'], yoy['총매출'], '전년')}</div>
        <div class="kpi"><div class="kpi-lbl">총지출</div>
          <div class="kpi-val">${fmtWon(totals['총지출'])}원</div>
          ${deltaBadge(totals['총지출'], prev['총지출'], '전월')}</div>
        <div class="kpi"><div class="kpi-lbl">손익</div>
          <div class="kpi-val ${pnl >= 0 ? 'pos' : 'neg'}">${pnl >= 0 ? '+' : ''}${fmtWon(pnl)}원</div>
          ${deltaBadge(pnl, prev['손익'], '전월')}
          ${deltaBadge(pnl, yoy['손익'], '전년')}</div>
        <div class="kpi"><div class="kpi-lbl">이익률</div>
          <div class="kpi-val ${(totals['이익률']||0) >= 0 ? 'pos' : 'neg'}">${totals['이익률'] || 0}%</div></div>
      </div>
      <div class="card"><div class="card-head">연간 추이 (1월~${selMonth}월)</div>
        <div style="padding:14px 20px"><canvas id="trend-chart" height="90"></canvas></div></div>
      <div class="card"><div class="card-head">${selYear}년 ${selMonth}월 · 지점별 손익</div>
        <div style="overflow-x:auto;padding:8px 0 4px">
          <table class="tbl">
            <thead><tr><th>지점</th><th>총매출</th><th>총지출</th><th>손익</th><th>이익률</th></tr></thead>
            <tbody>${rows.map(r => {
              const p = Math.round(r['손익'] || 0), rt = r['이익률'] || 0;
              return `<tr><td>${r.branch}</td>
                <td>${fmtWon(r['총매출'])}</td><td>${fmtWon(r['총지출'])}</td>
                <td><span class="bdg ${p >= 0 ? 'pos' : 'neg'}">${p >= 0 ? '▲' : '▼'} ${fmtWon(Math.abs(p))}</span></td>
                <td style="color:${rt >= 0 ? 'var(--pos)' : 'var(--red)'};font-weight:700">${rt >= 0 ? '+' : ''}${rt}%</td></tr>`;
            }).join('')}</tbody>
          </table></div></div>`;

    // 추이 차트 (고정형 — 애니메이션·인터랙션 OFF)
    const tr = await api(`/api/summary/trend?year=${selYear}&month=${selMonth}`);
    if (tr && tr.ok) {
      const t = await tr.json();
      const ctx = document.getElementById('trend-chart');
      if (ctx && t.months.length && window.Chart) {
        new Chart(ctx, {
          type: 'line',
          data: { labels: t.months.map(m => m + '월'),
            datasets: [
              { label: '총매출', data: t.revenue, borderColor: '#3D3835', backgroundColor: '#3D3835', tension: .3 },
              { label: '손익',   data: t.profit,  borderColor: '#2E7D5B', backgroundColor: '#2E7D5B', tension: .3 },
            ]},
          options: { animation: false, events: [], responsive: true,
            plugins: { legend: { position: 'top', align: 'end' } },
            scales: { y: { ticks: { callback: v => (v/10000).toLocaleString() + '만' } } } }
        });
      }
    }
  }

  /* ════ 지점 상세 ═══════════════════════════════════════════ */
  let selBranch = '';

  async function renderBranch(el) {
    const r = await api('/api/branches');
    const branches = r && r.ok ? await r.json() : [];
    if (!selBranch && branches.length) selBranch = branches[0];
    el.innerHTML = `
      <div class="ph"><div class="ph-title">지점 상세</div>
        <div class="ph-sub">손익계산서 · 목표 매출</div></div>
      <div class="filter-bar">${ymFilter(loadBranch)}
        <select id="f-br">${branches.map(b => `<option ${b === selBranch ? 'selected' : ''}>${b}</option>`).join('')}</select>
      </div>
      <div id="br-body"><div class="empty">로드 중…</div></div>`;
    document.getElementById('f-br').addEventListener('change', e => { selBranch = e.target.value; loadBranch(); });
    loadBranch();
  }

  async function loadBranch() {
    const body = document.getElementById('br-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';
    const r = await api(`/api/branch/pnl?year=${selYear}&month=${selMonth}&branch=${encodeURIComponent(selBranch)}`);
    if (!r || !r.ok) { body.innerHTML = '<div class="empty">오류</div>'; return; }
    const { summary: s = {}, rev_by_cat = {}, exp_by_cat = {}, goal = 0 } = await r.json();
    if (!s.branch) { body.innerHTML = '<div class="empty">📭 해당 지점 데이터가 없습니다</div>'; return; }

    const pnl = Math.round(s['손익'] || 0);
    const rev = Math.round(s['총매출'] || 0);
    const achieve = goal > 0 ? (rev / goal * 100) : 0;
    const aColor = achieve >= 100 ? 'var(--pos)' : (achieve >= 70 ? '#B86E1F' : 'var(--red)');

    const catRows = (obj) => Object.entries(obj).sort((a,b) => b[1]-a[1])
      .map(([k, v]) => `<div class="pnl-row"><span>${k}</span><span>${fmtWon(v)}</span></div>`).join('')
      || '<div class="pnl-row" style="color:var(--ink3)">내역 없음</div>';

    body.innerHTML = `
      <div class="kpi-grid">
        <div class="kpi"><div class="kpi-lbl">총매출</div><div class="kpi-val">${fmtWon(rev)}원</div></div>
        <div class="kpi"><div class="kpi-lbl">총지출</div><div class="kpi-val">${fmtWon(s['총지출'])}원</div></div>
        <div class="kpi"><div class="kpi-lbl">손익</div>
          <div class="kpi-val ${pnl >= 0 ? 'pos' : 'neg'}">${pnl >= 0 ? '+' : ''}${fmtWon(pnl)}원</div></div>
        <div class="kpi"><div class="kpi-lbl">이익률</div>
          <div class="kpi-val ${(s['이익률']||0) >= 0 ? 'pos' : 'neg'}">${s['이익률'] || 0}%</div></div>
      </div>

      <div class="card" style="padding:16px 20px">
        <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
          <span style="font-size:13px;font-weight:700">🎯 목표 매출</span>
          <input id="goal-input" type="number" value="${goal}" step="1000000" min="0"
            style="padding:8px 12px;border:1.5px solid var(--bds);border-radius:8px;width:160px;
            background:transparent;color:var(--ink);font-size:13.5px">
          <button class="xbtn" onclick="saveGoal()">저장</button>
          ${goal > 0 ? `
            <span style="font-size:12px;color:var(--ink3)">달성률</span>
            <span style="font-size:17px;font-weight:800;color:${aColor}">${achieve.toFixed(1)}%</span>
            <div style="flex:1;min-width:120px;background:var(--sf2);border-radius:999px;height:8px;overflow:hidden">
              <div style="width:${Math.min(achieve,100).toFixed(1)}%;height:100%;background:${aColor}"></div></div>` : ''}
        </div>
      </div>

      <div class="pnl-cols">
        <div class="card" style="padding:18px 20px">
          <div style="font-size:13px;font-weight:800;color:var(--pos);margin-bottom:10px">매출 (카테고리별)</div>
          ${catRows(rev_by_cat)}
          <div class="pnl-row tot"><span>총매출</span><span>${fmtWon(rev)}</span></div>
        </div>
        <div class="card" style="padding:18px 20px">
          <div style="font-size:13px;font-weight:800;color:var(--red);margin-bottom:10px">지출 (카테고리별)</div>
          <div class="pnl-row"><span>인건비합계</span><span>${fmtWon(s['인건비합계'])}</span></div>
          <div class="pnl-row"><span>부가세합계</span><span>${fmtWon(s['부가세합계'])}</span></div>
          ${catRows(exp_by_cat)}
          <div class="pnl-row tot"><span>총지출</span><span>${fmtWon(s['총지출'])}</span></div>
        </div>
      </div>`;
  }

  window.saveGoal = async function () {
    const v = parseInt(document.getElementById('goal-input').value) || 0;
    const r = await api('/api/branch/goal', { method: 'POST',
      body: JSON.stringify({ year: selYear, month: selMonth, branch: selBranch, goal: v }) });
    if (r && r.ok) { showToast('🎯 목표 저장 완료'); loadBranch(); }
    else showToast('저장 실패', 'err');
  };

  /* ════ 출퇴근 현황 ═════════════════════════════════════════ */
  let attBranch = '';

  async function renderAttendance(el) {
    const r = await api('/api/attendance/branches');
    const branches = r && r.ok ? await r.json() : [];
    el.innerHTML = `
      <div class="ph"><div class="ph-title">출퇴근 현황</div>
        <div class="ph-sub">직원 근태를 월별·지점별로 조회합니다</div></div>
      <div class="filter-bar">${ymFilter(loadAttendance)}
        <select id="f-att-br"><option value="">전체 지점</option>
          ${branches.map(b => `<option ${b === attBranch ? 'selected' : ''}>${b}</option>`).join('')}</select>
      </div>
      <div id="att-body"><div class="empty">로드 중…</div></div>`;
    document.getElementById('f-att-br').addEventListener('change', e => { attBranch = e.target.value; loadAttendance(); });
    loadAttendance();
  }

  async function loadAttendance() {
    const body = document.getElementById('att-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';
    const r = await api(`/api/attendance?year=${selYear}&month=${selMonth}&branch=${encodeURIComponent(attBranch)}`);
    if (!r || !r.ok) { body.innerHTML = '<div class="empty">오류</div>'; return; }
    const rows = await r.json();
    if (!rows.length) { body.innerHTML = '<div class="empty">📭 출퇴근 기록이 없습니다</div>'; return; }

    const names = new Set(rows.map(x => x.name));
    const totMin = rows.reduce((s, x) => s + (x.work_minutes || 0), 0);
    const lateCnt = rows.filter(x => x.status === 'late').length;
    const fmtMin = m => m ? `${Math.floor(m/60)}h ${String(m%60).padStart(2,'0')}m` : '—';

    body.innerHTML = `
      <div class="kpi-grid">
        <div class="kpi"><div class="kpi-lbl">출근 직원</div><div class="kpi-val">${names.size}명</div></div>
        <div class="kpi"><div class="kpi-lbl">총 출근</div><div class="kpi-val">${rows.length}건</div></div>
        <div class="kpi"><div class="kpi-lbl">누적 근무</div><div class="kpi-val">${Math.floor(totMin/60)}h</div></div>
        <div class="kpi"><div class="kpi-lbl">지각</div>
          <div class="kpi-val ${lateCnt ? 'neg' : ''}">${lateCnt}건</div></div>
      </div>
      <div class="card"><div class="card-head">상세 내역 (${rows.length}건)</div>
        <div style="overflow-x:auto;padding:8px 0 4px">
          <table class="tbl">
            <thead><tr><th>날짜</th><th>지점</th><th>이름</th><th>출근</th><th>퇴근</th><th>근무</th><th>휴게</th><th>상태</th></tr></thead>
            <tbody>${rows.map(x => `<tr>
              <td>${x.work_date}</td><td style="text-align:left">${x.branch || '—'}</td>
              <td style="text-align:left">${x.name}</td>
              <td>${x.clock_in || '—'}</td><td>${x.clock_out || '—'}</td>
              <td>${fmtMin(x.work_minutes)}</td><td>${fmtMin(x.break_minutes)}</td>
              <td>${x.status === 'late' ? '<span class="bdg neg">지각</span>' : '<span class="bdg pos">정상</span>'}</td>
            </tr>`).join('')}</tbody>
          </table></div></div>`;
  }

  /* ════ 직원 목록 ═══════════════════════════════════════════ */
  async function renderEmployees(el) {
    el.innerHTML = `
      <div class="ph"><div class="ph-title">직원</div>
        <div class="ph-sub">직원 마스터 조회 · 등록/수정은 기존 ERP(인사/급여)에서</div></div>
      <div id="emp-body"><div class="empty">로드 중…</div></div>`;
    const r = await api('/api/employees');
    if (!r || !r.ok) return;
    const emps = await r.json();
    const typeLbl = { insured: '4대보험', freelance: '프리랜서', business: '사업자', hourly: '시급제' };
    document.getElementById('emp-body').innerHTML = `
      <div class="card"><div class="card-head">전체 직원 ${emps.length}명</div>
        <div style="overflow-x:auto;padding:8px 0 4px">
          <table class="tbl">
            <thead><tr><th>이름</th><th>지점</th><th>유형</th><th>전화번호</th><th>이메일</th><th>입사일</th></tr></thead>
            <tbody>${emps.map(e => `<tr>
              <td>${e.name}</td><td style="text-align:left">${e.branch || '—'}</td>
              <td style="text-align:left">${typeLbl[e.emp_type] || e.emp_type || '—'}</td>
              <td>${e.phone || '—'}</td><td style="text-align:left">${e.email || '—'}</td>
              <td>${e.join_date || '—'}</td></tr>`).join('')}</tbody>
          </table></div></div>`;
  }

  /* ════ 데이터 업로드 ═══════════════════════════════════════ */
  async function renderUpload(el) {
    el.innerHTML = `
      <div class="ph"><div class="ph-title">데이터 업로드</div>
        <div class="ph-sub">같은 연월 재업로드 시 기존 데이터가 교체됩니다</div></div>
      <div class="filter-bar">${ymFilter(() => {})}</div>

      <div class="up-grid">
        <div class="card" style="padding:18px 20px">
          <div style="font-weight:800;margin-bottom:4px">💳 카드 매출</div>
          <div style="font-size:12px;color:var(--ink3);margin-bottom:12px">카드사 결과 집계 / 신용카드</div>
          <select id="card-kind" style="margin-bottom:8px">
            <option value="aggregate">카드사 결과 집계 조회</option>
            <option value="credit">신용카드</option></select>
          <input type="file" id="card-file" accept=".xlsx">
          <button class="xbtn primary" onclick="upCard()">업로드</button>
        </div>

        <div class="card" style="padding:18px 20px">
          <div style="font-weight:800;margin-bottom:4px">🏦 통장 내역</div>
          <div style="font-size:12px;color:var(--ink3);margin-bottom:12px">하나 / 신한 (해당 은행만 교체)</div>
          <select id="bank-kind" style="margin-bottom:8px">
            <option value="hana">🟩 하나은행</option>
            <option value="shinhan">🟦 신한은행</option></select>
          <input type="file" id="bank-file" accept=".xlsx">
          <button class="xbtn primary" onclick="upBank()">업로드</button>
        </div>

        <div class="card" style="padding:18px 20px">
          <div style="font-weight:800;margin-bottom:4px">💰 급여</div>
          <div style="font-size:12px;color:var(--ink3);margin-bottom:12px">시트: 지점별집계(4대보험) / 사업소득자</div>
          <input type="file" id="pay-file" accept=".xlsx,.xls">
          <button class="xbtn primary" onclick="upPayroll()">업로드</button>
        </div>

        <div class="card" style="padding:18px 20px">
          <div style="font-weight:800;margin-bottom:4px">🗑️ 데이터 삭제</div>
          <div style="font-size:12px;color:var(--ink3);margin-bottom:12px">선택 연월 데이터 삭제 (재업로드용)</div>
          <button class="xbtn" onclick="delData('card')" style="margin-bottom:6px">카드매출 삭제</button>
          <button class="xbtn" onclick="delData('bank')">통장내역 삭제</button>
        </div>
      </div>
      <div id="up-result"></div>
      <div class="card" style="padding:14px 20px;font-size:12.5px;color:var(--ink3)">
        💡 4대보험 고지내역·백업/복원은 기존 ERP(데이터 업로드)에서 계속 이용하세요.</div>`;
  }

  function upResult(html, isErr) {
    document.getElementById('up-result').innerHTML =
      `<div class="card" style="padding:14px 18px;font-size:13.5px;
        color:${isErr ? 'var(--red)' : 'var(--pos)'};font-weight:600">${html}</div>`;
  }

  async function doUpload(url, fileId, extra = {}) {
    const f = document.getElementById(fileId).files[0];
    if (!f) { showToast('파일을 선택하세요', 'err'); return; }
    const fd = new FormData();
    fd.append('year', selYear); fd.append('month', selMonth); fd.append('file', f);
    for (const [k, v] of Object.entries(extra)) fd.append(k, v);
    upResult('⏳ 처리 중…');
    const r = await api(url, { method: 'POST', body: fd });
    const d = r ? await r.json().catch(() => ({})) : {};
    if (r && r.ok) return d;
    upResult('❌ ' + (d.detail || '업로드 실패'), true);
    return null;
  }

  window.upCard = async function () {
    const kind = document.getElementById('card-kind').value;
    const d = await doUpload('/api/upload/card', 'card-file', { kind });
    if (d) upResult(`✅ 카드매출 ${d.count}건 저장 완료` + (d.unmapped ? ` (미매핑 ${d.unmapped}건)` : ''));
  };
  window.upBank = async function () {
    const bank = document.getElementById('bank-kind').value;
    const d = await doUpload('/api/upload/bank', 'bank-file', { bank });
    if (d) upResult(`✅ 통장내역 ${d.count}건 저장 (자동분류 ${d.auto}건 / 미분류 ${d.review}건)` +
      (d.review ? ' — 설정 → 미분류 검토에서 확인하세요' : ''));
  };
  window.upPayroll = async function () {
    const d = await doUpload('/api/upload/payroll', 'pay-file');
    if (d) upResult(`✅ 급여 저장 완료 — ${d.msg}`);
  };
  window.delData = async function (kind) {
    if (!confirm(`${selYear}년 ${selMonth}월 ${kind === 'card' ? '카드매출' : '통장내역'}을 삭제할까요?`)) return;
    const r = await api(`/api/upload/${kind}?year=${selYear}&month=${selMonth}`, { method: 'DELETE' });
    if (r && r.ok) upResult(`✅ ${selYear}년 ${selMonth}월 삭제 완료`);
  };

  /* ════ 설정 (미분류 검토 + 규칙) ═══════════════════════════ */
  let setTab = 'review';

  async function renderSettings(el) {
    await loadMeta();
    el.innerHTML = `
      <div class="ph"><div class="ph-title">설정</div>
        <div class="ph-sub">미분류 거래 검토 · 키워드 규칙 관리</div></div>
      <div class="filter-bar" style="gap:6px">
        <button class="xbtn ${setTab === 'review' ? 'primary' : ''}" onclick="setTabGo('review')">미분류 검토</button>
        <button class="xbtn ${setTab === 'rules' ? 'primary' : ''}" onclick="setTabGo('rules')">규칙 목록</button>
        ${setTab === 'review' ? ymFilter(loadSettings) : ''}
      </div>
      <div id="set-body"><div class="empty">로드 중…</div></div>`;
    loadSettings();
  }

  window.setTabGo = function (t) { setTab = t; renderSettings(document.getElementById('page-content')); };

  async function loadSettings() {
    const body = document.getElementById('set-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';

    if (setTab === 'review') {
      const r = await api(`/api/rules/transactions?year=${selYear}&month=${selMonth}&unclassified=1`);
      if (!r || !r.ok) return;
      const txs = await r.json();
      if (!txs.length) { body.innerHTML = '<div class="empty">✅ 미분류 거래가 없습니다</div>'; return; }

      const brOpts  = ['', ...META.branches].map(b => `<option value="${b}">${b || '— 지점 —'}</option>`).join('');
      const catOpts = ['', ...META.categories].map(c => `<option value="${c}">${c || '— 계정 —'}</option>`).join('');

      body.innerHTML = `
        <div class="card"><div class="card-head">미분류 ${txs.length}건</div>
          <div style="padding:8px 16px 16px">
            ${txs.map(t => `
              <div class="rv-row" id="rv-${t.id}">
                <div class="rv-info">
                  <b>[${t.tx_date}]</b> ${t.description}
                  <span style="color:${t.deposit ? 'var(--pos)' : 'var(--red)'};font-weight:700">
                    ${t.deposit ? '입금 ' + fmtWon(t.deposit) : '출금 ' + fmtWon(t.withdrawal)}</span>
                  <span style="color:var(--ink3);font-size:11px">${t.bank}</span>
                </div>
                <div class="rv-ctl">
                  <select id="br-${t.id}">${brOpts}</select>
                  <select id="cat-${t.id}">${catOpts}</select>
                  <label style="font-size:11.5px;display:flex;align-items:center;gap:4px">
                    <input type="checkbox" id="rule-${t.id}"> 규칙</label>
                  <button class="xbtn primary sm" onclick="saveClassify(${t.id},'${t.bank}','${(t.description||'').replace(/'/g,'')}')">저장</button>
                </div>
              </div>`).join('')}
          </div></div>`;
    } else {
      const r = await api('/api/rules');
      if (!r || !r.ok) return;
      const rules = await r.json();
      const brOpts  = META.branches.map(b => `<option>${b}</option>`).join('');
      const catOpts = META.categories.map(c => `<option>${c}</option>`).join('');
      body.innerHTML = `
        <div class="card" style="padding:16px 20px">
          <div style="font-weight:800;margin-bottom:10px">➕ 새 규칙</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <select id="nr-bank"><option value="hana">하나</option><option value="shinhan">신한</option></select>
            <input id="nr-kw" placeholder="키워드" style="padding:8px 12px;border:1.5px solid var(--bds);
              border-radius:8px;background:transparent;color:var(--ink)">
            <select id="nr-br">${brOpts}</select>
            <select id="nr-cat">${catOpts}</select>
            <button class="xbtn primary" onclick="addRule()">추가</button>
          </div></div>
        <div class="card"><div class="card-head">규칙 ${rules.length}개</div>
          <div style="overflow-x:auto;padding:8px 0 4px">
            <table class="tbl">
              <thead><tr><th>은행</th><th>키워드</th><th>지점</th><th>계정</th><th>적중</th><th></th></tr></thead>
              <tbody>${rules.map(r2 => `<tr>
                <td style="text-align:left">${r2.bank}</td>
                <td style="text-align:left"><code>${r2.keyword}</code></td>
                <td style="text-align:left">${r2.branch}</td>
                <td style="text-align:left">${r2.category}</td>
                <td>${r2.hit_count || 0}</td>
                <td><button class="xbtn sm" onclick="delRule(${r2.id})">🗑️</button></td>
              </tr>`).join('')}</tbody>
            </table></div></div>`;
    }
  }

  window.saveClassify = async function (id, bank, desc) {
    const br  = document.getElementById(`br-${id}`).value;
    const cat = document.getElementById(`cat-${id}`).value;
    if (!br || !cat) { showToast('지점과 계정을 선택하세요', 'err'); return; }
    const addRuleChk = document.getElementById(`rule-${id}`).checked;
    const r = await api('/api/rules/classify', { method: 'POST',
      body: JSON.stringify({ tx_id: id, branch: br, category: cat,
        add_rule: addRuleChk, bank, keyword: desc.slice(0, 12) }) });
    if (r && r.ok) {
      document.getElementById(`rv-${id}`).style.display = 'none';
      showToast('✅ 분류 저장' + (addRuleChk ? ' + 규칙 추가' : ''));
    } else showToast('저장 실패', 'err');
  };

  window.addRule = async function () {
    const body = {
      bank: document.getElementById('nr-bank').value,
      keyword: document.getElementById('nr-kw').value.trim(),
      branch: document.getElementById('nr-br').value,
      category: document.getElementById('nr-cat').value,
    };
    if (!body.keyword) { showToast('키워드를 입력하세요', 'err'); return; }
    const r = await api('/api/rules', { method: 'POST', body: JSON.stringify(body) });
    if (r && r.ok) { showToast('✅ 규칙 추가'); loadSettings(); }
  };

  window.delRule = async function (id) {
    if (!confirm('이 규칙을 삭제할까요?')) return;
    const r = await api(`/api/rules/${id}`, { method: 'DELETE' });
    if (r && r.ok) { showToast('삭제 완료'); loadSettings(); }
  };

  renderShell();
})();
