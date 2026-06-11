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

  // ── 테마 ───────────────────────────────────────────────────
  const savedTheme = localStorage.getItem('ws2_theme');
  if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme);
  window.toggleTheme = function () {
    const cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', cur);
    localStorage.setItem('ws2_theme', cur);
    renderShell();
  };

  // ── 페이지 정의 ────────────────────────────────────────────
  const PAGES = {
    dashboard:  { label: '대시보드',   icon: 'layout-grid',  sec: 'WORKSPACE' },
    branch:     { label: '지점',       icon: 'building-2',   sec: '관리' },
    payroll:    { label: '인사/급여',  icon: 'credit-card',  sec: '관리' },
    attendance: { label: '출퇴근 현황', icon: 'clock',        sec: '관리' },
    upload:     { label: '데이터 업로드', icon: 'upload',     sec: '데이터' },
    settings:   { label: '설정',       icon: 'settings',     sec: '데이터' },
  };
  let currentPage = 'dashboard';

  // ── 셸 렌더 ────────────────────────────────────────────────
  function renderShell() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const unclf  = META.unclassified || 0;
    let nav = '', lastSec = '';
    for (const [k, c] of Object.entries(PAGES)) {
      if (c.sec !== lastSec) { nav += `<div class="sb-sec">${c.sec}</div>`; lastSec = c.sec; }
      const bdg = (k === 'settings' && unclf > 0)
        ? `<span style="margin-left:auto;background:var(--red);color:#fff;border-radius:999px;
            font-size:10px;font-weight:700;padding:1px 7px">${unclf}</span>` : '';
      nav += `<div class="sb-item ${k === currentPage ? 'on' : ''}" onclick="nav('${k}')">
        <i data-lucide="${c.icon}"></i><span>${c.label}</span>${bdg}</div>`;
    }
    document.getElementById('app-root').innerHTML = `
      <div class="app">
        <nav class="sidebar">
          <div class="sb-logo"><img src="/static/img/logo.png" alt="LAONSPORTS"
            style="height:34px;object-fit:contain"></div>
          <div class="sb-nav">${nav}</div>
          <div class="sb-foot">
            ${user.name} (${user.role === 'admin' ? '관리자' : '사용자'})<br>
            <a onclick="toggleTheme()">${isDark ? '☀️ 라이트 모드' : '🌙 다크 모드'}</a> ·
            <a onclick="logout()">🚪 로그아웃</a>
          </div>
        </nav>
        <main class="main" id="page-content"></main>
        <nav class="bnav">
          ${Object.entries(PAGES).filter(([k]) => k !== 'attendance').map(([k, c]) => `
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
       payroll: renderPayroll, upload: renderUpload, settings: renderSettings,
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

  /* ════ 지점 (상세/관리/매출입력) ═══════════════════════════ */
  let selBranch = '';
  let brTab = 'detail';

  async function renderBranch(el) {
    const r = await api('/api/branches');
    const branches = r && r.ok ? await r.json() : [];
    if (!selBranch && branches.length) selBranch = branches[0];
    el.innerHTML = `
      <div class="ph"><div class="ph-title">지점</div>
        <div class="ph-sub">손익계산서 · 지점 관리 · 월별 매출 입력</div></div>
      <div class="filter-bar" style="gap:6px">
        <button class="xbtn ${brTab === 'detail' ? 'primary' : ''}" onclick="brTabGo('detail')">📊 상세</button>
        <button class="xbtn ${brTab === 'mgmt' ? 'primary' : ''}" onclick="brTabGo('mgmt')">🏢 지점 관리</button>
        <button class="xbtn ${brTab === 'revenue' ? 'primary' : ''}" onclick="brTabGo('revenue')">📝 매출 입력</button>
        <button class="xbtn ${brTab === 'reports' ? 'primary' : ''}" onclick="brTabGo('reports')">📬 지점 보고</button>
      </div>
      ${brTab !== 'mgmt' ? `<div class="filter-bar">${ymFilter(loadBranchTab)}
        ${brTab === 'detail' ? `
          <select id="f-br">${branches.map(b => `<option ${b === selBranch ? 'selected' : ''}>${b}</option>`).join('')}</select>
          <button class="xbtn" onclick="dlPnl()">📥 정산서 Excel</button>` : ''}
      </div>` : ''}
      <div id="br-body"><div class="empty">로드 중…</div></div>`;
    const sel = document.getElementById('f-br');
    if (sel) sel.addEventListener('change', e => { selBranch = e.target.value; loadBranchTab(); });
    loadBranchTab();
  }

  window.brTabGo = function (t) { brTab = t; renderBranch(document.getElementById('page-content')); };

  function loadBranchTab() {
    if (brTab === 'detail')  return loadBranch();
    if (brTab === 'mgmt')    return loadBranchMgmt();
    if (brTab === 'revenue') return loadBmr();
    if (brTab === 'reports') return loadReports();
  }

  window.dlPnl = async function () {
    const r = await api(`/api/branch/pnl/excel?year=${selYear}&month=${selMonth}&branches=${encodeURIComponent(selBranch)}`);
    if (!r || !r.ok) { showToast('데이터가 없습니다', 'err'); return; }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `정산서_${selBranch}_${selYear}년${String(selMonth).padStart(2,'0')}월.xlsx`;
    a.click();
  };

  // ── 지점 관리 ──────────────────────────────────────────────
  let brList = [];
  let locSelId = 0;

  async function loadBranchMgmt() {
    const body = document.getElementById('br-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';
    const r = await api('/api/branch/list');
    if (!r || !r.ok) return;
    brList = await r.json();
    if (!locSelId && brList.length) locSelId = brList[0].id;

    body.innerHTML = `
      <div class="card"><div class="card-head">지점 목록 (${brList.length}개) ·
        위치 등록 ${brList.filter(b => b.lat && b.lng).length}/${brList.length}개</div>
        <div style="overflow-x:auto;padding:8px 0 4px">
          <table class="tbl">
            <thead><tr><th>지점명</th><th>계약일</th><th>해지일</th><th>재계약</th><th>주소</th>
              <th>위치</th><th>반경</th><th>비고</th><th></th></tr></thead>
            <tbody>${brList.map(b => `<tr>
              <td style="text-align:left"><input id="bn-${b.id}" value="${b.name || ''}" class="cell-in" style="width:125px"></td>
              <td><input id="bc-${b.id}" value="${b.contract_date || ''}" class="cell-in" style="width:95px"></td>
              <td><input id="bt-${b.id}" value="${b.termination_date || ''}" class="cell-in" style="width:95px"></td>
              <td><input type="checkbox" id="ba-${b.id}" ${b.is_active ? 'checked' : ''}></td>
              <td style="text-align:left"><input id="addr-${b.id}" value="${b.address || ''}" class="cell-in" style="width:185px"></td>
              <td style="white-space:nowrap">${b.lat && b.lng
                ? `<span class="bdg pos" style="cursor:pointer" onclick="gotoLoc(${b.id})"
                     title="${(+b.lat).toFixed(5)}, ${(+b.lng).toFixed(5)}">✅ 등록</span>`
                : `<span class="bdg neg" style="cursor:pointer" onclick="gotoLoc(${b.id})">❌ 미등록</span>`}</td>
              <td>${b.attendance_radius || 300}m</td>
              <td><input id="bo-${b.id}" value="${b.note || ''}" class="cell-in" style="width:100px"></td>
              <td><button class="xbtn sm primary" onclick="saveBr(${b.id})">저장</button></td>
            </tr>`).join('')}</tbody>
          </table></div>
        <div style="padding:0 20px 14px;font-size:12px;color:var(--ink3)">
          💡 위치 뱃지를 클릭하면 아래 위치 편집으로 이동합니다.</div></div>

      <div class="card" style="padding:18px 20px;margin-bottom:14px">
        <div style="font-weight:800;margin-bottom:10px">➕ 지점 추가</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <input id="nb-name" placeholder="지점명 *" class="cell-in" style="width:160px">
          <input id="nb-contract" placeholder="계약일 (YYYY-MM-DD)" class="cell-in" style="width:150px">
          <input id="nb-note" placeholder="비고" class="cell-in" style="width:160px">
          <button class="xbtn primary" onclick="addBranch()">추가</button>
        </div></div>

      <div class="card" style="padding:18px 20px" id="loc-edit-card">
        <div style="font-weight:800;margin-bottom:4px">📍 위치 상세 편집 (GPS 출퇴근용)</div>
        <div style="font-size:12px;color:var(--ink3);margin-bottom:14px">
          오른쪽 주소 검색에서 클릭하면 주소가 자동 입력됩니다 → 좌표 자동 변환 → 저장</div>
        <div class="loc-grid">
          <div>
            <select id="loc-sel" style="width:100%;padding:9px 12px;border:1.5px solid var(--bds);
              border-radius:8px;background:var(--sf);color:var(--ink);margin-bottom:10px">
              ${brList.map(b => `<option value="${b.id}" ${b.id === locSelId ? 'selected' : ''}>${b.name}</option>`).join('')}
            </select>
            <input id="loc-addr" placeholder="주소" class="cell-in" style="width:100%;margin-bottom:8px">
            <button class="xbtn" onclick="geocodeAddr()" style="width:100%;margin-bottom:8px">📍 주소 → 위도/경도 자동 변환</button>
            <div style="display:flex;gap:8px;margin-bottom:8px">
              <input id="loc-lat" placeholder="위도" class="cell-in" style="flex:1">
              <input id="loc-lng" placeholder="경도" class="cell-in" style="flex:1">
            </div>
            <label style="font-size:12px;color:var(--ink2);font-weight:700">📡 출퇴근 허용 반경:
              <span id="rad-val"></span>m</label>
            <input id="loc-rad" type="range" min="100" max="500" step="50" style="width:100%;margin:6px 0 12px">
            <button class="xbtn primary" onclick="saveLoc()" style="width:100%;margin-bottom:14px">💾 위치 정보 저장</button>
            <div style="font-size:12px;font-weight:700;color:var(--ink2);margin-bottom:6px">📍 주소 검색 (다음 우편번호)</div>
            <div id="daum-postcode" style="height:380px;border:1px solid var(--bd);border-radius:10px;overflow:hidden"></div>
          </div>
          <div>
            <div style="font-size:12px;font-weight:700;color:var(--ink2);margin-bottom:6px">
              🗺️ 클릭형 지도 — <span style="color:var(--red)">지도를 클릭하면 그 위치가 좌표로 입력됩니다</span></div>
            <div id="loc-map" style="height:560px;border:1px solid var(--bd);border-radius:10px"></div>
            <div style="font-size:11.5px;color:var(--ink3);margin-top:6px">
              빨간 원 = 출퇴근 허용 반경. 자동 변환 위치가 틀리면 지도에서 올바른 위치를 클릭하세요.</div>
          </div>
        </div>
      </div>

      `;

    // 위치 편집 초기화 + 이벤트
    const radEl = document.getElementById('loc-rad');
    radEl.addEventListener('input', () => {
      document.getElementById('rad-val').textContent = radEl.value;
      updateLocMap();
    });
    ['loc-lat', 'loc-lng'].forEach(id =>
      document.getElementById(id).addEventListener('change', updateLocMap));
    document.getElementById('loc-sel').addEventListener('change', e => {
      locSelId = +e.target.value; fillLocForm();
    });
    initLocMap();
    fillLocForm();
    initDaumPostcode();
  }

  function fillLocForm() {
    const b = brList.find(x => x.id === locSelId) || {};
    document.getElementById('loc-addr').value = b.address || '';
    document.getElementById('loc-lat').value  = b.lat ?? '';
    document.getElementById('loc-lng').value  = b.lng ?? '';
    const rad = b.attendance_radius || 300;
    document.getElementById('loc-rad').value = rad;
    document.getElementById('rad-val').textContent = rad;
    updateLocMap(true);
  }

  // ── 클릭형 지도 (Leaflet) ──────────────────────────────────
  let locMap = null, locMarker = null, locCircle = null;

  function initLocMap() {
    const el = document.getElementById('loc-map');
    if (!el || !window.L) return;
    locMap = L.map(el).setView([37.5665, 126.9780], 11);   // 기본: 서울
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap',
    }).addTo(locMap);

    // 지도 클릭 → 좌표 입력
    locMap.on('click', (e) => {
      const { lat, lng } = e.latlng;
      document.getElementById('loc-lat').value = lat.toFixed(6);
      document.getElementById('loc-lng').value = lng.toFixed(6);
      updateLocMap();
      showToast(`📍 좌표 선택: ${lat.toFixed(5)}, ${lng.toFixed(5)} — 저장을 눌러주세요`);
    });
  }

  function updateLocMap(recenter) {
    if (!locMap) return;
    const lat = parseFloat(document.getElementById('loc-lat').value);
    const lng = parseFloat(document.getElementById('loc-lng').value);
    const rad = parseInt(document.getElementById('loc-rad').value) || 300;

    if (locMarker) { locMap.removeLayer(locMarker); locMarker = null; }
    if (locCircle) { locMap.removeLayer(locCircle); locCircle = null; }
    if (!lat || !lng) return;

    const b = brList.find(x => x.id === locSelId) || {};
    locMarker = L.marker([lat, lng]).addTo(locMap)
      .bindPopup(`<b>${b.name || ''}</b><br>반경 ${rad}m`);
    locCircle = L.circle([lat, lng], {
      radius: rad, color: '#E60028', fillColor: '#E60028', fillOpacity: 0.12, weight: 2,
    }).addTo(locMap);
    if (recenter) locMap.setView([lat, lng], 16);
  }

  function initDaumPostcode() {
    const mount = () => {
      new daum.Postcode({
        oncomplete: function (d) {
          const addr = d.roadAddress || d.jibunAddress;
          document.getElementById('loc-addr').value = addr;
          showToast('📋 주소 입력 완료 — 좌표 자동 변환을 눌러주세요');
        },
        width: '100%', height: '380px',
      }).embed(document.getElementById('daum-postcode'), { autoClose: false });
    };
    if (window.daum && window.daum.Postcode) { mount(); return; }
    const s = document.createElement('script');
    s.src = 'https://t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js';
    s.onload = mount;
    document.head.appendChild(s);
  }

  window.geocodeAddr = async function () {
    const addr = document.getElementById('loc-addr').value.trim();
    if (!addr) { showToast('주소를 먼저 입력하세요', 'err'); return; }
    showToast('🔍 좌표 변환 중…');
    const r = await api(`/api/geocode?address=${encodeURIComponent(addr)}`);
    const d = r ? await r.json().catch(() => ({})) : {};
    if (r && r.ok) {
      document.getElementById('loc-lat').value = d.lat.toFixed(6);
      document.getElementById('loc-lng').value = d.lng.toFixed(6);
      showToast(`✅ 좌표 변환 완료 — 지도에서 위치가 맞는지 확인하세요`);
      updateLocMap(true);
    } else showToast(d.detail || '좌표를 찾지 못했습니다', 'err');
  };

  window.saveLoc = async function () {
    const b = brList.find(x => x.id === locSelId);
    if (!b) return;
    const lat = parseFloat(document.getElementById('loc-lat').value) || null;
    const lng = parseFloat(document.getElementById('loc-lng').value) || null;
    const body = { ...b, address: document.getElementById('loc-addr').value.trim(),
      lat, lng, attendance_radius: parseInt(document.getElementById('loc-rad').value) || 300 };
    const r = await api('/api/branch/upsert', { method: 'POST', body: JSON.stringify(body) });
    if (r && r.ok) { showToast(`✅ '${b.name}' 위치 저장 완료`); loadBranchMgmt(); }
    else showToast('저장 실패', 'err');
  };

  window.gotoLoc = function (id) {
    locSelId = id;
    const sel = document.getElementById('loc-sel');
    if (sel) sel.value = id;
    fillLocForm();
    document.getElementById('loc-edit-card').scrollIntoView({ behavior: 'smooth' });
  };

  window.addBranch = async function () {
    const name = document.getElementById('nb-name').value.trim();
    if (!name) { showToast('지점명을 입력하세요', 'err'); return; }
    const r = await api('/api/branch/upsert', { method: 'POST', body: JSON.stringify({
      name, contract_date: document.getElementById('nb-contract').value.trim(),
      note: document.getElementById('nb-note').value.trim(), is_active: 1 }) });
    if (r && r.ok) { showToast(`✅ '${name}' 지점 추가 완료`); loadBranchMgmt(); }
    else showToast('추가 실패', 'err');
  };

  window.saveBr = async function (id) {
    const b = brList.find(x => x.id === id) || {};
    const v = (p) => document.getElementById(`${p}-${id}`).value.trim();
    const body = { ...b, id, name: v('bn'), contract_date: v('bc'),
      termination_date: v('bt'), address: v('addr'), note: v('bo'),
      is_active: document.getElementById(`ba-${id}`).checked ? 1 : 0 };
    const r = await api('/api/branch/upsert', { method: 'POST', body: JSON.stringify(body) });
    if (r && r.ok) showToast(`✅ ${body.name} 저장 완료`);
    else showToast('저장 실패', 'err');
  };

  // ── 지점 보고 (포털 연동) ──────────────────────────────────
  async function loadReports() {
    const body = document.getElementById('br-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';
    const r = await api('/api/reports');
    if (!r || !r.ok) return;
    const d = await r.json();
    const inqLbl = { pw_reset: '🔑 비밀번호 초기화', account: '📨 계정 문의', etc: '💬 기타' };

    const section = (title, rows, render, kind) => `
      <div class="card"><div class="card-head">${title} (${rows.length}건)</div>
        <div style="padding:8px 16px 16px">
          ${rows.length ? rows.map(x => `
            <div style="display:flex;align-items:center;gap:10px;padding:9px 4px;
                 border-bottom:1px solid var(--bd);font-size:13px;flex-wrap:wrap">
              <div style="flex:1;min-width:200px">${render(x)}</div>
              <button class="xbtn sm" onclick="resolveReport('${kind}',${x.id})">✅ 처리</button>
            </div>`).join('') : '<div style="color:var(--ink3);font-size:13px;padding:8px 0">📭 대기 건 없음</div>'}
        </div></div>`;

    body.innerHTML = `
      <div class="kpi-grid" style="grid-template-columns:repeat(4,1fr)">
        <div class="kpi"><div class="kpi-lbl">오늘 출근</div><div class="kpi-val">${d.attendance_today}명</div></div>
        <div class="kpi"><div class="kpi-lbl">AS 대기</div><div class="kpi-val ${d.as_requests.length ? 'neg' : ''}">${d.as_requests.length}건</div></div>
        <div class="kpi"><div class="kpi-lbl">비품 대기</div><div class="kpi-val ${d.supply_requests.length ? 'neg' : ''}">${d.supply_requests.length}건</div></div>
        <div class="kpi"><div class="kpi-lbl">포털 문의</div><div class="kpi-val ${d.inquiries.length ? 'neg' : ''}">${d.inquiries.length}건</div></div>
      </div>
      ${section('🔧 AS 요청', d.as_requests, x =>
        `<b>${x.branch}</b> · ${x.title} ${x.priority === 'urgent' ? '<span class="bdg neg">긴급</span>' : ''}
         <span style="color:var(--ink3);font-size:11.5px">${x.created_name || ''} · ${(x.created_at||'').slice(0,16)}</span>`, 'as')}
      ${section('📦 비품 요청', d.supply_requests, x =>
        `<b>${x.branch}</b> · ${x.item_name} ${x.quantity}${x.unit || '개'}
         <span style="color:var(--ink3);font-size:11.5px">${x.created_name || ''} · ${(x.created_at||'').slice(0,16)}</span>`, 'supply')}
      ${section('📨 포털 문의', d.inquiries, x =>
        `${inqLbl[x.type] || x.type} · <b>${x.name}</b> (${x.phone}) · ${x.branch || '지점 미입력'}
         <span style="color:var(--ink3);font-size:11.5px">${x.message || ''} · ${(x.created_at||'').slice(0,16)}</span>`, 'inquiry')}`;
  }

  window.resolveReport = async function (kind, id) {
    const r = await api('/api/reports/resolve', { method: 'POST',
      body: JSON.stringify({ kind, id }) });
    if (r && r.ok) { showToast('✅ 처리 완료'); loadReports(); }
  };

  // ── 월별 매출 직접 입력 ────────────────────────────────────
  const BMR_COLS = { dogeub:'도급비', pt_sales:'PT매출', gx_sales:'GX매출', cafe_sales:'카페매출',
    golf_sales:'골프매출', facility_fee:'시설상환비', cafe_labor:'카페인건비', other_sales:'기타매출' };

  async function loadBmr() {
    const body = document.getElementById('br-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';
    const r = await api(`/api/branch/monthly-revenue?year=${selYear}&month=${selMonth}`);
    if (!r || !r.ok) return;
    const rows = await r.json();
    body.innerHTML = `
      <div class="card"><div class="card-head">${selYear}년 ${selMonth}월 · 지점별 매출 직접 입력</div>
        <div style="overflow-x:auto;padding:8px 0 4px">
          <table class="tbl">
            <thead><tr><th>지점</th>${Object.values(BMR_COLS).map(l => `<th>${l}</th>`).join('')}<th>비고</th><th></th></tr></thead>
            <tbody>${rows.map((row, i) => `<tr>
              <td style="text-align:left">${row.branch}</td>
              ${Object.keys(BMR_COLS).map(c =>
                `<td><input id="bmr-${i}-${c}" value="${row[c] || 0}" class="cell-in" style="width:90px;text-align:right"></td>`).join('')}
              <td><input id="bmr-${i}-note" value="${row.note || ''}" class="cell-in" style="width:110px"></td>
              <td><button class="xbtn sm primary" onclick="saveBmr(${i},'${row.branch.replace(/'/g,'')}')">저장</button></td>
            </tr>`).join('')}</tbody>
          </table></div></div>`;
  }

  window.saveBmr = async function (i, branch) {
    const data = {};
    for (const c of Object.keys(BMR_COLS))
      data[c] = parseInt(document.getElementById(`bmr-${i}-${c}`).value.replace(/,/g, '')) || 0;
    data.note = document.getElementById(`bmr-${i}-note`).value;
    const r = await api('/api/branch/monthly-revenue', { method: 'POST',
      body: JSON.stringify({ year: selYear, month: selMonth, branch, data }) });
    if (r && r.ok) showToast(`✅ ${branch} 매출 저장`);
    else showToast('저장 실패', 'err');
  };

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
        <button class="xbtn" onclick="dlAttendance()">📥 Excel</button>
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

  window.dlAttendance = async function () {
    const r = await api(`/api/attendance?year=${selYear}&month=${selMonth}&branch=${encodeURIComponent(attBranch)}`);
    if (!r || !r.ok) return;
    const rows = await r.json();
    if (!rows.length) { showToast('데이터가 없습니다', 'err'); return; }
    const fmtMin = m => m ? `${Math.floor(m/60)}:${String(m%60).padStart(2,'0')}` : '';
    const csv = '﻿날짜,지점,이름,출근,퇴근,근무시간,휴게,상태\n' + rows.map(x =>
      [x.work_date, x.branch || '', x.name, x.clock_in || '', x.clock_out || '',
       fmtMin(x.work_minutes), fmtMin(x.break_minutes),
       x.status === 'late' ? '지각' : '정상'].join(',')).join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    a.download = `출퇴근현황_${selYear}년${String(selMonth).padStart(2,'0')}월${attBranch ? '_' + attBranch : ''}.csv`;
    a.click();
  };

  /* ════ 인사/급여 (직원 CRUD + 급여계산 + 결과) ═════════════ */
  const TYPE_LBL = { insured: '4대보험', freelance: '프리랜서', business: '사업자', hourly: '시급제' };
  let payTab = 'emps';
  let empCache = [];

  async function renderPayroll(el) {
    el.innerHTML = `
      <div class="ph"><div class="ph-title">인사/급여</div>
        <div class="ph-sub">직원 관리 · 급여 계산·확정 · 결과 조회 (명세서 발행은 기존 ERP)</div></div>
      <div class="filter-bar" style="gap:6px">
        <button class="xbtn ${payTab === 'emps' ? 'primary' : ''}" onclick="payTabGo('emps')">👥 직원 관리</button>
        <button class="xbtn ${payTab === 'calc' ? 'primary' : ''}" onclick="payTabGo('calc')">🧮 급여 계산</button>
        <button class="xbtn ${payTab === 'result' ? 'primary' : ''}" onclick="payTabGo('result')">📋 확정 결과</button>
        ${payTab !== 'emps' ? ymFilter(loadPayrollTab) : ''}
      </div>
      <div id="pay-body"><div class="empty">로드 중…</div></div>`;
    loadPayrollTab();
  }

  window.payTabGo = function (t) { payTab = t; renderPayroll(document.getElementById('page-content')); };

  function loadPayrollTab() {
    if (payTab === 'emps')   return loadEmps();
    if (payTab === 'calc')   return loadPayCalc();
    if (payTab === 'result') return loadPayResult();
  }

  // ── 직원 관리 ──────────────────────────────────────────────
  async function loadEmps() {
    const body = document.getElementById('pay-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';
    const r = await api('/api/employees');
    if (!r || !r.ok) return;
    empCache = await r.json();
    body.innerHTML = `
      <div style="margin-bottom:12px">
        <button class="xbtn primary" onclick="empForm()">➕ 직원 추가</button></div>
      <div id="emp-form"></div>
      <div class="card"><div class="card-head">전체 직원 ${empCache.length}명</div>
        <div style="overflow-x:auto;padding:8px 0 4px">
          <table class="tbl">
            <thead><tr><th>이름</th><th>지점</th><th>유형</th><th>기본급</th><th>전화번호</th><th>이메일</th><th>입사일</th><th></th></tr></thead>
            <tbody>${empCache.map(e => `<tr>
              <td style="text-align:left">${e.name}</td><td style="text-align:left">${e.branch || '—'}</td>
              <td style="text-align:left">${TYPE_LBL[e.emp_type] || e.emp_type || '—'}</td>
              <td>${fmtWon(e.base_salary)}</td>
              <td>${e.phone || '—'}</td><td style="text-align:left">${e.email || '—'}</td>
              <td>${e.join_date || '—'}</td>
              <td style="white-space:nowrap">
                <button class="xbtn sm" onclick="empForm(${e.id})">수정</button>
                <button class="xbtn sm" onclick="empDel(${e.id},'${e.name.replace(/'/g,'')}')">🗑️</button></td>
            </tr>`).join('')}</tbody>
          </table></div></div>`;
  }

  window.empForm = async function (id) {
    await loadMeta();
    const e = id ? (empCache.find(x => x.id === id) || {}) : {};
    const brOpts = META.branches.map(b => `<option ${b === e.branch ? 'selected' : ''}>${b}</option>`).join('');
    document.getElementById('emp-form').innerHTML = `
      <div class="card" style="padding:18px 20px;margin-bottom:14px">
        <div style="font-weight:800;margin-bottom:12px">${id ? '✏️ 직원 수정' : '➕ 직원 추가'}</div>
        <div class="emp-grid">
          <label>이름<input id="ef-name" value="${e.name || ''}"></label>
          <label>지점<select id="ef-branch">${brOpts}</select></label>
          <label>유형<select id="ef-type">
            ${Object.entries(TYPE_LBL).map(([k, l]) =>
              `<option value="${k}" ${k === e.emp_type ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
          <label>기본급<input id="ef-salary" type="number" value="${e.base_salary || 0}"></label>
          <label>부양가족<input id="ef-dep" type="number" value="${e.dependents || 1}"></label>
          <label>전화번호<input id="ef-phone" value="${e.phone || ''}" placeholder="01012345678"></label>
          <label>이메일<input id="ef-email" value="${e.email || ''}"></label>
          <label>입사일<input id="ef-join" value="${e.join_date || ''}" placeholder="2026-01-01"></label>
        </div>
        <div style="margin-top:14px;display:flex;gap:8px">
          <button class="xbtn primary" onclick="empSave(${id || 0})">저장</button>
          <button class="xbtn" onclick="document.getElementById('emp-form').innerHTML=''">취소</button>
        </div></div>`;
  };

  window.empSave = async function (id) {
    const v = (x) => document.getElementById(`ef-${x}`).value.trim();
    const body = { id, name: v('name'), branch: v('branch'), emp_type: v('type'),
      base_salary: parseInt(v('salary')) || 0, dependents: parseInt(v('dep')) || 1,
      phone: v('phone'), email: v('email'), join_date: v('join') };
    if (!body.name) { showToast('이름을 입력하세요', 'err'); return; }
    const r = await api('/api/employees', { method: 'POST', body: JSON.stringify(body) });
    const d = r ? await r.json().catch(() => ({})) : {};
    if (r && r.ok) {
      showToast('✅ 저장 완료' + (d.account ? ' · ' + d.account : ''));
      loadEmps();
    } else showToast(d.detail || '저장 실패', 'err');
  };

  window.empDel = async function (id, name) {
    if (!confirm(`'${name}' 직원을 삭제(비활성)할까요?`)) return;
    const r = await api(`/api/employees/${id}`, { method: 'DELETE' });
    if (r && r.ok) { showToast('삭제 완료'); loadEmps(); }
  };

  // ── 급여 계산 ──────────────────────────────────────────────
  async function loadPayCalc() {
    const body = document.getElementById('pay-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';
    const [er, pr] = await Promise.all([
      api('/api/employees'),
      api(`/api/payroll/entries?year=${selYear}&month=${selMonth}`),
    ]);
    if (!er || !er.ok) return;
    empCache = await er.json();
    const entries = pr && pr.ok ? await pr.json() : [];
    const entryMap = {};
    entries.forEach(en => { entryMap[en.employee_id] = en; });

    const groups = { insured: [], freelance: [], business: [] };
    empCache.forEach(e => { if (groups[e.emp_type]) groups[e.emp_type].push(e); });

    const section = (type, lbl) => groups[type].length ? `
      <div class="card"><div class="card-head">${lbl} (${groups[type].length}명)</div>
        <div style="overflow-x:auto;padding:8px 0 4px">
          <table class="tbl">
            <thead><tr><th>이름</th><th>지점</th><th>기본급</th><th>이번 달 지급액(세전)</th></tr></thead>
            <tbody>${groups[type].map(e => {
              const cur = entryMap[e.id] ? entryMap[e.id].gross_pay : (e.base_salary || 0);
              return `<tr><td style="text-align:left">${e.name}</td>
                <td style="text-align:left">${e.branch || '—'}</td>
                <td>${fmtWon(e.base_salary)}</td>
                <td><input id="pay-${e.id}" type="number" value="${cur || 0}"
                  class="cell-in" style="width:130px;text-align:right"></td></tr>`;
            }).join('')}</tbody>
          </table></div></div>` : '';

    body.innerHTML = `
      <div class="card" style="padding:12px 18px;font-size:12.5px;color:var(--ink3)">
        💡 지급액(세전)을 확인·수정 후 <b>급여 확정</b>을 누르면 세금·4대보험이 자동 계산되어 저장됩니다.
        공단 고지내역이 업로드된 직원은 실납부액이 자동 적용됩니다. 0원은 제외됩니다.</div>
      ${section('insured', '4대보험')}
      ${section('freelance', '프리랜서(사업소득)')}
      ${section('business', '사업자')}
      <button class="xbtn primary" style="padding:13px 28px;font-size:14.5px"
        onclick="confirmPayroll()">💾 ${selYear}년 ${selMonth}월 급여 확정</button>`;
  }

  window.confirmPayroll = async function () {
    if (!confirm(`${selYear}년 ${selMonth}월 급여를 확정할까요?\n기존 확정 내역은 교체됩니다.`)) return;
    const payments = {};
    empCache.forEach(e => {
      const el = document.getElementById(`pay-${e.id}`);
      if (el) payments[e.id] = parseInt(el.value) || 0;
    });
    const r = await api('/api/payroll/confirm', { method: 'POST',
      body: JSON.stringify({ year: selYear, month: selMonth, payments }) });
    const d = r ? await r.json().catch(() => ({})) : {};
    if (r && r.ok) {
      let msg = `✅ ${d.ok}명 급여 확정 완료`;
      if (d.actual_applied) msg += ` (공단 실납부액 ${d.actual_applied}명 적용)`;
      showToast(msg);
      if (d.errors && d.errors.length) alert('오류:\n' + d.errors.join('\n'));
      payTabGo('result');
    } else showToast(d.detail || '확정 실패', 'err');
  };

  // ── 확정 결과 ──────────────────────────────────────────────
  async function loadPayResult() {
    const body = document.getElementById('pay-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';
    const r = await api(`/api/payroll/entries?year=${selYear}&month=${selMonth}`);
    if (!r || !r.ok) return;
    const rows = await r.json();
    if (!rows.length) { body.innerHTML = '<div class="empty">📭 확정된 급여가 없습니다</div>'; return; }
    const totG = rows.reduce((s, x) => s + (x.gross_pay || 0), 0);
    const totN = rows.reduce((s, x) => s + (x.net_pay || 0), 0);
    body.innerHTML = `
      <div class="kpi-grid">
        <div class="kpi"><div class="kpi-lbl">확정 인원</div><div class="kpi-val">${rows.length}명</div></div>
        <div class="kpi"><div class="kpi-lbl">총 지급액(세전)</div><div class="kpi-val">${fmtWon(totG)}원</div></div>
        <div class="kpi"><div class="kpi-lbl">총 실수령액</div><div class="kpi-val pos">${fmtWon(totN)}원</div></div>
        <div class="kpi"><div class="kpi-lbl">공제 합계</div><div class="kpi-val neg">${fmtWon(totG - totN)}원</div></div>
      </div>
      <div class="card"><div class="card-head">${selYear}년 ${selMonth}월 확정 내역</div>
        <div style="overflow-x:auto;padding:8px 0 4px">
          <table class="tbl">
            <thead><tr><th>이름</th><th>지점</th><th>유형</th><th>세전</th><th>4대보험</th><th>소득세</th><th>지방세</th><th>실수령</th></tr></thead>
            <tbody>${rows.map(x => `<tr>
              <td style="text-align:left">${x.name}</td>
              <td style="text-align:left">${x.branch || '—'}</td>
              <td style="text-align:left">${TYPE_LBL[x.emp_type] || x.emp_type || '—'}</td>
              <td>${fmtWon(x.gross_pay)}</td>
              <td>${fmtWon((x.pension||0)+(x.health||0)+(x.employment||0)+(x.care||0))}</td>
              <td>${fmtWon(x.income_tax)}</td><td>${fmtWon(x.local_tax)}</td>
              <td style="font-weight:700;color:var(--pos)">${fmtWon(x.net_pay)}</td>
            </tr>`).join('')}</tbody>
          </table></div></div>
      <div class="card" style="padding:12px 18px;font-size:12.5px;color:var(--ink3)">
        💡 급여명세서 PDF 발행·이메일 발송은 기존 ERP(인사/급여 → 급여명세서)에서 이용하세요.</div>`;
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
          <div style="font-weight:800;margin-bottom:4px">🏥 4대보험 고지내역</div>
          <div style="font-size:12px;color:var(--ink3);margin-bottom:12px">공단 고지내역 3종 — 이름으로 직원 자동 매칭</div>
          <label style="font-size:11.5px;color:var(--ink3)">국민연금 (.xlsx)</label>
          <input type="file" id="ins-pension" accept=".xlsx">
          <label style="font-size:11.5px;color:var(--ink3)">건강보험 (.csv)</label>
          <input type="file" id="ins-health" accept=".csv">
          <label style="font-size:11.5px;color:var(--ink3)">고용보험 (.xlsx)</label>
          <input type="file" id="ins-employ" accept=".xlsx">
          <button class="xbtn primary" onclick="upInsurance()">업로드</button>
        </div>

        <div class="card" style="padding:18px 20px">
          <div style="font-weight:800;margin-bottom:4px">🗑️ 데이터 삭제</div>
          <div style="font-size:12px;color:var(--ink3);margin-bottom:12px">선택 연월 데이터 삭제 (재업로드용)</div>
          <button class="xbtn" onclick="delData('card')" style="margin-bottom:6px">카드매출 삭제</button>
          <button class="xbtn" onclick="delData('bank')">통장내역 삭제</button>
        </div>

        <div class="card" style="padding:18px 20px">
          <div style="font-weight:800;margin-bottom:4px">💾 백업 / 복원</div>
          <div style="font-size:12px;color:var(--ink3);margin-bottom:12px">DB 전체 백업 · 최근 7개 유지</div>
          <button class="xbtn primary" onclick="mkBackup()" style="margin-bottom:10px">지금 백업 생성</button>
          <div id="backup-list" style="font-size:12.5px">로드 중…</div>
        </div>
      </div>
      <div id="up-result"></div>`;
    loadBackups();
  }

  async function loadBackups() {
    const el = document.getElementById('backup-list');
    if (!el) return;
    const r = await api('/api/backups');
    if (!r || !r.ok) { el.textContent = '백업 목록 로드 실패'; return; }
    const list = await r.json();
    el.innerHTML = list.length ? list.map(b => `
      <div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--bd)">
        <span style="flex:1">📦 ${b.ts} <span style="color:var(--ink3)">(${b.size_mb}MB)</span></span>
        <button class="xbtn sm" onclick="restoreBackup('${b.name}')">복원</button>
      </div>`).join('') : '<span style="color:var(--ink3)">저장된 백업 없음</span>';
  }

  window.mkBackup = async function () {
    const r = await api('/api/backups', { method: 'POST' });
    if (r && r.ok) { showToast('✅ 백업 생성 완료'); loadBackups(); }
    else showToast('백업 실패', 'err');
  };

  window.restoreBackup = async function (name) {
    if (!confirm(`${name} 백업으로 복원할까요?\n현재 DB는 broken_*.db로 보존됩니다.`)) return;
    const r = await api('/api/backups/restore', { method: 'POST', body: JSON.stringify({ name }) });
    const d = r ? await r.json().catch(() => ({})) : {};
    if (r && r.ok) { alert('✅ ' + d.msg + '\n\n페이지를 새로고침하세요.'); }
    else showToast(d.detail || '복원 실패', 'err');
  };

  window.upInsurance = async function () {
    const fd = new FormData();
    fd.append('year', selYear); fd.append('month', selMonth);
    let any = false;
    for (const [id, key] of [['ins-pension','pension'],['ins-health','health'],['ins-employ','employ']]) {
      const f = document.getElementById(id).files[0];
      if (f) { fd.append(key, f); any = true; }
    }
    if (!any) { showToast('파일을 하나 이상 선택하세요', 'err'); return; }
    upResult('⏳ 처리 중…');
    const r = await api('/api/upload/insurance', { method: 'POST', body: fd });
    const d = r ? await r.json().catch(() => ({})) : {};
    if (r && r.ok) upResult(`✅ 고지내역 ${d.saved}명 저장 (매칭 ${d.matched} / 미매칭 ${d.unmatched})`);
    else upResult('❌ ' + (d.detail || '업로드 실패'), true);
  };

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
    if (d) upResult(`✅ 통장내역 ${d.count}건 저장 (자동분류 ${d.auto}건${d.ai ? ' / AI ' + d.ai + '건' : ''} / 미분류 ${d.review}건)` +
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
        <button class="xbtn ${setTab === 'ai' ? 'primary' : ''}" onclick="setTabGo('ai')">🤖 AI 설정</button>
        ${user.role === 'admin' ? `<button class="xbtn ${setTab === 'users' ? 'primary' : ''}"
          onclick="setTabGo('users')">👤 계정 관리</button>` : ''}
        ${setTab === 'review' ? ymFilter(loadSettings) : ''}
      </div>
      <div id="set-body"><div class="empty">로드 중…</div></div>`;
    loadSettings();
  }

  window.setTabGo = function (t) { setTab = t; renderSettings(document.getElementById('page-content')); };

  async function loadSettings() {
    const body = document.getElementById('set-body');
    body.innerHTML = '<div class="empty">로드 중…</div>';

    if (setTab === 'ai') {
      const r = await api('/api/ai/key');
      const d = r && r.ok ? await r.json() : { masked: '', set: false };
      body.innerHTML = `
        <div class="card" style="padding:18px 20px;max-width:560px">
          <div style="font-weight:800;margin-bottom:6px">🤖 OpenAI API 설정</div>
          <div style="font-size:12.5px;color:var(--ink3);margin-bottom:14px">
            API 키를 설정하면 통장 업로드 시 미분류 거래를 AI가 자동 분류합니다.</div>
          <div style="font-size:13px;margin-bottom:10px">현재: <b>${d.set ? d.masked : '미설정'}</b></div>
          <div style="display:flex;gap:8px">
            <input id="ai-key" type="password" placeholder="sk-proj-..." class="cell-in" style="flex:1">
            <button class="xbtn primary" onclick="saveAiKey()">저장</button>
          </div></div>`;
      return;
    }

    if (setTab === 'users') {
      const r = await api('/api/users');
      if (!r || !r.ok) { body.innerHTML = '<div class="empty">관리자 전용입니다</div>'; return; }
      const users = await r.json();
      body.innerHTML = `
        <div class="card" style="padding:18px 20px;margin-bottom:14px">
          <div style="font-weight:800;margin-bottom:10px">➕ 새 계정</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <input id="nu-id" placeholder="아이디" class="cell-in" style="width:130px">
            <input id="nu-name" placeholder="이름" class="cell-in" style="width:110px">
            <input id="nu-pw" type="password" placeholder="비밀번호 (8자+)" class="cell-in" style="width:150px">
            <select id="nu-role" class="cell-in"><option value="user">사용자</option><option value="admin">관리자</option></select>
            <button class="xbtn primary" onclick="addUser()">생성</button>
          </div></div>
        <div class="card" style="padding:18px 20px;margin-bottom:14px">
          <div style="font-weight:800;margin-bottom:10px">🔑 비밀번호 변경</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <input id="cp-id" placeholder="아이디" class="cell-in" style="width:130px">
            <input id="cp-pw" type="password" placeholder="새 비밀번호 (8자+)" class="cell-in" style="width:160px">
            <button class="xbtn primary" onclick="changePw()">변경</button>
          </div></div>
        <div class="card"><div class="card-head">전체 사용자 (${users.length}명)</div>
          <div style="overflow-x:auto;padding:8px 0 4px">
            <table class="tbl">
              <thead><tr><th>아이디</th><th>이름</th><th>권한</th><th>생성일</th><th></th></tr></thead>
              <tbody>${users.map(u => `<tr>
                <td style="text-align:left"><b>${u.username}</b></td>
                <td style="text-align:left">${u.name}</td>
                <td style="text-align:left">${u.role === 'admin' ? '🔴 관리자' : '🔵 사용자'}</td>
                <td>${(u.created_at || '').slice(0, 10)}</td>
                <td>${u.username !== 'admin'
                  ? `<button class="xbtn sm" onclick="delUser(${u.id},'${u.username}')">🗑️</button>` : '—'}</td>
              </tr>`).join('')}</tbody>
            </table></div></div>`;
      return;
    }

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

  window.saveAiKey = async function () {
    const key = document.getElementById('ai-key').value.trim();
    const r = await api('/api/ai/key', { method: 'POST', body: JSON.stringify({ key }) });
    const d = r ? await r.json().catch(() => ({})) : {};
    if (r && r.ok) { showToast('✅ API 키 저장 완료'); loadSettings(); }
    else showToast(d.detail || '저장 실패', 'err');
  };

  window.addUser = async function () {
    const body = {
      username: document.getElementById('nu-id').value.trim(),
      name: document.getElementById('nu-name').value.trim(),
      password: document.getElementById('nu-pw').value,
      role: document.getElementById('nu-role').value,
    };
    if (!body.username || !body.password) { showToast('아이디와 비밀번호를 입력하세요', 'err'); return; }
    const r = await api('/api/users', { method: 'POST', body: JSON.stringify(body) });
    const d = r ? await r.json().catch(() => ({})) : {};
    if (r && r.ok) { showToast('✅ 계정 생성 완료'); loadSettings(); }
    else showToast(d.detail || '생성 실패', 'err');
  };

  window.delUser = async function (id, username) {
    if (!confirm(`'${username}' 계정을 삭제할까요?`)) return;
    const r = await api(`/api/users/${id}`, { method: 'DELETE' });
    if (r && r.ok) { showToast('삭제 완료'); loadSettings(); }
  };

  window.changePw = async function () {
    const body = {
      username: document.getElementById('cp-id').value.trim(),
      new_password: document.getElementById('cp-pw').value,
    };
    if (!body.username || !body.new_password) { showToast('아이디와 새 비밀번호를 입력하세요', 'err'); return; }
    const r = await api('/api/users/password', { method: 'POST', body: JSON.stringify(body) });
    const d = r ? await r.json().catch(() => ({})) : {};
    if (r && r.ok) showToast('✅ 비밀번호 변경 완료');
    else showToast(d.detail || '변경 실패', 'err');
  };

  loadMeta().then(renderShell);
})();
