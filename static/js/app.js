/**
 * ═══════════════════════════════════════════════
 * NARA Analyzer — SPA Application Logic
 * ═══════════════════════════════════════════════
 */

// 크롬 확장 프로그램 에러 억제 (앱과 무관한 에러)
window.addEventListener('unhandledrejection', e => {
    if (e.reason?.message?.includes('message channel closed')) {
        e.preventDefault();
    }
});

// ===== 상수 정의 =====
const API_TIMEOUT_DEFAULT = 120000;
const API_TIMEOUT_ANALYSIS = 180000;
const PAGE_SIZE_DEFAULT = 50;
const CHART_DAYS_DEFAULT = 30;

// ──────────────────────────────────────────────
// 0. 빈값 표시 유틸리티
// ──────────────────────────────────────────────
function displayBudget(amount) {
    if (!amount || amount <= 0) return '예산 미공개';
    return formatBudget(amount);
}

function getDaysLeft(dateStr) {
    if (!dateStr) return null;
    const close = new Date(dateStr);
    const now = new Date();
    return Math.ceil((close - now) / 86400000);
}

function formatDaysLeft(dateStr) {
    const days = getDaysLeft(dateStr);
    if (days === null) return '마감일 미정';
    if (days < 0) return '마감';
    if (days === 0) return '오늘 마감';
    if (days <= 3) return `D-${days} ⏰`;
    return `D-${days}`;
}

// ──────────────────────────────────────────────
// 0-b. 테마 전환
// ──────────────────────────────────────────────
function getPreferredTheme() {
    const stored = localStorage.getItem('nara_theme');
    if (stored) return stored;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) {
        btn.textContent = theme === 'light' ? '🌙 다크 모드' : '☀️ 라이트 모드';
    }
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem('nara_theme', next);
    applyTheme(next);
}

// 초기 테마 적용
applyTheme(getPreferredTheme());

// 시스템 테마 변경 감지
window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
    if (!localStorage.getItem('nara_theme')) {
        applyTheme(e.matches ? 'light' : 'dark');
    }
});

// ──────────────────────────────────────────────
// 0-c. 빈 상태 공통 렌더러
// ──────────────────────────────────────────────
function renderEmptyState(icon, title, message, actionHtml = '') {
    return `<div class="empty-state-unified">
        <div class="empty-icon">${icon}</div>
        <h3>${title}</h3>
        <p>${message}</p>
        ${actionHtml}
    </div>`;
}

// ──────────────────────────────────────────────
// 1. 앱 상태 관리
// ──────────────────────────────────────────────
const state = {
    currentView: 'dashboard',
    businesses: [],
    bids: [],
    analyses: [],
    stats: {},
    isLoading: false,
    confirmCallback: null,
    bidPage: 1,
    bidsPerPage: 50,
    tagData: {
        'biz-types': [],
        'licenses': [],
        'regions': [],
        'keywords': [],
    },
};

// ── 관심공고 관리 (localStorage) ──
const FAV_STATUSES = {
    reviewing: { label: '⭐ 검토중', color: '#f59e0b' },
    proceeding: { label: '🚀 사업진행', color: '#3b82f6' },
    partnered: { label: '🤝 협업진행', color: '#8b5cf6' },
    completed: { label: '✅ 완료', color: '#10b981' },
    abandoned: { label: '❌ 포기', color: '#ef4444' },
};

let _favFilterStatus = 'all';
let _favDetailBidNo = null; // 현재 상세 모달에 열린 공고번호

function getFavorites() {
    try {
        const raw = JSON.parse(localStorage.getItem('nara_favorites') || '[]');
        // 기존 데이터 호환: 새 필드 없으면 기본값 보충
        return raw.map(f => ({
            status: 'reviewing',
            memo: '',
            partners: [],
            analysis_done: false,
            analysis_summary: '',
            org_name: '',
            budget: '',
            bid_close_dt: '',
            checklist: [
                { id: 'rfp', label: 'RFP/공고문 확인', hint: '나라장터에서 공고문/RFP를 다운로드하고 핵심 요구사항을 파악하세요', done: false },
                { id: 'qualify', label: '참가자격 요건 확인', hint: '면허, 실적, 재무상태 등 참가자격 충족 여부를 확인하세요', done: false },
                { id: 'docs', label: '제출서류 준비', hint: '사업자등록증, 인감증명서, 실적증명서 등 필수 서류를 준비하세요', done: false },
                { id: 'pricing', label: '가격 산정/견적', hint: '원가 계산, 이윤율 검토, 투찰가격을 산정하세요', done: false },
                { id: 'proposal', label: '제안서 작성', hint: '기술제안서, 사업수행계획서를 작성하세요', done: false },
                { id: 'submit', label: '입찰서 제출', hint: '나라장터에 입찰서를 전자 제출하세요 (마감시간 확인!)', done: false },
            ],
            result: null,
            ...f,
        }));
    } catch (e) { console.warn('관심공고 로컬 데이터 파싱 실패', e); return []; }
}

function saveFavorites(favs) {
    localStorage.setItem('nara_favorites', JSON.stringify(favs));
}

function isFavorite(bidNo) {
    return getFavorites().some(f => f.bid_ntce_no === bidNo);
}

function getFavByBidNo(bidNo) {
    return getFavorites().find(f => f.bid_ntce_no === bidNo) || null;
}

function updateFav(bidNo, updates) {
    let favs = getFavorites();
    const idx = favs.findIndex(f => f.bid_ntce_no === bidNo);
    if (idx >= 0) {
        favs[idx] = { ...favs[idx], ...updates };
        saveFavorites(favs);
    }
}

function toggleFavorite(bidNo, btnEl) {
    let favs = getFavorites();
    const idx = favs.findIndex(f => f.bid_ntce_no === bidNo);

    if (idx >= 0) {
        favs.splice(idx, 1);
        if (btnEl) {
            btnEl.classList.remove('active');
            btnEl.innerHTML = '☆ 관심공고 추가';
        }
        showToast('관심공고에서 해제되었습니다.', 'info');
    } else {
        const titleEl = document.getElementById('bqv-title');
        const overlay = document.getElementById('bid-quick-view');
        // 원본 데이터를 dataset에서 가져오기 (포맷된 텍스트가 아닌 원본값)
        favs.push({
            bid_ntce_no: bidNo,
            title: titleEl?.textContent || bidNo,
            org_name: overlay?.dataset?.orgName || '',
            budget: overlay?.dataset?.budget || '',
            bid_close_dt: overlay?.dataset?.closeDt || '',
            added_at: new Date().toISOString(),
            status: 'reviewing',
            memo: '',
            partners: [],
            analysis_done: false,
            analysis_summary: '',
        });
        if (btnEl) {
            btnEl.classList.add('active');
            btnEl.innerHTML = '⭐ 관심공고 해제';
        }
        showToast('관심공고에 추가되었습니다!', 'success');
    }

    saveFavorites(favs);
    if (state.currentView === 'favorites') loadFavorites();
    updateFavBadge();
}

function updateFavBadge() {
    const badge = document.getElementById('fav-menu-badge');
    if (badge) {
        const count = getFavorites().length;
        badge.textContent = count > 0 ? count : '';
        badge.style.display = count > 0 ? 'inline-flex' : 'none';
    }
    // 공고 수 뱃지
    const bidBadge = document.getElementById('bid-menu-badge');
    if (bidBadge && state.bids) {
        const activeBids = state.bids.filter(b => {
            const d = getDaysLeft(b.bid_close_dt);
            return d === null || d >= 0;
        }).length;
        bidBadge.textContent = activeBids > 0 ? activeBids : '';
        bidBadge.style.display = activeBids > 0 ? 'inline-flex' : 'none';
    }
}

function filterFavByStatus(status) {
    _favFilterStatus = status;
    // 상태 카드 활성화
    document.querySelectorAll('.fav-stat-card').forEach((card, i) => {
        const statuses = ['all', 'reviewing', 'proceeding', 'partnered', 'completed', 'abandoned'];
        card.classList.toggle('active', statuses[i] === status);
    });
    loadFavorites();
}

function loadFavorites() {
    const container = document.getElementById('favorites-body');
    if (!container) return;

    const allFavs = getFavorites();
    
    // 통계 업데이트
    const stats = { all: allFavs.length, reviewing: 0, proceeding: 0, partnered: 0, completed: 0, abandoned: 0 };
    allFavs.forEach(f => { if (stats[f.status] !== undefined) stats[f.status]++; });
    Object.keys(stats).forEach(k => {
        const el = document.getElementById(`fav-stat-${k}`);
        if (el) el.textContent = stats[k];
    });

    // 필터링
    let favs = _favFilterStatus === 'all' ? [...allFavs] : allFavs.filter(f => f.status === _favFilterStatus);

    // 검색 필터
    const searchInput = document.getElementById('fav-search-input');
    const searchQuery = searchInput?.value?.trim().toLowerCase() || '';
    if (searchQuery) {
        favs = favs.filter(f =>
            (f.title || '').toLowerCase().includes(searchQuery) ||
            (f.org_name || '').toLowerCase().includes(searchQuery) ||
            (f.bid_ntce_no || '').toLowerCase().includes(searchQuery) ||
            (f.memo || '').toLowerCase().includes(searchQuery)
        );
    }

    // 마감일 기준 정렬 (가까운 순)
    favs.sort((a, b) => {
        const da = getDaysLeft(a.bid_close_dt);
        const db = getDaysLeft(b.bid_close_dt);
        if (da === null && db === null) return 0;
        if (da === null) return 1;
        if (db === null) return -1;
        return da - db;
    });

    // 마감 임박 공고 알림 (3일 이내)
    const urgentFavs = allFavs.filter(f => {
        if (f.status === 'abandoned' || f.status === 'completed') return false;
        const days = getDaysLeft(f.bid_close_dt);
        return days !== null && days >= 0 && days <= 3;
    });

    if (allFavs.length === 0) {
        container.innerHTML = renderEmptyState('⭐', '관심공고가 없습니다', '공고 목록에서 ⭐ 버튼을 눌러 관심공고를 추가해보세요.', '<div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;justify-content:center"><button class="btn btn-primary" onclick="navigate(\'bids\')">📝 공고 목록 보기</button><button class="btn btn-outline" onclick="navigate(\'dashboard\')">🔍 키워드 검색하기</button></div>');
        return;
    }

    if (favs.length === 0) {
        container.innerHTML = renderEmptyState('💭', searchQuery ? '검색 결과 없음' : '해당 상태 없음', searchQuery ? `'${escapeHTML(searchQuery)}' 검색 결과가 없습니다.` : `'${FAV_STATUSES[_favFilterStatus]?.label || _favFilterStatus}' 상태의 공고가 없습니다.`);
        return;
    }

    const urgentBanner = urgentFavs.length > 0 ? `
        <div class="fav-urgent-banner">
            ⏰ <strong>마감 임박!</strong> 3일 이내 마감됩니다.
            ${urgentFavs.slice(0, 3).map(f => `<span class="fav-urgent-item" onclick="openFavDetail('${escapeHTML(f.bid_ntce_no)}')">${escapeHTML((f.title || f.bid_ntce_no).substring(0, 20))}...</span>`).join('')}
        </div>` : '';

    // 통계 계산
    let totalBudget = 0;
    const partnerSet = new Set();
    let analyzedCount = 0;
    allFavs.forEach(f => {
        const budgetNum = parseInt(String(f.budget).replace(/[^0-9]/g, '')) || 0;
        totalBudget += budgetNum;
        (f.partners || []).forEach(p => {
            const name = typeof p === 'string' ? p : p.name || '';
            if (name) partnerSet.add(name);
        });
        if (f.analysis_done) analyzedCount++;
    });
    const budgetDisplay = totalBudget >= 100000000 ? `${(totalBudget / 100000000).toFixed(1)}억원` : totalBudget >= 10000 ? `${(totalBudget / 10000).toFixed(0)}만원` : `${totalBudget}원`;

    container.innerHTML = `
        ${urgentBanner}
        <div class="fav-stats-bar">
            <div class="fav-stat-item"><span class="fav-stat-icon">📊</span><span class="fav-stat-value">${allFavs.length}</span><span class="fav-stat-label">전체</span></div>
            <div class="fav-stat-item"><span class="fav-stat-icon">💰</span><span class="fav-stat-value">${budgetDisplay}</span><span class="fav-stat-label">총 예산</span></div>
            <div class="fav-stat-item"><span class="fav-stat-icon">🤝</span><span class="fav-stat-value">${partnerSet.size}</span><span class="fav-stat-label">협업사</span></div>
            <div class="fav-stat-item"><span class="fav-stat-icon">🔬</span><span class="fav-stat-value">${analyzedCount}/${allFavs.length}</span><span class="fav-stat-label">분석완료</span></div>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;gap:8px;flex-wrap:wrap">
            <span style="color:var(--text-muted);font-size:0.85rem">${favs.length}건 표시 중</span>
            <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                <input type="text" id="fav-search-input" class="fav-detail-input" placeholder="🔍 검색..." value="${escapeHTML(searchQuery)}" oninput="loadFavorites()" style="width:140px;padding:6px 10px;font-size:0.82rem">
                <button class="btn btn-ghost btn-sm" onclick="shareFavSummary()" title="요약을 클립보드에 복사">📋 공유</button>
                <button class="btn btn-ghost btn-sm" onclick="exportFavoritesJSON()" title="JSON 내보내기">💾 내보내기</button>
                <button class="btn btn-ghost btn-sm" onclick="deleteFavsByStatus('${_favFilterStatus}')">🗑️ 삭제</button>
            </div>
        </div>
        ${favs.map(f => {
            const st = FAV_STATUSES[f.status] || FAV_STATUSES.reviewing;
            const partnerChips = (f.partners || []).map(p => `<span class="fav-partner-chip">🤝 ${escapeHTML(typeof p === 'string' ? p : p.name || '')}</span>`).join('');
            const analysisBadge = f.analysis_done ? '<span class="fav-analysis-badge">📊 분석완료</span>' : '';
            const memoSnippet = f.memo ? `<div class="fav-card-memo">📝 ${escapeHTML(f.memo.substring(0, 50))}${f.memo.length > 50 ? '...' : ''}</div>` : '';
            const naraUrl = getNaraDetailUrl(f.bid_ntce_no);
            const daysLeft = getDaysLeft(f.bid_close_dt);
            let deadlineClass = 'safe';
            const isExpired = daysLeft !== null && daysLeft < 0;
            if (isExpired) deadlineClass = 'expired';
            else if (daysLeft !== null && daysLeft <= 3) deadlineClass = 'urgent';
            else if (daysLeft !== null && daysLeft <= 7) deadlineClass = 'soon';
            const deadlineBadge = daysLeft !== null ? `<span class="fav-card-deadline ${deadlineClass}">${formatDaysLeft(f.bid_close_dt)}</span>` : '';

            return `
                <div class="fav-pipeline-card ${isExpired ? 'expired' : ''}" onclick="openFavDetail('${escapeHTML(f.bid_ntce_no)}')">
                    <div class="fav-pipeline-left">
                        <div class="fav-meta-row">
                            <span class="fav-status-badge" style="--status-color:${st.color}">${st.label}</span>
                            ${deadlineBadge}
                        </div>
                        <div class="fav-card-title">${escapeHTML(f.title || f.bid_ntce_no)}</div>
                        <div class="fav-card-meta">🏢 ${escapeHTML(f.org_name || '-')} · 💰 ${displayBudget(f.budget)}</div>
                        ${memoSnippet}
                        <div class="fav-card-chips">
                            ${partnerChips}
                            ${analysisBadge}
                        </div>
                        ${(() => {
                            if (isExpired) return '<div class="fav-card-next-task" style="color:var(--danger)">⏰ 마감된 공고입니다</div>';
                            const cl = f.checklist || [];
                            if (cl.length === 0) return '';
                            const done = cl.filter(c => c.done).length;
                            const pct = Math.round((done / cl.length) * 100);
                            const nextItem = cl.find(c => !c.done);
                            const nextTaskHtml = nextItem
                                ? `<div class="fav-card-next-task">➡️ 다음: ${escapeHTML(nextItem.label)}</div>`
                                : `<div class="fav-card-next-task all-done">✅ 입찰 준비 완료!</div>`;
                            return `<div class="fav-progress-bar">
                                <div class="fav-progress-track">
                                    <div class="fav-progress-fill" style="width:${pct}%;background:${pct===100?'var(--success)':'var(--accent-indigo, #6366f1)'}"></div>
                                </div>
                                <span class="fav-progress-text">${done}/${cl.length}</span>
                            </div>
                            ${nextTaskHtml}`;
                        })()}
                    </div>
                    <div class="fav-pipeline-right">
                        <button class="btn btn-sm btn-prepare" onclick="event.stopPropagation(); openFavDetail('${escapeHTML(f.bid_ntce_no)}')">📋 관리</button>
                        <button class="btn btn-accent btn-sm" onclick="event.stopPropagation(); openStrategyModal('${escapeHTML(f.bid_ntce_no)}')">🎯 분석</button>
                        <a href="${escapeHTML(naraUrl)}" target="_blank" rel="noopener" class="btn btn-outline btn-sm" onclick="event.stopPropagation()">🔗 나라장터</a>
                    </div>
                </div>`;
        }).join('')}
    `;
}


// ──────────────────────────────────────────────
// 2. API 유틸리티
// ──────────────────────────────────────────────
// 엔드포인트별 타임아웃 설정 (밀리초)
const API_TIMEOUTS = {
    default: 30000,       // 기본: 30초
    analysis: 180000,     // 분석 엔드포인트: 180초 (/api/analyze, /api/strategy)
    collection: 120000,   // 수집 엔드포인트: 120초 (/api/collect)
};

function getTimeoutForPath(path) {
    if (/\/(analyze|strategy)/.test(path)) return API_TIMEOUTS.analysis;
    if (/\/collect/.test(path)) return API_TIMEOUTS.collection;
    return API_TIMEOUTS.default;
}

async function api(method, path, body = null, { timeout } = {}) {
    const controller = new AbortController();
    const effectiveTimeout = timeout || getTimeoutForPath(path);
    const timeoutId = setTimeout(() => controller.abort(), effectiveTimeout);

    const opts = {
        method,
        signal: controller.signal,
    };
    if (body) {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = JSON.stringify(body);
    }

    try {
        const res = await fetch(`/api${path}`, opts);
        clearTimeout(timeoutId);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        // 204 No Content
        if (res.status === 204) return null;
        return await res.json();
    } catch (err) {
        clearTimeout(timeoutId);
        if (err.name === 'AbortError') {
            const sec = Math.round(effectiveTimeout / 1000);
            throw new Error(`요청 시간이 초과되었습니다. (${sec}초) 다시 시도해주세요.`);
        }
        if (err.message === 'Failed to fetch') {
            throw new Error('서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요.');
        }
        throw err;
    }
}


// ── 공고 간단 정보 팝업 ──
function openBidQuickView(bidData) {
    const overlay = document.getElementById('bid-quick-view');
    const titleEl = document.getElementById('bqv-title');
    const infoEl = document.getElementById('bqv-info');
    const actionsEl = document.getElementById('bqv-actions');

    const bidNo = bidData.bid_ntce_no || '';
    const title = bidData.title || bidData.bid_ntce_no || '제목 없음';
    const org = bidData.org_name || '-';
    const budget = displayBudget(bidData.budget);
    const daysLeftText = formatDaysLeft(bidData.bid_close_dt);
    const naraUrl = getNaraDetailUrl(bidNo);
    const isFav = isFavorite(bidNo);

    titleEl.textContent = title;

    const closeDateRaw = bidData.bid_close_dt ? formatDate(bidData.bid_close_dt) : '';

    infoEl.innerHTML = `
        <div class="bqv-row"><span class="bqv-label">🏢 발주기관</span><span class="bqv-value">${escapeHTML(org)}</span></div>
        ${bidData.dminstt_nm && bidData.dminstt_nm !== org ? `<div class="bqv-row"><span class="bqv-label">🏛️ 수요기관</span><span class="bqv-value">${escapeHTML(bidData.dminstt_nm)}</span></div>` : ''}
        <div class="bqv-row"><span class="bqv-label">💰 추정가격</span><span class="bqv-value">${budget}</span></div>
        <div class="bqv-row"><span class="bqv-label">📅 마감일</span><span class="bqv-value">${daysLeftText}${closeDateRaw ? ' <small style="color:var(--text-muted)">(' + escapeHTML(closeDateRaw) + ')</small>' : ''}</span></div>
        <div class="bqv-row"><span class="bqv-label">📋 공고번호</span><span class="bqv-value" style="font-size:0.8rem">${escapeHTML(bidNo)}</span></div>
        ${bidData.region ? `<div class="bqv-row"><span class="bqv-label">📍 지역</span><span class="bqv-value">${escapeHTML(bidData.region)}</span></div>` : ''}
        ${bidData.license_limit ? `<div class="bqv-row"><span class="bqv-label">⚠️ 참가자격</span><span class="bqv-value" style="color:var(--danger);font-weight:500">${escapeHTML(bidData.license_limit)}</span></div>` : ''}
        ${bidData.bid_type ? `<div class="bqv-row"><span class="bqv-label">📑 입찰방식</span><span class="bqv-value">${escapeHTML(bidData.bid_type)}</span></div>` : ''}
        ${bidData.matched_keywords?.length ? `<div class="bqv-row"><span class="bqv-label">🏷️ 매칭키워드</span><span class="bqv-value">${bidData.matched_keywords.map(k => '<span class="kw-chip">' + escapeHTML(k) + '</span>').join(' ')}</span></div>` : ''}
        ${bidData.requirements?.length ? `<div class="bqv-row" style="flex-direction:column;align-items:flex-start;gap:4px"><span class="bqv-label">📜 참가요건</span><div style="font-size:0.82rem;color:var(--text-secondary)">${bidData.requirements.map(r => escapeHTML(r)).join(' · ')}</div></div>` : ''}
    `;

    actionsEl.innerHTML = `
        <button class="btn btn-fav ${isFav ? 'active' : ''}" onclick="toggleFavorite('${escapeHTML(bidNo)}', this); event.stopPropagation()">
            ${isFav ? '⭐ 관심공고 해제' : '☆ 관심공고 추가'}
        </button>
        <button class="btn btn-prepare" onclick="document.getElementById('bid-quick-view').classList.remove('active'); prepareBid('${escapeHTML(bidNo)}', '${escapeHTML((bidData.title||'').replace(/'/g, ''))}', '${escapeHTML((org||'').replace(/'/g, ''))}', '${bidData.budget||''}', '${escapeHTML(bidData.bid_close_dt||'')}')">
            📋 입찰 준비하기
        </button>
        <button class="btn btn-outline" onclick="document.getElementById('bid-quick-view').classList.remove('active'); openStrategyModal('${escapeHTML(bidNo)}')">
            🔍 AI 분석하기
        </button>
        <button class="btn btn-outline" onclick="window.open('${escapeHTML(naraUrl)}', '_blank')">
            🔗 나라장터 바로가기
        </button>
    `;

    // 원본 데이터를 data-* 속성에 저장 (toggleFavorite에서 사용)
    overlay.dataset.orgName = org || '';
    overlay.dataset.budget = bidData.budget || '';
    overlay.dataset.closeDt = bidData.bid_close_dt || '';
    overlay.classList.add('active');
}

function closeBidQuickView(e) {
    if (e.target.id === 'bid-quick-view') {
        document.getElementById('bid-quick-view').classList.remove('active');
    }
}

