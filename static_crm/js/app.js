/**
 * 라온스포츠 포털 — SPA Shell v3.1
 * Modal-based forms, hash routing, auth helpers
 */
(function () {
  'use strict';

  // ── Auth helpers ──────────────────────────────────────────────
  function getToken() {
    return localStorage.getItem('raon_token') || sessionStorage.getItem('raon_token');
  }
  function getUser() {
    const isAdmin = localStorage.getItem('raon_admin') === '1';
    // 관리자는 선택한 지점으로 동작 (전 지점 접근 가능)
    const branch = isAdmin
      ? (localStorage.getItem('raon_admin_branch') || '')
      : (localStorage.getItem('raon_branch') || '');
    let roles = [];
    try { roles = JSON.parse(localStorage.getItem('raon_roles') || '[]'); } catch (e) { roles = []; }
    // admin/지점관리자는 전 직무 동급(effective)
    const effective = (isAdmin || roles.includes('manager'))
      ? ['info','trainer','golf_pro','gx','manager']
      : roles;
    return {
      role:   localStorage.getItem('raon_role') || 'staff',
      name:   localStorage.getItem('raon_name') || '',
      admin:  isAdmin,
      branch: branch,
      roles:  roles,
      effectiveRoles: effective,
    };
  }
  // 직무 보유 여부 (allowed 중 하나라도)
  function hasRole(u, allowed) {
    if (!allowed || !allowed.length) return true;
    const eff = u.effectiveRoles || [];
    return allowed.some(r => eff.includes(r));
  }
  function logout() {
    fetch('/api/auth/logout', { method: 'POST' }).finally(() => {
      ['raon_token','raon_role','raon_name','raon_branch','raon_admin','raon_admin_branch','raon_roles'].forEach(k => {
        localStorage.removeItem(k);
        sessionStorage.removeItem(k);
      });
      window.location.href = '/login';
    });
  }
  async function api(path, opts = {}) {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const resp = await fetch(window.API_BASE + path, { ...opts, headers });
    if (resp.status === 401) { logout(); return null; }
    return resp;
  }
  async function apiForm(path, formData, method = 'POST') {
    const token = getToken();
    const headers = {};
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return fetch(window.API_BASE + path, { method, headers, body: formData });
  }

  // ── Router ────────────────────────────────────────────────────
  // allowedRoles: 비어있으면 전원. staffOnly: 회원(member) 차단.
  // (직무: info 인포 / trainer 트레이너 / golf_pro 골프프로 / gx GX강사 / manager 지점관리자)
  const PAGES = {
    home:        { label: '홈',      icon: 'home',       staffOnly: false, allowedRoles: [] },
    attendance:  { label: '근태',    icon: 'clock',      staffOnly: true,  allowedRoles: ['info','trainer','golf_pro','manager'] },
    members:     { label: '회원',    icon: 'users',      staffOnly: true,  allowedRoles: ['info','trainer','golf_pro','manager'] },
    classes:     { label: '상품',    icon: 'package',    staffOnly: true,  allowedRoles: ['info','trainer','golf_pro','manager'] },
    operations:  { label: '운영관리', icon: 'settings',   staffOnly: true,  allowedRoles: ['info','manager'] },
    lessons:     { label: '수업관리', icon: 'dumbbell',   staffOnly: true,  allowedRoles: ['trainer','golf_pro','manager'] },
    gx:          { label: 'GX수업',   icon: 'activity',   staffOnly: true,  allowedRoles: ['gx','manager'] },
    instructors: { label: '강사',    icon: 'user-check', staffOnly: true,  allowedRoles: ['trainer','golf_pro','gx','manager'] },
    daily:       { label: '일일보고', icon: 'clipboard-list', staffOnly: true, allowedRoles: ['info','trainer','golf_pro','manager'] },
    payroll:     { label: '페이롤',   icon: 'wallet',     staffOnly: true,  allowedRoles: ['trainer','golf_pro','gx','manager'] },
    approvals:   { label: '결재함',   icon: 'inbox',      staffOnly: true,  allowedRoles: ['manager'] },
  };

  // 현재 사용자가 접근 가능한 페이지인지
  function canAccessPage(cfg, u) {
    if (cfg.staffOnly && u.role !== 'staff') return false;
    return hasRole(u, cfg.allowedRoles);
  }

  let currentPage = window.INITIAL_PAGE || 'home';
  const user = getUser();

  if (!getToken()) { window.location.href = '/login'; }

  // 접근 불가 페이지로 진입 시 홈으로 폴백
  if (PAGES[currentPage] && !canAccessPage(PAGES[currentPage], user)) {
    currentPage = 'home';
  }

  // ── Modal System ──────────────────────────────────────────────
  /**
   * createModal({ title, fields, onSubmit, submitLabel, size })
   * fields: [{ id, label, type, placeholder, required, options, hint, accept, row }]
   * type: text | textarea | number | date | time | select | radio | file | hidden
   */
  function createModal({ title, fields = [], onSubmit, submitLabel = '저장', size = '' }) {
    closeModal();

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.id = 'modal-overlay';
    overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });

    const modal = document.createElement('div');
    modal.className = 'modal' + (size === 'lg' ? ' modal-lg' : '');

    // Group consecutive fields with same row key
    let bodyHTML = '';
    let i = 0;
    while (i < fields.length) {
      const f = fields[i];
      if (f.type === 'hidden') { i++; continue; }
      if (f.row && i + 1 < fields.length && fields[i+1].row === f.row) {
        bodyHTML += `<div class="form-row">${fieldHTML(f)}${fieldHTML(fields[i+1])}</div>`;
        i += 2;
      } else {
        bodyHTML += fieldHTML(f);
        i++;
      }
    }

    modal.innerHTML = `
      <div class="modal-header">
        <div class="modal-title">${title}</div>
        <button class="modal-close" onclick="closeModal()">
          <i data-lucide="x" style="width:18px;height:18px"></i>
        </button>
      </div>
      <div class="modal-body">${bodyHTML}</div>
      <div class="modal-footer">
        <button class="btn" onclick="closeModal()">취소</button>
        <button class="btn primary" id="modal-submit">${submitLabel}</button>
      </div>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    if (window.lucide) lucide.createIcons();

    // Radio button interaction
    modal.querySelectorAll('.radio-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const name = btn.querySelector('input').name;
        modal.querySelectorAll(`.radio-btn input[name="${name}"]`).forEach(inp => {
          inp.closest('.radio-btn').classList.remove('selected');
        });
        btn.querySelector('input').checked = true;
        btn.classList.add('selected');
      });
    });

    // File preview
    modal.querySelectorAll('input[type=file]').forEach(inp => {
      inp.addEventListener('change', () => {
        const file = inp.files[0];
        if (!file) return;
        const prev = inp.closest('.file-upload-area').querySelector('.file-preview');
        if (prev && file.type.startsWith('image/')) {
          const reader = new FileReader();
          reader.onload = e => { prev.src = e.target.result; prev.style.display = 'block'; };
          reader.readAsDataURL(file);
        }
        inp.closest('.file-upload-area').querySelector('.file-label').textContent = file.name;
      });
    });

    // Submit handler
    modal.querySelector('#modal-submit').addEventListener('click', async () => {
      const data = {};
      let hasFile = false;
      fields.forEach(f => {
        if (f.type === 'radio') {
          const checked = modal.querySelector(`input[name="${f.id}"]:checked`);
          data[f.id] = checked ? checked.value : (f.options[0]?.value || f.options[0]);
        } else if (f.type === 'file') {
          const inp = modal.querySelector(`#modal-${f.id}`);
          data[f.id] = inp?.files[0] || null;
          if (data[f.id]) hasFile = true;
        } else if (f.type === 'hidden') {
          data[f.id] = f.value;
        } else {
          const el = modal.querySelector(`#modal-${f.id}`);
          data[f.id] = el ? el.value.trim() : '';
        }
        if (f.required && !data[f.id]) {
          modal.querySelector(`#modal-${f.id}`)?.focus();
        }
      });
      const btn = modal.querySelector('#modal-submit');
      btn.disabled = true;
      btn.textContent = '처리 중…';
      try {
        await onSubmit(data, hasFile);
        closeModal();
      } catch (err) {
        showToast(err.message || '오류가 발생했습니다', 'err');
        btn.disabled = false;
        btn.textContent = submitLabel;
      }
    });

    // Focus first input
    setTimeout(() => {
      const first = modal.querySelector('.form-control');
      if (first) first.focus();
    }, 150);
  }

  function fieldHTML(f) {
    const req = f.required ? '<span class="req">*</span>' : '';
    const hint = f.hint ? `<div class="form-hint">${f.hint}</div>` : '';
    let inner = '';

    if (f.type === 'textarea') {
      inner = `<textarea class="form-control" id="modal-${f.id}" placeholder="${f.placeholder||''}" rows="${f.rows||3}">${f.default||''}</textarea>`;
    } else if (f.type === 'select') {
      const opts = f.options.map(o => {
        const val = typeof o === 'object' ? o.value : o;
        const lbl = typeof o === 'object' ? o.label : o;
        const sel = val === f.default ? 'selected' : '';
        return `<option value="${val}" ${sel}>${lbl}</option>`;
      }).join('');
      inner = `<select class="form-control" id="modal-${f.id}">${opts}</select>`;
    } else if (f.type === 'radio') {
      const btns = f.options.map((o, idx) => {
        const val = typeof o === 'object' ? o.value : o;
        const lbl = typeof o === 'object' ? o.label : o;
        const checked = (f.default ? val === f.default : idx === 0) ? 'checked' : '';
        const sel    = (f.default ? val === f.default : idx === 0) ? 'selected' : '';
        return `<label class="radio-btn ${sel}"><input type="radio" name="${f.id}" value="${val}" ${checked}>${lbl}</label>`;
      }).join('');
      inner = `<div class="radio-group">${btns}</div>`;
    } else if (f.type === 'file') {
      inner = `
        <div class="file-upload-area" onclick="document.getElementById('modal-${f.id}').click()">
          <input type="file" id="modal-${f.id}" accept="${f.accept||'*'}">
          <i data-lucide="upload-cloud" style="width:24px;height:24px;color:var(--muted)"></i>
          <div class="file-label" style="font-size:13px;color:var(--muted);margin-top:6px">${f.placeholder||'파일을 클릭하여 선택'}</div>
          <img class="file-preview" src="" style="display:none">
        </div>`;
    } else {
      inner = `<input class="form-control" id="modal-${f.id}" type="${f.type||'text'}"
        placeholder="${f.placeholder||''}" value="${f.default||''}"
        ${f.min !== undefined ? 'min="'+f.min+'"' : ''}
        ${f.max !== undefined ? 'max="'+f.max+'"' : ''}>`;
    }

    return `<div class="form-group"><label class="form-label">${f.label}${req}</label>${inner}${hint}</div>`;
  }

  window.closeModal = function () {
    const el = document.getElementById('modal-overlay');
    if (el) el.remove();
  };

  // ── Render Shell ──────────────────────────────────────────────
  function renderShell() {
    const root = document.getElementById('app-root');

    const navItemsHTML = Object.entries(PAGES).map(([key, cfg]) => {
      if (!canAccessPage(cfg, user)) return '';
      return `
        <div class="nav-item ${key === currentPage ? 'active' : ''}" onclick="navigateTo('${key}')">
          <i data-lucide="${cfg.icon}" class="nav-icon"></i>
          <span>${cfg.label}</span>
        </div>`;
    }).join('');

    const tabsHTML = Object.entries(PAGES).map(([key, cfg]) => {
      if (!canAccessPage(cfg, user)) return '';
      return `
        <button class="tab ${key === currentPage ? 'active' : ''}" onclick="navigateTo('${key}')">
          <i data-lucide="${cfg.icon}"></i>
          <span>${cfg.label}</span>
        </button>`;
    }).join('');

    const pageInfo = PAGES[currentPage] || PAGES.home;

    root.innerHTML = `
      <div class="app">
        <nav class="sidebar">
          <div class="brand">
            <img src="/static/img/logo.png" alt="LAONSPORTS" style="height:36px;object-fit:contain;">
            <span class="brand-sub" style="font-size:14px;font-weight:700;margin-left:4px">${user.branch || '지점 포털'}</span>
          </div>
          <div class="nav-group">
            <div class="nav-label">메뉴</div>
            ${navItemsHTML}
          </div>
          <div class="sidebar-foot">
            <div class="user-card" onclick="logout()">
              <div class="avatar">${(user.name || '?').charAt(0)}</div>
              <div class="user-meta">
                <div class="name">${user.name || '사용자'}</div>
                <div class="role">${user.role === 'staff' ? '직원' : '회원'} · 로그아웃</div>
              </div>
            </div>
          </div>
        </nav>

        <header class="header">
          <div>
            <div class="page-title">${pageInfo.label}</div>
            <div class="crumbs">라온스포츠 · ${user.branch || ''}</div>
          </div>
          <div class="header-spacer"></div>
          <div class="header-action">
            ${user.admin ? `
              <select id="admin-branch-sel" onchange="adminBranchChange(this.value)"
                style="padding:8px 12px;border:1.5px solid rgba(128,128,128,.35);border-radius:9px;
                font-size:13px;font-weight:700;background:transparent;color:inherit;max-width:180px">
                <option value="">🏢 지점 선택…</option>
              </select>` : ''}
            <button class="icon-btn" onclick="openNotif()" title="알림" style="position:relative">
              <i data-lucide="bell"></i>
              <span id="notif-badge" style="display:none;position:absolute;top:-2px;right:-2px;
                min-width:16px;height:16px;padding:0 4px;border-radius:8px;background:#E60028;color:#fff;
                font-size:10px;font-weight:700;align-items:center;justify-content:center"></span>
            </button>
            <button class="icon-btn" onclick="toggleTheme()" title="다크모드">
              <i data-lucide="moon"></i>
            </button>
            <div class="avatar" style="cursor:pointer" onclick="logout()">${(user.name || '?').charAt(0)}</div>
          </div>
        </header>

        <main class="main" id="page-content">
          <div class="page"><div class="empty">로딩 중…</div></div>
        </main>

        <nav class="bottom-tabs">${tabsHTML}</nav>
      </div>
    `;

    if (window.lucide) lucide.createIcons();
    if (user.admin) loadAdminBranches();
    refreshNotif();
    renderPage(currentPage);
  }

  // ── 관리자 지점 선택기 ────────────────────────────────────────
  let _adminBranches = null;

  async function loadAdminBranches() {
    const sel = document.getElementById('admin-branch-sel');
    if (!sel) return;
    if (_adminBranches === null) {
      try {
        const r = await api('/api/branches');
        _adminBranches = r && r.ok ? await r.json() : [];
      } catch (e) { _adminBranches = []; }
    }
    sel.innerHTML = '<option value="">🏢 지점 선택…</option>' +
      _adminBranches.map(b =>
        `<option value="${b}" ${b === user.branch ? 'selected' : ''}>${b}</option>`).join('');
    // 미선택 상태면 첫 지점 자동 선택
    if (!user.branch && _adminBranches.length) {
      adminBranchChange(_adminBranches[0]);
    }
  }

  window.adminBranchChange = function (branch) {
    if (!branch) return;
    localStorage.setItem('raon_admin_branch', branch);
    user.branch = branch;
    renderShell();
  };

  // ── Page Renderers ────────────────────────────────────────────
  async function renderPage(page) {
    const container = document.getElementById('page-content');
    if (!container) return;
    switch (page) {
      case 'home':        await renderHome(container);
                          if (user.role === 'member') await renderMemberLessons(container);
                          break;
      case 'attendance':  await renderAttendance(container);  break;
      case 'operations':  await renderOperations(container);  break;
      case 'members':     await renderMembers(container);     break;
      case 'classes':     await renderClasses(container);     break;
      case 'instructors': await renderInstructors(container); break;
      case 'lessons':     await renderLessons(container);     break;
      case 'gx':          await renderGx(container);          break;
      case 'daily':       await renderDaily(container);       break;
      case 'payroll':     await renderPayroll(container);     break;
      case 'approvals':   await renderApprovals(container);   break;
      default:            container.innerHTML = '<div class="page"><div class="empty">페이지 없음</div></div>';
    }
    if (window.lucide) lucide.createIcons();
  }

  // ── 결재함 ────────────────────────────────────────────────────
  const APPROVAL_TYPE_LBL = {
    as: 'AS요청', supply: '물품요청', complaint: '민원', refund: '환불',
    suggestion: '의견제시', daily_report: '일일보고',
  };
  const APPROVAL_STATUS_LBL = {
    pending: '대기', branch_ok: '본사대기', completed: '완료', rejected: '반려',
  };

  async function renderApprovals(container) {
    container.innerHTML = '<div class="page"><div class="empty">결재함 로딩 중…</div></div>';
    const r = await api('/api/approvals?box=inbox');
    const items = r && r.ok ? await r.json() : [];
    const rows = items.map(it => `
      <tr>
        <td>${it.id}</td>
        <td>${APPROVAL_TYPE_LBL[it.item_type] || it.item_type}</td>
        <td style="text-align:left">${it.summary || '—'}</td>
        <td>${it.created_by_name || '—'}</td>
        <td>${APPROVAL_STATUS_LBL[it.status] || it.status}</td>
        <td style="white-space:nowrap">
          <button class="xbtn sm primary" onclick="approveItem(${it.id})">결재</button>
          <button class="xbtn sm" onclick="rejectItem(${it.id})">반려</button>
        </td>
      </tr>`).join('');
    container.innerHTML = `
      <div class="page">
        <div class="card">
          <div class="card-head">결재 대기 ${items.length}건
            <button class="xbtn sm" style="float:right" onclick="renderApprovalsAll()">전체보기</button>
          </div>
          ${items.length ? `<table class="tbl">
            <thead><tr><th>#</th><th>유형</th><th style="text-align:left">내용</th><th>요청자</th><th>상태</th><th></th></tr></thead>
            <tbody>${rows}</tbody></table>` : '<div class="empty">대기 중인 결재가 없습니다 👍</div>'}
        </div>
      </div>`;
    if (window.lucide) lucide.createIcons();
  }

  window.renderApprovalsAll = async function () {
    const container = document.getElementById('page-content');
    const r = await api('/api/approvals?box=all');
    const items = r && r.ok ? await r.json() : [];
    const rows = items.map(it => `
      <tr><td>${it.id}</td><td>${APPROVAL_TYPE_LBL[it.item_type] || it.item_type}</td>
      <td style="text-align:left">${it.summary || '—'}</td><td>${it.created_by_name || '—'}</td>
      <td>${APPROVAL_STATUS_LBL[it.status] || it.status}</td>
      <td>${it.branch_approved_by || '—'} / ${it.hq_approved_by || '—'}</td></tr>`).join('');
    container.innerHTML = `<div class="page"><div class="card">
      <div class="card-head">전체 결재 내역 ${items.length}건
        <button class="xbtn sm" style="float:right" onclick="navigateTo('approvals')">← 대기함</button></div>
      <table class="tbl"><thead><tr><th>#</th><th>유형</th><th style="text-align:left">내용</th>
        <th>요청자</th><th>상태</th><th>지점/본사 결재</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
  };

  window.approveItem = async function (id) {
    const r = await api(`/api/approvals/${id}/approve`, { method: 'POST' });
    if (r && r.ok) { showToast('✅ 결재 처리'); renderApprovals(document.getElementById('page-content')); refreshNotif(); }
    else { const d = r ? await r.json().catch(()=>({})) : {}; showToast(d.detail || '처리 실패', 'err'); }
  };
  window.rejectItem = async function (id) {
    const reason = prompt('반려 사유를 입력하세요');
    if (reason === null) return;
    const r = await api(`/api/approvals/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) });
    if (r && r.ok) { showToast('반려 처리'); renderApprovals(document.getElementById('page-content')); refreshNotif(); }
  };

  // ── 알림 ──────────────────────────────────────────────────────
  async function refreshNotif() {
    const badge = document.getElementById('notif-badge');
    if (!badge) return;
    try {
      const r = await api('/api/notifications/count');
      const d = r && r.ok ? await r.json() : { count: 0 };
      badge.textContent = d.count > 0 ? (d.count > 99 ? '99+' : d.count) : '';
      badge.style.display = d.count > 0 ? 'flex' : 'none';
    } catch (e) {}
  }
  window.openNotif = async function () {
    const r = await api('/api/notifications');
    const list = r && r.ok ? await r.json() : [];
    const body = list.length
      ? list.map(n => `<div style="padding:10px 12px;border-bottom:1px solid rgba(128,128,128,.18);
          ${n.is_read ? 'opacity:.55' : 'font-weight:600'}">
          ${n.message}<div style="font-size:11px;opacity:.6;margin-top:2px">${n.created_at || ''}</div></div>`).join('')
      : '<div class="empty" style="padding:24px">알림이 없습니다</div>';
    closeModal();
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay'; overlay.id = 'modal-overlay';
    overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });
    overlay.innerHTML = `
      <div class="modal">
        <div class="modal-header"><div class="modal-title">🔔 알림</div>
          <button class="modal-close" onclick="closeModal()">✕</button></div>
        <div class="modal-body" style="max-height:60vh;overflow:auto;padding:0">${body}</div>
        <div class="modal-footer"><button class="btn" onclick="markAllNotif()">모두 읽음</button>
          <button class="btn primary" onclick="closeModal()">닫기</button></div>
      </div>`;
    document.body.appendChild(overlay);
  };
  window.markAllNotif = async function () {
    await api('/api/notifications/read-all', { method: 'POST' });
    closeModal(); refreshNotif();
  };

  // ── 수업관리 (PT/레슨) ────────────────────────────────────────
  const SESS_LBL = { reserved:'예약', pending_sign:'서명대기', completed:'완료', no_show:'노쇼', canceled:'취소' };

  async function renderLessons(container) {
    container.innerHTML = '<div class="page"><div class="empty">수업 로딩 중…</div></div>';
    // 관리자는 지점 전체, 트레이너/프로는 본인 담당만
    const mine = user.effectiveRoles.includes('manager') ? 0 : 1;
    const r = await api(`/api/lessons/enrollments?mine=${mine}`);
    const list = r && r.ok ? await r.json() : [];
    const rows = list.map(e => `
      <tr onclick="openEnrollment(${e.id})" style="cursor:pointer">
        <td style="text-align:left;font-weight:600">${e.member_name}</td>
        <td style="text-align:left">${e.product_name}</td>
        <td>${e.lesson_type}</td>
        <td>${e.instructor_name || '<span style="color:#E60028">미지정</span>'}</td>
        <td>${e.used_sessions}/${e.total_sessions}</td>
        <td>${e.status === 'done' ? '종료' : '진행중'}</td>
      </tr>`).join('');
    container.innerHTML = `
      <div class="page"><div class="card">
        <div class="card-head">PT/레슨 수강권 ${list.length}건</div>
        ${list.length ? `<table class="tbl"><thead><tr>
          <th style="text-align:left">회원</th><th style="text-align:left">상품</th><th>종류</th>
          <th>담당강사</th><th>진행</th><th>상태</th></tr></thead>
          <tbody>${rows}</tbody></table>` : '<div class="empty">담당 수강권이 없습니다</div>'}
      </div></div>`;
    if (window.lucide) lucide.createIcons();
  }

  window.openEnrollment = async function (id) {
    const r = await api(`/api/lessons/enrollment/${id}`);
    if (!r || !r.ok) return;
    const e = await r.json();
    const sess = (e.sessions || []).map(s => `
      <tr>
        <td>${s.scheduled_date || '-'} ${s.scheduled_time || ''}</td>
        <td>${SESS_LBL[s.status] || s.status}</td>
        <td style="white-space:nowrap">
          ${s.status === 'reserved' ? `
            <button class="xbtn sm primary" onclick="sessComplete(${s.id},${id})">진행완료</button>
            <button class="xbtn sm" onclick="sessNoShow(${s.id},${id})">노쇼</button>
            <button class="xbtn sm" onclick="sessCancel(${s.id},${id})">취소</button>` : ''}
          ${s.status === 'pending_sign' ? '<span style="color:#f59e0b">회원 서명 대기</span>' : ''}
        </td>
      </tr>`).join('');
    const canMgmt = user.effectiveRoles.some(x => ['trainer','golf_pro','manager'].includes(x));
    closeModal();
    const ov = document.createElement('div');
    ov.className = 'modal-overlay'; ov.id = 'modal-overlay';
    ov.addEventListener('click', ev => { if (ev.target === ov) closeModal(); });
    ov.innerHTML = `
      <div class="modal modal-lg">
        <div class="modal-header"><div class="modal-title">${e.member_name} · ${e.product_name}</div>
          <button class="modal-close" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div style="margin-bottom:10px;font-size:13px">
            담당강사: <b>${e.instructor_name || '미지정'}</b> · 진행 ${e.used_sessions}/${e.total_sessions}회
            ${canMgmt ? `<button class="xbtn sm" style="margin-left:8px" onclick="changeInstructor(${id})">강사변경</button>` : ''}
          </div>
          ${canMgmt && e.status !== 'done' ? `
          <div style="display:flex;gap:6px;margin-bottom:12px">
            <input id="rsv-date" type="date" class="inp" style="flex:1">
            <input id="rsv-time" type="time" class="inp" style="flex:1">
            <button class="xbtn primary" onclick="addReserve(${id})">예약추가</button>
          </div>` : ''}
          <table class="tbl"><thead><tr><th>일시</th><th>상태</th><th></th></tr></thead>
            <tbody>${sess || '<tr><td colspan=3 style="text-align:center;color:var(--ink3)">예약 없음</td></tr>'}</tbody></table>
        </div>
      </div>`;
    document.body.appendChild(ov);
  };

  window.addReserve = async function (id) {
    const date = document.getElementById('rsv-date').value;
    const time = document.getElementById('rsv-time').value;
    if (!date) { showToast('날짜를 선택하세요','err'); return; }
    const r = await api(`/api/lessons/enrollment/${id}/reserve`, { method:'POST', body: JSON.stringify({ date, time }) });
    const d = r ? await r.json().catch(()=>({})) : {};
    if (r && r.ok) { showToast('✅ 예약'); openEnrollment(id); }
    else showToast(d.detail || '예약 실패','err');
  };
  window.sessComplete = async function (sid, eid) {
    const r = await api(`/api/lessons/session/${sid}/complete`, { method:'POST' });
    if (r && r.ok) { showToast('진행완료 — 회원 서명 대기'); openEnrollment(eid); }
  };
  window.sessNoShow = async function (sid, eid) {
    if (!confirm('노쇼 처리하면 진행 인정되어 페이롤에 포함됩니다. 계속할까요?')) return;
    const r = await api(`/api/lessons/session/${sid}/no-show`, { method:'POST' });
    if (r && r.ok) { showToast('노쇼 처리'); openEnrollment(eid); }
  };
  window.sessCancel = async function (sid, eid) {
    const r = await api(`/api/lessons/session/${sid}/cancel`, { method:'POST' });
    if (r && r.ok) { showToast('취소됨'); openEnrollment(eid); }
  };
  window.changeInstructor = async function (eid) {
    const r = await api(`/api/branch-instructors?kind=lesson`);
    const insts = r && r.ok ? await r.json() : [];
    if (!insts.length) { showToast('지정 가능한 강사가 없습니다','err'); return; }
    const opts = insts.map(i => `${i.employee_id}:${i.name}`).join('\n');
    const pick = prompt('담당강사 employee_id 입력:\n' + opts);
    if (!pick) return;
    const r2 = await api(`/api/lessons/enrollment/${eid}/instructor`, { method:'POST', body: JSON.stringify({ employee_id: parseInt(pick,10) }) });
    if (r2 && r2.ok) { showToast('강사 변경'); openEnrollment(eid); }
  };

  // ── GX 수업관리 (출석) ────────────────────────────────────────
  async function renderGx(container) {
    container.innerHTML = '<div class="page"><div class="empty">GX 수업 로딩 중…</div></div>';
    const r = await api('/api/gx/classes');
    const classes = r && r.ok ? await r.json() : [];
    const opts = classes.map(c => `<option value="${c.id}">${c.name} (${c.instructor_name||''})</option>`).join('');
    container.innerHTML = `
      <div class="page"><div class="card">
        <div class="card-head">GX 수업 출석체크</div>
        ${classes.length ? `
        <div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap">
          <select id="gx-class" class="inp" style="flex:1;min-width:160px">${opts}</select>
          <input id="gx-date" type="date" class="inp" value="${new Date().toISOString().slice(0,10)}">
          <button class="xbtn primary" onclick="loadGxAtt()">불러오기</button>
        </div>
        <div id="gx-att"></div>` : '<div class="empty">담당 GX 수업이 없습니다</div>'}
      </div></div>`;
    if (window.lucide) lucide.createIcons();
  }
  window.loadGxAtt = async function () {
    const pid = document.getElementById('gx-class').value;
    const date = document.getElementById('gx-date').value;
    const [mr, ar] = await Promise.all([
      api(`/api/gx/members?product_id=${pid}`),
      api(`/api/gx/attendance?product_id=${pid}&date=${date}`),
    ]);
    const members = mr && mr.ok ? await mr.json() : [];
    const att = ar && ar.ok ? await ar.json() : [];
    const present = {}; att.forEach(a => present[a.member_id] = a.present);
    const rows = members.map(m => `
      <tr><td style="text-align:left">${m.member_name}</td>
      <td><input type="checkbox" ${present[m.member_id] ? 'checked' : ''}
        onchange="setGxAtt(${pid},'${date}',${m.member_id},this.checked?1:0)"></td></tr>`).join('');
    document.getElementById('gx-att').innerHTML = members.length
      ? `<table class="tbl"><thead><tr><th style="text-align:left">회원</th><th>출석</th></tr></thead><tbody>${rows}</tbody></table>
         <div style="font-size:12px;opacity:.6;margin-top:6px">출석 인원에 따라 페이롤이 자동 계산됩니다.</div>`
      : '<div class="empty">등록된 회원이 없습니다</div>';
  };
  window.setGxAtt = async function (pid, date, mid, present) {
    await api('/api/gx/attendance', { method:'POST', body: JSON.stringify({ product_id: parseInt(pid), date, member_id: mid, present }) });
    showToast(present ? '출석' : '결석', present ? 'ok' : 'err');
  };

  // ── 일일보고 ──────────────────────────────────────────────────
  async function renderDaily(container) {
    container.innerHTML = '<div class="page"><div class="empty">로딩 중…</div></div>';
    const today = new Date().toISOString().slice(0,10);
    const r = await api(`/api/daily-report?date=${today}`);
    const d = r && r.ok ? await r.json() : { auto:{sales:[],sessions:[],sales_total:0,session_count:0}, comment:'' };
    const a = d.auto;
    container.innerHTML = `
      <div class="page"><div class="card">
        <div class="card-head">일일보고 — ${d.date}</div>
        <div style="display:flex;gap:12px;margin-bottom:10px">
          <div class="kpi"><div class="kpi-lbl">금일 매출</div><div class="kpi-val">${(a.sales_total||0).toLocaleString()}원</div></div>
          <div class="kpi"><div class="kpi-lbl">진행 수업</div><div class="kpi-val">${a.session_count||0}회</div></div>
        </div>
        <div style="font-weight:700;margin:8px 0 4px">자동 집계</div>
        <div style="font-size:13px;opacity:.8;margin-bottom:4px">매출 ${a.sales.length}건 · 수업 ${a.sessions.length}건</div>
        <textarea id="dr-comment" class="inp" rows="4" placeholder="특이사항·코멘트를 입력하세요">${d.comment||''}</textarea>
        <div style="margin-top:10px"><button class="xbtn primary" onclick="saveDaily('${d.date}')">보고 제출</button></div>
      </div></div>`;
    if (window.lucide) lucide.createIcons();
  }
  window.saveDaily = async function (date) {
    const comment = document.getElementById('dr-comment').value;
    const r = await api('/api/daily-report', { method:'POST', body: JSON.stringify({ date, comment }) });
    if (r && r.ok) showToast('✅ 일일보고 제출 (결재 상신)');
  };

  // ── 페이롤 ────────────────────────────────────────────────────
  async function renderPayroll(container) {
    container.innerHTML = '<div class="page"><div class="empty">로딩 중…</div></div>';
    const now = new Date();
    if (!window._plY) { window._plY = now.getFullYear(); window._plM = now.getMonth()+1; }
    const r = await api(`/api/payroll/crm?year=${window._plY}&month=${window._plM}`);
    const rows = r && r.ok ? await r.json() : [];
    const isAdmin = user.admin;
    const body = rows.map(x => `
      <tr><td style="text-align:left">${x.employee_name||x.employee_id}</td>
      <td>${x.pt_session_count}회 / ${(x.pt_amount||0).toLocaleString()}</td>
      <td>${x.gx_session_count}회 / ${(x.gx_amount||0).toLocaleString()}</td>
      <td style="font-weight:700">${(x.total_amount||0).toLocaleString()}</td>
      <td>${x.status==='confirmed'?'✅확정':'작성중'}</td></tr>`).join('');
    container.innerHTML = `
      <div class="page"><div class="card">
        <div class="card-head">수업 페이롤
          <span style="float:right">
            <input id="pl-y" type="number" value="${window._plY}" style="width:70px" class="inp">
            <input id="pl-m" type="number" value="${window._plM}" min="1" max="12" style="width:50px" class="inp">
            <button class="xbtn sm" onclick="reloadPayroll()">조회</button>
            ${isAdmin?`<button class="xbtn sm primary" onclick="confirmPayroll()">월 확정→ERP</button>`:''}
          </span></div>
        ${rows.length?`<table class="tbl"><thead><tr><th style="text-align:left">강사</th><th>PT</th><th>GX</th><th>합계</th><th>상태</th></tr></thead>
          <tbody>${body}</tbody></table>`:'<div class="empty">집계 내역이 없습니다</div>'}
        <div style="font-size:12px;opacity:.6;margin-top:6px">CRM 집계 → 본사관리자 확정 시 ERP로 반영됩니다.</div>
      </div></div>`;
  }
  window.reloadPayroll = function () {
    window._plY = parseInt(document.getElementById('pl-y').value)||window._plY;
    window._plM = parseInt(document.getElementById('pl-m').value)||window._plM;
    renderPayroll(document.getElementById('page-content'));
  };
  window.confirmPayroll = async function () {
    if (!confirm(`${window._plY}년 ${window._plM}월 페이롤을 확정하고 ERP로 넘길까요?`)) return;
    const r = await api(`/api/payroll/crm/confirm?year=${window._plY}&month=${window._plM}`, { method:'POST' });
    const d = r ? await r.json().catch(()=>({})) : {};
    if (r && r.ok) { showToast(`✅ ${d.confirmed}건 확정`); renderPayroll(document.getElementById('page-content')); }
    else showToast(d.detail||'확정 실패','err');
  };

  // ── 회원 포털: 내 수업 + 캔버스 서명 ──────────────────────────
  async function renderMemberLessons(container) {
    const r = await api('/api/my/lessons');
    if (!r || !r.ok) return;
    const d = await r.json();
    const page = container.querySelector('.page') || container;
    const card = document.createElement('div');
    card.className = 'card';
    card.style.marginTop = '14px';
    const pend = (d.pending_sign || []).map(s => `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid rgba(128,128,128,.15)">
        <div><b>${s.product_name}</b> · ${s.instructor_name || ''}<br>
          <span style="font-size:12px;opacity:.7">${s.scheduled_date || ''} ${s.scheduled_time || ''} — 수업 완료, 서명이 필요합니다</span></div>
        <button class="xbtn primary sm" onclick="openSign(${s.id})">서명하기</button>
      </div>`).join('');
    const up = (d.upcoming || []).map(s =>
      `<div style="padding:6px 0;font-size:13px">📅 ${s.scheduled_date || ''} ${s.scheduled_time || ''} · ${s.product_name} (${s.instructor_name||''})</div>`).join('');
    card.innerHTML = `
      <div class="card-head">내 수업</div>
      ${pend ? `<div style="margin-bottom:10px"><div style="font-weight:700;color:#E60028;margin-bottom:4px">✍️ 서명 대기 ${d.pending_sign.length}건</div>${pend}</div>` : ''}
      <div style="font-weight:700;margin:8px 0 4px">예정된 수업</div>
      ${up || '<div style="font-size:13px;opacity:.6">예정된 수업이 없습니다</div>'}
      <div style="font-size:12px;opacity:.6;margin-top:8px">완료/노쇼 누적: ${(d.completed||[]).length}회</div>`;
    page.appendChild(card);
  }

  window.openSign = function (sessionId) {
    closeModal();
    const ov = document.createElement('div');
    ov.className = 'modal-overlay'; ov.id = 'modal-overlay';
    ov.innerHTML = `
      <div class="modal">
        <div class="modal-header"><div class="modal-title">수업 완료 서명</div>
          <button class="modal-close" onclick="closeModal()">✕</button></div>
        <div class="modal-body">
          <div style="font-size:13px;opacity:.75;margin-bottom:8px">아래 칸에 서명해 주세요.</div>
          <canvas id="sign-pad" width="320" height="160"
            style="width:100%;border:1.5px dashed rgba(128,128,128,.5);border-radius:10px;touch-action:none;background:#fff"></canvas>
        </div>
        <div class="modal-footer">
          <button class="btn" onclick="clearSign()">지우기</button>
          <button class="btn primary" onclick="submitSign(${sessionId})">서명 완료</button>
        </div>
      </div>`;
    document.body.appendChild(ov);
    initSignPad();
  };

  let _sigCtx = null, _sigDrawing = false, _sigDirty = false;
  function initSignPad() {
    const c = document.getElementById('sign-pad');
    _sigCtx = c.getContext('2d');
    _sigCtx.lineWidth = 2.5; _sigCtx.lineCap = 'round'; _sigCtx.strokeStyle = '#111';
    _sigDirty = false;
    const pos = ev => {
      const r = c.getBoundingClientRect();
      const t = ev.touches ? ev.touches[0] : ev;
      return { x: (t.clientX - r.left) * (c.width / r.width), y: (t.clientY - r.top) * (c.height / r.height) };
    };
    const start = ev => { _sigDrawing = true; _sigDirty = true; const p = pos(ev); _sigCtx.beginPath(); _sigCtx.moveTo(p.x, p.y); ev.preventDefault(); };
    const move = ev => { if (!_sigDrawing) return; const p = pos(ev); _sigCtx.lineTo(p.x, p.y); _sigCtx.stroke(); ev.preventDefault(); };
    const end = () => { _sigDrawing = false; };
    c.addEventListener('mousedown', start); c.addEventListener('mousemove', move); window.addEventListener('mouseup', end);
    c.addEventListener('touchstart', start); c.addEventListener('touchmove', move); c.addEventListener('touchend', end);
  }
  window.clearSign = function () { const c = document.getElementById('sign-pad'); if (c) { _sigCtx.clearRect(0,0,c.width,c.height); _sigDirty=false; } };
  window.submitSign = async function (sessionId) {
    if (!_sigDirty) { showToast('서명을 입력하세요','err'); return; }
    const png = document.getElementById('sign-pad').toDataURL('image/png');
    const r = await api(`/api/my/lessons/session/${sessionId}/sign`, { method:'POST', body: JSON.stringify({ signature_png: png }) });
    const d = r ? await r.json().catch(()=>({})) : {};
    if (r && r.ok) { showToast('✅ 서명 완료'); closeModal(); renderPage('home'); }
    else showToast(d.detail || '서명 실패','err');
  };

  // ── Home ──────────────────────────────────────────────────────
  async function renderHome(container) {
    container.innerHTML = '<div class="page"><div class="empty">홈 로딩 중…</div></div>';
    try {
      const resp = await api('/api/home/data');
      if (!resp) return;
      const data = await resp.json();
      const { announcements = [], events = [], classes = [] } = data;

      const marqueeText = announcements.length
        ? announcements.map(a => a.title).join('    ·    ')
        : '라온스포츠 포털에 오신 것을 환영합니다';

      const ev = events[0];
      const heroHTML = ev ? `
        <div class="hero-main" style="${ev.image_path ? 'background-image:url('+ev.image_path+')' : 'background:#1a1410'}">
          ${ev.eyebrow ? `<div class="eyebrow"><i data-lucide="zap" style="width:12px;height:12px"></i> ${ev.eyebrow}</div>` : ''}
          <h2>${ev.title}</h2>
          <p>${ev.sub || ev.content || ''}</p>
          <button class="btn primary sm" onclick="openEvent(${ev.id})">자세히 보기 →</button>
        </div>` : `
        <div class="hero-main" style="background:#1a1410">
          <h2>라온스포츠에 오신 것을 환영합니다</h2>
          <p>최신 이벤트와 프로그램을 확인해 보세요.</p>
        </div>`;

      const sideEvs = events.slice(1, 3);
      const sideHTML = sideEvs.map(ev => `
        <div class="hero-side-card" style="cursor:pointer" onclick="openEvent(${ev.id})">
          <div class="deadline"><i data-lucide="calendar" style="width:12px;height:12px"></i> ${ev.ends_at || ''}</div>
          <h3>${ev.title}</h3>
          <p class="muted" style="font-size:13px;margin-top:4px">${(ev.sub || ev.content || '').slice(0, 60)}</p>
        </div>`).join('') || '<div class="hero-side-card"><p class="muted">진행중인 이벤트가 없습니다</p></div><div class="hero-side-card dark"><p>새 이벤트를 기대해 주세요</p></div>';

      const classHTML = classes.map(c => `
        <div class="class-card">
          <div class="thumb" style="background:linear-gradient(135deg,#E0382B22,#1a141022)">
            <div class="corner"><span class="badge red">${c.days || '매일'}</span></div>
          </div>
          <div class="meta">
            <div class="title">${c.class_name}</div>
            <div class="row"><i data-lucide="clock" style="width:13px;height:13px"></i><span>${c.start_time} ~ ${c.end_time}</span></div>
            <div class="row"><i data-lucide="user" style="width:13px;height:13px"></i><span>${c.instructor_name || '-'}</span></div>
          </div>
        </div>`).join('') || '<div class="empty">등록된 수업이 없습니다</div>';

      container.innerHTML = `
        <div class="page">
          <div class="marquee"><div class="marquee-wrap"><div class="marquee-track">${marqueeText + '    ·    ' + marqueeText}</div></div></div>
          <div class="hero-grid">${heroHTML}<div class="hero-side">${sideHTML}</div></div>
          <div style="margin-top:28px">
            <div class="card-head">
              <div><div class="section-title">오늘의 수업</div><div class="section-sub">현재 운영 중인 GX 프로그램</div></div>
            </div>
            <div class="class-grid">${classHTML}</div>
          </div>
        </div>`;
    } catch (err) {
      container.innerHTML = `<div class="page"><div class="empty">홈 데이터를 불러올 수 없습니다</div></div>`;
    }
    if (window.lucide) lucide.createIcons();
  }

  window.openEvent = function (id) { showToast('이벤트 상세보기 준비 중'); };

  // ── GPS 위치 취득 ─────────────────────────────────────────────
  let _cachedGps = null;
  let _gpsTs     = 0;

  async function getGps() {
    if (_cachedGps && Date.now() - _gpsTs < 120000) return _cachedGps; // 2분 캐시
    return new Promise((resolve) => {
      if (!navigator.geolocation) { resolve(null); return; }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          _cachedGps = { lat: pos.coords.latitude, lng: pos.coords.longitude };
          _gpsTs = Date.now();
          resolve(_cachedGps);
        },
        () => resolve(null),
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
      );
    });
  }

  // ── Attendance ────────────────────────────────────────────────
  function fmtMin(m) {
    if (!m) return '—';
    const h = Math.floor(m / 60), r = m % 60;
    return h + '시간 ' + r + '분';
  }

  function isMobile() {
    return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
  }

  async function renderAttendance(container) {
    if (user.role !== 'staff') {
      container.innerHTML = '<div class="page"><div class="empty">직원 전용 메뉴입니다</div></div>'; return;
    }
    container.innerHTML = '<div class="page"><div class="empty">근태 로딩 중…</div></div>';
    try {
      const today  = new Date().toISOString().slice(0, 10);
      const resp   = await api('/api/attendance/today');
      if (!resp) return;
      const record = await resp.json();

      const ci  = record.clock_in;
      const co  = record.clock_out;
      const bks = record.break_start; // 현재 휴게 중 여부
      const brk = record.break_minutes || 0;
      const wm  = record.work_minutes || 0;

      // 상태 뱃지
      let statusBadge = '<span class="badge outline">미기록</span>';
      if (co)       statusBadge = '<span class="badge ok">퇴근 완료</span>';
      else if (bks) statusBadge = '<span class="badge warn">휴게 중</span>';
      else if (ci)  statusBadge = '<span class="badge ok">근무 중</span>';

      // 버튼 구성
      let btnHtml = '';
      if (!ci) {
        btnHtml = `<button class="btn primary" onclick="clockIn()"><i data-lucide="log-in"></i> 출 근</button>`;
      } else if (!co) {
        if (bks) {
          btnHtml = `
            <button class="btn primary" onclick="breakEnd()"><i data-lucide="play"></i> 휴게 종료</button>
            <button class="btn" style="background:#e60028;color:#fff" onclick="clockOut()"><i data-lucide="log-out"></i> 퇴 근</button>`;
        } else {
          btnHtml = `
            <button class="btn ink" onclick="breakStart()"><i data-lucide="coffee"></i> 휴 게</button>
            <button class="btn" style="background:#e60028;color:#fff" onclick="clockOut()"><i data-lucide="log-out"></i> 퇴 근</button>`;
        }
      }

      container.innerHTML = `
        <div class="page">
          <div class="section-title">근태 관리</div>
          <div class="section-sub">오늘 ${today} · ${user.name}</div>
          <div id="gps-status" style="font-size:12px;color:#888;margin-bottom:8px">📍 위치 확인 중...</div>

          <div class="grid-2" style="margin:12px 0 18px;max-width:560px">
            <div class="stat"><div class="label">출근 시간</div>
              <div class="value" style="font-size:24px;font-weight:700">${ci || '—'}</div></div>
            <div class="stat"><div class="label">퇴근 시간</div>
              <div class="value" style="font-size:24px;font-weight:700">${co || '—'}</div></div>
            <div class="stat"><div class="label">근무 시간</div>
              <div class="value">${fmtMin(wm)}</div></div>
            <div class="stat"><div class="label">상태</div>
              <div class="value">${statusBadge}</div></div>
          </div>
          ${brk ? `<div style="font-size:13px;color:#888;margin-bottom:12px">☕ 휴게 ${fmtMin(brk)} 반영</div>` : ''}
          ${bks ? `<div style="font-size:13px;color:#d97706;margin-bottom:12px">☕ 휴게 중 (${bks} 시작)</div>` : ''}

          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:28px" id="att-btns">
            ${btnHtml}
          </div>

          <div class="card">
            <div class="card-head" style="padding:16px 20px 0">
              <div class="card-title">이번 달 근태 · 급여</div>
            </div>
            <div id="monthlyAttendance" style="padding:0 20px 16px"><div class="empty">불러오는 중…</div></div>
          </div>
        </div>`;
      if (window.lucide) lucide.createIcons();

      // GPS 상태 표시 + 버튼 제어
      getGps().then(gps => {
        const el   = document.getElementById('gps-status');
        const btns = document.getElementById('att-btns');
        if (!el) return;
        if (gps) {
          el.textContent = '📍 위치 확인됨';
          el.style.color = '#16a34a';
        } else {
          el.innerHTML = '⚠️ GPS 권한이 필요합니다 — 브라우저 주소창의 🔒 아이콘에서 위치 권한을 허용해 주세요';
          el.style.color = '#e60028';
          if (btns) {
            btns.innerHTML = `<div style="font-size:13px;color:#e60028;padding:8px 0">
              GPS 위치를 확인할 수 없어 출퇴근 처리가 불가합니다.<br>위치 권한 허용 후 새로고침 해주세요.</div>`;
          }
        }
      });

      loadMonthlyAttendance();
    } catch (err) {
      container.innerHTML = `<div class="page"><div class="empty">오류: ${err.message}</div></div>`;
    }
  }

  let _attCalYear = null, _attCalMonth = null;

  async function loadMonthlyAttendance(yr, mo) {
    const now  = new Date();
    if (!yr) { yr = _attCalYear || now.getFullYear(); }
    if (!mo) { mo = _attCalMonth || now.getMonth() + 1; }
    _attCalYear = yr; _attCalMonth = mo;

    const [r1, r2] = await Promise.all([
      api(`/api/attendance/monthly?year=${yr}&month=${mo}`),
      api(`/api/attendance/pay?year=${yr}&month=${mo}`),
    ]);
    const records  = r1 ? await r1.json() : [];
    const payData  = r2 ? await r2.json() : { records: [], total: 0 };
    const payMap   = {};
    (payData.records || []).forEach(p => { payMap[p.work_date] = p; });
    const recMap   = {};
    records.forEach(r => { recMap[r.work_date] = r; });
    const el = document.getElementById('monthlyAttendance');
    if (!el) return;

    // ── 요약 통계 ──────────────────────────────────────────
    const workDays  = records.filter(r => r.clock_in).length;
    const totalMin  = records.reduce((s, r) => s + (r.work_minutes || 0), 0);
    const totalPay  = payData.total || 0;
    const tH = Math.floor(totalMin / 60), tM = totalMin % 60;

    // ── 달력 그리드 (월요일 시작) ──────────────────────────
    const firstDay  = new Date(yr, mo - 1, 1);
    const lastDate  = new Date(yr, mo, 0).getDate();
    let startOffset = firstDay.getDay() - 1;       // Mon=0
    if (startOffset < 0) startOffset = 6;

    const todayStr  = now.toISOString().slice(0, 10);
    const dayNames  = ['월', '화', '수', '목', '금', '토', '일'];

    let cells = '';
    for (let i = 0; i < startOffset; i++) cells += '<div class="att-cal-cell empty"></div>';
    for (let d = 1; d <= lastDate; d++) {
      const ds  = `${yr}-${String(mo).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
      const r   = recMap[ds];
      const p   = payMap[ds];
      const dow = (startOffset + d - 1) % 7;       // 0=월 … 5=토 6=일
      const isToday = ds === todayStr;

      let inner = '', cellCls = '';
      if (r && r.clock_in) {
        cellCls = 'worked';
        const m  = r.work_minutes || 0;
        const hh = Math.floor(m / 60), mm = m % 60;
        const late = r.status === 'late' ? '<span class="att-late">지각</span>' : '';
        inner = `
          <div class="att-time">${r.clock_in}${r.clock_out ? '~' + r.clock_out : ''}</div>
          ${m ? `<div class="att-hours">${hh}h${mm ? ' ' + mm + 'm' : ''}</div>` : ''}
          ${p ? `<div class="att-pay">${(p.total_pay/10000).toFixed(p.total_pay%10000?1:0)}만</div>` : ''}
          ${late}`;
      }
      cells += `
        <div class="att-cal-cell ${cellCls} ${isToday ? 'today' : ''}">
          <div class="att-day ${dow === 5 ? 'sat' : ''} ${dow === 6 ? 'sun' : ''}">${d}</div>
          ${inner}
        </div>`;
    }

    el.innerHTML = `
      <style>
        .att-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0}
        .att-stat{background:var(--sf2,#f7f4f1);border-radius:12px;padding:12px 14px;text-align:center}
        .att-stat .lb{font-size:11px;color:#999;font-weight:600;margin-bottom:4px}
        .att-stat .vl{font-size:17px;font-weight:800;letter-spacing:-.02em}
        .att-stat .vl.pay{color:#16a34a}
        .att-cal-nav{display:flex;align-items:center;justify-content:center;gap:14px;margin:6px 0 12px}
        .att-cal-nav button{border:1px solid rgba(128,128,128,.25);background:transparent;color:inherit;
          border-radius:8px;width:32px;height:32px;font-size:15px;cursor:pointer}
        .att-cal-nav .ym{font-size:15px;font-weight:800}
        .att-cal-head{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:4px}
        .att-cal-head div{text-align:center;font-size:11px;font-weight:700;color:#999;padding:4px 0}
        .att-cal-head div:nth-child(6){color:#3b82f6}
        .att-cal-head div:nth-child(7){color:#e60028}
        .att-cal{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
        .att-cal-cell{min-height:64px;border-radius:10px;padding:5px 6px;background:var(--sf2,#f7f4f1);
          display:flex;flex-direction:column;gap:1px;position:relative;overflow:hidden}
        .att-cal-cell.empty{background:transparent}
        .att-cal-cell.worked{background:#eef6ff;border:1px solid #bfdbfe}
        .att-cal-cell.today{outline:2px solid #e60028;outline-offset:-2px}
        .att-day{font-size:11.5px;font-weight:700}
        .att-day.sat{color:#3b82f6}.att-day.sun{color:#e60028}
        .att-time{font-size:9.5px;color:#3b6bb3;font-weight:600;line-height:1.2;word-break:keep-all}
        .att-hours{font-size:10px;font-weight:700;color:#1d4ed8}
        .att-pay{font-size:10.5px;font-weight:800;color:#16a34a}
        .att-late{position:absolute;top:4px;right:5px;font-size:8.5px;color:#d97706;font-weight:700}
        @media(prefers-color-scheme:dark){
          .att-cal-cell.worked{background:rgba(59,130,246,.12);border-color:rgba(59,130,246,.3)}
        }
        @media(max-width:520px){.att-cal-cell{min-height:56px;padding:4px}}
      </style>
      <div class="att-summary">
        <div class="att-stat"><div class="lb">출근일 수</div><div class="vl">${workDays}일</div></div>
        <div class="att-stat"><div class="lb">누적 근무</div><div class="vl">${tH}시간${tM ? ' ' + tM + '분' : ''}</div></div>
        <div class="att-stat"><div class="lb">누적 급여</div><div class="vl pay">${totalPay > 0 ? totalPay.toLocaleString() + '원' : '—'}</div></div>
      </div>
      <div class="att-cal-nav">
        <button onclick="attCalMove(-1)">‹</button>
        <span class="ym">${yr}년 ${mo}월</span>
        <button onclick="attCalMove(1)">›</button>
      </div>
      <div class="att-cal-head">${dayNames.map(d => `<div>${d}</div>`).join('')}</div>
      <div class="att-cal">${cells}</div>`;
  }

  window.attCalMove = function (delta) {
    let y = _attCalYear, m = _attCalMonth + delta;
    if (m < 1)  { m = 12; y--; }
    if (m > 12) { m = 1;  y++; }
    loadMonthlyAttendance(y, m);
  };

  async function _doAttendance(endpoint) {
    const gps  = await getGps();
    const time = new Date().toTimeString().slice(0, 5);
    if (!gps) {
      showToast('📍 GPS 위치를 확인할 수 없습니다. 위치 권한을 허용하고 다시 시도해 주세요.', 'err');
      return { resp: null, time };
    }
    const body = { time, lat: gps.lat, lng: gps.lng };
    const resp = await api(endpoint, { method: 'POST', body: JSON.stringify(body) });
    return { resp, time };
  }

  window.clockIn    = async function () {
    const { resp, time } = await _doAttendance('/api/attendance/clock-in');
    if (resp && resp.ok) { showToast('✅ 출근 완료 — ' + time); navigateTo('attendance'); }
    else { const d = await resp?.json().catch(() => ({})); showToast(d?.detail || '처리 실패', 'err'); }
  };
  window.clockOut   = async function () {
    const { resp, time } = await _doAttendance('/api/attendance/clock-out');
    if (resp && resp.ok) { showToast('✅ 퇴근 완료 — ' + time); navigateTo('attendance'); }
    else { const d = await resp?.json().catch(() => ({})); showToast(d?.detail || '처리 실패', 'err'); }
  };
  window.breakStart = async function () {
    const { resp, time } = await _doAttendance('/api/attendance/break-start');
    if (resp && resp.ok) { showToast('☕ 휴게 시작 — ' + time); navigateTo('attendance'); }
    else { const d = await resp?.json().catch(() => ({})); showToast(d?.detail || '처리 실패', 'err'); }
  };
  window.breakEnd   = async function () {
    const { resp, time } = await _doAttendance('/api/attendance/break-end');
    if (resp && resp.ok) { showToast('▶ 휴게 종료 — ' + time); navigateTo('attendance'); }
    else { const d = await resp?.json().catch(() => ({})); showToast(d?.detail || '처리 실패', 'err'); }
  };

  // ── Operations ────────────────────────────────────────────────
  async function renderOperations(container) {
    if (user.role !== 'staff') {
      container.innerHTML = '<div class="page"><div class="empty">직원 전용 메뉴입니다</div></div>'; return;
    }
    container.innerHTML = `
      <div class="page">
        <div class="section-title">운영 관리</div>
        <div class="section-sub">재고 · 비품요청 · A/S · 이벤트 · 공지</div>
        <div class="tabs line" style="margin-bottom:22px" id="opsTabs">
          <button class="on" onclick="showOpsTab('inventory',this)">재고</button>
          <button onclick="showOpsTab('supply',this)">비품 요청</button>
          <button onclick="showOpsTab('as',this)">A/S</button>
          <button onclick="showOpsTab('events',this)">이벤트</button>
          <button onclick="showOpsTab('announcements',this)">공지사항</button>
          <button onclick="showOpsTab('instructorsMgmt',this)">강사 관리</button>
        </div>
        <div id="opsContent"><div class="empty">불러오는 중…</div></div>
      </div>`;
    showOpsTab('inventory');
  }

  window.showOpsTab = async function (tab, btnEl) {
    if (btnEl) {
      document.querySelectorAll('#opsTabs button').forEach(b => b.classList.remove('on'));
      btnEl.classList.add('on');
    }
    const content = document.getElementById('opsContent');
    if (!content) return;
    content.innerHTML = '<div class="empty">불러오는 중…</div>';
    const branch = user.branch || '';

    try {
      if (tab === 'inventory') {
        const resp  = await api(`/api/operations/inventory?branch=${encodeURIComponent(branch)}`);
        const items = await resp.json();
        content.innerHTML = `
          <div class="card-head">
            <div class="card-title">재고 목록</div>
            <button class="btn primary sm" onclick="modalAddInventory()"><i data-lucide="plus"></i> 품목 추가</button>
          </div>
          <table class="table">
            <thead><tr><th>품목</th><th>분류</th><th>수량</th><th>최소수량</th><th>단위</th><th>조작</th></tr></thead>
            <tbody>
              ${items.map(i => `
                <tr>
                  <td><b>${i.item_name}</b></td><td>${i.category}</td>
                  <td style="font-size:16px;font-weight:700;color:${i.quantity<=i.min_quantity?'var(--accent)':'inherit'}">${i.quantity}</td>
                  <td>${i.min_quantity}</td><td>${i.unit}</td>
                  <td>
                    <button class="btn sm" onclick="modalAdjustInventory(${i.id},'in','${i.item_name}')">입고</button>
                    <button class="btn sm" onclick="modalAdjustInventory(${i.id},'out','${i.item_name}')">출고</button>
                  </td>
                </tr>`).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--muted)">재고 없음</td></tr>'}
            </tbody>
          </table>`;
        if (window.lucide) lucide.createIcons();

      } else if (tab === 'supply') {
        const resp  = await api(`/api/operations/supply?branch=${encodeURIComponent(branch)}`);
        const items = await resp.json();
        const statusLabel = { pending:'대기', approved:'승인', rejected:'반려', delivered:'수령완료' };
        content.innerHTML = `
          <div class="card-head">
            <div class="card-title">비품 요청</div>
            <button class="btn primary sm" onclick="modalNewSupply()"><i data-lucide="plus"></i> 요청 등록</button>
          </div>
          <table class="table">
            <thead><tr><th>품목</th><th>수량</th><th>사유</th><th>상태</th><th>요청일</th></tr></thead>
            <tbody>
              ${items.map(i => `
                <tr>
                  <td><b>${i.item_name}</b></td>
                  <td>${i.quantity} ${i.unit}</td>
                  <td style="color:var(--muted);font-size:13px">${i.reason||'—'}</td>
                  <td><span class="badge ${i.status==='approved'||i.status==='delivered'?'ok':i.status==='rejected'?'red':'warn'}">${statusLabel[i.status]||i.status}</span></td>
                  <td>${i.created_at?i.created_at.slice(0,10):''}</td>
                </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted)">요청 없음</td></tr>'}
            </tbody>
          </table>`;
        if (window.lucide) lucide.createIcons();

      } else if (tab === 'as') {
        const resp  = await api(`/api/operations/as?branch=${encodeURIComponent(branch)}`);
        const items = await resp.json();
        const prioLabel = { urgent:'긴급', normal:'일반', low:'낮음' };
        const statLabel = { open:'접수', in_progress:'처리중', done:'완료' };
        content.innerHTML = `
          <div class="card-head">
            <div class="card-title">A/S 요청</div>
            <button class="btn primary sm" onclick="modalNewAs()"><i data-lucide="plus"></i> A/S 접수</button>
          </div>
          <table class="table">
            <thead><tr><th>제목</th><th>설명</th><th>우선순위</th><th>상태</th><th>등록일</th></tr></thead>
            <tbody>
              ${items.map(i => `
                <tr>
                  <td><b>${i.title}</b></td>
                  <td style="color:var(--muted);font-size:13px">${(i.description||'').slice(0,40)}</td>
                  <td><span class="badge ${i.priority==='urgent'?'red':i.priority==='low'?'outline':'warn'}">${prioLabel[i.priority]||i.priority}</span></td>
                  <td><span class="badge ${i.status==='done'?'ok':i.status==='in_progress'?'warn':'outline'}">${statLabel[i.status]||i.status}</span></td>
                  <td>${i.created_at?i.created_at.slice(0,10):''}</td>
                </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted)">요청 없음</td></tr>'}
            </tbody>
          </table>`;
        if (window.lucide) lucide.createIcons();

      } else if (tab === 'events') {
        const resp  = await api(`/api/operations/events?branch=${encodeURIComponent(branch)}`);
        const items = await resp.json();
        content.innerHTML = `
          <div class="card-head">
            <div class="card-title">이벤트 관리</div>
            <button class="btn primary sm" onclick="modalNewEvent()"><i data-lucide="plus"></i> 이벤트 추가</button>
          </div>
          <table class="table">
            <thead><tr><th>제목</th><th>태그</th><th>마감일</th><th>활성</th><th>등록일</th></tr></thead>
            <tbody>
              ${items.map(i => `
                <tr>
                  <td><b>${i.title}</b></td>
                  <td><span class="badge outline">${i.eyebrow||'—'}</span></td>
                  <td>${i.ends_at||'—'}</td>
                  <td><span class="badge ${i.is_active?'ok':'outline'}">${i.is_active?'활성':'비활성'}</span></td>
                  <td>${i.created_at?i.created_at.slice(0,10):''}</td>
                </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted)">이벤트 없음</td></tr>'}
            </tbody>
          </table>`;
        if (window.lucide) lucide.createIcons();

      } else if (tab === 'announcements') {
        const resp  = await api(`/api/operations/announcements?branch=${encodeURIComponent(branch)}`);
        const items = await resp.json();
        content.innerHTML = `
          <div class="card-head">
            <div class="card-title">공지사항</div>
            <button class="btn primary sm" onclick="modalNewAnnouncement()"><i data-lucide="plus"></i> 공지 등록</button>
          </div>
          <table class="table">
            <thead><tr><th>제목</th><th>내용</th><th>우선순위</th><th>대상</th><th>만료일</th></tr></thead>
            <tbody>
              ${items.map(i => `
                <tr>
                  <td><b>${i.title}</b></td>
                  <td style="color:var(--muted);font-size:13px">${(i.content||'').slice(0,40)}</td>
                  <td><span class="badge ${i.priority==='urgent'?'red':'outline'}">${i.priority==='urgent'?'긴급':'일반'}</span></td>
                  <td>${i.target_branch==='all'?'전체':i.target_branch}</td>
                  <td>${i.expires_at||'—'}</td>
                </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted)">공지 없음</td></tr>'}
            </tbody>
          </table>`;
        if (window.lucide) lucide.createIcons();

      } else if (tab === 'instructorsMgmt') {
        const resp  = await api(`/api/operations/instructors?branch=${encodeURIComponent(branch)}`);
        const items = await resp.json();
        content.innerHTML = `
          <div class="card-head">
            <div class="card-title">강사 관리</div>
            <button class="btn primary sm" onclick="modalNewInstructor()"><i data-lucide="plus"></i> 강사 추가</button>
          </div>
          <table class="table">
            <thead><tr><th>이름</th><th>영문</th><th>역할</th><th>소개</th></tr></thead>
            <tbody>
              ${items.map(i => `
                <tr>
                  <td><b>${i.name}</b></td>
                  <td style="color:var(--muted)">${i.english||'—'}</td>
                  <td><span class="badge outline">${i.role||'—'}</span></td>
                  <td style="color:var(--muted);font-size:13px">${(i.bio||'').slice(0,50)}</td>
                </tr>`).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--muted)">강사 없음</td></tr>'}
            </tbody>
          </table>`;
        if (window.lucide) lucide.createIcons();
      }
    } catch (err) {
      content.innerHTML = `<div class="empty">오류: ${err.message}</div>`;
    }
  };

  // ── Operations Modal Forms ────────────────────────────────────
  window.modalAddInventory = function () {
    createModal({
      title: '재고 품목 추가',
      fields: [
        { id:'item_name', label:'품목명', type:'text', required:true, placeholder:'예: 운동 매트' },
        { id:'category',  label:'분류',   type:'select',
          options:[{value:'일반',label:'일반'},{value:'운동기구',label:'운동기구'},
                   {value:'소모품',label:'소모품'},{value:'청소용품',label:'청소용품'},{value:'사무용품',label:'사무용품'}] },
        { id:'quantity',     label:'초기 수량',  type:'number', default:'0',  min:0, row:'qty' },
        { id:'min_quantity', label:'최소 수량',  type:'number', default:'0',  min:0, row:'qty' },
        { id:'unit', label:'단위', type:'text', default:'개', placeholder:'개 / 롤 / 박스' },
      ],
      submitLabel: '추가',
      onSubmit: async (data) => {
        const resp = await api('/api/operations/inventory', {
          method: 'POST',
          body: JSON.stringify({ ...data, branch: user.branch,
            quantity: parseInt(data.quantity)||0, min_quantity: parseInt(data.min_quantity)||0 })
        });
        if (!resp?.ok) throw new Error('추가 실패');
        showToast('품목이 추가되었습니다');
        showOpsTab('inventory');
      }
    });
  };

  window.modalAdjustInventory = function (id, type, name) {
    createModal({
      title: (type === 'in' ? '📥 입고' : '📤 출고') + ' — ' + name,
      fields: [
        { id:'qty',  label:'수량', type:'number', default:'1', min:1, required:true },
        { id:'note', label:'메모', type:'text', placeholder:'선택사항' },
      ],
      submitLabel: type === 'in' ? '입고 처리' : '출고 처리',
      onSubmit: async (data) => {
        const resp = await api(`/api/operations/inventory/${id}/adjust`, {
          method: 'POST',
          body: JSON.stringify({ type, qty: parseInt(data.qty)||1, note: data.note })
        });
        if (!resp?.ok) throw new Error('처리 실패');
        showToast(type === 'in' ? '입고 처리 완료' : '출고 처리 완료');
        showOpsTab('inventory');
      }
    });
  };

  window.modalNewSupply = function () {
    createModal({
      title: '비품 요청 등록',
      fields: [
        { id:'item_name', label:'품목명', type:'text', required:true, placeholder:'필요한 품목을 입력하세요' },
        { id:'quantity',  label:'수량',   type:'number', default:'1', min:1, row:'qu' },
        { id:'unit',      label:'단위',   type:'text',   default:'개', row:'qu' },
        { id:'reason', label:'요청 사유', type:'textarea', placeholder:'필요한 이유를 간략히 적어주세요' },
      ],
      submitLabel: '요청 등록',
      onSubmit: async (data) => {
        const resp = await api('/api/operations/supply', {
          method: 'POST',
          body: JSON.stringify({ ...data, branch: user.branch, created_name: user.name,
            quantity: parseInt(data.quantity)||1 })
        });
        if (!resp?.ok) throw new Error('등록 실패');
        showToast('비품 요청이 접수되었습니다');
        showOpsTab('supply');
      }
    });
  };

  window.modalNewAs = function () {
    createModal({
      title: 'A/S 요청 접수',
      fields: [
        { id:'title', label:'요청 제목', type:'text', required:true, placeholder:'예: 러닝머신 3번 오작동' },
        { id:'priority', label:'우선순위', type:'radio',
          options:[{value:'urgent',label:'🔴 긴급'},{value:'normal',label:'🟡 일반'},{value:'low',label:'🟢 낮음'}],
          default:'normal' },
        { id:'description', label:'상세 내용', type:'textarea', rows:4,
          placeholder:'증상, 위치, 발생 시점 등을 자세히 적어주세요' },
      ],
      submitLabel: 'A/S 접수',
      onSubmit: async (data) => {
        const resp = await api('/api/operations/as', {
          method: 'POST',
          body: JSON.stringify({ ...data, branch: user.branch, created_name: user.name })
        });
        if (!resp?.ok) throw new Error('접수 실패');
        showToast('A/S 요청이 접수되었습니다');
        showOpsTab('as');
      }
    });
  };

  window.modalNewEvent = function () {
    createModal({
      title: '이벤트 추가',
      size: 'lg',
      fields: [
        { id:'title',   label:'이벤트 제목', type:'text', required:true, placeholder:'예: 여름 특별 GX 이벤트' },
        { id:'eyebrow', label:'태그 (상단 라벨)', type:'text', placeholder:'예: 이벤트 / 프로모션' },
        { id:'content', label:'내용', type:'textarea', rows:4, placeholder:'이벤트 상세 내용을 입력하세요' },
        { id:'ends_at', label:'마감일', type:'date' },
        { id:'image',   label:'이미지', type:'file', accept:'image/*', placeholder:'이미지를 클릭하여 선택 (선택사항)' },
      ],
      submitLabel: '이벤트 등록',
      onSubmit: async (data, hasFile) => {
        const fd = new FormData();
        fd.append('title',   data.title);
        fd.append('eyebrow', data.eyebrow || '');
        fd.append('content', data.content || '');
        fd.append('ends_at', data.ends_at || '');
        fd.append('branch',  user.branch || '');
        if (data.image) fd.append('image', data.image);
        const resp = await apiForm('/api/operations/events', fd);
        if (!resp?.ok) throw new Error('등록 실패');
        showToast('이벤트가 등록되었습니다');
        showOpsTab('events');
      }
    });
  };

  window.modalNewAnnouncement = function () {
    createModal({
      title: '공지사항 등록',
      fields: [
        { id:'title',   label:'제목', type:'text', required:true, placeholder:'공지 제목을 입력하세요' },
        { id:'content', label:'내용', type:'textarea', rows:4, placeholder:'공지 내용을 입력하세요' },
        { id:'priority', label:'우선순위', type:'radio',
          options:[{value:'normal',label:'일반'},{value:'urgent',label:'🔴 긴급'}], default:'normal' },
        { id:'target_branch', label:'대상 지점', type:'text',
          default: user.branch || 'all', placeholder:'all = 전체, 특정 지점명 입력 가능' },
        { id:'expires_at', label:'만료일 (선택)', type:'date' },
      ],
      submitLabel: '공지 등록',
      onSubmit: async (data) => {
        const resp = await api('/api/operations/announcements', {
          method: 'POST',
          body: JSON.stringify({ ...data, created_by: user.name })
        });
        if (!resp?.ok) throw new Error('등록 실패');
        showToast('공지사항이 등록되었습니다');
        showOpsTab('announcements');
      }
    });
  };

  window.modalNewInstructor = function () {
    createModal({
      title: '강사 추가',
      size: 'lg',
      fields: [
        { id:'name',    label:'이름',   type:'text', required:true, placeholder:'강사 이름', row:'nm' },
        { id:'english', label:'영문명', type:'text', placeholder:'English Name', row:'nm' },
        { id:'role',    label:'역할',   type:'text', placeholder:'예: GX강사 / 퍼스널트레이너', row:'rl' },
        { id:'branch',  label:'지점',   type:'text', default: user.branch, row:'rl' },
        { id:'bio',     label:'소개',   type:'textarea', rows:3, placeholder:'강사 소개를 입력하세요' },
        { id:'photo',   label:'프로필 사진', type:'file', accept:'image/*', placeholder:'사진을 클릭하여 선택 (선택사항)' },
      ],
      submitLabel: '강사 추가',
      onSubmit: async (data) => {
        const fd = new FormData();
        ['name','english','role','branch','bio'].forEach(k => fd.append(k, data[k]||''));
        if (data.photo) fd.append('photo', data.photo);
        const resp = await apiForm('/api/operations/instructors', fd);
        if (!resp?.ok) throw new Error('추가 실패');
        showToast('강사가 등록되었습니다');
        showOpsTab('instructorsMgmt');
      }
    });
  };

  // ── Members ───────────────────────────────────────────────────
  async function renderMembers(container) {
    if (user.role !== 'staff') {
      container.innerHTML = '<div class="page"><div class="empty">직원 전용 메뉴입니다</div></div>'; return;
    }
    container.innerHTML = `
      <div class="page">
        <div class="card-head">
          <div><div class="section-title">회원 관리</div><div class="section-sub">${user.branch}</div></div>
          <button class="btn primary" onclick="modalNewMember()"><i data-lucide="user-plus"></i> 신규 등록</button>
        </div>
        <div style="margin-bottom:14px">
          <input class="input" id="memberSearch" placeholder="이름 또는 전화번호 검색…" style="max-width:300px"
                 oninput="searchMembers(this.value)">
        </div>
        <div id="memberList"><div class="empty">불러오는 중…</div></div>
      </div>`;
    if (window.lucide) lucide.createIcons();
    loadMembers('');
  }

  async function loadMembers(q) {
    const branch = user.branch || '';
    const resp   = await api(`/api/members?branch=${encodeURIComponent(branch)}&q=${encodeURIComponent(q)}`);
    if (!resp) return;
    const members = await resp.json();
    const el = document.getElementById('memberList');
    if (!el) return;
    el.innerHTML = `
      <table class="table">
        <thead><tr><th>이름</th><th>전화번호</th><th>이메일</th><th>가입일</th><th>상태</th></tr></thead>
        <tbody>
          ${members.map(m => `
            <tr class="row-hover" style="cursor:pointer" onclick="modalViewMember(${m.id},'${(m.name||'').replace(/'/g,"\\'")}','${m.phone||''}','${m.email||''}','${m.join_date||''}','${m.status||'active'}','${m.note||''}')">
              <td><b>${m.name}</b></td>
              <td>${m.phone || '—'}</td>
              <td style="color:var(--muted);font-size:13px">${m.email || '—'}</td>
              <td>${m.join_date || '—'}</td>
              <td><span class="badge ${m.status==='active'?'ok':'outline'}">${m.status==='active'?'활성':'비활성'}</span></td>
            </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted)">회원 없음</td></tr>'}
        </tbody>
      </table>`;
  }

  window.searchMembers = function (q) { loadMembers(q); };

  window.modalNewMember = function () {
    createModal({
      title: '회원 신규 등록',
      size: 'lg',
      fields: [
        { id:'name',       label:'이름',     type:'text',   required:true, placeholder:'회원 이름', row:'nm' },
        { id:'phone',      label:'전화번호', type:'text',   placeholder:'010-0000-0000', row:'nm' },
        { id:'email',      label:'이메일',   type:'text',   placeholder:'example@email.com', row:'em' },
        { id:'birth_date', label:'생년월일', type:'date',   row:'em' },
        { id:'gender',     label:'성별',     type:'select',
          options:[{value:'',label:'선택 안함'},{value:'남',label:'남성'},{value:'여',label:'여성'}], row:'gj' },
        { id:'join_date',  label:'가입일',   type:'date',   row:'gj' },
        { id:'note',       label:'메모',     type:'textarea', rows:2, placeholder:'선택사항' },
      ],
      submitLabel: '회원 등록',
      onSubmit: async (data) => {
        const resp = await api('/api/members', {
          method: 'POST',
          body: JSON.stringify({ ...data, branch: user.branch, status: 'active' })
        });
        if (!resp?.ok) throw new Error('등록 실패');
        showToast('회원이 등록되었습니다');
        loadMembers('');
      }
    });
  };

  window.modalViewMember = function (id, name, phone, email, joinDate, status, note) {
    createModal({
      title: '회원 정보 — ' + name,
      fields: [
        { id:'name',      label:'이름',     type:'text',   default: name },
        { id:'phone',     label:'전화번호', type:'text',   default: phone },
        { id:'email',     label:'이메일',   type:'text',   default: email, row:'em' },
        { id:'join_date', label:'가입일',   type:'date',   default: joinDate, row:'em' },
        { id:'status',    label:'상태',     type:'select',
          options:[{value:'active',label:'활성'},{value:'inactive',label:'비활성'}], default: status },
        { id:'note',      label:'메모',     type:'textarea', rows:2, default: note },
        { id:'_id',       label:'',         type:'hidden',  value: String(id) },
      ],
      submitLabel: '저장',
      onSubmit: async (data) => {
        const resp = await api(`/api/members/${id}`, {
          method: 'PATCH',
          body: JSON.stringify({ name: data.name, phone: data.phone, email: data.email,
            join_date: data.join_date, status: data.status, note: data.note })
        });
        if (!resp?.ok) throw new Error('저장 실패');
        showToast('회원 정보가 수정되었습니다');
        loadMembers('');
      }
    });
  };

  // ── Classes ───────────────────────────────────────────────────
  const PROD_CAT = {
    gx:     { label: 'GX 프로그램', icon: 'activity',     color: '#e60028' },
    lesson: { label: '레슨 프로그램', icon: 'target',     color: '#3b82f6' },
    goods:  { label: '상품',        icon: 'shopping-bag', color: '#16a34a' },
  };

  async function renderClasses(container) {
    container.innerHTML = '<div class="page"><div class="empty">상품 로딩 중…</div></div>';
    try {
      const branch = user.branch || '';
      const [pResp, sResp] = await Promise.all([
        api(`/api/products?branch=${encodeURIComponent(branch)}`),
        user.role === 'staff' ? api(`/api/sales?branch=${encodeURIComponent(branch)}`) : Promise.resolve(null),
      ]);
      if (!pResp) return;
      const products = await pResp.json();
      const sales    = sResp ? await sResp.json() : [];

      const isStaff = user.role === 'staff';
      const addBtn  = isStaff
        ? `<button class="btn primary sm" onclick="modalNewProduct()"><i data-lucide="plus"></i> 상품 추가</button>` : '';
      const payBtn  = isStaff
        ? `<button class="btn sm" style="background:#16a34a;color:#fff" onclick="modalNewSale()"><i data-lucide="credit-card"></i> 결제 등록</button>` : '';

      const fmtWon = v => (v || 0).toLocaleString() + '원';

      const catSection = (cat) => {
        const items = products.filter(p => p.category === cat);
        const cfg   = PROD_CAT[cat];
        if (!items.length && !isStaff) return '';
        return `
          <div style="margin-bottom:28px">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
              <i data-lucide="${cfg.icon}" style="width:17px;height:17px;color:${cfg.color}"></i>
              <span style="font-size:15px;font-weight:800">${cfg.label}</span>
              <span style="font-size:12px;color:#999">${items.length}개</span>
            </div>
            <div class="class-grid">
              ${items.map(p => {
                let detail = '';
                if (cat === 'gx') {
                  detail = `
                    <div class="row"><i data-lucide="clock" style="width:13px;height:13px"></i><span>${p.days || '매일'} · ${p.start_time}~${p.end_time}</span></div>
                    <div class="row"><i data-lucide="user" style="width:13px;height:13px"></i><span>${p.instructor_name || '강사 미배정'}</span></div>
                    <div class="row"><i data-lucide="users" style="width:13px;height:13px"></i><span>정원 ${p.capacity}명</span></div>`;
                } else if (cat === 'lesson') {
                  detail = `
                    <div class="row"><i data-lucide="target" style="width:13px;height:13px"></i><span>${p.lesson_type}</span></div>
                    <div class="row"><i data-lucide="repeat" style="width:13px;height:13px"></i><span>${p.sessions}회</span></div>`;
                }
                const delBtn = isStaff
                  ? `<button onclick="deleteProduct(${p.id})" title="삭제"
                       style="position:absolute;top:8px;right:8px;border:none;background:rgba(0,0,0,.35);
                       color:#fff;border-radius:6px;width:24px;height:24px;cursor:pointer;font-size:13px">×</button>` : '';
                return `
                  <div class="class-card" style="position:relative">
                    ${delBtn}
                    <div class="meta">
                      <div class="title">${p.name}</div>
                      ${detail}
                      <div class="row" style="margin-top:6px">
                        <span style="font-size:15px;font-weight:800;color:${cfg.color}">${fmtWon(p.price)}</span>
                      </div>
                    </div>
                  </div>`;
              }).join('') || '<div class="empty" style="grid-column:1/-1">등록된 항목이 없습니다</div>'}
            </div>
          </div>`;
      };

      // 최근 결제 내역 (직원만)
      let salesHtml = '';
      if (isStaff) {
        salesHtml = `
          <div class="card" style="margin-top:8px">
            <div class="card-head" style="padding:16px 20px 0">
              <div class="card-title">💳 최근 결제 내역</div>
            </div>
            <div style="padding:8px 20px 16px;overflow-x:auto">
              ${sales.length ? `
                <table class="table">
                  <thead><tr><th>일자</th><th>회원</th><th>상품</th><th>분류</th><th>금액</th><th>결제</th><th>관리비</th><th>담당</th></tr></thead>
                  <tbody>
                    ${sales.slice(0, 30).map(s => `
                      <tr>
                        <td>${s.sale_date || (s.created_at || '').slice(0,10)}</td>
                        <td>${s.member_name || '—'}</td>
                        <td>${s.product_name}</td>
                        <td>${PROD_CAT[s.category]?.label || s.category || '—'}</td>
                        <td style="font-weight:700">${fmtWon(s.amount)}</td>
                        <td>${s.pay_method}</td>
                        <td>${s.is_mgmt_fee ? '✅' : '—'}</td>
                        <td>${s.sold_by || '—'}</td>
                      </tr>`).join('')}
                  </tbody>
                </table>` : '<div class="empty">결제 내역이 없습니다</div>'}
            </div>
          </div>`;
      }

      container.innerHTML = `
        <div class="page">
          <div class="card-head">
            <div><div class="section-title">상품 관리</div><div class="section-sub">${branch} · GX · 레슨 · 상품 / 결제 등록</div></div>
            <div style="display:flex;gap:8px">${payBtn}${addBtn}</div>
          </div>
          ${catSection('gx')}
          ${catSection('lesson')}
          ${catSection('goods')}
          ${salesHtml}
        </div>`;
      if (window.lucide) lucide.createIcons();
    } catch (err) {
      container.innerHTML = `<div class="page"><div class="empty">오류: ${err.message}</div></div>`;
    }
  }

  window.deleteProduct = async function (pid) {
    if (!confirm('이 상품을 삭제(비활성)하시겠습니까?')) return;
    const resp = await api(`/api/products/${pid}`, { method: 'DELETE' });
    if (resp?.ok) { showToast('삭제되었습니다'); renderClasses(document.getElementById('page-content')); }
    else showToast('삭제 실패', 'err');
  };

  // ── 상품 추가: 1단계 카테고리 선택 → 2단계 상세 입력 ─────────
  window.modalNewProduct = function () {
    createModal({
      title: '상품 추가 — 분류 선택',
      fields: [
        { id:'category', label:'상품 분류', type:'radio', options:[
          { value:'gx',     label:'GX 프로그램' },
          { value:'lesson', label:'레슨 (PT·골프)' },
          { value:'goods',  label:'상품 (카페 등)' },
        ]},
      ],
      submitLabel: '다음',
      onSubmit: async (data) => {
        setTimeout(() => openProductForm(data.category), 100);
      }
    });
  };

  async function openProductForm(category) {
    if (category === 'gx') {
      // 강사 목록 불러와서 select 옵션 구성
      let instructors = [];
      try {
        const r = await api(`/api/operations/instructors?branch=${encodeURIComponent(user.branch || '')}`);
        if (r) instructors = await r.json();
      } catch (e) {}
      const instOpts = instructors.map(i => i.name);
      createModal({
        title: 'GX 프로그램 추가',
        size: 'lg',
        fields: [
          { id:'name',  label:'프로그램 이름', type:'text', required:true, placeholder:'예: 줌바댄스 / 필라테스' },
          { id:'instructor_name', label:'담당 강사', type: instOpts.length ? 'select' : 'text',
            options: instOpts.length ? ['', ...instOpts] : undefined,
            placeholder:'강사 이름', hint: instOpts.length ? '' : '강사 탭에서 강사를 먼저 등록하면 선택할 수 있습니다' },
          { id:'price', label:'금액 (원)', type:'number', default:'0', min:0 },
          { id:'days',  label:'운영 요일', type:'text', placeholder:'예: 월수금 / 화목 / 매일', row:'dt' },
          { id:'capacity', label:'정원 (명)', type:'number', default:'20', min:1, row:'dt' },
          { id:'start_time', label:'시작 시간', type:'time', default:'10:00', row:'tm' },
          { id:'end_time',   label:'종료 시간', type:'time', default:'11:00', row:'tm' },
        ],
        submitLabel: 'GX 등록',
        onSubmit: async (data) => submitProduct({ ...data, category:'gx',
          price: parseInt(data.price)||0, capacity: parseInt(data.capacity)||20 }),
      });
    } else if (category === 'lesson') {
      createModal({
        title: '레슨 프로그램 추가',
        size: 'lg',
        fields: [
          { id:'lesson_type', label:'레슨 종류', type:'radio', options:[
            { value:'PT', label:'PT' }, { value:'골프레슨', label:'골프레슨' },
          ]},
          { id:'name',     label:'상품명', type:'text', required:true, placeholder:'예: PT 10회권 / 골프 주2회 레슨' },
          { id:'sessions', label:'횟수 (회)', type:'number', default:'10', min:1, row:'ps' },
          { id:'price',    label:'금액 (원)', type:'number', default:'0',  min:0, row:'ps' },
        ],
        submitLabel: '레슨 등록',
        onSubmit: async (data) => submitProduct({ ...data, category:'lesson',
          price: parseInt(data.price)||0, sessions: parseInt(data.sessions)||0 }),
      });
    } else {
      createModal({
        title: '상품 추가',
        fields: [
          { id:'name',  label:'상품명',   type:'text', required:true, placeholder:'예: 아메리카노 / 운동타올' },
          { id:'price', label:'가격 (원)', type:'number', default:'0', min:0 },
        ],
        submitLabel: '상품 등록',
        onSubmit: async (data) => submitProduct({ ...data, category:'goods',
          price: parseInt(data.price)||0 }),
      });
    }
  }

  async function submitProduct(data) {
    const resp = await api('/api/products', {
      method: 'POST',
      body: JSON.stringify({ ...data, branch: user.branch || '' })
    });
    if (!resp?.ok) {
      const d = await resp?.json().catch(() => ({}));
      throw new Error(d?.detail || '등록 실패');
    }
    showToast('✅ 등록되었습니다');
    renderClasses(document.getElementById('page-content'));
  }

  // ── 결제 등록 (CRM) ───────────────────────────────────────────
  window.modalNewSale = async function () {
    const branch = user.branch || '';
    let products = [], members = [];
    try {
      const [pR, mR] = await Promise.all([
        api(`/api/products?branch=${encodeURIComponent(branch)}`),
        api(`/api/members?branch=${encodeURIComponent(branch)}`),
      ]);
      if (pR) products = await pR.json();
      if (mR) members  = await mR.json();
    } catch (e) {}

    const prodOpts = products.map(p =>
      `${PROD_CAT[p.category]?.label || ''} | ${p.name} (${(p.price||0).toLocaleString()}원)`);
    const membOpts = members.map(m => `${m.name} (${m.phone || '번호없음'})`);

    createModal({
      title: '💳 결제 등록',
      size: 'lg',
      fields: [
        { id:'member',  label:'회원', type: membOpts.length ? 'select' : 'text',
          options: membOpts.length ? ['직접 입력', ...membOpts] : undefined,
          placeholder:'회원 이름', hint:'목록에 없으면 직접 입력을 선택하세요' },
        { id:'member_direct', label:'회원 이름 (직접 입력 시)', type:'text', placeholder:'비회원/직접 입력' },
        { id:'product', label:'상품', type: prodOpts.length ? 'select' : 'text',
          options: prodOpts.length ? prodOpts : undefined, required:true,
          placeholder:'상품명' },
        { id:'amount',  label:'결제 금액 (원)', type:'number', default:'0', min:0, required:true,
          hint:'상품 기본가와 다르면 수정하세요 (할인 등)' },
        { id:'pay_method', label:'결제 수단', type:'radio', options:[
          { value:'카드', label:'💳 카드' }, { value:'현금', label:'💵 현금' }, { value:'계좌이체', label:'🏦 계좌이체' },
        ]},
        { id:'is_mgmt_fee', label:'관리비 청구 대상', type:'radio', options:[
          { value:'0', label:'아니오' }, { value:'1', label:'예 (아파트 관리비 청구서 반영)' },
        ]},
      ],
      submitLabel: '결제 저장',
      onSubmit: async (data) => {
        // 회원 매칭
        let memberId = 0, memberName = data.member_direct || '';
        if (data.member && data.member !== '직접 입력') {
          const idx = membOpts.indexOf(data.member);
          if (idx >= 0) { memberId = members[idx].id; memberName = members[idx].name; }
        }
        // 상품 매칭
        let productId = 0, productName = data.product, category = '';
        const pIdx = prodOpts.indexOf(data.product);
        if (pIdx >= 0) {
          productId   = products[pIdx].id;
          productName = products[pIdx].name;
          category    = products[pIdx].category;
        }
        const amount = parseInt(data.amount) || 0;
        if (amount <= 0) throw new Error('결제 금액을 입력하세요');

        const resp = await api('/api/sales', {
          method: 'POST',
          body: JSON.stringify({
            branch, member_id: memberId, member_name: memberName,
            product_id: productId, product_name: productName, category,
            amount, pay_method: data.pay_method, is_mgmt_fee: parseInt(data.is_mgmt_fee) || 0,
          })
        });
        if (!resp?.ok) {
          const d = await resp?.json().catch(() => ({}));
          throw new Error(d?.detail || '저장 실패');
        }
        showToast('✅ 결제가 등록되었습니다');
        renderClasses(document.getElementById('page-content'));
      }
    });

    // 상품 선택 시 금액 자동 입력
    setTimeout(() => {
      const sel = document.getElementById('modal-product');
      if (sel && sel.tagName === 'SELECT') {
        sel.addEventListener('change', () => {
          const idx = prodOpts.indexOf(sel.value);
          const amtEl = document.getElementById('modal-amount');
          if (idx >= 0 && amtEl) amtEl.value = products[idx].price || 0;
        });
      }
    }, 200);
  };

  // ── Instructors ───────────────────────────────────────────────
  async function renderInstructors(container) {
    container.innerHTML = '<div class="page"><div class="empty">강사 로딩 중…</div></div>';
    try {
      const branch     = user.branch || '';
      const resp       = await api(`/api/operations/instructors?branch=${encodeURIComponent(branch)}`);
      if (!resp) return;
      const instructors = await resp.json();
      const addBtn = user.role === 'staff'
        ? `<button class="btn primary sm" onclick="modalNewInstructor()"><i data-lucide="plus"></i> 강사 추가</button>` : '';
      container.innerHTML = `
        <div class="page">
          <div class="card-head">
            <div><div class="section-title">강사 소개</div><div class="section-sub">라온스포츠 전문 트레이너</div></div>
            ${addBtn}
          </div>
          <div class="grid-3">
            ${instructors.map(i => `
              <div class="instructor-card">
                <div class="photo" style="${i.photo_path ? 'background-image:url('+i.photo_path+')' : 'background:var(--surface-2)'}">
                  ${!i.photo_path ? `<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:48px;color:var(--muted)">${i.name.charAt(0)}</div>` : ''}
                  <div class="name-overlay">
                    <div class="name">${i.name}</div>
                    <div style="font-size:12px;opacity:.8">${i.english || ''}</div>
                  </div>
                </div>
                <div class="body">
                  <span class="badge outline">${i.role || '강사'}</span>
                  <p style="margin:8px 0 4px;font-size:13px;color:var(--muted-2)">${(i.bio || '').slice(0, 100)}</p>
                </div>
              </div>`).join('') || '<div class="empty" style="grid-column:1/-1">등록된 강사가 없습니다</div>'}
          </div>
        </div>`;
      if (window.lucide) lucide.createIcons();
    } catch (err) {
      container.innerHTML = `<div class="page"><div class="empty">오류: ${err.message}</div></div>`;
    }
  }

  // ── Navigation ────────────────────────────────────────────────
  window.navigateTo = function (page) {
    const cfg = PAGES[page];
    if (!cfg) return;
    if (!canAccessPage(cfg, user)) { showToast('접근 권한이 없는 메뉴입니다', 'err'); return; }
    currentPage = page;
    history.pushState({ page }, '', '/' + page);
    renderShell();
  };
  window.addEventListener('popstate', e => {
    if (e.state && e.state.page) { currentPage = e.state.page; renderShell(); }
  });

  // ── Toast ─────────────────────────────────────────────────────
  function showToast(msg, type = 'ok') {
    let stack = document.querySelector('.toast-stack');
    if (!stack) { stack = document.createElement('div'); stack.className = 'toast-stack'; document.body.appendChild(stack); }
    const t = document.createElement('div');
    t.className = 'toast';
    t.innerHTML = `<i data-lucide="${type === 'err' ? 'alert-circle' : 'check-circle'}" class="ic"></i> ${msg}`;
    stack.appendChild(t);
    if (window.lucide) lucide.createIcons();
    setTimeout(() => t.remove(), 3500);
  }

  // ── Theme ─────────────────────────────────────────────────────
  window.toggleTheme = function () {
    const html  = document.documentElement;
    const isDark = html.getAttribute('data-theme') === 'dark';
    html.setAttribute('data-theme', isDark ? 'light' : 'dark');
    localStorage.setItem('raon_theme', isDark ? 'light' : 'dark');
  };

  // Apply saved theme
  const savedTheme = localStorage.getItem('raon_theme');
  if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme);

  window.logout = logout;

  // ── Boot ──────────────────────────────────────────────────────
  renderShell();
})();