// ── 관심공고 상세 모달 ──
function openFavDetail(bidNo) {
    const fav = getFavByBidNo(bidNo);
    if (!fav) { showToast('관심공고 데이터를 찾을 수 없습니다.', 'error'); return; }
    _favDetailBidNo = bidNo;

    document.getElementById('fav-detail-title').textContent = fav.title || bidNo;

    // 입찰 진행 단계 프로그래스 바
    const cl = fav.checklist || [];
    const clDone = cl.filter(c => c.done).length;
    const clPct = cl.length > 0 ? Math.round((clDone / cl.length) * 100) : 0;
    const st = FAV_STATUSES[fav.status] || FAV_STATUSES.reviewing;
    const naraUrl = getNaraDetailUrl(bidNo);

    // 공고 정보 + 진행 상태 바
    document.getElementById('fav-detail-info').innerHTML = `
        <div class="fav-progress-overview">
            <div class="fav-progress-header">
                <span class="fav-status-badge" style="--status-color:${st.color}">${st.label}</span>
                <span style="font-size:0.78rem;color:var(--text-muted)">준비 ${clPct}%</span>
            </div>
            <div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden;margin:6px 0 12px">
                <div style="width:${clPct}%;height:100%;background:${clPct===100?'var(--success)':'var(--accent-indigo, #6366f1)'};border-radius:3px;transition:width 0.3s"></div>
            </div>
        </div>
        <div class="bqv-row"><span class="bqv-label">🏢 발주기관</span><span class="bqv-value">${escapeHTML(fav.org_name || '-')}</span></div>
        <div class="bqv-row"><span class="bqv-label">💰 예산</span><span class="bqv-value">${displayBudget(fav.budget)}</span></div>
        <div class="bqv-row"><span class="bqv-label">📅 마감</span><span class="bqv-value">${formatDaysLeft(fav.bid_close_dt)}${fav.bid_close_dt ? ' <small style="color:var(--text-muted)">(' + escapeHTML(fav.bid_close_dt.substring(0,10)) + ')</small>' : ''}</span></div>
        <div class="bqv-row"><span class="bqv-label">📋 공고번호</span><span class="bqv-value" style="font-size:0.78rem">${escapeHTML(bidNo)}</span></div>
        <div class="bqv-row"><span class="bqv-label">📅 추가일</span><span class="bqv-value">${fav.added_at ? new Date(fav.added_at).toLocaleDateString('ko-KR') : '-'}</span></div>
        <div style="margin-top:8px"><a href="${escapeHTML(naraUrl)}" target="_blank" rel="noopener" class="btn btn-outline btn-sm" style="width:100%;text-align:center">🔗 나라장터에서 공고 상세 확인 →</a></div>
    `;

    // 상태 선택
    const statusEl = document.getElementById('fav-detail-status');
    statusEl.innerHTML = Object.entries(FAV_STATUSES).map(([key, val]) => `
        <button class="fav-status-btn ${fav.status === key ? 'active' : ''}" data-status="${key}" style="--status-color:${val.color}"
            onclick="document.querySelectorAll('.fav-status-btn').forEach(b=>b.classList.remove('active')); this.classList.add('active'); updateFav(_favDetailBidNo, {status: this.dataset.status}); showToast('상태가 변경되었습니다', 'success'); const rs=document.getElementById('fav-detail-result-section'); if(rs) rs.style.display=(this.dataset.status==='completed'||this.dataset.status==='abandoned')?'block':'none'">
            ${val.label}
        </button>
    `).join('');

    // 메모
    document.getElementById('fav-detail-memo').value = fav.memo || '';

    // 협업사
    renderFavPartners(fav.partners || []);

    // 과거 협업사 추천
    const suggestions = suggestPartners(bidNo);
    const suggestEl = document.getElementById('fav-partner-suggest');
    if (suggestEl && suggestions.length > 0) {
        suggestEl.innerHTML = `
            <div style="margin-top:8px;padding:8px 10px;background:rgba(99,102,241,0.05);border-radius:8px;border:1px dashed rgba(99,102,241,0.3)">
                <div style="font-size:0.75rem;color:var(--accent-indigo, #6366f1);font-weight:600;margin-bottom:4px">💡 이전 협업사 추천</div>
                <div style="display:flex;gap:6px;flex-wrap:wrap">${suggestions.map(s => `
                    <button class="btn btn-sm btn-ghost" style="font-size:0.75rem;padding:2px 8px" onclick="addSuggestedPartner('${escapeHTML(s.name.replace(/'/g,''))}', '${escapeHTML(s.role.replace(/'/g,''))}', '${escapeHTML(s.contact.replace(/'/g,''))}')">
                        + ${escapeHTML(s.name)} (${s.count}회)
                    </button>
                `).join('')}</div>
            </div>`;
    } else if (suggestEl) {
        suggestEl.innerHTML = '';
    }

    // 분석 결과
    const analysisEl = document.getElementById('fav-detail-analysis');
    if (fav.analysis_done && fav.analysis_summary) {
        analysisEl.innerHTML = `<div class="fav-analysis-result">${escapeHTML(fav.analysis_summary)}</div>`;
    } else {
        analysisEl.innerHTML = `<div style="color:var(--text-muted);font-size:0.85rem">💭 아직 AI 분석이 수행되지 않았습니다.<br><button class="btn btn-prepare btn-sm" style="margin-top:8px" onclick="document.getElementById('fav-detail-overlay').classList.remove('active'); openStrategyModal('${escapeHTML(bidNo)}')">🔍 AI 분석 실행하기</button></div>`;
    }

    // 체크리스트
    const checklistEl = document.getElementById('fav-detail-checklist');
    if (checklistEl) {
        const checklist = fav.checklist || [];
        const doneCount = checklist.filter(c => c.done).length;
        const progress = checklist.length > 0 ? Math.round((doneCount / checklist.length) * 100) : 0;
        checklistEl.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
                <div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden">
                    <div style="width:${progress}%;height:100%;background:${progress===100?'var(--success)':'var(--accent-indigo, #6366f1)'};border-radius:3px;transition:width 0.3s"></div>
                </div>
                <span style="font-size:0.78rem;color:var(--text-muted);white-space:nowrap">${doneCount}/${checklist.length} (${progress}%)</span>
            </div>
            ${checklist.map((c, i) => {
                const isCurrentStep = !c.done && (i === 0 || checklist[i-1].done);
                return `
                <label class="fav-checklist-item ${isCurrentStep ? 'current-step' : ''}" title="${escapeHTML(c.hint || '')}">
                    <input type="checkbox" ${c.done ? 'checked' : ''}
                        onchange="toggleChecklistItem('${escapeHTML(bidNo)}', ${i}, this.checked)">
                    <div style="flex:1">
                        <span class="${c.done ? 'done' : ''}" style="${isCurrentStep ? 'font-weight:600;color:var(--text-primary)' : ''}">
                            <span class="checklist-num">${i+1}</span>${escapeHTML(c.label)}
                        </span>
                        ${c.hint && !c.done ? `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px;padding-left:22px">${escapeHTML(c.hint)}</div>` : ''}
                    </div>
                </label>`;
            }).join('')}
        `;
    }

    // 입찰 결과 (완료/포기 상태일 때)
    const resultSection = document.getElementById('fav-detail-result-section');
    if (resultSection) {
        const showResult = fav.status === 'completed' || fav.status === 'abandoned';
        resultSection.style.display = showResult ? 'block' : 'none';
        // 항상 초기화
        ['fav-result-type','fav-result-amount','fav-result-competitors','fav-result-note'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        if (showResult && fav.result) {
            const r = fav.result;
            document.getElementById('fav-result-type').value = r.type || '';
            document.getElementById('fav-result-amount').value = r.amount || '';
            document.getElementById('fav-result-competitors').value = r.competitors || '';
            document.getElementById('fav-result-note').value = r.note || '';
        }
    }

    // 버튼 설정 (naraUrl은 위에서 이미 정의됨)
    document.getElementById('fav-detail-nara-btn').onclick = () => window.open(naraUrl, '_blank');
    document.getElementById('fav-detail-analyze-btn').onclick = () => {
        document.getElementById('fav-detail-overlay').classList.remove('active');
        openStrategyModal(bidNo);
    };

    // 협업 이력 — 같은 협업사가 참여한 다른 공고 표시
    const partnerHistory = getPartnerHistory(bidNo, fav.partners || []);
    const historySection = document.querySelector('.fav-detail-section.partner-history') || (() => {
        const section = document.createElement('div');
        section.className = 'fav-detail-section partner-history';
        section.innerHTML = '<h4>📜 협업 이력</h4><div id="fav-detail-partner-history"></div>';
        document.getElementById('fav-detail-analysis').closest('.fav-detail-section').after(section);
        return section;
    })();
    const historyEl = historySection.querySelector('#fav-detail-partner-history') || historySection.querySelector('div');
    if (partnerHistory.length > 0) {
        historyEl.innerHTML = partnerHistory.map(h => `
            <div class="fav-history-item">
                <span class="fav-history-partner">🤝 ${escapeHTML(h.partnerName)}</span>
                <span class="fav-history-count">다른 공고 ${h.otherBids.length}건 참여</span>
                <div class="fav-history-bids">${h.otherBids.map(b => `<span class="fav-history-bid" onclick="openFavDetail('${escapeHTML(b.bid_ntce_no)}')">${escapeHTML(b.title?.substring(0,25) || b.bid_ntce_no)}...</span>`).join('')}</div>
            </div>
        `).join('');
    } else {
        historyEl.innerHTML = '<span style="color:var(--text-muted);font-size:0.85rem">아직 협업 이력이 없습니다</span>';
    }

    // 스크롤 초기화 + 모달 열기
    const detailBody = document.querySelector('.fav-detail-body');
    if (detailBody) detailBody.scrollTop = 0;
    document.getElementById('fav-detail-overlay').classList.add('active');
}

function closeFavDetail(e) {
    if (e.target.id === 'fav-detail-overlay') {
        document.getElementById('fav-detail-overlay').classList.remove('active');
    }
}

function renderFavPartners(partners) {
    const container = document.getElementById('fav-detail-partners');
    if (!partners || partners.length === 0) {
        container.innerHTML = '<span style="color:var(--text-muted);font-size:0.85rem">등록된 협업사가 없습니다</span>';
        return;
    }
    const totalShare = partners.reduce((sum, p) => sum + (typeof p === 'object' ? (p.share || 0) : 0), 0);
    container.innerHTML = (totalShare > 0 ? `<div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:6px">총 배분: ${totalShare}%</div>` : '') +
    partners.map((p, i) => {
        const name = typeof p === 'string' ? p : p.name || '';
        const role = typeof p === 'object' ? (p.role || '') : '';
        const contact = typeof p === 'object' ? (p.contact || '') : '';
        const share = typeof p === 'object' ? (p.share || 0) : 0;
        return `<div class="fav-partner-tag" style="flex-direction:column;align-items:flex-start;gap:3px;padding:8px 12px">
            <div style="display:flex;align-items:center;gap:6px;width:100%">
                <span style="font-weight:600">🤝 ${escapeHTML(name)}</span>
                ${role ? `<span style="font-size:0.72rem;background:var(--bg-hover);padding:1px 6px;border-radius:4px">${escapeHTML(role)}</span>` : ''}
                ${share ? `<span style="font-size:0.72rem;color:var(--warning);font-weight:600">${share}%</span>` : ''}
                <button class="fav-partner-remove" onclick="removeFavPartner(${i})" style="margin-left:auto">×</button>
            </div>
            ${contact ? `<span style="font-size:0.72rem;color:var(--text-muted)">📞 ${escapeHTML(contact)}</span>` : ''}
        </div>`;
    }).join('');
}

function addFavPartner() {
    const input = document.getElementById('fav-partner-input');
    const roleInput = document.getElementById('fav-partner-role');
    const contactInput = document.getElementById('fav-partner-contact');
    const shareInput = document.getElementById('fav-partner-share');
    const name = input.value.trim();
    const role = roleInput ? roleInput.value.trim() : '';
    const contact = contactInput ? contactInput.value.trim() : '';
    const share = shareInput ? parseInt(shareInput.value) || 0 : 0;
    if (!name) return;

    const fav = getFavByBidNo(_favDetailBidNo);
    if (!fav) return;

    const partners = fav.partners || [];
    partners.push({ name, role, contact, share });
    updateFav(_favDetailBidNo, { partners });
    renderFavPartners(partners);
    input.value = '';
    if (roleInput) roleInput.value = '';
    if (contactInput) contactInput.value = '';
    if (shareInput) shareInput.value = '';
    showToast(`'${name}' 협업사가 추가되었습니다.`, 'success');
}

function addSuggestedPartner(name, role, contact) {
    const fav = getFavByBidNo(_favDetailBidNo);
    if (!fav) return;
    const partners = fav.partners || [];
    if (partners.some(p => (typeof p === 'string' ? p : p.name) === name)) {
        showToast(`'${name}'은(는) 이미 추가된 협업사입니다.`, 'info');
        return;
    }
    partners.push({ name, role, contact, share: 0 });
    updateFav(_favDetailBidNo, { partners });
    renderFavPartners(partners);
    showToast(`'${name}' 협업사가 추가되었습니다!`, 'success');
}

function removeFavPartner(index) {
    const fav = getFavByBidNo(_favDetailBidNo);
    if (!fav) return;
    const partners = fav.partners || [];
    partners.splice(index, 1);
    updateFav(_favDetailBidNo, { partners });
    renderFavPartners(partners);
}

function saveFavDetail() {
    if (!_favDetailBidNo) return;

    const activeStatusBtn = document.querySelector('.fav-status-btn.active');
    const status = activeStatusBtn?.dataset?.status || 'reviewing';
    const memo = document.getElementById('fav-detail-memo').value.trim();

    const updates = { status, memo };

    // 입찰 결과 저장 (완료/포기 상태일 때)
    if (status === 'completed' || status === 'abandoned') {
        const resultType = document.getElementById('fav-result-type');
        const resultAmount = document.getElementById('fav-result-amount');
        const resultCompetitors = document.getElementById('fav-result-competitors');
        const resultNote = document.getElementById('fav-result-note');
        if (resultType) {
            updates.result = {
                type: resultType.value || '',
                amount: resultAmount?.value ? parseInt(resultAmount.value) : 0,
                competitors: resultCompetitors?.value ? parseInt(resultCompetitors.value) : 0,
                note: resultNote?.value?.trim() || '',
            };
        }
    }

    updateFav(_favDetailBidNo, updates);
    showToast('관심공고 정보가 저장되었습니다.', 'success');

    document.getElementById('fav-detail-overlay').classList.remove('active');
    if (state.currentView === 'favorites') loadFavorites();
    updateFavBadge();
}

function toggleChecklistItem(bidNo, index, checked) {
    const fav = getFavByBidNo(bidNo);
    if (!fav || !fav.checklist) return;
    fav.checklist[index].done = checked;
    updateFav(bidNo, { checklist: fav.checklist });

    // 진행률 바 즉시 업데이트
    const cl = fav.checklist;
    const doneCount = cl.filter(c => c.done).length;
    const pct = cl.length > 0 ? Math.round((doneCount / cl.length) * 100) : 0;
    const progressBar = document.querySelector('.fav-progress-overview');
    if (progressBar) {
        const fill = progressBar.querySelector('div[style*="width"]');
        if (fill) {
            fill.style.width = pct + '%';
            fill.style.background = pct === 100 ? 'var(--success)' : 'var(--accent-indigo, #6366f1)';
        }
        const pctText = progressBar.querySelector('.fav-progress-header span:last-child');
        if (pctText) pctText.textContent = `준비 ${pct}%`;
    }

    // 체크리스트 영역 진행률 텍스트 업데이트
    const checklistEl = document.getElementById('fav-detail-checklist');
    if (checklistEl) {
        const pctEl = checklistEl.querySelector('span[style*="font-size"]');
        if (pctEl) pctEl.textContent = `${doneCount}/${cl.length} (${pct}%)`;
        const barFill = checklistEl.querySelector('div[style*="width"]');
        if (barFill) {
            barFill.style.width = pct + '%';
            barFill.style.background = pct === 100 ? 'var(--success)' : 'var(--accent-indigo, #6366f1)';
        }
    }
}

function deleteFavsByStatus(status) {
    const label = status === 'all' ? '모든' : (FAV_STATUSES[status]?.label || status);
    showConfirm('관심공고 삭제', `${label} 관심공고를 삭제하시겠습니까?`, () => {
        if (status === 'all') {
            saveFavorites([]);
        } else {
            saveFavorites(getFavorites().filter(f => f.status !== status));
        }
        loadFavorites();
        updateFavBadge();
    });
}

// 관심공고 요약 텍스트를 클립보드에 복사
function shareFavSummary() {
    const favs = getFavorites();
    if (favs.length === 0) { showToast('공유할 관심공고가 없습니다.', 'info'); return; }

    const lines = ['📋 NARA Analyzer 관심공고 요약', `📅 ${new Date().toLocaleDateString('ko-KR')}`, ''];
    favs.forEach((f, i) => {
        const st = FAV_STATUSES[f.status]?.label || f.status;
        const budget = displayBudget(f.budget);
        const partners = (f.partners || []).map(p => typeof p === 'string' ? p : p.name || '').filter(Boolean);
        const cl = f.checklist || [];
        const done = cl.filter(c => c.done).length;
        lines.push(`${i+1}. [${st}] ${f.title || f.bid_ntce_no}`);
        lines.push(`   🏢 ${f.org_name || '-'} | 💰 ${budget} | 📅 ${formatDaysLeft(f.bid_close_dt)}`);
        if (done > 0) lines.push(`   ✅ 체크리스트 ${done}/${cl.length} 완료`);
        if (partners.length > 0) lines.push(`   🤝 협업사: ${partners.join(', ')}`);
        if (f.memo) lines.push(`   📝 ${f.memo.substring(0, 50)}`);
        lines.push('');
    });

    navigator.clipboard.writeText(lines.join('\n')).then(() => {
        showToast('관심공고 요약이 클립보드에 복사되었습니다!', 'success');
    }).catch(() => {
        showToast('클립보드 복사에 실패했습니다. 브라우저 권한을 확인해주세요.', 'error');
    });
}

// 관심공고 JSON 내보내기
function exportFavoritesJSON() {
    const favs = getFavorites();
    if (favs.length === 0) { showToast('내보낼 관심공고가 없습니다.', 'info'); return; }
    const blob = new Blob([JSON.stringify(favs, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nara_favorites_${new Date().toISOString().substring(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('관심공고 데이터가 내보내졌습니다!', 'success');
}

function removeFavFromDetail() {
    if (!_favDetailBidNo) return;
    showConfirm('관심공고 삭제', '이 관심공고를 삭제하시겠습니까?', () => {

        let favs = getFavorites();
        favs = favs.filter(f => f.bid_ntce_no !== _favDetailBidNo);
        saveFavorites(favs);

        document.getElementById('fav-detail-overlay').classList.remove('active');
        if (state.currentView === 'favorites') loadFavorites();
        updateFavBadge();
        showToast('관심공고가 삭제되었습니다.', 'info');
    });
}

// 공고 목록에서 바로 관심공고 토글
function toggleFavFromBid(bidNo, title, orgName, budget, closeDt, btnEl) {
    let favs = getFavorites();
    const idx = favs.findIndex(f => f.bid_ntce_no === bidNo);

    if (idx >= 0) {
        favs.splice(idx, 1);
        if (btnEl) { btnEl.classList.remove('active'); btnEl.innerHTML = '☆ 관심공고'; }
        showToast('관심공고에서 해제되었습니다.', 'info');
    } else {
        favs.push({
            bid_ntce_no: bidNo,
            title: title || bidNo,
            org_name: orgName || '',
            budget: budget || '',
            bid_close_dt: closeDt || '',
            added_at: new Date().toISOString(),
            status: 'reviewing',
            memo: '',
            partners: [],
            analysis_done: false,
            analysis_summary: '',
        });
        if (btnEl) { btnEl.classList.add('active'); btnEl.innerHTML = '⭐ 관심공고'; }
        showToast('관심공고에 추가되었습니다!', 'success');
    }

    saveFavorites(favs);
    updateFavBadge();
}

// 입찰 준비하기 — 관심공고 추가 + 상태 '진행중' + 상세 모달 열기
function prepareBid(bidNo, title, orgName, budget, closeDt) {
    let favs = getFavorites();
    const existing = favs.find(f => f.bid_ntce_no === bidNo);

    if (!existing) {
        favs.push({
            bid_ntce_no: bidNo,
            title: title || bidNo,
            org_name: orgName || '',
            budget: budget || '',
            bid_close_dt: closeDt || '',
            added_at: new Date().toISOString(),
            status: 'proceeding',
            memo: '',
            partners: [],
            analysis_done: false,
            analysis_summary: '',
        });
        saveFavorites(favs);
        showToast('관심공고에 추가하고 입찰 준비를 시작합니다!', 'success');
    } else if (existing.status === 'reviewing') {
        existing.status = 'proceeding';
        saveFavorites(favs);
        showToast('입찰 준비 단계로 전환합니다!', 'success');
    }

    updateFavBadge();
    openFavDetail(bidNo);
}

// 협업 이력 — 같은 협업사가 참여한 다른 공고 추적
function getPartnerHistory(currentBidNo, partners) {
    if (!partners || partners.length === 0) return [];

    const allFavs = getFavorites();
    const result = [];

    partners.forEach(p => {
        const pName = typeof p === 'string' ? p : p.name || '';
        if (!pName) return;

        const otherBids = allFavs.filter(f => {
            if (f.bid_ntce_no === currentBidNo) return false;
            return (f.partners || []).some(fp => {
                const fpName = typeof fp === 'string' ? fp : fp.name || '';
                return fpName === pName;
            });
        });

        if (otherBids.length > 0) {
            result.push({ partnerName: pName, otherBids });
        }
    });

    return result;
}

// 관심공고 CSV 내보내기
function exportFavorites() {
    const favs = getFavorites();
    if (favs.length === 0) { showToast('내보낼 관심공고가 없습니다.', 'info'); return; }

    const headers = ['공고번호', '공고명', '발주기관', '예산', '마감일', '상태', '메모', '협업사', '분석완료', '추가일'];
    const statusLabels = { reviewing: '검토중', proceeding: '사업진행', partnered: '협업진행', completed: '완료', abandoned: '포기' };

    const rows = favs.map(f => [
        f.bid_ntce_no,
        (f.title || '').replace(/"/g, '""'),
        (f.org_name || '').replace(/"/g, '""'),
        f.budget || '',
        f.bid_close_dt || '',
        statusLabels[f.status] || f.status || '',
        (f.memo || '').replace(/"/g, '""').replace(/\n/g, ' '),
        (f.partners || []).map(p => typeof p === 'string' ? p : `${p.name||''}(${p.role||''})`).join(', '),
        f.analysis_done ? 'O' : 'X',
        f.added_at ? new Date(f.added_at).toLocaleDateString('ko-KR') : '',
    ]);

    const csv = '\uFEFF' + [headers, ...rows].map(r => r.map(c => `"${c}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `관심공고_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`${favs.length}건 CSV 내보내기 완료`, 'success');
}


// ──────────────────────────────────────────────
// 3. 네비게이션
// ──────────────────────────────────────────────
function navigate(view) {
    state.currentView = view;

    // 모든 뷰 숨기기
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));

    // 해당 뷰 표시
    const target = document.getElementById(`view-${view}`);
    if (target) target.classList.add('active');

    // 사이드바 active 상태 변경
    document.querySelectorAll('.menu-item').forEach(item => {
        item.classList.toggle('active', item.dataset.view === view);
    });

    // 모바일: 사이드바 닫기
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-overlay').classList.remove('active');

    // 관심공고 배지 항상 갱신
    updateFavBadge();

    // 데이터 로드
    switch (view) {
        case 'dashboard': loadDashboard(); break;
        case 'bids': loadBids(); break;
        case 'favorites': loadFavorites(); break;
        case 'businesses': loadBusinesses(); break;
        case 'analysis': loadAnalyses(); break;
        case 'settings': loadSettings(); break;
    }

    // 접근성: 뷰 전환 시 포커스 이동
    const viewId = `view-${view}`;
    const activeSection = document.getElementById(viewId);
    if (activeSection) {
        const heading = activeSection.querySelector('h2, h3, [tabindex="-1"]');
        if (heading) {
            heading.setAttribute('tabindex', '-1');
            heading.focus({ preventScroll: true });
        }
    }

    // 뷰 전환 stagger 등장 애니메이션
    animateViewCards(view);
}


// ──────────────────────────────────────────────
// 4. 대시보드
// ──────────────────────────────────────────────
// ──────────────────────────────────────────────
// 자동 공고 수집 (DB 비어있거나 6시간 이상 지났을 때)
// ──────────────────────────────────────────────
let _autoCollectRunning = false;

function _shouldAutoCollect(stats) {
    // 이미 수집 중이면 스킵
    if (_autoCollectRunning) return false;

    // DB에 공고가 없으면 즉시 수집
    if (!stats.bids || stats.bids === 0) return true;

    // 마지막 수집이 6시간 이상 지났으면 수집
    if (stats.last_collected_at) {
        try {
            const lastTime = new Date(stats.last_collected_at.replace(' ', 'T') + 'Z');
            const now = new Date();
            const hoursAgo = (now - lastTime) / (1000 * 60 * 60);
            if (hoursAgo >= 6) return true;
        } catch (e) {
            console.warn('수집 시간 파싱 실패:', e);
        }
    }

    return false;
}

async function _runAutoCollect() {
    if (_autoCollectRunning) return;
    _autoCollectRunning = true;

    // 브리핑 패널과 TOP10에 수집중 표시
    _showCollectingBanner(true);

    try {
        // 관심 키워드 기반 자동 수집 (body 없이 POST → 서버에서 settings 키워드 사용)
        const result = await api('POST', '/bids/collect', {});
        console.log(`✅ 자동 수집 완료: ${result.collected}건 수집, ${result.saved}건 신규 저장`);

        _showCollectingBanner(false, result);

        // 수집 후 대시보드 데이터 갱신 (통계, TOP10, 차트)
        setTimeout(async () => {
            try {
                // 통계 갱신
                const newStats = await api('GET', '/dashboard/stats');
                if (newStats) {
                    animateCounter('stat-bids', newStats.bids || 0);
                    animateCounter('stat-urgent', newStats.urgent_count || 0);
                    const bidsChangeEl = document.getElementById('stat-bids-change');
                    if (bidsChangeEl && newStats.today_bids > 0) {
                        bidsChangeEl.textContent = `오늘 +${newStats.today_bids}건`;
                        bidsChangeEl.style.opacity = '1';
                    }
                }
                // TOP10 + 브리핑 갱신
                loadTop10();
                // 차트 갱신
                loadCharts();
            } catch (e) {
                console.warn('갱신 실패:', e.message);
            }
        }, 500);

    } catch (err) {
        console.error('자동 수집 실패:', err.message);
        _showCollectingBanner(false, null, err.message);
    } finally {
        _autoCollectRunning = false;
    }
}

function _showCollectingBanner(isLoading, result, errorMsg) {
    // 브리핑 패널 상단에 수집 상태 배너 표시
    const briefingBody = document.getElementById('briefing-body');
    const briefingBadge = document.getElementById('briefing-badge');
    const top10List = document.getElementById('top10-list');

    if (isLoading) {
        // 수집 중 표시
        if (briefingBadge) briefingBadge.textContent = '수집중...';
        const loadingHTML = `
            <div class="auto-collect-banner collecting">
                <div class="auto-collect-spinner"></div>
                <div class="auto-collect-text">
                    <strong>🔄 공고 수집 중입니다</strong>
                    <span>관심 키워드 기반으로 나라장터에서 공고를 가져오고 있습니다...</span>
                </div>
            </div>`;
        if (briefingBody) briefingBody.innerHTML = loadingHTML;
        if (top10List) top10List.innerHTML = loadingHTML;
    } else if (errorMsg) {
        // 오류 표시
        if (briefingBadge) briefingBadge.textContent = '수집 실패';
        const errorHTML = `
            <div class="auto-collect-banner error">
                <div class="auto-collect-text">
                    <strong>⚠️ 수집 중 오류가 발생했습니다</strong>
                    <span>${escapeHTML(errorMsg)}</span>
                </div>
            </div>`;
        if (briefingBody) briefingBody.innerHTML = errorHTML;
    } else if (result) {
        // 수집 완료 → 잠시 성공 메시지 후 실제 데이터로 교체 (setTimeout에서 갱신됨)
        if (briefingBadge) briefingBadge.textContent = '갱신중...';
        const doneHTML = `
            <div class="auto-collect-banner done">
                <div class="auto-collect-text">
                    <strong>✅ 수집 완료!</strong>
                    <span>${result.collected}건 수집, ${result.saved}건 신규 저장 — 추천 공고를 분석하고 있습니다...</span>
                </div>
            </div>`;
        if (briefingBody) briefingBody.innerHTML = doneHTML;
    }
}

async function loadDashboard() {
    // 대시보드 통계를 한 번만 호출하고 결과를 재사용
    let dashboardStats = null;
    try {
        dashboardStats = await api('GET', '/dashboard/stats');
        if (dashboardStats) {
            animateCounter('stat-businesses', dashboardStats.businesses || 0);
            animateCounter('stat-bids', dashboardStats.bids || 0);
            animateCounter('stat-analyses', dashboardStats.analyses || 0);
            animateCounter('stat-urgent', dashboardStats.urgent_count || 0);

            // 오늘 수집 건수 표시
            const bidsChangeEl = document.getElementById('stat-bids-change');
            if (bidsChangeEl && dashboardStats.today_bids > 0) {
                bidsChangeEl.textContent = `오늘 +${dashboardStats.today_bids}건`;
                bidsChangeEl.style.opacity = '1';
            }

            // 통계 로드 성공 시 시스템 상태 표시
            const footerText = document.querySelector('.footer-text');
            const footerDot = document.getElementById('footer-status-dot');
            if (footerText) footerText.textContent = '시스템 정상 가동';
            if (footerDot) footerDot.style.background = 'var(--success)';

            // ── 자동 수집 판단 ──
            const needsAutoCollect = _shouldAutoCollect(dashboardStats);
            if (needsAutoCollect) {
                _runAutoCollect();  // 비동기 - 백그라운드 실행
            }
        }
    } catch (err) {
        console.warn('대시보드 통계 로드 실패:', err.message);
        ['stat-businesses', 'stat-bids', 'stat-analyses', 'stat-urgent'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = '-';
        });
        const footerText = document.querySelector('.footer-text');
        const footerDot = document.getElementById('footer-status-dot');
        if (footerText) footerText.textContent = '연결 오류';
        if (footerDot) footerDot.style.background = 'var(--danger)';
    }

    try {
        const recent = await api('GET', '/dashboard/recent');
        renderRecentAnalyses(recent || []);
    } catch (err) {
        console.warn('최근 분석 로드 실패:', err.message);
    }

    // 차트 로드
    loadCharts();

    // TOP 10 추천 사업도 함께 로드
    loadTop10();

    // 관심 키워드 패널 로드
    loadKeywordSearchPanel();

    // 대시보드 환영 헤더 날짜 표시
    const dashDateEl = document.getElementById('dashboard-date');
    if (dashDateEl) {
        const now = new Date();
        const weekday = ['일','월','화','수','목','금','토'][now.getDay()];
        const hour = now.getHours();
        let greeting = '좋은 아침입니다';
        if (hour >= 12 && hour < 18) greeting = '좋은 오후입니다';
        else if (hour >= 18) greeting = '좋은 저녁입니다';
        dashDateEl.textContent = `${now.getFullYear()}년 ${now.getMonth()+1}월 ${now.getDate()}일 (${weekday}) · ${greeting}`;
    }


    // 관심공고 배지 갱신
    updateFavBadge();

    // 동적 온보딩 가이드 (dashboardStats 재사용 — 이중 호출 방지)
    const guideEl = document.getElementById('hero-guide');
    // getFavorites()를 한 번만 호출하여 캐싱
    const _cachedFavs = getFavorites();
    if (guideEl && dashboardStats) {
        try {
            const hasBiz = (dashboardStats.businesses || 0) > 0;
            const hasBids = (dashboardStats.bids || 0) > 0;
            const hasAnalysis = (dashboardStats.analyses || 0) > 0;
            const hasFav = _cachedFavs.length > 0;

            const steps = [
                { done: hasBiz, label: '사업자 등록', action: "navigate('businesses')", icon: '🏢' },
                { done: hasBids, label: '공고 수집', action: "collectBids()", icon: '📋' },
                { done: hasAnalysis, label: 'AI 분석', action: "runAnalysis()", icon: '🎯' },
                { done: hasFav, label: '관심공고 관리', action: "navigate('favorites')", icon: '⭐' },
            ];

            const allDone = steps.every(s => s.done);
            if (allDone) {
                guideEl.innerHTML = '<span style="color:var(--success)">✅ 모든 설정이 완료되었습니다! 공고를 검토하고 입찰에 참여하세요.</span>';
            } else {
                guideEl.innerHTML = steps.map((s, i) => `
                    <span class="onboard-step ${s.done ? 'done' : ''}" onclick="${s.action}" style="cursor:${s.done ? 'default' : 'pointer'}">
                        <span class="onboard-num">${s.done ? '✓' : i+1}</span>${s.label}
                    </span>
                    ${i < steps.length - 1 ? '<span class="onboard-arrow">→</span>' : ''}
                `).join('');
            }
        } catch(e) { console.warn('가이드 업데이트 실패', e); }
    }

    // 대시보드 관심공고 요약
    const favs = _cachedFavs;
    const activeFavs = favs.filter(f => f.status !== 'completed' && f.status !== 'abandoned');
    const urgentFavs = activeFavs.filter(f => {
        const d = getDaysLeft(f.bid_close_dt);
        return d !== null && d >= 0 && d <= 3;
    });
    const heroContent = document.querySelector('.hero-content .hero-text');
    if (heroContent && favs.length > 0) {
        let favSummary = document.getElementById('hero-fav-summary');
        if (!favSummary) {
            favSummary = document.createElement('div');
            favSummary.id = 'hero-fav-summary';
            favSummary.style.cssText = 'font-size:0.85rem;color:var(--text-muted);margin-top:6px;display:flex;gap:12px;flex-wrap:wrap';
            heroContent.appendChild(favSummary);
        }
        // 가장 임박한 미완료 공고의 다음 할 일 표시
        const nextAction = activeFavs
            .filter(f => { const d = getDaysLeft(f.bid_close_dt); return d !== null && d >= 0; })
            .sort((a, b) => (getDaysLeft(a.bid_close_dt) || 999) - (getDaysLeft(b.bid_close_dt) || 999))
            .map(f => {
                const nextItem = (f.checklist || []).find(c => !c.done);
                return nextItem ? { fav: f, item: nextItem } : null;
            })
            .find(x => x);

        favSummary.innerHTML = `
            <span>⭐ 관심공고 ${favs.length}건</span>
            <span>📋 진행중 ${activeFavs.length}건</span>
            ${urgentFavs.length > 0 ? `<span style="color:var(--danger);font-weight:600;cursor:pointer" onclick="navigate('favorites')">⏰ 마감임박 ${urgentFavs.length}건</span>` : ''}
        `;
        if (nextAction) {
            const d = getDaysLeft(nextAction.fav.bid_close_dt);
            let nextEl = document.getElementById('hero-next-action');
            if (!nextEl) {
                nextEl = document.createElement('div');
                nextEl.id = 'hero-next-action';
                nextEl.style.cssText = 'margin-top:8px;padding:8px 12px;background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15);border-radius:8px;font-size:0.82rem;cursor:pointer';
                heroContent.appendChild(nextEl);
            }
            nextEl.innerHTML = `
                <div style="font-weight:600;color:var(--accent-indigo, #6366f1);margin-bottom:2px">🎯 다음 할 일</div>
                <div>${escapeHTML(nextAction.fav.title?.substring(0, 35) || nextAction.fav.bid_ntce_no)}${nextAction.fav.title?.length > 35 ? '...' : ''} <span style="color:var(--danger);font-weight:500">(D-${d})</span></div>
                <div style="color:var(--text-muted)">→ ${escapeHTML(nextAction.item.label)}</div>
            `;
            nextEl.onclick = () => openFavDetail(nextAction.fav.bid_ntce_no);
        }
    }

    // 입찰 파이프라인 요약
    const pipelineEl = document.getElementById('fav-pipeline-summary');
    const pipelineStages = document.getElementById('pipeline-stages');
    const pipelineUrgent = document.getElementById('pipeline-urgent');
    if (pipelineEl && favs.length > 0) {
        pipelineEl.style.display = 'block';

        const counts = {};
        Object.keys(FAV_STATUSES).forEach(k => counts[k] = 0);
        favs.forEach(f => counts[f.status] = (counts[f.status] || 0) + 1);

        pipelineStages.innerHTML = Object.entries(FAV_STATUSES).map(([key, val]) => `
            <div class="pipeline-stage ${counts[key] > 0 ? 'has-items' : ''}" onclick="_favFilterStatus='${key}'; navigate('favorites')">
                <span class="pipeline-stage-count">${counts[key]}</span>
                <span class="pipeline-stage-label">${val.label}</span>
            </div>
        `).join('<span class="pipeline-arrow">→</span>');

        const nextActions = favs
            .filter(f => f.status !== 'completed' && f.status !== 'abandoned')
            .map(f => {
                const cl = f.checklist || [];
                const next = cl.find(c => !c.done);
                const d = getDaysLeft(f.bid_close_dt);
                return { ...f, nextTask: next?.label || '모든 체크 완료', daysLeft: d };
            })
            .sort((a, b) => (a.daysLeft ?? 999) - (b.daysLeft ?? 999))
            .slice(0, 3);

        if (nextActions.length > 0) {
            pipelineUrgent.innerHTML = nextActions.map(f => {
                const dBadge = f.daysLeft !== null && f.daysLeft <= 3
                    ? `<span style="color:var(--danger);font-weight:600">D-${f.daysLeft}</span>`
                    : f.daysLeft !== null ? `D-${f.daysLeft}` : '';
                return `<div class="pipeline-action-item" onclick="openFavDetail('${escapeHTML(f.bid_ntce_no)}')">
                    <span class="pipeline-action-title">${escapeHTML((f.title || '').substring(0, 30))}${(f.title||'').length > 30 ? '...' : ''}</span>
                    <span class="pipeline-action-next">➡️ ${escapeHTML(f.nextTask)}</span>
                    <span class="pipeline-action-deadline">${dBadge}</span>
                </div>`;
            }).join('');
        }
    } else if (pipelineEl) {
        pipelineEl.style.display = 'none';
    }
}

function renderRecentAnalyses(analyses) {
    const tbody = document.getElementById('recent-analyses-body');
    if (!analyses || analyses.length === 0) {
        tbody.innerHTML = `
            <tr class="empty-row">
                <td colspan="6">
                    <div class="empty-state-inline">
                        <span>📊</span>
                        <p>분석 결과가 없습니다. 분석을 실행해보세요.</p>
                    </div>
                </td>
            </tr>`;
        return;
    }

    tbody.innerHTML = analyses.slice(0, 10).map(a => {
        const strategy = tryParseJSON(a.strategy_report);
        const bidTitle = a.bid_title || a.bid_ntce_no || '-';
        const orgName = a.org_name || '-';
        const budget = displayBudget(a.budget);
        const bizName = a.company_name || a.biz_id || '-';
        const score = a.match_score || 0;
        const date = a.analyzed_at ? formatDate(a.analyzed_at) : '-';

        return `
            <tr style="cursor:pointer" onclick="openStrategyModal('${escapeHTML(a.bid_ntce_no || '')}')" title="클릭하여 전략 분석 보기">
                <td class="td-title" title="${escapeHTML(bidTitle)}">${escapeHTML(bidTitle)}</td>
                <td>${escapeHTML(orgName)}</td>
                <td class="td-budget">${budget}</td>
                <td>${escapeHTML(bizName)}</td>
                <td><span class="score-badge ${getScoreClass(score)}">${getScoreEmoji(score)} ${score.toFixed(0)}점</span></td>
                <td class="text-muted">${date}</td>
            </tr>`;
    }).join('');
}


// ──────────────────────────────────────────────
// 5. 공고 목록 (키워드 매칭 중심)
// ──────────────────────────────────────────────
async function loadBids() {
    const tbody = document.getElementById('bids-body');
    tbody.innerHTML = renderSkeletonRows(5, 6);

    // 저장된 관심 키워드로 빠른검색 칩 동적 생성
    try {
        const settings = await api('GET', '/settings/full');
        const chips = document.getElementById('search-chips');
        if (chips && settings.keywords && settings.keywords.length > 0) {
            chips.innerHTML = settings.keywords.map(kw =>
                `<button class="search-chip" data-keyword="${escapeHTML(kw)}">${escapeHTML(kw)}</button>`
            ).join('');
        }
    } catch (e) {
        console.warn('키워드 칩 로드 실패:', e.message);
    }

    try {
        // 키워드 매칭된 공고만 로드
        const curated = await api('GET', '/dashboard/curated?limit=200');
        state.bids = (curated || []).map(c => ({
            ...c,
            bid_ntce_no: c.bid_ntce_no || '',
            title: c.title || '',
            org_name: c.org_name || '',
            budget: c.budget,
            bid_close_dt: c.bid_close_dt || '',
            relevance_score: c.relevance_score || 0,
            matched_keywords: c.matched_keywords || [],
        }));
        state.bidPage = 1;
        // 필터 적용 후 렌더링
        filterBids();
    } catch (err) {
        showToast(`공고 목록 로드 실패: ${err.message}`, 'error');
        tbody.innerHTML = `
            <tr class="empty-row">
                <td colspan="7">
                    <div class="empty-state-inline">
                        <span>⚠️</span>
                        <p>데이터를 불러올 수 없습니다.</p>
                    </div>
                </td>
            </tr>`;
    }
}

function getNaraDetailUrl(bidNtceNo, bidNtceOrd) {
    // 나라장터 입찰공고 상세페이지 URL (2024~ 신규 형식)
    const ord = bidNtceOrd || '000';
    return `https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=${encodeURIComponent(bidNtceNo)}&bidPbancOrd=${encodeURIComponent(ord)}`;
}

function renderBids(bids) {
    const tbody = document.getElementById('bids-body');
    if (!bids || bids.length === 0) {
        tbody.innerHTML = `
            <tr class="empty-row">
                <td colspan="7">
                    ${renderEmptyState('📝', '매칭 공고 없음', '키워드와 매칭되는 공고가 없습니다. 공고를 수집해주세요.')}
                </td>
            </tr>`;
        const paginationEl = document.getElementById('bids-pagination');
        if (paginationEl) paginationEl.innerHTML = '';
        return;
    }

    // 페이지네이션 계산
    const totalPages = Math.ceil(bids.length / state.bidsPerPage);
    if (state.bidPage > totalPages) state.bidPage = totalPages;
    if (state.bidPage < 1) state.bidPage = 1;
    const startIdx = (state.bidPage - 1) * state.bidsPerPage;
    const pageBids = bids.slice(startIdx, startIdx + state.bidsPerPage);

    tbody.innerHTML = pageBids.map((bid, idx) => {
        const score = bid.relevance_score ? bid.relevance_score.toFixed(0) : '0';
        const kwChips = (bid.matched_keywords || []).map(k =>
            `<span class="kw-chip">${escapeHTML(k)}</span>`
        ).join('');
        const naraUrl = getNaraDetailUrl(bid.bid_ntce_no, bid.bid_ntce_ord);
        const daysLeftText = formatDaysLeft(bid.bid_close_dt);
        const daysLeft = getDaysLeft(bid.bid_close_dt);
        let badgeClass = 'unknown';
        if (daysLeft !== null) {
            if (daysLeft < 0) badgeClass = 'closed';
            else if (daysLeft <= 3) badgeClass = 'urgent';
            else badgeClass = 'active';
        }
        const isFav = isFavorite(bid.bid_ntce_no);

        return `
        <tr data-bid-no="${escapeHTML(bid.bid_ntce_no)}" class="bid-row-toggle ${isFav ? 'bid-row-fav' : ''} ${badgeClass === 'closed' ? 'bid-row-expired' : ''}" style="cursor:pointer">
            <td class="td-title" title="${escapeHTML(bid.title || '')}">
                ${isFav ? '<span style="color:#f59e0b">⭐</span> ' : ''}${escapeHTML(bid.title || '-')}
                <div class="td-keywords">${kwChips}${bid.license_limit ? `<span class="kw-chip" style="background:rgba(239,68,68,0.1);color:var(--danger);border-color:rgba(239,68,68,0.3)">⚠ ${escapeHTML(bid.license_limit.substring(0, 20))}</span>` : ''}</div>
            </td>
            <td>${escapeHTML(bid.org_name || '-')}</td>
            <td class="td-budget">${displayBudget(bid.budget)}</td>
            <td><span class="bid-status-badge ${badgeClass}">${daysLeftText}</span></td>
            <td><span class="relevance-badge ${parseInt(score) >= 70 ? 'score-high' : parseInt(score) >= 40 ? 'score-mid' : 'score-low'}">${score}점</span></td>
            <td style="text-align:center">
                <button class="btn-mini-fav ${isFav ? 'active' : ''}"
                    onclick="event.stopPropagation(); toggleFavFromBid('${escapeHTML(bid.bid_ntce_no)}', this.closest('tr').querySelector('.td-title').textContent.trim(), '${escapeHTML((bid.org_name||'').replace(/'/g,''))}', '${bid.budget||''}', '${escapeHTML(bid.bid_close_dt||'')}', this); this.textContent=this.classList.contains('active')?'⭐':'☆'; this.closest('tr').classList.toggle('bid-row-fav')"
                    title="관심공고">${isFav ? '⭐' : '☆'}</button>
            </td>
            <td>
                <a href="${escapeHTML(naraUrl)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-nara"
                   onclick="event.stopPropagation()" title="나라장터에서 상세 확인">
                    🔗 상세
                </a>
            </td>
        </tr>
        <tr class="bid-detail-row" id="detail-${escapeHTML(bid.bid_ntce_no)}">
            <td colspan="7">
                <div class="bid-detail-content">
                    ${(bid.license_limit || bid.region || bid.contract_method) ? `
                    <div class="bid-qual-banner">
                        <div class="bid-qual-title">📋 자격요건 및 입찰조건</div>
                        <div class="bid-qual-grid">
                            ${bid.license_limit ? `<div class="bid-qual-item bid-qual-critical">
                                <span class="bid-qual-icon">⚠️</span>
                                <div><div class="bid-qual-label">면허/자격 제한</div>
                                <div class="bid-qual-value">${escapeHTML(bid.license_limit)}</div></div>
                            </div>` : ''}
                            ${bid.region ? `<div class="bid-qual-item">
                                <span class="bid-qual-icon">📍</span>
                                <div><div class="bid-qual-label">지역 제한</div>
                                <div class="bid-qual-value">${escapeHTML(bid.region)}</div></div>
                            </div>` : ''}
                            ${bid.contract_method ? `<div class="bid-qual-item">
                                <span class="bid-qual-icon">📝</span>
                                <div><div class="bid-qual-label">계약 방법</div>
                                <div class="bid-qual-value">${escapeHTML(bid.contract_method)}</div></div>
                            </div>` : ''}
                            ${bid.bid_method ? `<div class="bid-qual-item">
                                <span class="bid-qual-icon">🏷️</span>
                                <div><div class="bid-qual-label">입찰 방식</div>
                                <div class="bid-qual-value">${escapeHTML(bid.bid_method)}</div></div>
                            </div>` : ''}
                            ${bid.budget ? `<div class="bid-qual-item">
                                <span class="bid-qual-icon">💰</span>
                                <div><div class="bid-qual-label">추정가격</div>
                                <div class="bid-qual-value">${displayBudget(bid.budget)}</div></div>
                            </div>` : ''}
                            ${bid.category ? `<div class="bid-qual-item">
                                <span class="bid-qual-icon">🏢</span>
                                <div><div class="bid-qual-label">업종 분류</div>
                                <div class="bid-qual-value">${escapeHTML(bid.category)}</div></div>
                            </div>` : ''}
                        </div>
                    </div>` : ''}
                    <div class="bid-detail-grid">
                        <div class="bid-detail-item">
                            <span class="bid-detail-label">공고번호</span>
                            <span class="bid-detail-value">${escapeHTML(bid.bid_ntce_no || '-')}${bid.bid_ntce_ord ? ` (${bid.bid_ntce_ord}차)` : ''}</span>
                        </div>
                        <div class="bid-detail-item">
                            <span class="bid-detail-label">발주기관</span>
                            <span class="bid-detail-value">${escapeHTML(bid.org_name || '-')}</span>
                        </div>
                        ${(bid.demand_org_name || bid.dminstt_nm) && (bid.demand_org_name || bid.dminstt_nm) !== bid.org_name ? `<div class="bid-detail-item">
                            <span class="bid-detail-label">수요기관</span>
                            <span class="bid-detail-value">${escapeHTML(bid.demand_org_name || bid.dminstt_nm)}</span>
                        </div>` : ''}
                        <div class="bid-detail-item">
                            <span class="bid-detail-label">마감일</span>
                            <span class="bid-detail-value"><span class="bid-status-badge ${badgeClass}">${daysLeftText}</span> ${bid.bid_close_dt ? formatDate(bid.bid_close_dt) : ''}</span>
                        </div>
                        <div class="bid-detail-item">
                            <span class="bid-detail-label">적합도</span>
                            <span class="bid-detail-value"><span class="relevance-badge ${parseInt(score) >= 70 ? 'score-high' : parseInt(score) >= 40 ? 'score-mid' : 'score-low'}">${score}점 ${getScoreGrade(parseInt(score))}</span></span>
                        </div>
                        ${bid.bid_begin_dt ? `<div class="bid-detail-item">
                            <span class="bid-detail-label">입찰개시</span>
                            <span class="bid-detail-value">${formatDate(bid.bid_begin_dt)}</span>
                        </div>` : ''}
                        ${kwChips ? `<div class="bid-detail-item" style="grid-column:1/-1"><span class="bid-detail-label">매칭 키워드</span><div class="bid-detail-value">${kwChips}</div></div>` : ''}
                    </div>
                    <div class="bid-detail-actions">
                        <button class="btn btn-sm ${isFavorite(bid.bid_ntce_no) ? 'btn-fav active' : 'btn-fav'}" onclick="event.stopPropagation(); toggleFavFromBid('${escapeHTML(bid.bid_ntce_no)}', '${escapeHTML((bid.title||'').replace(/'/g, ''))}', '${escapeHTML((bid.org_name||'').replace(/'/g, ''))}', '${bid.budget||''}', '${escapeHTML(bid.bid_close_dt||'')}', this)">${isFavorite(bid.bid_ntce_no) ? '⭐ 관심공고' : '☆ 관심공고'}</button>
                        <button class="btn btn-sm btn-prepare" onclick="event.stopPropagation(); prepareBid('${escapeHTML(bid.bid_ntce_no)}', '${escapeHTML((bid.title||'').replace(/'/g, ''))}', '${escapeHTML((bid.org_name||'').replace(/'/g, ''))}', '${bid.budget||''}', '${escapeHTML(bid.bid_close_dt||'')}')">📋 입찰 준비하기</button>
                        <a href="${escapeHTML(naraUrl)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm"
                           onclick="event.stopPropagation()">🔗 나라장터에서 확인</a>
                        <button class="btn btn-gradient btn-sm btn-strategy-analyze" data-bid-no="${escapeHTML(bid.bid_ntce_no)}">🎯 전략 분석</button>
                    </div>
                </div>
            </td>
        </tr>`;
    }).join('');

    // 페이지네이션 UI 렌더링
    let paginationEl = document.getElementById('bids-pagination');
    if (!paginationEl) {
        paginationEl = document.createElement('div');
        paginationEl.id = 'bids-pagination';
        paginationEl.style.cssText = 'display:flex;align-items:center;justify-content:center;gap:12px;padding:16px 0;';
        const table = tbody.closest('table');
        if (table && table.parentElement) table.parentElement.appendChild(paginationEl);
    }
    if (totalPages <= 1) {
        paginationEl.innerHTML = `<span style="color:var(--text-muted);font-size:0.85rem">총 ${bids.length}건</span>`;
    } else {
        paginationEl.innerHTML = `
            <button class="btn btn-secondary btn-sm" onclick="changeBidPage(-1)" ${state.bidPage <= 1 ? 'disabled' : ''}>⬅ 이전</button>
            <span style="color:var(--text-secondary);font-size:0.9rem">${state.bidPage} / ${totalPages} 페이지 (총 ${bids.length}건)</span>
            <button class="btn btn-secondary btn-sm" onclick="changeBidPage(1)" ${state.bidPage >= totalPages ? 'disabled' : ''}>다음 ➡</button>
        `;
    }
}

function changeBidPage(delta) {
    state.bidPage += delta;
    // 현재 필터된 bids가 있으면 그것을 사용, 없으면 state.bids
    const query = document.getElementById('bid-search')?.value?.trim();
    if (query) {
        const filtered = state.bids.filter(b =>
            (b.title || '').toLowerCase().includes(query.toLowerCase()) ||
            (b.org_name || '').toLowerCase().includes(query.toLowerCase()) ||
            (b.bid_ntce_no || '').toLowerCase().includes(query.toLowerCase())
        );
        renderBids(filtered);
    } else {
        renderBids(state.bids);
    }
}

function toggleBidDetail(bidNo) {
    const row = document.getElementById(`detail-${escapeHTML(bidNo)}`);
    if (row) {
        row.classList.toggle('active');
    }
}

let _searchDebounce = null;
let _sortField = null;
let _sortDir = 'desc'; // 'asc' or 'desc'

function sortBids(field) {
    // 같은 필드 클릭 시 방향 토글
    if (_sortField === field) {
        _sortDir = _sortDir === 'asc' ? 'desc' : 'asc';
    } else {
        _sortField = field;
        _sortDir = field === 'bid_close_dt' ? 'asc' : 'desc'; // 마감일은 임박 순이 기본
    }

    // 헤더 화살표 업데이트
    document.querySelectorAll('.sortable .sort-arrow').forEach(el => el.textContent = '↕');
    const activeHeader = document.getElementById(`th-${field}`);
    if (activeHeader) {
        activeHeader.querySelector('.sort-arrow').textContent = _sortDir === 'asc' ? '↑' : '↓';
    }

    // 접근성: aria-sort 업데이트
    document.querySelectorAll('.sortable[aria-sort]').forEach(el => el.setAttribute('aria-sort', 'none'));
    if (activeHeader) {
        activeHeader.setAttribute('aria-sort', _sortDir === 'asc' ? 'ascending' : 'descending');
    }

    // 정렬 실행
    const sorted = [...state.bids].sort((a, b) => {
        let valA, valB;

        if (field === 'budget') {
            valA = a.budget || 0;
            valB = b.budget || 0;
        } else if (field === 'bid_close_dt') {
            valA = a.bid_close_dt || 'z';
            valB = b.bid_close_dt || 'z';
        } else if (field === 'relevance_score') {
            valA = a.relevance_score || 0;
            valB = b.relevance_score || 0;
        } else {
            return 0;
        }

        if (valA < valB) return _sortDir === 'asc' ? -1 : 1;
        if (valA > valB) return _sortDir === 'asc' ? 1 : -1;
        return 0;
    });

    state.bids = sorted;
    state.bidPage = 1;
    renderBids(state.bids);
}

function filterBids() {
    const query = document.getElementById('bid-search').value.trim();
    const hideExpired = document.getElementById('bid-hide-expired')?.checked || false;
    const budgetFilter = document.getElementById('bid-filter-budget')?.value || '';

    // 마감/예산 필터 적용 함수
    function applyFilters(bids) {
        let result = bids;
        if (hideExpired) {
            result = result.filter(b => {
                const d = getDaysLeft(b.bid_close_dt);
                return d === null || d >= 0;
            });
        }
        if (budgetFilter) {
            const B = 100000000; // 1억
            result = result.filter(b => {
                const amt = parseFloat(b.budget) || 0;
                if (budgetFilter === 'under1') return amt > 0 && amt < B;
                if (budgetFilter === '1to5') return amt >= B && amt < 5 * B;
                if (budgetFilter === '5to10') return amt >= 5 * B && amt < 10 * B;
                if (budgetFilter === 'over10') return amt >= 10 * B;
                return true;
            });
        }
        return result;
    }

    // 결과 건수 표시
    function updateCount(filtered, total) {
        const el = document.getElementById('bid-count-info');
        if (el) {
            el.textContent = filtered < total ? `${filtered}건 / 전체 ${total}건` : `${total}건`;
        }
    }

    // 디바운싱: 300ms 후 서버 검색 실행
    clearTimeout(_searchDebounce);
    _searchDebounce = setTimeout(async () => {
        if (!query) {
            // 빈 검색어 → 전체 공고 표시 (필터 적용)
            const filtered = applyFilters(state.bids);
            renderBids(filtered);
            updateCount(filtered.length, state.bids.length);
            clearActiveChips();
            return;
        }

        // 로컬 필터 우선 (즉시 반응)
        const localFiltered = applyFilters(state.bids.filter(b =>
            (b.title || '').toLowerCase().includes(query.toLowerCase()) ||
            (b.org_name || '').toLowerCase().includes(query.toLowerCase()) ||
            (b.bid_ntce_no || '').toLowerCase().includes(query.toLowerCase())
        ));
        renderBids(localFiltered);
        updateCount(localFiltered.length, state.bids.length);

        // 서버 검색 (DB 전체에서 LIKE 검색)
        try {
            let serverBids = await api('GET', `/bids?keyword=${encodeURIComponent(query)}&limit=100`);
            if (serverBids && serverBids.length > localFiltered.length) {
                // 서버 결과에 relevance_score, matched_keywords 기본값 추가
                serverBids = serverBids.map(b => ({
                    ...b,
                    relevance_score: b.relevance_score || 0,
                    matched_keywords: b.matched_keywords || []
                }));
                const filtered = applyFilters(serverBids);
                renderBids(filtered);
                updateCount(filtered.length, serverBids.length);
            }
        } catch (e) { console.warn('서버 검색 실패, 로컬 결과 유지', e); }
    }, 300);
}

function quickSearch(keyword) {
    const input = document.getElementById('bid-search');
    input.value = keyword;

    // 칩 활성화 토글
    document.querySelectorAll('.search-chip').forEach(chip => {
        chip.classList.toggle('active', chip.textContent.includes(keyword));
    });

    filterBids();
}

function clearActiveChips() {
    document.querySelectorAll('.search-chip').forEach(c => c.classList.remove('active'));
}

async function collectByKeyword() {
    // 중복 실행 방지
    if (state.isLoading) return;

    const keyword = document.getElementById('bid-search').value.trim();
    if (!keyword) {
        showToast('검색어를 입력해주세요.', 'warning');
        return;
    }

    showLoading(`'${keyword}' 키워드로 나라장터 검색 중...`, '최근 30일 공고를 직접 수집합니다');
    try {
        updateLoadingText(`🔍 '${keyword}' 키워드로 공고 수집 중...`, '나라장터 API에 요청을 보내고 있습니다');
        const result = await api('POST', '/bids/collect', { keyword });
        const count = result?.collected || 0;
        const saved = result?.saved || 0;

        // 수집 후 목록 새로고침 (키워드 필터 유지)
        updateLoadingText('📋 수집된 공고 목록 갱신 중...', `${count}건 수집 완료, 목록을 업데이트합니다`);
        try {
            const bids = await api('GET', `/bids?keyword=${encodeURIComponent(keyword)}&limit=200`);
            state.bids = bids || [];
            renderBids(state.bids);
        } catch (e) {
            console.warn('수집 후 목록 갱신 실패', e);
            loadBids();
        }

        hideLoading();
        showToast(`🌐 '${keyword}' 검색 결과: ${count}건 수집, ${saved}건 신규 저장`, 'success');
    } catch (err) {
        hideLoading();
        showToast(`수집 실패: ${err.message}`, 'error');
    }
}

async function collectBids() {
    // 중복 실행 방지
    if (state.isLoading) return;

    showLoading('관심 키워드로 공고 수집 중...', '설정된 키워드로 나라장터를 검색합니다');
    try {
        updateLoadingText('🔍 나라장터 공고 수집 중...', '관심 키워드로 공고를 검색하고 있습니다');
        const result = await api('POST', '/bids/collect');
        const count = result?.collected || 0;
        const saved = result?.saved || 0;
        const keywords = result?.keywords_used || [];

        updateLoadingText('📋 공고 목록 갱신 중...', `${count}건 수집 완료, 화면을 업데이트합니다`);

        hideLoading();
        if (keywords.length > 0) {
            showToast(`🎯 [${keywords.join(', ')}] 키워드로 ${count}건 수집, ${saved}건 신규 저장`, 'success');
        } else {
            showToast(`${count}건의 공고가 수집되었습니다. (${saved}건 신규)`, 'success');
        }
        // 수집 완료 후 공고 목록으로 이동하여 결과 확인
        navigate('bids');
    } catch (err) {
        hideLoading();
        showToast(`공고 수집 실패: ${err.message}`, 'error');
    }
}


// ──────────────────────────────────────────────
// 6. 사업자 관리
// ──────────────────────────────────────────────
async function loadBusinesses() {
    const grid = document.getElementById('business-grid');
    grid.innerHTML = '<div class="skeleton skeleton-card"></div>'.repeat(3);

    try {
        const businesses = await api('GET', '/businesses');
        state.businesses = businesses || [];
        renderBusinesses(state.businesses);
    } catch (err) {
        showToast(`사업자 목록 로드 실패: ${err.message}`, 'error');
        grid.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">⚠️</div>
                <h3>데이터를 불러올 수 없습니다</h3>
                <p>서버 연결을 확인해주세요.</p>
            </div>`;
    }
}

function renderBusinesses(businesses) {
    const grid = document.getElementById('business-grid');

    if (!businesses || businesses.length === 0) {
        grid.innerHTML = `
            <div class="empty-state" id="business-empty">
                <div class="empty-icon">🏢</div>
                <h3>등록된 사업자가 없습니다</h3>
                <p>사업자를 등록하면 공고와 자동 매칭 분석이 가능합니다.</p>
                <button class="btn btn-primary" onclick="showBusinessModal()">
                    <span class="btn-icon">➕</span> 첫 사업자 등록하기
                </button>
            </div>`;
        return;
    }

    grid.innerHTML = businesses.map((biz, idx) => {
        const types = parseJsonField(biz.business_types);
        const licenses = parseJsonField(biz.licenses);
        const regions = parseJsonField(biz.regions);
        const keywords = parseJsonField(biz.keywords);

        return `
        <div class="business-card" style="animation-delay: ${idx * 0.08}s">
            <div class="biz-card-header">
                <div>
                    <div class="biz-card-name">${escapeHTML(biz.company_name)}</div>
                    ${biz.ceo_name ? `<div class="biz-card-ceo">대표: ${escapeHTML(biz.ceo_name)}</div>` : ''}
                </div>
                <span class="biz-card-id">${escapeHTML(biz.biz_id)}</span>
            </div>
            <div class="biz-card-body">
                ${types.length ? `
                <div class="biz-card-row">
                    <span class="biz-card-row-label">업종</span>
                    <div class="biz-tags">
                        ${types.map(t => `<span class="biz-tag">${escapeHTML(t)}</span>`).join('')}
                    </div>
                </div>` : ''}
                ${licenses.length ? `
                <div class="biz-card-row">
                    <span class="biz-card-row-label">면허</span>
                    <div class="biz-tags">
                        ${licenses.map(l => `<span class="biz-tag license">${escapeHTML(l)}</span>`).join('')}
                    </div>
                </div>` : ''}
                ${regions.length ? `
                <div class="biz-card-row">
                    <span class="biz-card-row-label">지역</span>
                    <div class="biz-tags">
                        ${regions.map(r => `<span class="biz-tag region">${escapeHTML(r)}</span>`).join('')}
                    </div>
                </div>` : ''}
                ${keywords.length ? `
                <div class="biz-card-row">
                    <span class="biz-card-row-label">키워드</span>
                    <div class="biz-tags">
                        ${keywords.map(k => `<span class="biz-tag">${escapeHTML(k)}</span>`).join('')}
                    </div>
                </div>` : ''}
                ${(biz.min_budget || biz.max_budget) ? `
                <div class="biz-card-row">
                    <span class="biz-card-row-label">예산</span>
                    <span class="biz-card-budget">
                        <strong>${biz.min_budget ? formatBudget(biz.min_budget) : '0원'}</strong>
                        ~
                        <strong>${biz.max_budget ? formatBudget(biz.max_budget) : '무제한'}</strong>
                    </span>
                </div>` : ''}
                ${(biz.employee_count || biz.annual_revenue) ? `
                <div class="biz-meta" style="padding:8px 0;color:var(--text-muted);font-size:0.85rem;border-top:1px solid var(--border);margin-top:8px">
                    ${biz.employee_count ? `👥 직원 ${biz.employee_count}명` : ''}${biz.employee_count && biz.annual_revenue ? ' | ' : ''}${biz.annual_revenue ? `💰 연매출 ${formatBudget(biz.annual_revenue)}` : ''}
                </div>` : ''}
            </div>
            <div class="biz-card-footer">
                <button class="btn btn-secondary btn-sm btn-biz-edit" data-biz-id="${escapeHTML(biz.biz_id)}">
                    ✏️ 수정
                </button>
                <button class="btn btn-secondary btn-sm btn-biz-delete" data-biz-id="${escapeHTML(biz.biz_id)}" data-biz-name="${escapeHTML(biz.company_name)}">
                    🗑️ 삭제
                </button>
            </div>
        </div>`;
    }).join('');
}

function showBusinessModal(business = null) {
    const overlay = document.getElementById('modal-overlay');
    const title = document.getElementById('modal-title');
    const submitBtn = document.getElementById('modal-submit-btn');
    const form = document.getElementById('business-form');

    // 폼 초기화
    form.reset();
    clearAllTags();

    if (business) {
        // 수정 모드
        document.getElementById('form-mode').value = 'edit';
        document.getElementById('form-original-biz-id').value = business.biz_id;
        title.textContent = '사업자 수정';
        submitBtn.textContent = '수정';

        document.getElementById('form-biz-id').value = business.biz_id || '';
        document.getElementById('form-biz-id').readOnly = true;
        document.getElementById('form-company-name').value = business.company_name || '';
        document.getElementById('form-ceo-name').value = business.ceo_name || '';
        document.getElementById('form-employee-count').value = business.employee_count || '';
        document.getElementById('form-annual-revenue').value = business.annual_revenue || '';
        document.getElementById('form-min-budget').value = business.min_budget || '';
        document.getElementById('form-max-budget').value = business.max_budget || '';

        // 태그 채우기
        setTags('biz-types', parseJsonField(business.business_types));
        setTags('licenses', parseJsonField(business.licenses));
        setTags('regions', parseJsonField(business.regions));
        setTags('keywords', parseJsonField(business.keywords));

        // 과거 수행실적 채우기
        const pastProjects = parseJsonField(business.past_projects);
        document.getElementById('form-past-projects').value = pastProjects.join('\n');
    } else {
        // 등록 모드
        document.getElementById('form-mode').value = 'create';
        document.getElementById('form-original-biz-id').value = '';
        document.getElementById('form-biz-id').readOnly = false;
        title.textContent = '사업자 등록';
        submitBtn.textContent = '등록';
    }

    overlay.classList.add('active');
}

async function saveBusiness(event) {
    event.preventDefault();

    const mode = document.getElementById('form-mode').value;
    const originalBizId = document.getElementById('form-original-biz-id').value;

    const body = {
        biz_id: document.getElementById('form-biz-id').value.trim(),
        company_name: document.getElementById('form-company-name').value.trim(),
        ceo_name: document.getElementById('form-ceo-name').value.trim() || null,
        employee_count: parseInt(document.getElementById('form-employee-count').value) || null,
        annual_revenue: parseInt(document.getElementById('form-annual-revenue').value) || null,
        min_budget: parseInt(document.getElementById('form-min-budget').value) || null,
        max_budget: parseInt(document.getElementById('form-max-budget').value) || null,
        business_types: state.tagData['biz-types'],
        licenses: state.tagData['licenses'],
        regions: state.tagData['regions'],
        keywords: state.tagData['keywords'],
        past_projects: (document.getElementById('form-past-projects').value || '')
            .split('\n').map(s => s.trim()).filter(Boolean),
    };

    if (!body.biz_id || !body.company_name) {
        showToast('사업자등록번호와 회사명은 필수입니다.', 'warning');
        return;
    }

    try {
        if (mode === 'edit') {
            await api('PUT', `/businesses/${encodeURIComponent(originalBizId)}`, body);
            showToast(`'${body.company_name}' 정보가 수정되었습니다.`, 'success');
        } else {
            await api('POST', '/businesses', body);
            showToast(`'${body.company_name}' 사업자가 등록되었습니다.`, 'success');
        }
        closeModal();
        loadBusinesses();
    } catch (err) {
        showToast(`저장 실패: ${err.message}`, 'error');
    }
}

function confirmDeleteBusiness(bizId, companyName) {
    showConfirm(
        '사업자 삭제',
        `'${companyName}' 사업자를 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.`,
        () => deleteBusiness(bizId)
    );
}

async function deleteBusiness(bizId) {
    try {
        await api('DELETE', `/businesses/${encodeURIComponent(bizId)}`);
        showToast('사업자가 삭제되었습니다.', 'success');
        loadBusinesses();
    } catch (err) {
        showToast(`삭제 실패: ${err.message}`, 'error');
    }
}


// ──────────────────────────────────────────────
// 7. 분석 실행
// ──────────────────────────────────────────────
async function runAnalysis() {
    // 중복 실행 방지
    if (state.isLoading) return;

    showLoading('참여 가능 공고 분석 중...', '수집된 공고 × 사업자 프로필 매칭 → 참여 가능 분류 (1~3분 소요)');
    try {
        updateLoadingText('🔬 공고 데이터 분석 중...', '사업자 프로필과 공고를 매칭하고 있습니다');
        const result = await api('POST', '/analyze');
        const participable = result?.participable || 0;
        const total = result?.total_bids || 0;
        const analyzed = result?.analyzed || 0;

        updateLoadingText('📊 분석 결과 정리 중...', `${analyzed}건 분석 완료, 결과를 표시합니다`);
        hideLoading();

        if (result?.message) {
            showToast(result.message, participable > 0 ? 'success' : 'warning');
        } else {
            showToast(`전체 ${total}건 중 참여 가능 ${participable}건 발견! (${analyzed}건 분석 완료)`, 'success');
        }
        navigate('analysis');
    } catch (err) {
        hideLoading();
        showToast(`분석 실패: ${err.message}`, 'error');
    }
}


// ──────────────────────────────────────────────
// 8. 분석 결과
// ──────────────────────────────────────────────
async function loadAnalyses() {
    const list = document.getElementById('analysis-list');
    list.innerHTML = '<div class="skeleton skeleton-card" style="height:200px;margin-bottom:16px"></div>'.repeat(3);

    try {
        const analyses = await api('GET', '/analyses');
        state.analyses = analyses || [];
        renderAnalyses(state.analyses);
    } catch (err) {
        showToast(`분석 결과 로드 실패: ${err.message}`, 'error');
        list.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">⚠️</div>
                <h3>데이터를 불러올 수 없습니다</h3>
                <p>서버 연결을 확인해주세요.</p>
            </div>`;
    }
}

function renderAnalyses(analyses) {
    const list = document.getElementById('analysis-list');

    if (!analyses || analyses.length === 0) {
        list.innerHTML = `
            <div class="empty-state" id="analysis-empty">
                <div class="empty-icon empty-float-icon">🔬</div>
                <h3 class="empty-title">분석 결과가 없습니다</h3>
                <p class="empty-desc">추천 사업 TOP 10에서 🎯 버튼을 눌러 전략 분석을 실행하거나,<br>아래 버튼으로 전체 분석을 시작하세요</p>
                <div style="display:flex;gap:12px;justify-content:center;margin-top:16px">
                    <button class="btn btn-gradient" onclick="runAnalysis()">
                        <span class="btn-icon">🚀</span> 전체 분석 시작
                    </button>
                    <button class="btn btn-outline" onclick="navigate('dashboard')">
                        <span class="btn-icon">🏠</span> 대시보드
                    </button>
                </div>
            </div>`;
        return;
    }

    // 상단 안내 배너
    const hasOpenAI = analyses.some(a => {
        const s = tryParseJSON(a.strategy_report);
        return s?.metadata?.analysis_engine !== 'fallback';
    });

    let banner = '';
    if (!hasOpenAI) {
        banner = `
        <div class="analysis-banner">
            <div class="analysis-banner-icon">💡</div>
            <div>
                <strong>AI 분석을 활성화하려면 Gemini 또는 OpenAI API 키를 설정하세요</strong>
                <p style="margin:4px 0 0;color:var(--text-secondary);font-size:0.85rem">
                    설정 → API 키 관리에서 AI API 키를 입력하면 경쟁사 분석, 차별화 전략, 제안서 기획 등 상세 AI 분석이 가능합니다.
                </p>
            </div>
            <button class="btn btn-sm btn-outline" onclick="navigate('settings')" style="flex-shrink:0">⚙️ 설정</button>
        </div>`;
    }

    list.innerHTML = banner + analyses.map((a, idx) => {
        const strategy = tryParseJSON(a.strategy_report);
        const bidTitle = a.bid_title || a.bid_ntce_no || '알 수 없는 공고';
        const orgName = a.org_name || '-';
        const budget = displayBudget(a.budget);
        const relevance = a.relevance_score || 0;
        const matchScore = a.match_score || 0;
        const bizName = a.company_name || a.biz_id || '-';
        const date = a.analyzed_at ? formatDate(a.analyzed_at) : '-';
        const isFallback = strategy?.metadata?.analysis_engine === 'fallback';
        const engineName = isFallback ? '🔧 기본분석' : `🤖 ${strategy?.metadata?.llm_engine || 'AI'}`;
        const naraUrl = getNaraDetailUrl(a.bid_ntce_no);

        const bidSummary = strategy?.bid_summary || a.summary || '요약 정보가 없습니다.';
        const competitorAnalysis = strategy?.competitor_analysis || strategy?.competitors || '경쟁사 분석 정보가 없습니다.';
        const strategyText = strategy?.differentiation_strategy || strategy?.strategy || strategy?.recommendation || '전략 정보가 없습니다.';
        
        let checklistHtml = '';
        const items = strategy?.action_items || strategy?.checklist;
        if (Array.isArray(items)) {
            checklistHtml = '<ul class="analysis-checklist">' + items.map(item => 
                `<li>${escapeHTML(typeof item === 'string' ? item : JSON.stringify(item))}</li>`
            ).join('') + '</ul>';
        } else if (typeof items === 'string') {
            checklistHtml = formatStrategyText(items);
        } else {
            checklistHtml = '<p style="color:var(--text-muted)">체크리스트가 없습니다.</p>';
        }

        return `
        <div class="analysis-card" style="animation-delay: ${idx * 0.1}s">
            <div class="analysis-card-header">
                <div style="flex:1;min-width:0">
                    <div class="analysis-bid-title">${escapeHTML(bidTitle)}</div>
                    <div class="analysis-bid-org">
                        🏢 ${escapeHTML(orgName)} · 💰 ${budget} · 📅 ${date}
                        ${bizName !== '-' ? ` · 🤝 ${escapeHTML(bizName)}` : ''}
                    </div>
                    <span class="analysis-engine-badge">${engineName}</span>
                </div>
                <div style="display:flex;gap:8px;align-items:center">
                    <button class="btn btn-sm ${isFavorite(a.bid_ntce_no) ? 'btn-fav active' : 'btn-fav'}"
                        onclick="event.stopPropagation(); toggleFavFromBid('${escapeHTML(a.bid_ntce_no)}', '${escapeHTML((bidTitle||'').replace(/'/g,''))}', '${escapeHTML((orgName||'').replace(/'/g,''))}', '${a.budget||''}', '', this); this.textContent=isFavorite('${escapeHTML(a.bid_ntce_no)}')?'⭐':'☆'"
                        title="관심공고">${isFavorite(a.bid_ntce_no) ? '⭐' : '☆'}</button>
                    <button class="btn btn-sm btn-secondary" onclick="exportPDF()" title="PDF 내보내기">📄 PDF</button>
                    <a href="${escapeHTML(naraUrl)}" target="_blank" class="btn btn-sm btn-outline" onclick="event.stopPropagation()" title="나라장터에서 보기">🔗 나라장터</a>
                    <button class="btn btn-sm btn-gradient btn-strategy-analyze" data-bid-no="${escapeHTML(a.bid_ntce_no)}" title="재분석">🔄 재분석</button>
                    <button class="btn btn-sm btn-outline btn-danger btn-analysis-delete" data-analysis-id="${a.id}" title="삭제">🗑️</button>
                    <span class="score-badge ${getScoreClass(matchScore)}">
                        ${getScoreEmoji(matchScore)} ${matchScore.toFixed(0)}점
                    </span>
                </div>
            </div>
            <div class="analysis-card-body">
                ${isFallback ? `<div class="analysis-fallback-notice">ℹ️ 기본 분석 모드 · AI API 키를 설정하면 상세 분석이 제공됩니다</div>` : ''}
                <div class="score-bars">
                    <div class="score-bar-item">
                        <div class="score-bar-label">
                            <span>관련도 점수</span>
                            <span class="score-bar-value">${relevance.toFixed(1)} <small style="color:var(--text-muted);font-size:0.7rem">${getScoreGrade(relevance)}</small></span>
                        </div>
                        <div class="score-bar-track">
                            <div class="score-bar-fill ${getScoreClass(relevance)}" style="width: ${Math.min(relevance, 100)}%"></div>
                        </div>
                    </div>
                    <div class="score-bar-item">
                        <div class="score-bar-label">
                            <span>매칭 점수</span>
                            <span class="score-bar-value">${matchScore.toFixed(1)} <small style="color:var(--text-muted);font-size:0.7rem">${getScoreGrade(matchScore)}</small></span>
                        </div>
                        <div class="score-bar-track">
                            <div class="score-bar-fill ${getScoreClass(matchScore)}" style="width: ${Math.min(matchScore, 100)}%"></div>
                        </div>
                    </div>
                </div>

                <div class="strategy-section">
                    <div class="strategy-tabs">
                        <button class="strategy-tab active" onclick="switchTab(this, 'summary-${idx}')">📋 사업요약</button>
                        <button class="strategy-tab" onclick="switchTab(this, 'competitor-${idx}')">🏢 경쟁사</button>
                        <button class="strategy-tab" onclick="switchTab(this, 'strategy-${idx}')">🎯 전략</button>
                        <button class="strategy-tab" onclick="switchTab(this, 'checklist-${idx}')">✅ 체크리스트</button>
                    </div>
                    <div class="strategy-content active" id="summary-${idx}">
                        ${formatStrategyText(typeof bidSummary === 'string' ? bidSummary : JSON.stringify(bidSummary, null, 2))}
                    </div>
                    <div class="strategy-content" id="competitor-${idx}">
                        ${formatStrategyText(typeof competitorAnalysis === 'string' ? competitorAnalysis : JSON.stringify(competitorAnalysis, null, 2))}
                    </div>
                    <div class="strategy-content" id="strategy-${idx}">
                        ${formatStrategyText(typeof strategyText === 'string' ? strategyText : JSON.stringify(strategyText, null, 2))}
                    </div>
                    <div class="strategy-content" id="checklist-${idx}">
                        ${checklistHtml}
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');
}

function switchTab(tabEl, contentId) {
    // 해당 카드 내 탭들만 비활성화
    const card = tabEl.closest('.analysis-card');
    card.querySelectorAll('.strategy-tab').forEach(t => t.classList.remove('active'));
    card.querySelectorAll('.strategy-content').forEach(c => c.classList.remove('active'));

    tabEl.classList.add('active');
    const content = document.getElementById(contentId);
    if (content) content.classList.add('active');
}

// 분석 결과 개별 삭제
function deleteAnalysis(id) {
    showConfirm(
        '분석 결과 삭제',
        '이 분석 결과를 삭제하시겠습니까?',
        async () => {
            try {
                await api('DELETE', `/analyses/${id}`);
                showToast('분석 결과가 삭제되었습니다.', 'success');
                loadAnalyses();
            } catch (e) {
                showToast(`삭제 실패: ${e.message}`, 'error');
            }
        }
    );
}

// 분석 결과 전체 삭제
function clearAllAnalyses() {
    showConfirm(
        '전체 분석 결과 삭제',
        '모든 분석 결과를 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.',
        async () => {
            try {
                const result = await api('DELETE', '/analyses');
                showToast(result.message || '전체 삭제 완료', 'success');
                loadAnalyses();
            } catch (e) {
                showToast(`전체 삭제 실패: ${e.message}`, 'error');
            }
        }
    );
}


// ──────────────────────────────────────────────
// 9. 모달 관리
// ──────────────────────────────────────────────
function closeModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const overlay = document.getElementById('modal-overlay');
    if (overlay) overlay.classList.remove('active');
}

function showConfirm(title, message, callback) {
    const titleEl = document.getElementById('confirm-title');
    const msgEl = document.getElementById('confirm-message');
    const overlay = document.getElementById('confirm-overlay');
    if (titleEl) titleEl.textContent = title;
    if (msgEl) msgEl.textContent = message;
    state.confirmCallback = callback;
    if (overlay) overlay.classList.add('active');
}

function closeConfirm() {
    const overlay = document.getElementById('confirm-overlay');
    if (overlay) overlay.classList.remove('active');
    state.confirmCallback = null;
}

function confirmAction() {
    if (state.confirmCallback) {
        state.confirmCallback();
    }
    closeConfirm();
}


// ──────────────────────────────────────────────
// 10. 토스트 알림
// ──────────────────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️',
    };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || icons.info}</span>
        <span>${escapeHTML(message)}</span>
        <button class="toast-close" onclick="removeToast(this.parentElement)">&times;</button>
    `;

    container.appendChild(toast);

    // 3초 후 자동 제거
    setTimeout(() => removeToast(toast), 4000);
}

function removeToast(toast) {
    if (!toast || !toast.parentElement) return;
    toast.classList.add('removing');
    setTimeout(() => {
        if (toast.parentElement) toast.parentElement.removeChild(toast);
    }, 300);
}


// ──────────────────────────────────────────────
// 11. 로딩 오버레이
// ──────────────────────────────────────────────
function showLoading(message = '처리 중...', sub = '잠시만 기다려주세요') {
    const textEl = document.getElementById('loading-text');
    const subEl = document.getElementById('loading-sub');
    const overlay = document.getElementById('loading-overlay');
    if (textEl) textEl.textContent = message;
    if (subEl) subEl.textContent = sub;
    if (overlay) overlay.classList.add('active');
    state.isLoading = true;
    // 중복 클릭 방지: 모든 액션 버튼 비활성화
    document.querySelectorAll('.action-card button, .btn-gradient, .btn-primary').forEach(btn => {
        btn.setAttribute('disabled', 'true');
    });
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.classList.remove('active');
    state.isLoading = false;
    // 버튼 다시 활성화
    document.querySelectorAll('.action-card button, .btn-gradient, .btn-primary').forEach(btn => {
        btn.removeAttribute('disabled');
    });
}

// 로딩 오버레이 텍스트 실시간 업데이트 (단계별 진행 표시용)
function updateLoadingText(message, sub) {
    const textEl = document.getElementById('loading-text');
    const subEl = document.getElementById('loading-sub');
    if (textEl && message) textEl.textContent = message;
    if (subEl && sub) subEl.textContent = sub;
}


// ──────────────────────────────────────────────
// 12. 태그 인풋 관리
// ──────────────────────────────────────────────
function initTagInput(inputId, tagKey) {
    const input = document.getElementById(`input-${inputId}`);
    if (!input) return;

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const value = input.value.trim();
            if (value && !state.tagData[tagKey].includes(value)) {
                state.tagData[tagKey].push(value);
                renderTags(tagKey);
            }
            input.value = '';
        }
    });

    // 클릭 시 인풋 포커스
    const wrap = document.getElementById(`tag-wrap-${inputId}`);
    if (wrap) {
        wrap.addEventListener('click', () => input.focus());
    }
}

function setTags(tagKey, values) {
    state.tagData[tagKey] = [...values];
    renderTags(tagKey);
}

function renderTags(tagKey) {
    const container = document.getElementById(`tags-${tagKey}`);
    if (!container) return;

    container.innerHTML = state.tagData[tagKey].map((tag, idx) => `
        <span class="form-tag">
            ${escapeHTML(tag)}
            <span class="tag-remove" data-tag-key="${escapeHTML(tagKey)}" data-tag-idx="${idx}">✕</span>
        </span>
    `).join('');
}

function removeTag(tagKey, index) {
    state.tagData[tagKey].splice(index, 1);
    renderTags(tagKey);
}

function clearAllTags() {
    Object.keys(state.tagData).forEach(key => {
        state.tagData[key] = [];
        renderTags(key);
    });
}


// ──────────────────────────────────────────────
// 13. 유틸리티 함수
// ──────────────────────────────────────────────
function formatBudget(amount) {
    if (!amount || amount === 0) return '0원';
    const n = Number(amount);
    if (isNaN(n)) return String(amount);

    if (n >= 100000000) {
        const eok = n / 100000000;
        return (eok % 1 === 0 ? eok.toString() : eok.toFixed(1)) + '억원';
    } else if (n >= 10000) {
        const man = (n / 10000).toFixed(0);
        return `${Number(man).toLocaleString()}만원`;
    }
    return `${n.toLocaleString()}원`;
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    try {
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr;
        return d.toLocaleDateString('ko-KR', {
            year: 'numeric', month: '2-digit', day: '2-digit',
            timeZone: 'Asia/Seoul'
        });
    } catch (e) {
        console.warn('날짜 포맷 실패', e);
        return dateStr;
    }
}

function getScoreClass(score) {
    if (score >= 70) return 'high success';
    if (score >= 40) return 'medium warning';
    return 'low danger';
}

function getScoreEmoji(score) {
    if (score >= 70) return '🟢';
    if (score >= 40) return '🟡';
    return '🔴';
}

function escapeHTML(str) {
    if (str == null) return '';
    return String(str).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function tryParseJSON(str) {
    if (!str) return null;
    if (typeof str === 'object') return str;
    try {
        return JSON.parse(str);
    } catch (e) {
        console.warn('JSON 파싱 실패', e);
        return null;
    }
}

function parseJsonField(value) {
    if (!value) return [];
    if (Array.isArray(value)) return value;
    if (typeof value === 'string') {
        try {
            const parsed = JSON.parse(value);
            return Array.isArray(parsed) ? parsed : [];
        } catch (e) {
            console.warn('JSON 필드 파싱 실패', e);
            return [];
        }
    }
    return [];
}

function animateCounter(elementId, target) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const start = parseInt(el.textContent) || 0;
    const duration = 800;
    const startTime = performance.now();

    function update(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // Ease out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = Math.round(start + (target - start) * eased);
        el.textContent = current.toLocaleString();
        if (progress < 1) {
            requestAnimationFrame(update);
        } else {
            // 카운트 완료 시 그라디언트 효과 클래스 추가
            el.classList.add('counter-done');
        }
    }

    requestAnimationFrame(update);
}

function renderSkeletonRows(rows, cols) {
    let html = '';
    for (let r = 0; r < rows; r++) {
        html += '<tr>';
        for (let c = 0; c < cols; c++) {
            html += `<td><div class="skeleton skeleton-text" style="width:${60 + Math.random() * 30}%"></div></td>`;
        }
        html += '</tr>';
    }
    return html;
}


// ──────────────────────────────────────────────
// 14. 모바일 사이드바 토글
// ──────────────────────────────────────────────
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    sidebar.classList.toggle('open');
    overlay.classList.toggle('active');

    // 접근성: aria-expanded 업데이트
    const toggleBtn = document.getElementById('mobile-menu-btn');
    const isOpen = sidebar.classList.contains('open');
    if (toggleBtn) {
        toggleBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        toggleBtn.setAttribute('aria-label', isOpen ? '메뉴 닫기' : '메뉴 열기');
    }
}


// ──────────────────────────────────────────────
// 15. 키보드 단축키
// ──────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
    // ESC로 모달 닫기 (통합 핸들러)
    if (e.key === 'Escape') {
        // 관심공고 상세 모달
        const favDetail = document.getElementById('fav-detail-overlay');
        if (favDetail && favDetail.classList.contains('active')) {
            favDetail.classList.remove('active'); return;
        }
        // 공고 간단 정보 팝업
        const bqv = document.getElementById('bid-quick-view');
        if (bqv && bqv.classList.contains('active')) {
            bqv.classList.remove('active'); return;
        }
        // 전략 모달
        const stratModal = document.getElementById('strategy-modal-overlay');
        if (stratModal && stratModal.classList.contains('active')) {
            closeStrategyModal(); return;
        }
        // 확인 모달
        if (document.getElementById('confirm-overlay').classList.contains('active')) {
            closeConfirm(); return;
        }
        // 사업자 등록/수정 모달
        if (document.getElementById('modal-overlay').classList.contains('active')) {
            closeModal(); return;
        }
    }
    // Ctrl+S / Cmd+S: 관심공고 모달 저장
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        const favOverlay = document.getElementById('fav-detail-overlay');
        if (favOverlay?.classList.contains('active')) {
            e.preventDefault();
            saveFavDetail();
        }
    }
});


// ──────────────────────────────────────────────
// 16. 초기화
// ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // 태그 인풀 초기화
    initTagInput('biz-types', 'biz-types');
    initTagInput('licenses', 'licenses');
    initTagInput('regions', 'regions');
    initTagInput('keywords', 'keywords');

    // IntersectionObserver 기반 스크롤 등장 애니메이션 초기화
    initScrollAnimations();

    // 설정 페이지 키워드 인풀 초기화
    initSettingsTagInput('settings-keyword-input', 'keywords');
    initSettingsTagInput('settings-exclude-input', 'exclude_keywords');

    // 협업사 입력 Enter 키 지원
    const partnerInput = document.getElementById('fav-partner-input');
    const partnerRoleInput = document.getElementById('fav-partner-role');
    if (partnerInput) {
        partnerInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); addFavPartner(); }
        });
    }
    if (partnerRoleInput) {
        partnerRoleInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); addFavPartner(); }
        });
    }

    // ── 키보드 단축키: 상단 통합 핸들러(L2383)로 이동됨 ──

    // ── 이벤트 위임: XSS 방지를 위해 inline onclick 대신 data 속성 + 이벤트 리스너 사용 ──
    document.body.addEventListener('click', (e) => {
        // 검색 칩 키워드 클릭
        const chip = e.target.closest('.search-chip[data-keyword]');
        if (chip) {
            quickSearch(chip.dataset.keyword);
            return;
        }

        // 공고 행 토글 (상세 펼치기)
        const bidRow = e.target.closest('tr.bid-row-toggle[data-bid-no]');
        if (bidRow) {
            toggleBidDetail(bidRow.dataset.bidNo);
            return;
        }

        // 전략 분석 버튼 (공고 상세, 분석 카드, TOP10 등 공통)
        const stratBtn = e.target.closest('.btn-strategy-analyze[data-bid-no]');
        if (stratBtn) {
            e.stopPropagation();
            openStrategyModal(stratBtn.dataset.bidNo);
            return;
        }

        // 사업자 수정 버튼
        const bizEditBtn = e.target.closest('.btn-biz-edit[data-biz-id]');
        if (bizEditBtn) {
            const biz = state.businesses.find(b => b.biz_id === bizEditBtn.dataset.bizId);
            if (biz) showBusinessModal(biz);
            return;
        }

        // 사업자 삭제 버튼
        const bizDelBtn = e.target.closest('.btn-biz-delete[data-biz-id]');
        if (bizDelBtn) {
            confirmDeleteBusiness(bizDelBtn.dataset.bizId, bizDelBtn.dataset.bizName);
            return;
        }

        // 분석 결과 삭제 버튼
        const analysisDelBtn = e.target.closest('.btn-analysis-delete[data-analysis-id]');
        if (analysisDelBtn) {
            e.stopPropagation();
            deleteAnalysis(Number(analysisDelBtn.dataset.analysisId));
            return;
        }

        // 태그 제거 버튼
        const tagRemoveBtn = e.target.closest('.tag-remove[data-tag-key]');
        if (tagRemoveBtn) {
            removeTag(tagRemoveBtn.dataset.tagKey, Number(tagRemoveBtn.dataset.tagIdx));
            return;
        }

        // 설정 키워드 태그 제거 버튼
        const settingsTagBtn = e.target.closest('.tag-remove-settings[data-field]');
        if (settingsTagBtn) {
            removeSettingsTag(settingsTagBtn.dataset.field, settingsTagBtn.dataset.value);
            return;
        }

        // TOP10 카드 클릭 → 간단 정보 팝업
        const top10Card = e.target.closest('.top10-card[data-bid-no]');
        if (top10Card && !e.target.closest('.btn-mini-analyze')) {
            openBidQuickView({
                bid_ntce_no: top10Card.dataset.bidNo,
                title: top10Card.dataset.title || '',
                org_name: top10Card.dataset.orgName || '',
                budget: top10Card.dataset.budget || '',
                bid_close_dt: top10Card.dataset.closeDt || '',
            });
            return;
        }

        // 브리핑 아이템 클릭 → 간단 정보 팝업
        const briefingItem = e.target.closest('.briefing-item');
        if (briefingItem && briefingItem.dataset.bidNo) {
            const bidData = {
                bid_ntce_no: briefingItem.dataset.bidNo,
                title: briefingItem.dataset.title || '',
                org_name: briefingItem.dataset.orgName || '',
                budget: briefingItem.dataset.budget || '',
                bid_close_dt: briefingItem.dataset.closeDt || '',
            };
            openBidQuickView(bidData);
            return;
        }

        // 키워드 검색 결과 카드 클릭 → 간단 정보 팝업
        const kspCard = e.target.closest('.ksp-result-card[data-bid-no]');
        if (kspCard) {
            openBidQuickView({
                bid_ntce_no: kspCard.dataset.bidNo,
                title: kspCard.dataset.title || '',
                org_name: kspCard.dataset.orgName || '',
                budget: kspCard.dataset.budget || '',
                bid_close_dt: kspCard.dataset.closeDt || '',
            });
            return;
        }
    });

    // 사이드바 메뉴 키보드 접근성
    document.querySelectorAll('#sidebar .sidebar-menu li[tabindex]').forEach(li => {
        li.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                li.click();
            }
        });
    });

    // 대시보드 로드
    navigate('dashboard');

    // 테이블 가로 스크롤 감지 (모바일 스크롤 힌트)
    const _resizeObservers = [];
    document.querySelectorAll('.table-container').forEach(tc => {
        const checkScroll = () => {
            const table = tc.querySelector('table');
            if (table && table.scrollWidth > tc.clientWidth) {
                tc.classList.add('scrollable');
            } else {
                tc.classList.remove('scrollable');
            }
        };
        checkScroll();
        const ro = new ResizeObserver(checkScroll);
        ro.observe(tc);
        _resizeObservers.push(ro);
    });

    // ResizeObserver 정리: 페이지 언로드 시 해제
    window.addEventListener('beforeunload', () => {
        _resizeObservers.forEach(ro => ro.disconnect());
    });
});


// ──────────────────────────────────────────────
// 17. 설정 페이지
// ──────────────────────────────────────────────
let settingsData = { keywords: [], exclude_keywords: [], min_relevance_score: 40 };

async function loadSettings() {
    try {
        const data = await api('GET', '/settings/full');
        settingsData = data;
        renderSettingsKeywords();
        renderApiStatus(data.api_status || {});
        const slider = document.getElementById('relevance-slider');
        const display = document.getElementById('relevance-value');
        if (slider && data.min_relevance_score != null) {
            slider.value = data.min_relevance_score;
            display.textContent = data.min_relevance_score;
        }
        // Slack URL도 같은 응답에서 처리
        const slackInput = document.getElementById('slack-webhook-input');
        if (slackInput && data.slack_webhook_url) {
            slackInput.value = data.slack_webhook_url;
        }
    } catch (e) {
        console.warn('설정 로드 실패:', e.message);
        try {
            const fallback = await api('GET', '/settings');
            settingsData = { ...settingsData, ...fallback };
            renderSettingsKeywords();
            renderApiStatus(fallback.api_keys || {});
        } catch (e2) {
            console.warn('설정 fallback도 실패:', e2.message);
        }
    }

    // 스케줄러 상태도 함께 로드
    loadSchedulerStatus();
}

function renderSettingsKeywords() {
    const kwContainer = document.getElementById('settings-keywords-tags');
    const exContainer = document.getElementById('settings-exclude-tags');
    if (!kwContainer) return;

    kwContainer.innerHTML = (settingsData.keywords || []).map(kw =>
        `<span class="form-tag">${escapeHTML(kw)} <span class="tag-remove tag-remove-settings" data-field="keywords" data-value="${escapeHTML(kw)}">✕</span></span>`
    ).join('');

    if (exContainer) {
        exContainer.innerHTML = (settingsData.exclude_keywords || []).map(kw =>
            `<span class="form-tag tag-danger">${escapeHTML(kw)} <span class="tag-remove tag-remove-settings" data-field="exclude_keywords" data-value="${escapeHTML(kw)}">✕</span></span>`
        ).join('');
    }
}

async function loadApiKeys() {
    try {
        const data = await api('GET', '/settings/api-keys');

        // 상태 dot 업데이트
        const dotData = document.getElementById('status-dot-data');
        const dotNaver = document.getElementById('status-dot-naver');
        const dotOpenai = document.getElementById('status-dot-openai');
        const dotGemini = document.getElementById('status-dot-gemini');

        if (dotData) dotData.className = `status-dot ${data.data_go_kr_api_key?.set ? 'active' : 'inactive'}`;
        if (dotNaver) dotNaver.className = `status-dot ${data.naver_client_id?.set ? 'active' : 'inactive'}`;
        if (dotOpenai) dotOpenai.className = `status-dot ${data.openai_api_key?.set ? 'active' : 'inactive'}`;
        if (dotGemini) dotGemini.className = `status-dot ${data.gemini_api_key?.set ? 'active' : 'inactive'}`;

        // 마스킹된 값 표시
        const maskedData = document.getElementById('masked-data-go-kr');
        const maskedNaver = document.getElementById('masked-naver');
        const maskedOpenai = document.getElementById('masked-openai');
        const maskedGemini = document.getElementById('masked-gemini');

        if (maskedData) maskedData.textContent = data.data_go_kr_api_key?.set ? `현재: ${data.data_go_kr_api_key.masked}` : '미설정';
        if (maskedNaver) maskedNaver.textContent = data.naver_client_id?.set ? `현재: ${data.naver_client_id.masked}` : '미설정';
        if (maskedOpenai) maskedOpenai.textContent = data.openai_api_key?.set ? `현재: ${data.openai_api_key.masked}` : '미설정';
        if (maskedGemini) maskedGemini.textContent = data.gemini_api_key?.set ? `현재: ${data.gemini_api_key.masked}` : '미설정';

        // LLM 엔진 선택 반영
        const engineSelect = document.getElementById('llm-engine-select');
        if (engineSelect && data.llm_engine?.masked) {
            engineSelect.value = data.llm_engine.masked;
        }

    } catch (e) {
        console.warn('API 키 로드 실패:', e.message);
    }
}

async function saveApiKeys() {
    const body = {};
    const dataKey = document.getElementById('api-key-data-go-kr')?.value?.trim();
    const naverId = document.getElementById('api-key-naver-id')?.value?.trim();
    const naverSecret = document.getElementById('api-key-naver-secret')?.value?.trim();
    const openaiKey = document.getElementById('api-key-openai')?.value?.trim();
    const geminiKey = document.getElementById('api-key-gemini')?.value?.trim();
    const llmEngine = document.getElementById('llm-engine-select')?.value;

    if (dataKey) body.data_go_kr_api_key = dataKey;
    if (naverId) body.naver_client_id = naverId;
    if (naverSecret) body.naver_client_secret = naverSecret;
    if (openaiKey) body.openai_api_key = openaiKey;
    if (geminiKey) body.gemini_api_key = geminiKey;
    if (llmEngine) body.llm_engine = llmEngine;

    if (Object.keys(body).length === 0) {
        showToast('변경할 API 키를 입력해주세요.', 'warning');
        return;
    }

    try {
        const result = await api('PUT', '/settings/api-keys', body);
        showToast(result.message || 'API 키가 저장되었습니다.', 'success');

        // 입력 필드 초기화
        if (dataKey) document.getElementById('api-key-data-go-kr').value = '';
        if (naverId) document.getElementById('api-key-naver-id').value = '';
        if (naverSecret) document.getElementById('api-key-naver-secret').value = '';
        if (openaiKey) document.getElementById('api-key-openai').value = '';
        if (geminiKey) document.getElementById('api-key-gemini').value = '';

        // 상태 갱신
        loadApiKeys();
    } catch (e) {
        showToast(`API 키 저장 실패: ${e.message}`, 'error');
    }
}

function toggleApiKeyVisibility(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
}

// 기존 renderApiStatus 호환 — loadSettings에서 호출됨
function renderApiStatus(status) {
    // 새 UI에서는 loadApiKeys()로 대체
    loadApiKeys();
}

function initSettingsTagInput(inputId, field) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const val = e.target.value.trim();
            if (val && !(settingsData[field] || []).includes(val)) {
                if (!settingsData[field]) settingsData[field] = [];
                settingsData[field].push(val);
                renderSettingsKeywords();
                saveKeywords(); // 자동 저장
            }
            e.target.value = '';
        }
    });
}

function removeSettingsTag(field, value) {
    settingsData[field] = (settingsData[field] || []).filter(v => v !== value);
    renderSettingsKeywords();
    saveKeywords(); // 자동 저장
}

async function saveKeywords() {
    try {
        await api('PUT', '/settings/keywords', {
            keywords: settingsData.keywords || [],
            exclude_keywords: settingsData.exclude_keywords || []
        });
        showToast('키워드가 저장되었습니다.', 'success');
    } catch (e) {
        showToast(`키워드 저장 실패: ${e.message}`, 'error');
    }
}

async function saveRelevance() {
    const slider = document.getElementById('relevance-slider');
    if (!slider) return;
    const score = parseInt(slider.value);
    try {
        await api('PUT', '/settings/relevance', { min_relevance_score: score });
        showToast(`관련도 설정이 ${score}점으로 저장되었습니다.`, 'success');
    } catch (e) {
        showToast(`설정 저장 실패: ${e.message}`, 'error');
    }
}


// ──────────────────────────────────────────────
// 18. 대시보드 차트
// ──────────────────────────────────────────────
async function loadCharts() {
    try {
        const data = await api('GET', '/dashboard/charts');
        renderDailyTrend(data.daily_trend || [], data.keyword_trends || {});
        renderOrgBudget(data.org_budget_top10 || []);
        renderKeywordDist(data.keyword_trends || {});
    } catch (e) {
        console.warn('차트 데이터 로드 실패:', e.message);
    }
}

const CHART_COLORS = [
    '#6366f1', '#06b6d4', '#10b981', '#f59e0b', '#ef4444',
    '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#84cc16',
];

function renderDailyTrend(totalData, keywordTrends) {
    const container = document.getElementById('daily-trend-chart');
    if (!container) return;

    if (!totalData.length) {
        container.innerHTML = renderEmptyState('📈', '데이터 없음', '공고를 수집하면 차트가 표시됩니다');
        return;
    }

    // 날짜 범위 계산 (최근 30일)
    const allDates = [];
    const today = new Date();
    for (let i = 29; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        allDates.push(d.toISOString().slice(0, 10));
    }

    // 전체 데이터를 날짜 맵으로
    const totalMap = {};
    totalData.forEach(d => { totalMap[d.date] = d.count; });
    const totalValues = allDates.map(d => totalMap[d] || 0);

    // 키워드별 데이터 맵
    const kwNames = Object.keys(keywordTrends);
    const kwDataSets = kwNames.map(kw => {
        const map = {};
        (keywordTrends[kw] || []).forEach(d => { map[d.date] = d.count; });
        return allDates.map(d => map[d] || 0);
    });

    // 최대값 계산
    const maxVal = Math.max(...totalValues, 1);

    // SVG 차트 크기
    const W = 780, H = 260, PAD_L = 45, PAD_R = 15, PAD_T = 15, PAD_B = 35;
    const chartW = W - PAD_L - PAD_R;
    const chartH = H - PAD_T - PAD_B;

    // 좌표 계산
    function toX(i) { return PAD_L + (i / (allDates.length - 1)) * chartW; }
    function toY(v) { return PAD_T + chartH - (v / maxVal) * chartH; }

    // 경로 생성 (smooth curve)
    function makePath(values) {
        if (!values.length) return '';
        const pts = values.map((v, i) => [toX(i), toY(v)]);
        let d = `M${pts[0][0]},${pts[0][1]}`;
        for (let i = 1; i < pts.length; i++) {
            const cpx = (pts[i-1][0] + pts[i][0]) / 2;
            d += ` C${cpx},${pts[i-1][1]} ${cpx},${pts[i][1]} ${pts[i][0]},${pts[i][1]}`;
        }
        return d;
    }

    // 영역 경로 (전체 공고용)
    function makeArea(values) {
        const path = makePath(values);
        if (!path) return '';
        const lastX = toX(values.length - 1);
        const firstX = toX(0);
        return path + ` L${lastX},${PAD_T + chartH} L${firstX},${PAD_T + chartH} Z`;
    }

    // Y축 눈금
    const yTicks = 5;
    let yGridSvg = '';
    let yLabelSvg = '';
    for (let i = 0; i <= yTicks; i++) {
        const val = Math.round((maxVal / yTicks) * i);
        const y = toY(val);
        yGridSvg += `<line x1="${PAD_L}" x2="${W - PAD_R}" y1="${y}" y2="${y}" stroke="rgba(148,163,184,0.12)" stroke-dasharray="3,3"/>`;
        yLabelSvg += `<text x="${PAD_L - 8}" y="${y + 4}" fill="#64748b" font-size="10" text-anchor="end">${val >= 1000 ? (val/1000).toFixed(1)+'k' : val}</text>`;
    }

    // X축 날짜 라벨 (5개만)
    let xLabelSvg = '';
    const labelStep = Math.ceil(allDates.length / 5);
    for (let i = 0; i < allDates.length; i += labelStep) {
        const x = toX(i);
        xLabelSvg += `<text x="${x}" y="${H - 5}" fill="#64748b" font-size="10" text-anchor="middle">${allDates[i].slice(5)}</text>`;
    }

    // 전체 공고 영역 + 라인
    const totalArea = makeArea(totalValues);
    const totalLine = makePath(totalValues);

    let svgContent = `
        <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" style="width:100%;height:auto;min-height:220px">
            <defs>
                <linearGradient id="totalGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="rgba(99,102,241,0.25)"/>
                    <stop offset="100%" stop-color="rgba(99,102,241,0.02)"/>
                </linearGradient>
            </defs>
            ${yGridSvg}
            ${yLabelSvg}
            ${xLabelSvg}
            <path d="${totalArea}" fill="url(#totalGrad)"/>
            <path d="${totalLine}" fill="none" stroke="#6366f1" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.7"/>
    `;

    // 키워드별 라인
    kwDataSets.forEach((values, idx) => {
        const hasData = values.some(v => v > 0);
        if (!hasData) return;
        const color = CHART_COLORS[(idx + 1) % CHART_COLORS.length];
        const path = makePath(values);
        svgContent += `<path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;

        // 데이터 포인트 (마지막 값)
        const lastVal = values[values.length - 1];
        if (lastVal > 0) {
            const lx = toX(values.length - 1);
            const ly = toY(lastVal);
            svgContent += `<circle cx="${lx}" cy="${ly}" r="3.5" fill="${color}" stroke="var(--text-primary, #0f172a)" stroke-width="1.5"/>`;
        }
    });

    // 전체 공고 포인트 (각 날짜)
    totalValues.forEach((v, i) => {
        if (v > 0) {
            svgContent += `<circle cx="${toX(i)}" cy="${toY(v)}" r="3" fill="var(--accent-indigo, #6366f1)" stroke="var(--text-primary, #0f172a)" stroke-width="1.5" opacity="0.8">
                <title>${allDates[i].slice(5)}: ${v}건</title>
            </circle>`;
        }
    });

    svgContent += '</svg>';

    // 범례
    let legendHtml = `<div class="chart-legend">
        <span class="legend-item"><span class="legend-dot" style="background:var(--accent-indigo, #6366f1)"></span> 전체 공고</span>`;
    kwNames.forEach((kw, idx) => {
        const hasData = kwDataSets[idx]?.some(v => v > 0);
        if (!hasData) return;
        const color = CHART_COLORS[(idx + 1) % CHART_COLORS.length];
        const total = kwDataSets[idx].reduce((a, b) => a + b, 0);
        legendHtml += `<span class="legend-item"><span class="legend-dot" style="background:${color}"></span> ${escapeHTML(kw)} (${total}건)</span>`;
    });
    legendHtml += '</div>';

    container.innerHTML = svgContent + legendHtml;
}

function renderOrgBudget(data) {
    const container = document.getElementById('org-budget-chart');
    if (!container) return;
    if (!data.length) {
        container.innerHTML = renderEmptyState('🏢', '데이터 없음', '공고를 수집하면 차트가 표시됩니다');
        return;
    }
    const maxBudget = Math.max(...data.map(d => d.total_budget), 1);
    container.innerHTML = data.map(d => {
        const width = (d.total_budget / maxBudget) * 100;
        const budgetStr = formatBudget(d.total_budget);
        const label = (d.org_name || '미지정').slice(0, 12);
        return `<div class="hbar-row">
            <span class="hbar-label" title="${escapeHTML(d.org_name)}">${escapeHTML(label)}</span>
            <div class="hbar-track">
                <div class="hbar-fill" style="width:${width}%">${budgetStr} (${d.bid_count}건)</div>
            </div>
        </div>`;
    }).join('');
}


// ──────────────────────────────────────────────
// 19. PDF 내보내기
// ──────────────────────────────────────────────
function exportPDF() {
    document.body.classList.add('print-active');
    window.addEventListener('afterprint', function onAfterPrint() {
        document.body.classList.remove('print-active');
        window.removeEventListener('afterprint', onAfterPrint);
    });
    window.print();
}


// ──────────────────────────────────────────────
// 20. 스케줄러 관리
// ──────────────────────────────────────────────

async function loadSchedulerStatus() {
    try {
        const status = await api('GET', '/scheduler/status');
        const dot = document.getElementById('scheduler-dot');
        const text = document.getElementById('scheduler-status-text');
        const nextRun = document.getElementById('scheduler-next-run');
        const lastRun = document.getElementById('scheduler-last-run');
        const toggleBtn = document.getElementById('scheduler-toggle-btn');
        const timeInput = document.getElementById('scheduler-time-input');

        if (!dot) return;

        if (status.is_running) {
            dot.className = 'status-dot active';
            text.textContent = '🟢 스케줄러 실행 중';
            toggleBtn.textContent = '⏹️ 중지';
            toggleBtn.onclick = () => stopScheduler();
        } else {
            dot.className = 'status-dot inactive';
            text.textContent = '⏸️ 스케줄러 중지됨';
            toggleBtn.textContent = '▶️ 시작';
            toggleBtn.onclick = () => startScheduler();
        }

        if (status.next_run_at) {
            const next = new Date(status.next_run_at);
            const now = new Date();
            const diffMs = next - now;
            let nextRunText;
            if (diffMs <= 0) {
                nextRunText = '곧 실행 예정';
            } else {
                const diffH = Math.floor(diffMs / 3600000);
                const diffM = Math.floor((diffMs % 3600000) / 60000);
                nextRunText = `${diffH}시간 ${diffM}분 후`;
            }
            nextRun.textContent = `다음 실행: ${next.toLocaleString('ko-KR')} (${nextRunText})`;
        } else {
            nextRun.textContent = '다음 실행: -';
        }

        if (status.last_run_at) {
            const last = new Date(status.last_run_at);
            lastRun.textContent = `최근 실행: ${last.toLocaleString('ko-KR')} (총 ${status.total_runs}회, 오류 ${status.total_errors}회)`;
        }

        if (status.schedule_time && timeInput) {
            timeInput.value = status.schedule_time;
        }
    } catch (e) {
        console.warn('스케줄러 상태 로드 실패:', e.message);
    }
}

async function updateScheduleTime() {
    const timeInput = document.getElementById('scheduler-time-input');
    if (!timeInput || !timeInput.value) return;
    const [h, m] = timeInput.value.split(':').map(Number);
    try {
        await api('PUT', '/scheduler/time', { hour: h, minute: m });
        showToast(`스케줄이 매일 ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}으로 변경되었습니다.`, 'success');
        loadSchedulerStatus();
    } catch (e) {
        showToast(`시각 변경 실패: ${e.message}`, 'error');
    }
}

async function startScheduler() {
    try {
        await api('POST', '/scheduler/start');
        showToast('스케줄러가 시작되었습니다.', 'success');
        loadSchedulerStatus();
    } catch (e) {
        showToast(`시작 실패: ${e.message}`, 'error');
    }
}

async function stopScheduler() {
    try {
        await api('POST', '/scheduler/stop');
        showToast('스케줄러가 중지되었습니다.', 'info');
        loadSchedulerStatus();
    } catch (e) {
        showToast(`중지 실패: ${e.message}`, 'error');
    }
}

// toggleScheduler 제거됨 — loadSchedulerStatus()에서 toggleBtn.onclick을 동적으로 설정

async function runScheduleNow() {
    // 중복 실행 방지
    if (state.isLoading) return;

    showLoading('즉시 실행 중...', '공고 수집 → 분석 → 알림 파이프라인 실행');
    try {
        updateLoadingText('🚀 파이프라인 실행 중...', '공고 수집 → 분석 → 알림 순서로 처리합니다');
        const result = await api('POST', '/scheduler/run-now');
        const r = result.result || {};

        updateLoadingText('✅ 실행 완료, 결과 정리 중...', `수집 ${r.collected || 0}건, 분석 ${r.analyzed || 0}건`);
        loadSchedulerStatus();
        if (state.currentView === 'dashboard') await loadDashboard();

        hideLoading();
        showToast(`즉시 실행 완료! 수집: ${r.collected || 0}건, 분석: ${r.analyzed || 0}건`, 'success');
    } catch (e) {
        hideLoading();
        showToast(`실행 실패: ${e.message}`, 'error');
    }
}


// ──────────────────────────────────────────────
// 21. Slack 관리
// ──────────────────────────────────────────────

async function saveSlackWebhook() {
    const input = document.getElementById('slack-webhook-input');
    if (!input || !input.value.trim()) {
        showToast('Webhook URL을 입력해주세요.', 'warning');
        return;
    }
    try {
        await api('PUT', '/settings/slack', { webhook_url: input.value.trim() });
        showToast('Slack 웹훅 URL이 저장되었습니다.', 'success');
    } catch (e) {
        showToast(`저장 실패: ${e.message}`, 'error');
    }
}

async function testSlack() {
    try {
        await api('POST', '/slack/test');
        showToast('Slack 테스트 메시지가 전송되었습니다! 채널을 확인하세요.', 'success');
    } catch (e) {
        showToast(`테스트 실패: ${e.message}`, 'error');
    }
}

// (스케줄러 상태 로드는 loadSettings 함수 내부에서 직접 호출)


// ──────────────────────────────────────────────
// 22. 오늘의 추천 사업 TOP 10
// ──────────────────────────────────────────────

async function loadTop10() {
    const list = document.getElementById('top10-list');
    if (!list) return;
    list.innerHTML = '<div class="skeleton skeleton-card" style="height:100px;margin-bottom:12px"></div>'.repeat(3);

    try {
        const data = await api('GET', '/dashboard/top10');
        renderTop10(data);
        renderBriefing(data);
    } catch (e) {
        console.warn('TOP 10 로드 실패:', e.message);
        list.innerHTML = '<div class="empty-state-inline"><span>⚠️</span><p>데이터를 불러올 수 없습니다.</p></div>';
        renderBriefing({});
    }
}

function renderTop10(data) {
    const list = document.getElementById('top10-list');
    const desc = document.getElementById('top10-desc');
    if (!list) return;

    const items = data?.top10 || [];
    const totalMatched = data?.total_matched || 0;
    const keywords = data?.keywords_used || [];

    if (desc) {
        desc.textContent = items.length > 0
            ? `전체 ${totalMatched}건 중 TOP ${items.length} · 키워드: ${keywords.join(', ')}`
            : (data?.message || '매칭 없음');
    }

    if (!items.length) {
        list.innerHTML = `<div class="empty-state-inline"><span>🔍</span><p>${escapeHTML(data?.message || '공고를 수집하면 순위가 표시됩니다.')}</p></div>`;
        return;
    }

    list.innerHTML = items.map((item, i) => {
        const rank = i + 1;
        const gradeMap = { A: { cls: 'grade-a', label: 'A 적극 추천' }, B: { cls: 'grade-b', label: 'B 검토 추천' }, C: { cls: 'grade-c', label: 'C 참고' } };
        const grade = gradeMap[item.grade] || gradeMap['C'];
        const budget = displayBudget(item.budget);
        const daysLeft = item.days_left !== null && item.days_left < 999
            ? (item.days_left <= 0 ? '⏰ 마감' : item.days_left <= 3 ? `🔴 D-${item.days_left}` : `D-${item.days_left}`)
            : '';
        const closeDt = item.bid_close_dt ? item.bid_close_dt.substring(0, 10) : '';
        const reqs = (item.requirements || []).join(' · ');
        const kwChips = (item.matched_keywords || []).map(k => `<span class="kw-chip">${escapeHTML(k)}</span>`).join('');

        return `<div class="top10-card ${grade.cls}" style="animation-delay:${i * 0.05}s" data-bid-no="${escapeHTML(item.bid_ntce_no || '')}" data-title="${escapeHTML(item.title || '')}" data-org-name="${escapeHTML(item.org_name || '')}" data-budget="${item.budget || ''}" data-close-dt="${escapeHTML(item.bid_close_dt || '')}">
            <div class="top10-rank">${rank}</div>
            <div class="top10-body">
                <div class="top10-header">
                    <span class="top10-title">${escapeHTML(item.title || '제목 없음')}</span>
                    <span class="top10-grade ${grade.cls}">${grade.label}</span>
                </div>
                <div class="top10-meta">
                    <span>🏢 ${escapeHTML(item.org_name || '-')}</span>
                    <span>💰 ${budget}</span>
                    ${closeDt ? `<span>📅 ${closeDt} ${daysLeft}</span>` : ''}
                </div>
                ${reqs ? `<div class="top10-reqs">${reqs}</div>` : ''}
                <div class="top10-footer">
                    <div class="top10-scores">
                        <span title="종합 점수">⭐ ${item.total_score}점</span>
                        ${item.matched_business ? `<span title="매칭 사업자">🏢 ${escapeHTML(item.matched_business)}</span>` : ''}
                    </div>
                    <div style="display:flex;align-items:center;gap:6px">
                        <div class="top10-keywords">${kwChips}</div>
                        <button class="btn-mini-fav ${isFavorite(item.bid_ntce_no) ? 'active' : ''}"
                            onclick="event.stopPropagation(); toggleFavFromBid('${escapeHTML(item.bid_ntce_no)}', '${escapeHTML((item.title||'').replace(/'/g,''))}', '${escapeHTML((item.org_name||'').replace(/'/g,''))}', '${item.budget||''}', '${escapeHTML(item.bid_close_dt||'')}', this); this.textContent=this.classList.contains('active')?'⭐':'☆'"
                            title="관심공고">${isFavorite(item.bid_ntce_no) ? '⭐' : '☆'}</button>
                        <button class="btn-mini-analyze btn-strategy-analyze" data-bid-no="${escapeHTML(item.bid_ntce_no)}" title="AI 전략 분석">🎯</button>
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');
}

// renderKeywordDist는 loadCharts()에서 keyword_trends로 호출됨 (파일 하단에 정의)


// ──────────────────────────────────────────────
// 22-B. 오늘의 추천 공고 브리핑 (사업자 맞춤)
// ──────────────────────────────────────────────
function renderBriefing(data) {
    const body = document.getElementById('briefing-body');
    const badge = document.getElementById('briefing-badge');
    if (!body) return;

    const items = data?.top10 || [];

    // 마감되지 않은 공고만 (D-day 1일 이상)
    const viable = items.filter(item => item.days_left > 0 || item.days_left === 999);

    if (!viable.length) {
        if (badge) badge.textContent = '공고 없음';
        body.innerHTML = `<div class="briefing-empty">
            <span>📭</span>
            <p>참여 가능한 추천 공고가 없습니다</p>
            <small>공고를 수집하면 사업자 프로필에 맞는 공고를 추천합니다</small>
        </div>`;
        return;
    }

    const top = viable.slice(0, 10);
    if (badge) badge.textContent = `${top.length}건 추천`;

    body.innerHTML = top.map((item, i) => {
        const grade = item.grade || 'C';
        const gradeLabel = grade === 'A' ? '적극추천' : grade === 'B' ? '검토추천' : '참고';
        const daysText = item.days_left === 999 ? '마감미정' : `D-${item.days_left}`;
        const daysClass = item.days_left <= 3 ? 'urgent' : item.days_left <= 7 ? 'soon' : 'safe';
        const budgetText = displayBudget(item.budget);
        const naraUrl = getNaraDetailUrl(item.bid_ntce_no);

        // 자격요건 칩
        const qualChips = [];
        if (item.license_limit) qualChips.push(`<span class="briefing-qual critical">⚠️ ${escapeHTML(item.license_limit.substring(0, 20))}</span>`);
        if (item.region) qualChips.push(`<span class="briefing-qual region">📍 ${escapeHTML(item.region)}</span>`);
        if (item.contract_method) qualChips.push(`<span class="briefing-qual method">📝 ${escapeHTML(item.contract_method)}</span>`);

        return `<div class="briefing-item" data-bid-no="${escapeHTML(item.bid_ntce_no || '')}" data-title="${escapeHTML(item.title || '')}" data-org-name="${escapeHTML(item.org_name || '')}" data-budget="${item.budget || ''}" data-close-dt="${escapeHTML(item.bid_close_dt || '')}">
            <div class="briefing-rank grade-${grade.toLowerCase()}">${i + 1}</div>
            <div class="briefing-content">
                <div class="briefing-item-header">
                    <span class="briefing-item-title">${escapeHTML(item.title)}</span>
                    <div style="display:flex;gap:4px;align-items:center;flex-shrink:0">
                        <span class="briefing-grade grade-${grade.toLowerCase()}">${gradeLabel}</span>
                        <span class="briefing-days ${daysClass}">${daysText}</span>
                        <button class="btn-mini-fav ${isFavorite(item.bid_ntce_no) ? 'active' : ''}"
                            onclick="event.stopPropagation(); toggleFavFromBid('${escapeHTML(item.bid_ntce_no)}', '${escapeHTML((item.title||'').replace(/'/g,''))}', '${escapeHTML((item.org_name||'').replace(/'/g,''))}', '${item.budget||''}', '${escapeHTML(item.bid_close_dt||'')}', this); this.textContent=this.classList.contains('active')?'⭐':'☆'"
                            title="관심공고">${isFavorite(item.bid_ntce_no) ? '⭐' : '☆'}</button>
                        <button class="btn-mini-analyze btn-strategy-analyze" data-bid-no="${escapeHTML(item.bid_ntce_no)}" onclick="event.stopPropagation()" title="AI 전략 분석">🎯</button>
                    </div>
                </div>
                <div class="briefing-item-meta">
                    🏢 ${escapeHTML(item.org_name || '기관 미상')} · 💰 ${budgetText}
                </div>
                ${item.matched_business ? `<div class="briefing-match-reason">✅ ${escapeHTML(item.matched_business)}와 매칭 (${item.total_score}점)</div>` : ''}
                ${qualChips.length ? `<div class="briefing-qual-row">${qualChips.join('')}</div>` : ''}
                ${(item.matched_keywords||[]).length ? `<div class="briefing-item-kw">🏷️ ${(item.matched_keywords||[]).join(', ')}</div>` : ''}
            </div>
        </div>`;
    }).join('');
}


// ──────────────────────────────────────────────
// 23. 전략 분석 모달
// ──────────────────────────────────────────────
// ── 전략 분석 결과 공유 ──
function shareStrategyResult() {
    const panels = ['overview', 'competitor', 'strategy', 'proposal'];
    const labels = ['📊 종합 분석', '🏢 경쟁사 분석', '🎯 입찰 전략', '📝 제안서 가이드'];
    const title = document.getElementById('strategy-modal-title')?.textContent || '';
    const lines = [`🔍 AI 전략 분석 결과 — ${title}`, `📅 ${new Date().toLocaleDateString('ko-KR')}`, ''];

    panels.forEach((p, i) => {
        const el = document.getElementById(`stab-${p}-content`);
        if (el && el.textContent.trim() !== '분석 중...') {
            lines.push(`${labels[i]}`);
            lines.push(el.textContent.trim().substring(0, 500));
            lines.push('');
        }
    });

    navigator.clipboard.writeText(lines.join('\n')).then(() => {
        showToast('분석 결과가 클립보드에 복사되었습니다!', 'success');
    }).catch(() => showToast('복사 실패', 'error'));
}

// 전략 분석에서 바로 입찰 준비하기
function prepareBidFromStrategy() {
    const overlay = document.getElementById('strategy-modal-overlay');
    const bidNo = overlay?.dataset?.bidNo || '';
    if (bidNo) {
        // 모달 닫기
        overlay.classList.remove('active');
        // 공고 제목 가져오기
        const titleEl = document.getElementById('strategy-modal-title');
        const bidTitle = titleEl?.textContent?.replace(/^🤖\s*/, '').replace(/AI 전략 분석.*/, '').trim() || '';
        prepareBid(bidNo, bidTitle, '', '', '');
    }
}

// 과거 협업사 추천
function suggestPartners(bidNo) {
    const allFavs = getFavorites();
    const partnerCounts = {};

    allFavs.forEach(f => {
        if (f.bid_ntce_no === bidNo) return;
        if (f.status !== 'completed' && f.status !== 'partnered') return;
        (f.partners || []).forEach(p => {
            const name = typeof p === 'string' ? p : p.name || '';
            if (!name) return;
            if (!partnerCounts[name]) {
                partnerCounts[name] = { count: 0, role: (typeof p === 'object' ? p.role : '') || '', contact: (typeof p === 'object' ? p.contact : '') || '' };
            }
            partnerCounts[name].count++;
        });
    });

    return Object.entries(partnerCounts)
        .sort((a, b) => b[1].count - a[1].count)
        .slice(0, 5)
        .map(([name, info]) => ({ name, count: info.count, role: info.role, contact: info.contact }));
}

async function openStrategyModal(bidNo) {
    // 이미 전략 분석 모달이 열려있고 로딩 중이면 중복 방지
    const overlay = document.getElementById('strategy-modal-overlay');
    if (overlay.classList.contains('active') && overlay.dataset.loading === 'true') return;

    const title = document.getElementById('strategy-modal-title');
    const subtitle = document.getElementById('strategy-modal-subtitle');

    // 모달 열기 + 로딩 플래그 설정
    overlay.classList.add('active');
    overlay.dataset.loading = 'true';
    overlay.dataset.bidNo = bidNo;
    title.textContent = '🤖 AI 전략 분석 중...';
    subtitle.textContent = `공고번호: ${bidNo} — 분석 요청을 처리하고 있습니다`;

    // 나라장터 링크 설정
    const naraLink = document.getElementById('strategy-nara-link');
    if (naraLink) naraLink.href = getNaraDetailUrl(bidNo);

    // 탭 초기화
    ['stab-summary-content', 'stab-past-content', 'stab-competitor-content', 'stab-strategy-content', 'stab-proposal-content'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '<p style="color:var(--text-muted)">⏳ 분석 중...</p>';
    });
    const diffEl = document.getElementById('stab-diff-content');
    if (diffEl) diffEl.innerHTML = '<p style="color:var(--text-muted)">📊 RFP 변경점 로딩 중...</p>';

    // 첫 번째 탭 활성화
    document.querySelectorAll('.strategy-modal-tab').forEach((t, i) => t.classList.toggle('active', i === 0));
    document.querySelectorAll('.strategy-panel').forEach((p, i) => p.classList.toggle('active', i === 0));

    // 전략 분석 API 호출
    try {
        subtitle.textContent = `공고번호: ${bidNo} — 🔍 공고 정보 조회 및 AI 분석 요청 중...`;
        const result = await api('POST', '/analyze-strategy', { bid_ntce_no: bidNo });
        const s = result.strategy || result;

        title.textContent = escapeHTML(s.bid_info?.title || result.bid_title || '전략 분석 완료');
        subtitle.textContent = `🏢 ${escapeHTML(s.bid_info?.org_name || result.org_name || '')} · 💰 ${formatBudget(s.bid_info?.budget || result.budget || 0)}`;

        // 분석 엔진 배지
        const engine = s.metadata?.analysis_engine || '';
        const engineBadge = engine.includes('+search')
            ? '<span class="kw-chip" style="background:var(--accent-gradient);color:#fff;margin-left:8px">🌐 웹 검색 포함</span>'
            : engine !== 'fallback' && engine
                ? `<span class="kw-chip" style="margin-left:8px">🤖 ${escapeHTML(engine)}</span>`
                : '';

        // 데이터 소스 현황
        const ds = s.metadata?.data_sources || {};
        let sourceInfo = '';
        if (ds.past_awards_count > 0 || ds.news_articles_count > 0) {
            sourceInfo = `<div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">`;
            if (ds.past_awards_count > 0) sourceInfo += `<span class="kw-chip">📋 과거 낙찰 ${ds.past_awards_count}건</span>`;
            if (ds.news_articles_count > 0) sourceInfo += `<span class="kw-chip">📰 관련 뉴스 ${ds.news_articles_count}건</span>`;
            if (ds.rfp_available) sourceInfo += `<span class="kw-chip">📄 RFP 분석</span>`;
            if (ds.business_profile_available) sourceInfo += `<span class="kw-chip">🏢 사업자 매칭</span>`;
            sourceInfo += `</div>`;
        }

        // 사업요약 탭
        const summaryEl = document.getElementById('stab-summary-content');
        if (summaryEl) {
            summaryEl.innerHTML = engineBadge + sourceInfo + formatStrategyText(s.bid_summary || s.summary || '요약 정보 없음');
        }

        // 📊 과거 수행사 · KPI 탭
        const pastEl = document.getElementById('stab-past-content');
        if (pastEl) {
            let pastHtml = '';

            // 과거 수행사 분석
            if (s.past_project_analysis) {
                pastHtml += '<h4 style="color:var(--text-primary);margin:0 0 12px">📋 작년 수행사 분석</h4>';
                pastHtml += formatStrategyText(s.past_project_analysis);
            }

            // 올해 차별화 포인트
            if (s.year_over_year_improvement) {
                pastHtml += '<h4 style="color:var(--text-primary);margin:20px 0 12px">🎯 올해 차별화 포인트 (작년 대비)</h4>';
                pastHtml += formatStrategyText(s.year_over_year_improvement);
            }

            // 발주처 정책 동향
            if (s.org_policy_insight) {
                pastHtml += '<h4 style="color:var(--text-primary);margin:20px 0 12px">🏛️ 발주처 정책 동향</h4>';
                pastHtml += formatStrategyText(s.org_policy_insight);
            }

            if (!pastHtml) {
                pastHtml = '<div class="empty-state-inline"><span>📊</span><p>과거 수행사 정보가 수집되지 않았습니다.<br>공공데이터포털 API 키를 설정하면 자동으로 수집됩니다.</p></div>';
            }
            pastEl.innerHTML = pastHtml;
        }

        // 경쟁사 탭
        const competitorEl = document.getElementById('stab-competitor-content');
        if (competitorEl) competitorEl.innerHTML = formatStrategyText(s.competitor_analysis || s.competitors || '경쟁사 분석 정보 없음');

        // 전략 탭: 차별화 전략
        let strategyHtml = formatStrategyText(s.differentiation_strategy || s.strategy || '전략 정보 없음');
        if (s.risk_factors) {
            strategyHtml += `<h4 style="color:var(--text-primary);margin-top:20px">⚠️ 리스크 요소</h4>` + formatStrategyText(s.risk_factors);
        }
        if (s.budget_analysis) {
            strategyHtml += `<h4 style="color:var(--text-primary);margin-top:20px">💰 예산 분석</h4>` + formatStrategyText(s.budget_analysis);
        }
        const strategyEl = document.getElementById('stab-strategy-content');
        if (strategyEl) strategyEl.innerHTML = strategyHtml;

        // 제안서 기획 탭
        let proposalHtml = formatStrategyText(s.proposal_outline || '제안서 기획 정보 없음');
        if (s.action_items && Array.isArray(s.action_items)) {
            proposalHtml += `<h4 style="color:var(--text-primary);margin-top:20px">✅ 체크리스트</h4><ul style="color:var(--text-secondary);padding-left:20px">`;
            proposalHtml += s.action_items.map(a => `<li>${escapeHTML(typeof a === 'string' ? a : JSON.stringify(a))}</li>`).join('');
            proposalHtml += '</ul>';
        }
        if (s.overall_recommendation) {
            proposalHtml += `<h4 style="color:var(--text-primary);margin-top:20px">🎯 종합 권고</h4>` + formatStrategyText(s.overall_recommendation);
        }
        const proposalEl = document.getElementById('stab-proposal-content');
        if (proposalEl) proposalEl.innerHTML = proposalHtml;

        // 관심공고에 분석 결과 자동 반영
        if (isFavorite(bidNo)) {
            const summaryText = (s.bid_summary || s.summary || '').substring(0, 300);
            updateFav(bidNo, {
                analysis_done: true,
                analysis_summary: summaryText,
                title: s.bid_info?.title || result.bid_title || undefined,
                org_name: s.bid_info?.org_name || result.org_name || undefined,
            });
        }

    } catch (e) {
        title.textContent = '⚠️ 분석 실패';
        const errorMsg = `<p style="color:var(--danger);padding:20px;text-align:center">⚠️ ${escapeHTML(e.message || '분석에 실패했습니다')}<br><button class="btn btn-sm btn-primary" onclick="openStrategyModal('${bidNo}')" style="margin-top:12px">🔄 다시 시도</button></p>`;
        ['stab-summary-content', 'stab-past-content', 'stab-competitor-content', 'stab-strategy-content', 'stab-proposal-content'].forEach(id => {
            const el = document.getElementById(id);
            if (el && el.innerHTML.includes('⏳')) el.innerHTML = errorMsg;
        });
    } finally {
        // 로딩 플래그 해제
        overlay.dataset.loading = 'false';
    }

    // RFP Diff 비동기 로드
    loadRfpDiff(bidNo);
}

function formatStrategyText(text) {
    if (!text) return '';
    if (typeof text !== 'string') text = JSON.stringify(text, null, 2);

    // 1. 먼저 모든 HTML을 이스케이프 (XSS 방지 — 화이트리스트 방식)
    let safe = escapeHTML(text);

    // 2. 이스케이프된 텍스트에서 안전한 마크다운 패턴만 복원
    safe = safe
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/^### (.+)$/gm, '<h4>$1</h4>')
        .replace(/^## (.+)$/gm, '<h3>$1</h3>')
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        .replace(/\n/g, '<br>');

    // 3. 연속된 <li> 항목을 <ul>로 감싸기
    safe = safe.replace(/(<li>.*?<\/li>(?:<br>)?)+/gs, (match) => {
        return '<ul>' + match.replace(/<br>/g, '') + '</ul>';
    });

    return `<div class="strategy-text">${safe}</div>`;
}

async function loadRfpDiff(bidNo) {
    const container = document.getElementById('stab-diff-content');
    if (!container) return;
    try {
        const data = await api('GET', `/bids/${encodeURIComponent(bidNo)}/diff`);
        if (!data.diff || !data.past_bid) {
            container.innerHTML = `<div class="empty-state-inline"><span>📊</span><p>${escapeHTML(data.message || '유사한 과거 공고를 찾을 수 없습니다.')}</p></div>`;
            return;
        }

        // Diff 통계
        let html = `<div class="diff-summary">
            <div class="diff-stat similarity"><div class="diff-stat-value">${(data.similarity * 100).toFixed(0)}%</div><div class="diff-stat-label">유사도</div></div>
            <div class="diff-stat added-stat"><div class="diff-stat-value">+${data.diff.added_count || 0}</div><div class="diff-stat-label">추가됨</div></div>
            <div class="diff-stat removed-stat"><div class="diff-stat-value">-${data.diff.removed_count || 0}</div><div class="diff-stat-label">삭제됨</div></div>
        </div>`;

        // 과거 공고 정보
        html += `<p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:12px">📋 비교 대상: <strong style="color:var(--text-primary)">${escapeHTML(data.past_bid.title || '')}</strong></p>`;

        // Diff 뷰어
        if (data.key_changes && data.key_changes.length) {
            html += '<div class="diff-viewer">';
            data.key_changes.forEach(c => {
                const cls = c.type === 'added' ? 'added' : c.type === 'removed' ? 'removed' : 'context';
                const prefix = c.type === 'added' ? '+ ' : c.type === 'removed' ? '- ' : '  ';
                html += `<div class="diff-line ${cls}">${prefix}${escapeHTML(c.content)}</div>`;
            });
            html += '</div>';
        }

        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div class="empty-state-inline"><span>📊</span><p>변경점 분석 실패: ${escapeHTML(e.message)}</p></div>`;
    }
}

function switchStrategyTab(tabEl, contentId) {
    document.querySelectorAll('.strategy-modal-tab').forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.strategy-panel').forEach(p => p.classList.remove('active'));
    tabEl.classList.add('active');
    tabEl.setAttribute('aria-selected', 'true');
    const content = document.getElementById(contentId);
    if (content) content.classList.add('active');
}

function closeStrategyModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const overlay = document.getElementById('strategy-modal-overlay');
    if (overlay) overlay.classList.remove('active');
}



// (TOP 10 로드는 loadDashboard 함수 내부에서 직접 호출)


// ──────────────────────────────────────────────
// 24. 사업자 문서 업로드 & AI 자동 파싱
// ──────────────────────────────────────────────

function handleDragOver(e) {
    e.preventDefault();
    e.currentTarget.classList.add('drag-over');
}

function handleDragLeave(e) {
    e.currentTarget.classList.remove('drag-over');
}

function handleFileDrop(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('drag-over');
    const files = e.dataTransfer.files;
    if (files.length > 0) uploadBusinessDocs(files);
}

function handleFileSelect(e) {
    const files = e.target.files;
    if (files.length > 0) uploadBusinessDocs(files);
}

async function uploadBusinessDocs(fileList) {
    const statusEl = document.getElementById('doc-upload-status');
    const statusText = document.getElementById('doc-upload-text');
    const resultEl = document.getElementById('doc-upload-result');
    const areaEl = document.getElementById('doc-upload-area');

    // 상태 표시
    statusEl.style.display = 'flex';
    resultEl.style.display = 'none';
    statusText.textContent = `📄 ${fileList.length}개 파일 분석 중...`;

    try {
        let result;

        if (fileList.length === 1) {
            // 단일 파일
            const formData = new FormData();
            formData.append('file', fileList[0]);

            const response = await fetch('/api/businesses/parse-doc', {
                method: 'POST',
                body: formData,
            });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || '파싱 실패');
            }
            result = await response.json();
        } else {
            // 복수 파일
            const formData = new FormData();
            for (const f of fileList) {
                formData.append('files', f);
            }

            const response = await fetch('/api/businesses/parse-docs', {
                method: 'POST',
                body: formData,
            });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || '파싱 실패');
            }
            result = await response.json();
        }

        // 폼 자동 채우기
        fillFormFromParsedDoc(result);

        // 결과 표시
        statusEl.style.display = 'none';
        resultEl.style.display = 'block';

        const confLabel = result.confidence === 'high' ? '✅ 높음' : result.confidence === 'medium' ? '⚠️ 보통' : '❓ 낮음';
        const confClass = result.confidence === 'low' ? ' low-confidence' : '';

        let chips = [];
        if (result.biz_id) chips.push(`사업자번호: ${result.biz_id}`);
        if (result.company_name) chips.push(`회사명: ${result.company_name}`);
        if (result.ceo_name) chips.push(`대표: ${result.ceo_name}`);
        if (result.business_types?.length) chips.push(`업종 ${result.business_types.length}건`);
        if (result.annual_revenue) chips.push(`매출: ${formatBudget(result.annual_revenue)}`);

        resultEl.className = `doc-upload-result${confClass}`;
        resultEl.innerHTML = `
            <div class="result-title">${confLabel} AI 자동 추출 완료</div>
            <div class="result-items">
                ${chips.map(c => `<span class="result-chip">${escapeHTML(c)}</span>`).join('')}
            </div>
        `;

        showToast('📄 문서에서 사업자 정보를 추출하여 폼에 입력했습니다.', 'success');

    } catch (e) {
        statusEl.style.display = 'none';
        resultEl.style.display = 'block';
        resultEl.className = 'doc-upload-result low-confidence';
        resultEl.innerHTML = `<div class="result-title">❌ 파싱 실패: ${escapeHTML(e.message)}</div>`;
        showToast('문서 파싱에 실패했습니다.', 'error');
    }
}

function fillFormFromParsedDoc(data) {
    // 기본 필드 (null 체크 포함)
    if (data.biz_id) {
        const el = document.getElementById('form-biz-id');
        if (el) el.value = data.biz_id;
    }
    if (data.company_name) {
        const el = document.getElementById('form-company-name');
        if (el) el.value = data.company_name;
    }
    if (data.ceo_name) {
        const el = document.getElementById('form-ceo-name');
        if (el) el.value = data.ceo_name;
    }
    if (data.annual_revenue) {
        const el = document.getElementById('form-annual-revenue');
        if (el) el.value = data.annual_revenue;
    }
    if (data.employee_count) {
        const el = document.getElementById('form-employee-count');
        if (el) el.value = data.employee_count;
    }

    // 태그 필드들
    if (data.business_types?.length) {
        addTagsFromArray('biz-types', data.business_types);
    }
    if (data.regions?.length) {
        addTagsFromArray('regions', data.regions);
    }
    if (data.keywords?.length) {
        addTagsFromArray('keywords', data.keywords);
    }
    if (data.licenses?.length) {
        addTagsFromArray('licenses', data.licenses);
    }
}

function addTagsFromArray(tagType, values) {
    // 기존 태그 데이터에 접근 (state.tagData 전역 변수 활용)
    if (!state.tagData[tagType]) state.tagData[tagType] = [];

    for (const val of values) {
        const trimmed = val.trim();
        if (!trimmed) continue;
        // 중복 방지
        if (state.tagData[tagType].includes(trimmed)) continue;
        state.tagData[tagType].push(trimmed);
    }

    // 기존 renderTags로 일괄 렌더링
    renderTags(tagType);
}


// ──────────────────────────────────────────────
// 대시보드 관심 키워드 검색 패널
// ──────────────────────────────────────────────
let _kspResults = [];  // 검색된 공고 원본
let _kspActiveKeyword = null;

async function loadKeywordSearchPanel() {
    const container = document.getElementById('ksp-keywords');
    if (!container) return;

    try {
        const settings = await api('GET', '/settings/full');
        const keywords = settings?.keywords || [];
        const excludeKeywords = settings?.exclude_keywords || [];

        if (keywords.length === 0) {
            container.innerHTML = `
                <div style="color:var(--text-muted);font-size:0.85rem;padding:8px 0">
                    ⚙️ 설정에서 관심 키워드를 등록하면 여기에 표시됩니다.
                    <a onclick="navigate('settings')" style="color:var(--accent-indigo, #6366f1);cursor:pointer;font-weight:600">설정 바로가기 →</a>
                </div>`;
            return;
        }

        // 키워드 칩 렌더링
        container.innerHTML = keywords.map(kw => `
            <button class="ksp-chip" data-keyword="${escapeHTML(kw)}" onclick="kspClickKeyword(this, '${escapeHTML(kw)}')">
                🏷️ ${escapeHTML(kw)}
            </button>
        `).join('');

        // 제외 키워드가 있으면 표시
        if (excludeKeywords.length > 0) {
            container.innerHTML += `
                <span style="color:var(--text-muted);font-size:0.75rem;padding:8px 4px;opacity:0.6">
                    🚫 제외: ${excludeKeywords.map(k => escapeHTML(k)).join(', ')}
                </span>`;
        }

        // 검색 입력 Enter 이벤트
        const input = document.getElementById('ksp-search-input');
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    dashboardKeywordSearch();
                }
            });
        }

    } catch (err) {
        console.warn('키워드 패널 로드 실패:', err.message);
    }
}

async function kspClickKeyword(chipEl, keyword) {
    // 칩 활성화 토글
    document.querySelectorAll('.ksp-chip').forEach(c => c.classList.remove('active'));
    chipEl.classList.add('active');
    _kspActiveKeyword = keyword;

    // 검색 입력에 키워드 반영
    const input = document.getElementById('ksp-search-input');
    if (input) input.value = keyword;

    // 수집 & 검색 실행
    await _kspCollectAndSearch(keyword);
}

async function dashboardKeywordSearch() {
    const input = document.getElementById('ksp-search-input');
    const keyword = input?.value?.trim();
    if (!keyword) {
        showToast('검색할 키워드를 입력해주세요.', 'warning');
        return;
    }

    // 칩 활성화 (있으면)
    document.querySelectorAll('.ksp-chip').forEach(c => {
        c.classList.toggle('active', c.dataset.keyword === keyword);
    });
    _kspActiveKeyword = keyword;

    await _kspCollectAndSearch(keyword);
}

async function _kspCollectAndSearch(keyword) {
    const resultsEl = document.getElementById('ksp-results');
    const subFilterEl = document.getElementById('ksp-sub-filter');

    // 로딩 표시
    resultsEl.style.display = 'block';
    resultsEl.innerHTML = `
        <div class="ksp-no-result">
            <div class="doc-upload-spinner" style="margin:0 auto 12px"></div>
            🔍 '${escapeHTML(keyword)}' 키워드로 나라장터 검색 중...
        </div>`;
    subFilterEl.style.display = 'none';

    try {
        // 1) 나라장터에서 수집
        const collectResult = await api('POST', '/bids/collect', { keyword });
        const collected = collectResult?.collected || 0;
        const saved = collectResult?.saved || 0;

        // 2) DB에서 해당 키워드로 검색
        const bids = await api('GET', `/bids?keyword=${encodeURIComponent(keyword)}&limit=100`);
        _kspResults = bids || [];

        // 3) 결과 렌더링
        _renderKspResults(_kspResults, keyword, collected, saved);

        // 4) 세부 필터 표시
        if (_kspResults.length > 0) {
            subFilterEl.style.display = 'block';
            document.getElementById('ksp-result-count').textContent = `${_kspResults.length}건`;
            document.getElementById('ksp-sub-search').value = '';
        }

    } catch (err) {
        resultsEl.innerHTML = `<div class="ksp-no-result">❌ 검색 실패: ${escapeHTML(err.message)}</div>`;
    }
}

function _renderKspResults(bids, keyword, collected, saved) {
    const resultsEl = document.getElementById('ksp-results');

    if (!bids || bids.length === 0) {
        resultsEl.innerHTML = `
            <div class="ksp-no-result">
                📭 '${escapeHTML(keyword)}' 관련 공고가 없습니다.
                <br><small style="color:var(--text-muted)">${collected || 0}건 수집, ${saved || 0}건 신규 저장</small>
            </div>`;
        return;
    }

    let header = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding:0 4px">
            <span style="font-size:0.85rem;color:var(--text-muted)">
                🔍 <strong style="color:var(--text-primary)">${escapeHTML(keyword)}</strong> 검색 결과
                ${collected ? ` · 수집 ${collected}건, 신규 ${saved}건` : ''}
            </span>
            <button class="btn btn-ghost btn-sm" onclick="kspGoToBids('${escapeHTML(keyword)}')">
                📋 공고 목록에서 보기 →
            </button>
        </div>`;

    const cards = bids.slice(0, 30).map(b => {
        const title = b.title || b.bid_ntce_no || '제목 없음';
        const org = b.org_name || '-';
        const budget = displayBudget(b.budget);
        const daysLeftText = formatDaysLeft(b.bid_close_dt);
        const daysLeft = getDaysLeft(b.bid_close_dt);
        let badgeClass = 'unknown';
        if (daysLeft !== null) {
            if (daysLeft < 0) badgeClass = 'closed';
            else if (daysLeft <= 3) badgeClass = 'urgent';
            else badgeClass = 'active';
        }
        const isExpired = badgeClass === 'closed';
        const naraUrl = getNaraDetailUrl(b.bid_ntce_no, b.bid_ntce_ord);

        // 자격요건 칩 생성
        const qualChips = [];
        if (b.license_limit) qualChips.push(`<span class="ksp-qual-chip critical">⚠️ ${escapeHTML(b.license_limit.substring(0, 30))}</span>`);
        if (b.region) qualChips.push(`<span class="ksp-qual-chip region">📍 ${escapeHTML(b.region)}</span>`);
        if (b.contract_method) qualChips.push(`<span class="ksp-qual-chip method">📝 ${escapeHTML(b.contract_method)}</span>`);
        if (b.bid_method) qualChips.push(`<span class="ksp-qual-chip method">🏷️ ${escapeHTML(b.bid_method)}</span>`);

        return `
            <div class="ksp-result-card ${isExpired ? 'ksp-expired' : ''}" data-bid-no="${escapeHTML(b.bid_ntce_no || '')}" data-title="${escapeHTML(title)}" data-org-name="${escapeHTML(org)}" data-budget="${b.budget || ''}" data-close-dt="${escapeHTML(b.bid_close_dt || '')}">
                <div class="ksp-result-info">
                    <div class="ksp-result-title">
                        <span class="bid-status-badge ${badgeClass}" style="flex-shrink:0">${daysLeftText}</span>
                        ${escapeHTML(title)}
                    </div>
                    <div class="ksp-result-meta">
                        🏢 ${escapeHTML(org)} · 💰 ${budget}
                    </div>
                    ${qualChips.length ? `<div class="ksp-qual-chips">${qualChips.join('')}</div>` : ''}
                </div>
                <div style="display:flex;gap:6px;flex-shrink:0;align-items:center">
                    <button class="btn-mini-fav ${isFavorite(b.bid_ntce_no) ? 'active' : ''}"
                        onclick="event.stopPropagation(); toggleFavFromBid('${escapeHTML(b.bid_ntce_no)}', '${escapeHTML((title||'').replace(/'/g,''))}', '${escapeHTML((org||'').replace(/'/g,''))}', '${b.budget||''}', '${escapeHTML(b.bid_close_dt||'')}', this); this.textContent=this.classList.contains('active')?'⭐':'☆'"
                        title="관심공고">${isFavorite(b.bid_ntce_no) ? '⭐' : '☆'}</button>
                    ${isExpired ? '' : `<button class="btn btn-sm btn-prepare"
                        onclick="event.stopPropagation(); prepareBid('${escapeHTML(b.bid_ntce_no)}', '${escapeHTML((title||'').replace(/'/g,''))}', '${escapeHTML((org||'').replace(/'/g,''))}', '${b.budget||''}', '${escapeHTML(b.bid_close_dt||'')}')" title="입찰준비">📋 입찰준비</button>`}
                    <a href="${escapeHTML(naraUrl)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-nara" onclick="event.stopPropagation()" title="나라장터">🔗</a>
                    <button class="btn-mini-analyze btn-strategy-analyze" data-bid-no="${escapeHTML(b.bid_ntce_no)}"
                        onclick="event.stopPropagation()" title="AI 분석">🎯</button>
                </div>
            </div>`;
    }).join('');

    resultsEl.innerHTML = header + cards;
    if (bids.length > 30) {
        resultsEl.innerHTML += `
            <div style="text-align:center;padding:12px;color:var(--text-muted);font-size:0.82rem">
                ... 외 ${bids.length - 30}건 (공고 목록에서 전체 확인)
            </div>`;
    }
}

function filterDashboardResults() {
    const subQuery = document.getElementById('ksp-sub-search')?.value?.trim()?.toLowerCase() || '';
    const budgetFilter = document.getElementById('ksp-filter-budget')?.value || '';
    const deadlineFilter = document.getElementById('ksp-filter-deadline')?.value || '';
    const orgFilter = document.getElementById('ksp-filter-org')?.value?.trim()?.toLowerCase() || '';

    // 필터 없으면 전체 표시
    if (!subQuery && !budgetFilter && !deadlineFilter && !orgFilter) {
        _renderKspResults(_kspResults, _kspActiveKeyword || '');
        document.getElementById('ksp-result-count').textContent = `${_kspResults.length}건`;
        return;
    }

    const now = new Date();
    const filtered = _kspResults.filter(b => {
        // 키워드 필터
        if (subQuery) {
            const match = (b.title || '').toLowerCase().includes(subQuery) ||
                (b.org_name || '').toLowerCase().includes(subQuery) ||
                (b.bid_ntce_no || '').toLowerCase().includes(subQuery);
            if (!match) return false;
        }

        // 예산 필터 (만원 단위)
        if (budgetFilter) {
            const budget = b.budget || 0;
            const limitWon = parseInt(budgetFilter) * 10000; // 만원 → 원
            if (budgetFilter === '100001') {
                if (budget <= 1000000000) return false; // 10억 초과
            } else {
                if (budget > limitWon) return false;
            }
        }

        // 마감일 필터
        if (deadlineFilter) {
            if (!b.bid_close_dt) return false;
            const closeDate = new Date(b.bid_close_dt);
            const diffDays = (closeDate - now) / 86400000;
            if (diffDays < 0 || diffDays > parseInt(deadlineFilter)) return false;
        }

        // 기관 필터
        if (orgFilter) {
            if (!(b.org_name || '').toLowerCase().includes(orgFilter)) return false;
        }

        return true;
    });

    // 필터 표시 라벨 생성
    const labels = [];
    if (subQuery) labels.push(subQuery);
    if (budgetFilter) {
        const budgetLabels = {'5000':'5천만↓','10000':'1억↓','50000':'5억↓','100000':'10억↓','100001':'10억↑'};
        labels.push(budgetLabels[budgetFilter] || budgetFilter);
    }
    if (deadlineFilter) labels.push(`${deadlineFilter}일내`);
    if (orgFilter) labels.push(orgFilter);

    document.getElementById('ksp-result-count').textContent = `${filtered.length}건 / ${_kspResults.length}건`;
    _renderKspResults(filtered, `${_kspActiveKeyword || ''} → ${labels.join(' · ')}`);
}

function clearSubFilter() {
    const input = document.getElementById('ksp-sub-search');
    if (input) input.value = '';
    const budget = document.getElementById('ksp-filter-budget');
    if (budget) budget.value = '';
    const deadline = document.getElementById('ksp-filter-deadline');
    if (deadline) deadline.value = '';
    const org = document.getElementById('ksp-filter-org');
    if (org) org.value = '';
    filterDashboardResults();
}

function kspGoToBids(keyword) {
    navigate('bids');
    setTimeout(() => {
        const input = document.getElementById('bid-search');
        if (input) {
            input.value = keyword;
            filterBids();
        }
    }, 300);
}

// ──────────────────────────────────────────────
// 키워드 분포 차트
// ──────────────────────────────────────────────
function renderKeywordDist(keywordTrends) {
    const container = document.getElementById('keyword-dist-chart');
    if (!container) return;
    
    const kwNames = Object.keys(keywordTrends);
    if (!kwNames.length) {
        container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px 0">설정에서 키워드를 등록하면 분포가 표시됩니다</p>';
        return;
    }
    
    // 키워드별 총 건수 계산
    const kwTotals = kwNames.map(kw => ({
        name: kw,
        total: (keywordTrends[kw] || []).reduce((sum, d) => sum + d.count, 0)
    })).sort((a, b) => b.total - a.total);
    
    const maxTotal = Math.max(...kwTotals.map(k => k.total), 1);
    
    container.innerHTML = kwTotals.map((kw, idx) => {
        const pct = (kw.total / maxTotal) * 100;
        const color = CHART_COLORS[(idx) % CHART_COLORS.length];
        return `<div class="kw-dist-row">
            <span class="kw-dist-label">${escapeHTML(kw.name)}</span>
            <div class="kw-dist-bar-track">
                <div class="kw-dist-bar" style="width:${pct}%;background:${color}">${kw.total}건</div>
            </div>
        </div>`;
    }).join('');

    // 차트 바 진입 애니메이션 적용
    animateChartBars();
}


// ──────────────────────────────────────────────
// 27. 제안서 고도화 전략 분석
// ──────────────────────────────────────────────

let _proposalProgressTimer = null;

async function analyzeProposalStrategy() {
    // 현재 열려 있는 전략 모달에서 공고번호 가져오기
    const strategyOverlay = document.getElementById('strategy-modal-overlay');
    const bidNo = strategyOverlay?.dataset?.bidNo;
    if (!bidNo) {
        showToast('분석할 공고를 먼저 선택해주세요.', 'warning');
        return;
    }

    // 제안서 전략 모달 열기
    const overlay = document.getElementById('proposal-strategy-overlay');
    const loading = document.getElementById('proposal-loading');
    const content = document.getElementById('proposal-strategy-content');
    const subtitle = document.getElementById('proposal-strategy-subtitle');

    overlay.classList.add('active');
    loading.style.display = 'flex';
    content.innerHTML = '';
    subtitle.textContent = `공고번호: ${bidNo} — 데이터 기반 심층 분석 중...`;

    // 프로그레스바 애니메이션
    _startProposalProgress();

    try {
        const requestBody = { bid_ntce_no: bidNo };
        // 사업자 ID 자동 포함 (다중 사업자 환경 지원)
        if (state.businesses && state.businesses.length > 0) {
            requestBody.biz_id = state.businesses[0].biz_id;
        }
        const response = await fetch('/api/analyze-proposal-strategy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || '분석에 실패했습니다.');
        }

        const data = await response.json();
        content.innerHTML = renderProposalStrategy(data);
        subtitle.textContent = `${escapeHTML(data.bid_title || '')} — 분석 완료`;
        showToast('📊 제안서 고도화 전략 분석 완료!', 'success');
    } catch (error) {
        content.innerHTML = `
            <div class="proposal-error">
                <div class="pe-icon">⚠️</div>
                <h3>분석 중 오류가 발생했습니다</h3>
                <p>${escapeHTML(error.message)}</p>
                <button class="btn btn-primary btn-sm" onclick="analyzeProposalStrategy()">🔄 다시 시도</button>
            </div>`;
        showToast('제안서 전략 분석 실패: ' + error.message, 'error');
    } finally {
        loading.style.display = 'none';
        _stopProposalProgress();
    }
}

function _startProposalProgress() {
    const bar = document.getElementById('pl-progress-bar');
    if (!bar) return;
    let progress = 0;
    bar.style.width = '0%';
    _proposalProgressTimer = setInterval(() => {
        progress += Math.random() * 3 + 0.5;
        if (progress > 92) progress = 92;
        bar.style.width = `${progress}%`;
    }, 1000);
}

function _stopProposalProgress() {
    if (_proposalProgressTimer) {
        clearInterval(_proposalProgressTimer);
        _proposalProgressTimer = null;
    }
    const bar = document.getElementById('pl-progress-bar');
    if (bar) bar.style.width = '100%';
}

function renderProposalStrategy(data) {
    const s = data.strategy || data;
    let html = '<div class="ps-report">';

    // ─── 헤더 ───
    html += `
        <div class="ps-header">
            <div class="ps-header-main">
                <h3>${escapeHTML(data.bid_title || '')}</h3>
                <div class="ps-header-meta">
                    <span class="ps-meta-tag">🏛️ ${escapeHTML(data.org_name || '')}</span>
                    <span class="ps-meta-tag">🏢 ${escapeHTML(data.matched_business || '자동 선택')}</span>
                    ${data.match_score ? `<span class="ps-meta-tag ps-score">🎯 매칭 ${data.match_score}점</span>` : ''}
                </div>
            </div>
        </div>`;

    // ─── 1. 경쟁사 분석 ───
    if (s.competitor_intelligence) {
        const ci = s.competitor_intelligence;
        html += `
            <div class="ps-section ps-competitor">
                <div class="ps-section-header">
                    <span class="ps-section-icon">🏢</span>
                    <h4>경쟁사 수주 패턴 분석</h4>
                </div>
                <div class="ps-section-body">`;

        if (ci.top_competitors && ci.top_competitors.length > 0) {
            html += '<div class="ps-competitor-grid">';
            ci.top_competitors.slice(0, 6).forEach((c, i) => {
                const rankClass = i < 3 ? 'top' : '';
                html += `
                    <div class="ps-competitor-card ${rankClass}">
                        <div class="ps-cc-rank">#${i + 1}</div>
                        <div class="ps-cc-name">${escapeHTML(c.company_name || c.name || '')}</div>
                        <div class="ps-cc-stats">
                            <div class="ps-cc-stat">
                                <span class="ps-cc-num">${c.win_count || 0}</span>
                                <span class="ps-cc-label">수주</span>
                            </div>
                            <div class="ps-cc-stat">
                                <span class="ps-cc-num">${c.avg_bid_rate ? c.avg_bid_rate.toFixed(1) : '-'}%</span>
                                <span class="ps-cc-label">투찰률</span>
                            </div>
                            ${c.total_amount ? `
                            <div class="ps-cc-stat">
                                <span class="ps-cc-num">${displayBudget(c.total_amount)}</span>
                                <span class="ps-cc-label">총액</span>
                            </div>` : ''}
                        </div>
                    </div>`;
            });
            html += '</div>';
        }

        if (ci.market_concentration) {
            html += `<div class="ps-insight-box">
                <strong>📊 시장 집중도:</strong> ${formatStrategyText(
                    typeof ci.market_concentration === 'string'
                    ? ci.market_concentration
                    : JSON.stringify(ci.market_concentration)
                )}
            </div>`;
        }

        if (ci.our_competitive_position) {
            html += `<div class="ps-callout ps-callout-primary">
                <strong>💡 우리 포지셔닝:</strong> ${formatStrategyText(ci.our_competitive_position)}
            </div>`;
        }
        html += '</div></div>';
    }

    // ─── 2. 발주기관 정책 ───
    if (s.org_policy_analysis) {
        const op = s.org_policy_analysis;
        html += `
            <div class="ps-section ps-org">
                <div class="ps-section-header">
                    <span class="ps-section-icon">🏛️</span>
                    <h4>발주기관 정책 방향</h4>
                </div>
                <div class="ps-section-body">`;

        if (op.policy_direction) {
            html += `<div class="ps-content">${formatStrategyText(op.policy_direction)}</div>`;
        }

        if (op.recurring_project_insight) {
            html += `<div class="ps-callout ps-callout-success">
                <strong>🔄 반복 사업 인사이트:</strong> ${formatStrategyText(op.recurring_project_insight)}
            </div>`;
        }

        if (op.preferred_vendors_insight) {
            html += `<div class="ps-callout ps-callout-warning">
                <strong>⭐ 선호 업체 패턴:</strong> ${formatStrategyText(op.preferred_vendors_insight)}
            </div>`;
        }
        html += '</div></div>';
    }

    // ─── 3. 지역 트렌드 ───
    if (s.regional_analysis) {
        const ra = s.regional_analysis;
        html += `
            <div class="ps-section ps-regional">
                <div class="ps-section-header">
                    <span class="ps-section-icon">🗺️</span>
                    <h4>지역 트렌드 분석</h4>
                </div>
                <div class="ps-section-body">`;

        if (ra.market_trend) html += `<div class="ps-content">${formatStrategyText(ra.market_trend)}</div>`;
        if (ra.policy_alignment) {
            html += `<div class="ps-callout ps-callout-primary">
                <strong>📋 정책 부합도:</strong> ${formatStrategyText(ra.policy_alignment)}
            </div>`;
        }
        if (ra.local_preference) html += `<div class="ps-content">${formatStrategyText(ra.local_preference)}</div>`;
        html += '</div></div>';
    }

    // ─── 4. 투찰률 가이드 ───
    if (s.bid_rate_recommendation) {
        const br = s.bid_rate_recommendation;
        html += `
            <div class="ps-section ps-bidrate">
                <div class="ps-section-header">
                    <span class="ps-section-icon">💰</span>
                    <h4>투찰률 최적화 가이드</h4>
                </div>
                <div class="ps-section-body">
                    <div class="ps-bidrate-display">`;

        if (br.optimal_rate) {
            html += `
                <div class="ps-bidrate-main">
                    <div class="ps-bidrate-value">${br.optimal_rate}<span class="ps-bidrate-unit">%</span></div>
                    <div class="ps-bidrate-label">최적 투찰률</div>
                </div>`;
        }
        if (br.range) {
            html += `
                <div class="ps-bidrate-range">
                    <div class="ps-bidrate-bar">
                        <div class="ps-bidrate-fill" style="left:${Math.max(0, (br.range[0]-75)/25*100)}%;width:${(br.range[1]-br.range[0])/25*100}%"></div>
                        <div class="ps-bidrate-marker" style="left:${(br.optimal_rate-75)/25*100}%"></div>
                    </div>
                    <div class="ps-bidrate-ticks">
                        <span>75%</span>
                        <span>${br.range[0]}%</span>
                        <span style="font-weight:700;color:var(--success-color)">${br.optimal_rate}%</span>
                        <span>${br.range[1]}%</span>
                        <span>100%</span>
                    </div>
                </div>`;
        }
        html += '</div>';
        if (br.rationale) html += `<div class="ps-content" style="margin-top:12px">${formatStrategyText(br.rationale)}</div>`;
        if (br.confidence) html += `<div class="ps-meta-small">신뢰도: ${(br.confidence * 100).toFixed(0)}%</div>`;
        html += '</div></div>';
    }

    // ─── 5. RFP 변화 분석 ───
    if (s.rfp_change_analysis) {
        const rfp = s.rfp_change_analysis;
        html += `
            <div class="ps-section ps-rfp">
                <div class="ps-section-header">
                    <span class="ps-section-icon">📋</span>
                    <h4>RFP 전년 대비 변화점</h4>
                </div>
                <div class="ps-section-body">`;

        if (rfp.vs_last_year) html += `<div class="ps-content">${formatStrategyText(rfp.vs_last_year)}</div>`;
        if (rfp.new_requirements && rfp.new_requirements.length > 0) {
            html += '<div class="ps-list-box"><strong>🆕 신규 요구사항:</strong><ul>';
            rfp.new_requirements.forEach(r => { html += `<li>${escapeHTML(typeof r === 'string' ? r : JSON.stringify(r))}</li>`; });
            html += '</ul></div>';
        }
        html += '</div></div>';
    }

    // ─── 6. 제안서 강화 포인트 ───
    if (s.proposal_enhancement) {
        const pe = s.proposal_enhancement;
        html += `
            <div class="ps-section ps-enhance">
                <div class="ps-section-header">
                    <span class="ps-section-icon">🚀</span>
                    <h4>제안서 강화 포인트</h4>
                </div>
                <div class="ps-section-body">`;

        if (pe.title_strategy) html += `<div class="ps-enhance-item"><strong>📌 제목 전략:</strong> ${formatStrategyText(pe.title_strategy)}</div>`;
        if (pe.tech_differentiation) {
            const tech = typeof pe.tech_differentiation === 'string' ? pe.tech_differentiation : (pe.tech_differentiation || []).join(', ');
            html += `<div class="ps-enhance-item"><strong>⚙️ 기술 차별화:</strong> ${formatStrategyText(tech)}</div>`;
        }
        if (pe.team_composition_advice) html += `<div class="ps-enhance-item"><strong>👥 팀 구성:</strong> ${formatStrategyText(pe.team_composition_advice)}</div>`;
        if (pe.pricing_strategy) html += `<div class="ps-enhance-item"><strong>💲 가격 전략:</strong> ${formatStrategyText(pe.pricing_strategy)}</div>`;
        html += '</div></div>';
    }

    // ─── 7. AI 종합 전략 ───
    if (s.llm_strategy_report) {
        html += `
            <div class="ps-section ps-llm">
                <div class="ps-section-header">
                    <span class="ps-section-icon">🤖</span>
                    <h4>AI 종합 전략 보고서</h4>
                </div>
                <div class="ps-section-body">
                    <div class="ps-llm-content">${formatStrategyText(
                        typeof s.llm_strategy_report === 'string'
                        ? s.llm_strategy_report
                        : JSON.stringify(s.llm_strategy_report, null, 2)
                    )}</div>
                </div>
            </div>`;
    }

    // ─── 8. 액션 플랜 ───
    if (s.action_plan && s.action_plan.length > 0) {
        html += `
            <div class="ps-section ps-action">
                <div class="ps-section-header">
                    <span class="ps-section-icon">✅</span>
                    <h4>액션 플랜</h4>
                </div>
                <div class="ps-section-body">
                    <div class="ps-action-list">`;

        s.action_plan.forEach((item, i) => {
            const task = typeof item === 'string' ? item : (item.task || JSON.stringify(item));
            const detail = typeof item === 'object' ? item.detail : '';
            const deadline = typeof item === 'object' ? item.deadline : '';
            const priority = typeof item === 'object' ? item.priority : '';
            html += `
                <div class="ps-action-item ${priority ? 'ps-priority-' + priority : ''}">
                    <div class="ps-action-num">${i + 1}</div>
                    <div class="ps-action-body">
                        <div class="ps-action-task">${escapeHTML(task)}</div>
                        ${detail ? `<div class="ps-action-detail">${escapeHTML(detail)}</div>` : ''}
                        ${deadline ? `<div class="ps-action-deadline">⏰ ${escapeHTML(deadline)}</div>` : ''}
                    </div>
                </div>`;
        });
        html += '</div></div></div>';
    }

    html += '</div>';
    return html;
}

function closeProposalStrategyModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const overlay = document.getElementById('proposal-strategy-overlay');
    if (overlay) overlay.classList.remove('active');
    _stopProposalProgress();
}


// ──────────────────────────────────────────────
// 29. 프리미엄 UI 인터랙션 애니메이션
// ──────────────────────────────────────────────

/**
 * 뷰 전환 시 내부 카드/패널에 stagger 등장 애니메이션 적용
 * navigate() 함수 끝에서 호출됨
 */
function animateViewCards(viewId) {
    const view = document.getElementById('view-' + viewId);
    if (!view) return;
    const cards = view.querySelectorAll('.stat-card, .briefing-item, .card, .analysis-card, .fav-pipeline-card, .keyword-search-panel, .briefing-panel');
    cards.forEach((card, i) => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(12px)';
        setTimeout(() => {
            card.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
            card.style.opacity = '1';
            card.style.transform = 'translateY(0)';
        }, i * 60);
    });
}

/**
 * 차트 바(.kw-dist-bar, .hbar-fill)에 width:0 → 목표값 트랜지션 효과
 * renderKeywordDist() 함수 끝에서 호출됨
 */
function animateChartBars() {
    document.querySelectorAll('.kw-dist-bar, .hbar-fill').forEach(bar => {
        const targetWidth = bar.style.width;
        bar.style.width = '0';
        bar.style.transition = 'width 0.8s cubic-bezier(0.4,0,0.2,1)';
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                bar.style.width = targetWidth;
            });
        });
    });
}

/**
 * IntersectionObserver 기반 — 카드가 뷰포트에 진입할 때 등장 애니메이션
 * DOMContentLoaded에서 호출됨
 */
function initScrollAnimations() {
    if (!('IntersectionObserver' in window)) return;
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('in-view');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    document.querySelectorAll('.stat-card, .briefing-panel, .keyword-search-panel, .fav-pipeline-summary').forEach(el => {
        el.classList.add('observe-reveal');
        observer.observe(el);
    });
}


// ──────────────────────────────────────────────
// 점수 등급 헬퍼 함수
// ──────────────────────────────────────────────
function getScoreGrade(score) {
    if (score >= 80) return '우수';
    if (score >= 60) return '양호';
    if (score >= 40) return '보통';
    return '부족';
}
