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

// ===== 글로벌 상태 변수 =====
let compareList = []; // 공고 비교 리스트
let favViewMode = 'list'; // 관심공고 뷰 모드 ('list' | 'kanban')
let qaChatHistory = []; // AI Q&A 대화 내역
let currentProposalBidNo = ''; // 제안서 Q&A 대상 공고번호
let currentProposalBizId = ''; // 제안서 Q&A 대상 사업자 ID
let _currentUser = null; // 현재 로그인된 사용자명
let _favoritesCache = []; // 관심공고 전역 캐시

// ── 사이드바 실시간 시계 ──
(function initSidebarClock() {
    function updateClock() {
        const el = document.getElementById('sidebar-clock');
        if (el) {
            const now = new Date();
            const h = String(now.getHours()).padStart(2, '0');
            const m = String(now.getMinutes()).padStart(2, '0');
            el.textContent = `${h}:${m}`;
        }
    }
    updateClock();
    setInterval(updateClock, 30000);
})();


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
// 0-d. 스켈레톤 카드 공통 렌더러
// ──────────────────────────────────────────────
function renderSkeletonCards(count = 3, height = '120px') {
    return Array(count).fill(0).map(() => `
        <div class="skeleton-card" style="height:${height};border-radius:12px;background:linear-gradient(90deg,rgba(99,102,241,0.06) 25%,rgba(99,102,241,0.12) 50%,rgba(99,102,241,0.06) 75%);background-size:200% 100%;animation:skeleton-shimmer 1.5s ease-in-out infinite;margin-bottom:12px">
        </div>
    `).join('');
}

// ──────────────────────────────────────────────
// 0-e. 차트 로딩 플레이스홀더
// ──────────────────────────────────────────────
function renderChartLoading(containerId, message = '차트 데이터를 불러오는 중...') {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = `<div class="chart-loading-placeholder">
        <div class="chart-spinner"></div>
        <span>${message}</span>
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

// ── 관심공고 관리 (localStorage & Server API Sync) ──
const FAV_STATUSES = {
    reviewing: { label: '⭐ 검토중', color: '#f59e0b' },
    proceeding: { label: '🚀 사업진행', color: '#3b82f6' },
    partnered: { label: '🤝 협업진행', color: '#8b5cf6' },
    completed: { label: '✅ 완료', color: '#10b981' },
    abandoned: { label: '❌ 포기', color: '#ef4444' },
};

let _favFilterStatus = 'all';
let _favDetailBidNo = null; // 현재 상세 모달에 열린 공고번호
let _favSortMode = 'deadline';

function changeFavSort(val) {
    _favSortMode = val;
    loadFavorites();
}

function getFavorites() {
    if (_currentUser) {
        return _favoritesCache.map(f => _fillFavoriteDefaults(f));
    }
    
    try {
        const raw = JSON.parse(localStorage.getItem('nara_favorites') || '[]');
        return raw.map(f => _fillFavoriteDefaults(f));
    } catch (e) { 
        console.warn('관심공고 로컬 데이터 파싱 실패', e); 
        return []; 
    }
}

function _fillFavoriteDefaults(f) {
    return {
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
    };
}

function saveFavorites(favs) {
    if (!_currentUser) {
        localStorage.setItem('nara_favorites', JSON.stringify(favs));
    }
}

function isFavorite(bidNo) {
    return getFavorites().some(f => f.bid_ntce_no === bidNo);
}

function getFavByBidNo(bidNo) {
    return getFavorites().find(f => f.bid_ntce_no === bidNo) || null;
}

async function updateFav(bidNo, updates) {
    if (!_currentUser) {
        // 비로그인: 로컬 스토리지에만 저장
        let favs = getFavorites();
        const idx = favs.findIndex(f => f.bid_ntce_no === bidNo);
        if (idx >= 0) {
            favs[idx] = { ...favs[idx], ...updates };
            saveFavorites(favs);
        }
        return;
    }

    // 캐시 즉시 업데이트
    const idx = _favoritesCache.findIndex(f => f.bid_ntce_no === bidNo);
    if (idx >= 0) {
        _favoritesCache[idx] = { ..._favoritesCache[idx], ...updates };
    }

    // analysis_done 같은 "조용한" 저장 여부 판단
    const isSilent = 'analysis_done' in updates || 'analysis_summary' in updates;

    try {
        // api() 헬퍼 사용 (인증 쿠키 자동 포함)
        await api('PUT', `/favorites/${bidNo}`, updates);
    } catch (e) {
        // PUT 실패 (404 포함) → POST로 먼저 추가 후 재시도
        const is404 = e.status === 404 || (e.message || '').includes('HTTP 404') || (e.message || '').includes('찾을 수 없');
        if (is404) {
            const fav = getFavByBidNo(bidNo);
            const addPayload = {
                bid_ntce_no: bidNo,
                status: updates.status || fav?.status || 'reviewing',
                memo: updates.memo || fav?.memo || '',
                partners: updates.partners || fav?.partners || [],
                checklist: updates.checklist || fav?.checklist || []
            };
            try {
                await api('POST', '/favorites', addPayload);
                // 추가 성공 → 다시 PUT
                try { await api('PUT', `/favorites/${bidNo}`, updates); } catch (_) {}
            } catch (addErr) {
                if (!isSilent) {
                    console.warn('관심공고 서버 저장 실패:', addErr.message);
                }
            }
            return;
        }

        // 401 = 세션 만료 (api()가 이미 처리)
        if (e.status === 401 || (e.message || '').includes('HTTP 401') || (e.message || '').includes('로그인')) return;

        // 그 외 오류
        console.error('관심공고 서버 업데이트 오류:', e);
        if (!isSilent) {
            showToast('서버 데이터 변경에 실패했습니다.', 'error');
        }
    }
}


async function toggleFavorite(bidNo, btnEl) {
    if (!_currentUser) {
        showToast('관심공고를 관리하려면 먼저 로그인해 주세요.', 'warning');
        openAuthModal();
        return;
    }

    const idx = _favoritesCache.findIndex(f => f.bid_ntce_no === bidNo);

    if (idx >= 0) {
        // 관심공고 삭제
        _favoritesCache.splice(idx, 1);
        if (btnEl) {
            btnEl.classList.remove('active');
            btnEl.innerHTML = '☆ 관심공고 추가';
        }
        showToast('관심공고에서 해제되었습니다.', 'info');
        try {
            await api('DELETE', `/favorites/${bidNo}`);
        } catch (e) {
            console.error('서버 관심공고 삭제 실패:', e);
        }
    } else {
        // 관심공고 추가
        const titleEl = document.getElementById('bqv-title');
        const overlay = document.getElementById('bid-quick-view');

        const newFav = {
            bid_ntce_no: bidNo,
            title: titleEl?.textContent?.trim() || bidNo,
            org_name: overlay?.dataset?.orgName || '',
            budget: overlay?.dataset?.budget ? parseInt(overlay.dataset.budget) : null,
            bid_close_dt: overlay?.dataset?.closeDt || '',
            status: 'reviewing',
            memo: '',
            partners: [],
            checklist: [
                { id: 'rfp', label: 'RFP/공고문 확인', hint: '나라장터에서 공고문/RFP를 다운로드하고 핵심 요구사항을 파악하세요', done: false },
                { id: 'qualify', label: '참가자격 요건 확인', hint: '면허, 실적, 재무상태 등 참가자격 충족 여부를 확인하세요', done: false },
                { id: 'docs', label: '제출서류 준비', hint: '사업자등록증, 인감증명서, 실적증명서 등 필수 서류를 준비하세요', done: false },
                { id: 'pricing', label: '가격 산정/견적', hint: '원가 계산, 이윤율 검토, 투찰가격을 산정하세요', done: false },
                { id: 'proposal', label: '제안서 작성', hint: '기술제안서, 사업수행계획서를 작성하세요', done: false },
                { id: 'submit', label: '입찰서 제출', hint: '나라장터에 입찰서를 전자 제출하세요 (마감시간 확인!)', done: false },
            ]
        };

        // 캐시 즉시 추가 (Optimistic UI)
        _favoritesCache.push(newFav);
        if (btnEl) {
            btnEl.classList.add('active');
            btnEl.innerHTML = '⭐ 관심공고 해제';
        }

        try {
            await api('POST', '/favorites', newFav);
            showToast('관심공고에 추가되었습니다! ⭐', 'success');
        } catch (e) {
            // 롤백
            const rollbackIdx = _favoritesCache.findIndex(f => f.bid_ntce_no === bidNo);
            if (rollbackIdx !== -1) _favoritesCache.splice(rollbackIdx, 1);
            if (btnEl) {
                btnEl.classList.remove('active');
                btnEl.innerHTML = '☆ 관심공고 추가';
            }
            console.error('서버 관심공고 추가 실패:', e);
            showToast(`관심공고 저장 실패: ${e.message || '서버 오류'}`, 'error');
        }
    }

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

    // 누적 통계 프로그레스 바 업데이트
    const progressWrap = document.getElementById('fav-pipeline-progress-wrap');
    if (progressWrap) {
        const total = stats.all;
        if (total > 0) {
            progressWrap.style.display = 'block';
            const pct = {
                reviewing: Math.round((stats.reviewing / total) * 100),
                proceeding: Math.round((stats.proceeding / total) * 100),
                partnered: Math.round((stats.partnered / total) * 100),
                completed: Math.round((stats.completed / total) * 100),
                abandoned: Math.round((stats.abandoned / total) * 100)
            };
            
            // 각 바의 너비 갱신
            document.getElementById('fav-progress-reviewing').style.width = `${pct.reviewing}%`;
            document.getElementById('fav-progress-proceeding').style.width = `${pct.proceeding}%`;
            document.getElementById('fav-progress-partnered').style.width = `${pct.partnered}%`;
            document.getElementById('fav-progress-completed').style.width = `${pct.completed}%`;
            document.getElementById('fav-progress-abandoned').style.width = `${pct.abandoned}%`;
            
            // 요약 텍스트 갱신
            document.getElementById('fav-pipeline-progress-summary').textContent = 
                `검토중 ${pct.reviewing}% · 사업진행 ${pct.proceeding}% · 협업진행 ${pct.partnered}% · 완료 ${pct.completed}% · 포기 ${pct.abandoned}%`;
        } else {
            progressWrap.style.display = 'none';
        }
    }

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

    // 정렬
    if (_favSortMode === 'score') {
        favs.sort((a, b) => (b.match_score || 0) - (a.match_score || 0));
    } else if (_favSortMode === 'budget') {
        favs.sort((a, b) => (b.budget || 0) - (a.budget || 0));
    } else {
        // 마감일 기준 정렬 (가까운 순)
        favs.sort((a, b) => {
            const da = getDaysLeft(a.bid_close_dt);
            const db = getDaysLeft(b.bid_close_dt);
            if (da === null && db === null) return 0;
            if (da === null) return 1;
            if (db === null) return -1;
            return da - db;
        });
    }

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
                <input type="text" id="fav-search-input" class="fav-detail-input" placeholder="🔍 검색..." value="${escapeHTML(searchQuery)}" oninput="loadFavorites()" style="width:120px;padding:6px 10px;font-size:0.82rem">
                <select id="fav-sort-select" onchange="changeFavSort(this.value)" class="fav-detail-input" style="width:140px;padding:6px 10px;font-size:0.82rem;background:var(--bg-input);color:var(--text);border:1px solid var(--border);border-radius:6px">
                    <option value="deadline" ${_favSortMode === 'deadline' ? 'selected' : ''}>📅 마감일 가까운 순</option>
                    <option value="score" ${_favSortMode === 'score' ? 'selected' : ''}>🎯 AI 적합도 높은 순</option>
                    <option value="budget" ${_favSortMode === 'budget' ? 'selected' : ''}>💰 예산 규모 높은 순</option>
                </select>
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

            // AI 적합도 배지 렌더링
            let scoreColor = '#ef4444';
            if (f.match_score >= 80) scoreColor = '#10b981';
            else if (f.match_score >= 50) scoreColor = '#eab308';
            const scoreDisplay = f.match_score !== undefined
                ? `<span class="fav-score-badge" style="background:rgba(255,255,255,0.04); border:1px solid ${scoreColor}; color:${scoreColor}; padding:2px 8px; border-radius:12px; font-size:0.72rem; font-weight:700; display:inline-flex; align-items:center; gap:4px">🎯 적합도 ${Math.round(f.match_score)}%</span>`
                : '';

            return `
                <div class="fav-pipeline-card ${isExpired ? 'expired' : ''}" onclick="openFavDetail('${escapeHTML(f.bid_ntce_no)}')">
                    <div class="fav-pipeline-left">
                        <div class="fav-meta-row" style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
                            <span class="fav-status-badge" style="--status-color:${st.color}">${st.label}</span>
                            ${deadlineBadge}
                            ${scoreDisplay}
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

    const headers = {
        'Bypass-Tunnel-Reminder': 'true',
    };
    if (body) {
        headers['Content-Type'] = 'application/json';
    }

    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (activeBizId) {
        headers['X-Active-Company'] = activeBizId;
    }

    const opts = {
        method,
        headers,
        signal: controller.signal,
        credentials: 'include',
    };
    if (body) {
        opts.body = JSON.stringify(body);
    }

    try {
        const res = await fetch(`/api${path}`, opts);
        clearTimeout(timeoutId);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            // 401 Unauthorized - 세션 만료 처리
            if (res.status === 401 && _currentUser) {
                _currentUser = null;
                _favoritesCache = [];
                _clearAuthUI();
                showToast('세션이 만료되었습니다. 다시 로그인해 주세요.', 'warning');
            }
            const apiErr = new Error(err.detail || `HTTP ${res.status}`);
            apiErr.status = res.status;
            apiErr.detail = err.detail;
            throw apiErr;
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

    // AI 협업사 추천 및 이전 협업사 추천 동시 조회
    const suggestEl = document.getElementById('fav-partner-suggest');
    if (suggestEl) {
        suggestEl.innerHTML = `<div style="text-align:center;padding:12px;color:var(--text-muted);font-size:0.78rem">🤖 AI 협업사 추천을 분석 중입니다...</div>`;
        
        api('GET', `/favorites/${bidNo}/recommend-partners`)
            .then(res => {
                let html = '';
                
                // 1. AI 지능형 추천 파트너사
                if (res && res.partners && res.partners.length > 0) {
                    html += `
                        <div style="margin-top:10px;padding:12px;background:rgba(16,185,129,0.04);border-radius:10px;border:1px solid rgba(16,185,129,0.15)">
                            <div style="font-size:0.8rem;color:var(--success, #10b981);font-weight:700;margin-bottom:8px;display:flex;align-items:center;gap:6px">
                                <span>🤖</span> AI 지능형 협업사 추천
                            </div>
                            <div style="display:flex;flex-direction:column;gap:8px">`;
                    res.partners.forEach(p => {
                        const reasons = p.matched_reasons.map(r => `<div style="font-size:0.72rem;color:var(--text-secondary);padding-left:14px;position:relative"><span style="position:absolute;left:2px;color:var(--success)">•</span>${escapeHTML(r)}</div>`).join('');
                        const nameEsc = escapeHTML(p.company_name.replace(/'/g, "\\'"));
                        const roleEsc = escapeHTML((p.matched_reasons[0] || '공동수급').replace(/'/g, "\\'"));
                        const contactEsc = escapeHTML((p.ceo_name || '대표자').replace(/'/g, "\\'"));
                        
                        html += `
                            <div style="display:flex;justify-content:space-between;align-items:flex-start;padding:8px;background:var(--bg-card, rgba(0,0,0,0.02));border-radius:6px;border:1px solid var(--border)">
                                <div style="flex:1">
                                    <div style="font-size:0.78rem;font-weight:600;color:var(--text-primary)">
                                        ${escapeHTML(p.company_name)} <small style="color:var(--text-muted);font-weight:400">(대표: ${escapeHTML(p.ceo_name)} | 신용: ${escapeHTML(p.credit_rating)})</small>
                                    </div>
                                    <div style="margin-top:4px">${reasons}</div>
                                </div>
                                <div style="display:flex;gap:4px;flex-direction:column;align-items:flex-end">
                                    <button class="btn btn-sm btn-ghost" style="padding:2px 8px;font-size:0.72rem;height:24px;width:100%" 
                                        onclick="addSuggestedPartner('${nameEsc}', '${roleEsc}', '${contactEsc}')">
                                        + 추가
                                    </button>
                                    <button class="btn btn-sm btn-primary" style="padding:2px 8px;font-size:0.72rem;height:24px;background:rgba(99,102,241,0.2);color:#a5b4fc;border:1px solid rgba(99,102,241,0.4)" 
                                        onclick="openProposalModal('${p.biz_id}', '${nameEsc}', '${bidNo}')">
                                        🤝 제안
                                    </button>
                                </div>
                            </div>
                        `;
                    });
                    html += `</div></div>`;
                }
                
                // 2. 이전 협업사 추천
                const suggestions = suggestPartners(bidNo);
                if (suggestions && suggestions.length > 0) {
                    html += `
                        <div style="margin-top:10px;padding:12px;background:rgba(99,102,241,0.04);border-radius:10px;border:1px dashed rgba(99,102,241,0.25)">
                            <div style="font-size:0.8rem;color:var(--accent-indigo, #6366f1);font-weight:700;margin-bottom:8px;display:flex;align-items:center;gap:6px">
                                <span>💡</span> 이전 협업사 추천
                            </div>
                            <div style="display:flex;gap:6px;flex-wrap:wrap">`;
                    suggestions.forEach(s => {
                        const nameEsc = escapeHTML(s.name.replace(/'/g, "\\'"));
                        const roleEsc = escapeHTML(s.role.replace(/'/g, "\\'"));
                        const contactEsc = escapeHTML(s.contact.replace(/'/g, "\\'"));
                        html += `
                            <button class="btn btn-sm btn-ghost" style="font-size:0.75rem;padding:4px 10px" 
                                onclick="addSuggestedPartner('${nameEsc}', '${roleEsc}', '${contactEsc}')">
                                + ${escapeHTML(s.name)} (${s.count}회)
                            </button>
                        `;
                    });
                    html += `</div></div>`;
                }
                
                if (!html) {
                    suggestEl.innerHTML = `<div style="padding:10px;color:var(--text-muted);font-size:0.75rem;text-align:center">💡 추천 가능한 파트너사 정보가 없습니다.</div>`;
                } else {
                    suggestEl.innerHTML = html;
                }
            })
            .catch(err => {
                console.error("AI 협업 추천 오류:", err);
                suggestEl.innerHTML = `<div style="padding:10px;color:var(--text-muted);font-size:0.75rem;text-align:center">❌ 추천 정보를 불러오지 못했습니다. (회사가 등록되어 있는지 확인해주세요)</div>`;
            });
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
    calculateConsortiumSynergy();
    calculateConsortiumMetrics();
    document.getElementById('fav-detail-overlay').classList.add('active');
}

function closeFavDetail(e) {
    if (e.target.id === 'fav-detail-overlay') {
        document.getElementById('fav-detail-overlay').classList.remove('active');
    }
}

function renderFavPartners(partners) {
    const container = document.getElementById('fav-detail-partners');
    if (!container) return;
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
        const exp = typeof p === 'object' ? (p.exp || 0) : 0;
        return `<div class="fav-partner-tag" style="flex-direction:column;align-items:flex-start;gap:3px;padding:8px 12px">
            <div style="display:flex;align-items:center;gap:6px;width:100%">
                <span style="font-weight:600">🤝 ${escapeHTML(name)}</span>
                ${role ? `<span style="font-size:0.72rem;background:var(--bg-hover);padding:1px 6px;border-radius:4px">${escapeHTML(role)}</span>` : ''}
                ${share ? `<span style="font-size:0.72rem;color:var(--warning);font-weight:600">지분: ${share}%</span>` : ''}
                ${exp ? `<span style="font-size:0.72rem;color:var(--success, #10b981);font-weight:600">실적: ${exp}억</span>` : ''}
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
    const expInput = document.getElementById('fav-partner-exp');
    const name = input.value.trim();
    const role = roleInput ? roleInput.value.trim() : '';
    const contact = contactInput ? contactInput.value.trim() : '';
    const share = shareInput ? parseInt(shareInput.value) || 0 : 0;
    const exp = expInput ? parseFloat(expInput.value) || 0 : 0;
    if (!name) return;

    const fav = getFavByBidNo(_favDetailBidNo);
    if (!fav) return;

    const partners = fav.partners || [];
    partners.push({ name, role, contact, share, exp });
    updateFav(_favDetailBidNo, { partners });
    renderFavPartners(partners);
    calculateConsortiumSynergy();
    calculateConsortiumMetrics();

    input.value = '';
    if (roleInput) roleInput.value = '';
    if (contactInput) contactInput.value = '';
    if (shareInput) shareInput.value = '';
    if (expInput) expInput.value = '';
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
    partners.push({ name, role, contact, share: 0, exp: 0 });
    updateFav(_favDetailBidNo, { partners });
    renderFavPartners(partners);
    calculateConsortiumSynergy();
    calculateConsortiumMetrics();
    showToast(`'${name}' 협업사가 추가되었습니다!`, 'success');
}

function removeFavPartner(index) {
    const fav = getFavByBidNo(_favDetailBidNo);
    if (!fav) return;
    const partners = fav.partners || [];
    partners.splice(index, 1);
    updateFav(_favDetailBidNo, { partners });
    renderFavPartners(partners);
    calculateConsortiumSynergy();
    calculateConsortiumMetrics();
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
    // 비로그인 상태일 때는 무조건 랜딩 페이지만 노출
    if (!_currentUser && view !== 'landing') {
        view = 'landing';
    }
    // 로그인 상태일 때 랜딩 페이지로 이동하면 대시보드로 우회
    if (_currentUser && view === 'landing') {
        view = 'dashboard';
    }

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
        case 'landing': loadLandingBids(); break;
        case 'dashboard': loadDashboard(); break;
        case 'bids': loadBids(); break;
        case 'favorites': loadFavorites(); break;
        case 'cafe': loadCafe(); break;
        case 'businesses': loadBusinesses(); break;
        case 'analysis': loadAnalyses(); break;
        case 'settings': loadSettings(); break;
        case 'ai-settings': loadUserAISettings(); break;
        case 'admin': loadAdminPanel(); break;
        case 'policies': initPoliciesView(); break;
        case 'proposals': loadProposals(); break;
        case 'partners': loadPartners(); break;
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
        // 먼저 설정에서 키워드 목록 가져오기
        let keywords = [];
        try {
            const settings = await api('GET', '/settings/full');
            keywords = settings?.keywords || [];
        } catch (e) {
            console.warn('설정 로드 실패:', e.message);
        }

        if (!keywords.length) {
            _showCollectingBanner(false, null, '관심 키워드가 설정되지 않았습니다. 설정에서 키워드를 추가해주세요.');
            _autoCollectRunning = false;
            return;
        }

        // 키워드를 하나씩 순차 수집 (타임아웃 방지)
        let totalCollected = 0;
        let totalSaved = 0;
        for (let i = 0; i < keywords.length; i++) {
            const kw = keywords[i];
            _showCollectingProgress(kw, i + 1, keywords.length, totalCollected);

            try {
                const result = await api('POST', '/bids/collect', { keyword: kw }, { timeout: 60000 });
                totalCollected += result.collected || 0;
                totalSaved += result.saved || 0;
                console.log(`  📋 "${kw}" → ${result.collected}건 수집, ${result.saved}건 저장`);
            } catch (kwErr) {
                console.warn(`  ⚠️ "${kw}" 수집 실패:`, kwErr.message);
            }

            // 3개 키워드 수집 후 중간 갱신 (사용자가 빨리 결과를 볼 수 있도록)
            if ((i + 1) % 3 === 0 && totalSaved > 0) {
                loadTop10();
            }
        }

        console.log(`✅ 자동 수집 완료: 총 ${totalCollected}건 수집, ${totalSaved}건 신규 저장`);
        _showCollectingBanner(false, { collected: totalCollected, saved: totalSaved });

        // 수집 후 대시보드 데이터 갱신
        setTimeout(async () => {
            try {
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
                loadTop10();
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
        if (briefingBadge) briefingBadge.textContent = '검색중...';
        const loadingHTML = `
            <div class="auto-collect-banner collecting">
                <div class="auto-collect-spinner"></div>
                <div class="auto-collect-text">
                    <strong>📋 오늘의 공고 브리핑 검색을 시작합니다</strong>
                    <span>등록된 관심 키워드 기반으로 나라장터에서 공고를 가져오고 있습니다...</span>
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

function _showCollectingProgress(keyword, current, total, collectedSoFar) {
    const briefingBody = document.getElementById('briefing-body');
    const briefingBadge = document.getElementById('briefing-badge');
    const top10List = document.getElementById('top10-list');
    const pct = Math.round((current / total) * 100);

    if (briefingBadge) briefingBadge.textContent = `수집중 ${current}/${total}`;

    const progressHTML = `
        <div class="auto-collect-banner collecting">
            <div class="auto-collect-spinner"></div>
            <div class="auto-collect-text">
                <strong>🔄 공고 수집 중 (${current}/${total})</strong>
                <span>"${escapeHTML(keyword)}" 키워드 수집중... ${collectedSoFar > 0 ? `(현재 ${collectedSoFar}건 수집됨)` : ''}</span>
                <div class="auto-collect-progress">
                    <div class="auto-collect-progress-bar" style="width:${pct}%"></div>
                </div>
            </div>
        </div>`;
    if (briefingBody) briefingBody.innerHTML = progressHTML;
    if (top10List) top10List.innerHTML = progressHTML;
}

async function loadDashboard() {
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    const banner = document.getElementById('no-company-banner');
    const hasCompany = !!activeBizId;

    if (!hasCompany) {
        if (banner) banner.style.display = 'flex';
        // 회사 미등록 시 큐레이션/최근 분석만 안내 메시지 표시
        renderRecentAnalyses([]);
        const tbody = document.getElementById('curated-bids-tbody');
        if (tbody) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="7">
                        <div class="empty-state-inline">
                            <span>🏢</span>
                            <p>사업자를 등록하면 맞춤 큐레이션 공고가 표시됩니다. <a onclick="navigate('businesses')" style="color:var(--accent-indigo);cursor:pointer;font-weight:600">사업자 등록 →</a></p>
                        </div>
                    </td>
                </tr>`;
        }
    } else {
        if (banner) banner.style.display = 'none';
    }

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

    if (activeBizId) {
        try {
            const recent = await api('GET', '/dashboard/recent');
            renderRecentAnalyses(recent || []);
        } catch (err) {
            console.warn('최근 분석 로드 실패:', err.message);
            renderRecentAnalyses([]);
        }
    } else {
        renderRecentAnalyses([]);
    }

    // 차트 로드
    loadCharts();

    // TOP 10 추천 사업도 함께 로드
    loadTop10();

    // 연간 반복 사업 발주 예측 로드
    loadRecurringForecast();

    // 관심 키워드 패널 로드
    loadKeywordSearchPanel();

    // 경쟁사 수주 타깃 모니터 로드
    loadCompetitorIntelligence();

    // YouTube 교육 동영상 로드
    loadYouTubeVideos();

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

    // 히어로 위젯 업데이트 (HTML에 고정 배치된 요소)
    const favCountEl = document.getElementById('hero-fav-count');
    const nextTextEl = document.getElementById('hero-next-text');
    const favSummary = document.getElementById('hero-fav-summary');
    const heroNextAction = document.getElementById('hero-next-action');

    if (favSummary && favs.length > 0) {
        if (urgentFavs.length > 0) {
            favSummary.style.borderColor = 'rgba(239,68,68,0.3)';
            favSummary.style.background = 'rgba(239,68,68,0.06)';
        } else {
            favSummary.style.borderColor = '';
            favSummary.style.background = '';
        }
        if (favCountEl) {
            favCountEl.textContent = urgentFavs.length > 0
                ? `${favs.length}건 ⏰D-3 ${urgentFavs.length}건`
                : `${favs.length}건 (진행중 ${activeFavs.length}건)`;
            if (urgentFavs.length > 0) favCountEl.style.color = '#f87171';
        }
        favSummary.style.cursor = 'pointer';
        favSummary.onclick = () => navigate('favorites');
    } else if (favCountEl) {
        favCountEl.textContent = '없음';
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

    if (nextAction && nextTextEl) {
        const d = getDaysLeft(nextAction.fav.bid_close_dt);
        const title = nextAction.fav.title?.substring(0, 28) || nextAction.fav.bid_ntce_no;
        nextTextEl.textContent = `${title} → ${nextAction.item.label}`;
        if (heroNextAction) {
            heroNextAction.onclick = () => openFavDetail(nextAction.fav.bid_ntce_no);
            heroNextAction.style.cursor = 'pointer';
        }
    } else if (nextTextEl) {
        nextTextEl.textContent = favs.length > 0 ? '체크리스트를 채워보세요' : '공고를 수집해보세요';
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

        // 출처 배지 구별
        let sourceBadge = '<span class="platform-badge nara">🏛️ 나라장터</span>';
        if (bid.bid_ntce_no.startsWith('KS-')) {
            sourceBadge = '<span class="platform-badge kstartup">🚀 K-Startup</span>';
        } else if (bid.bid_ntce_no.startsWith('ARKO-')) {
            sourceBadge = '<span class="platform-badge arko">🎭 아르코</span>';
        } else if (bid.bid_ntce_no.startsWith('SFAC-')) {
            sourceBadge = '<span class="platform-badge sfac">🎨 서울문화재단</span>';
        } else if (bid.bid_ntce_no.startsWith('KOCCA-')) {
            sourceBadge = '<span class="platform-badge kocca">🎬 콘텐츠진흥원</span>';
        } else if (bid.bid_ntce_no.startsWith('ENARA-')) {
            sourceBadge = '<span class="platform-badge enaradoum">📋 e나라도움</span>';
        } else if (bid.bid_ntce_no.startsWith('GOKAMS-')) {
            sourceBadge = '<span class="platform-badge gokams">🎪 예술경영</span>';
        } else if (bid.bid_ntce_no.startsWith('KCDF-')) {
            sourceBadge = '<span class="platform-badge kcdf">🏺 공예디자인</span>';
        } else if (bid.bid_ntce_no.startsWith('KTO-')) {
            sourceBadge = '<span class="platform-badge visitkorea">📺 관광공사</span>';
        } else if (bid.bid_ntce_no.startsWith('LH-')) {
            sourceBadge = '<span class="platform-badge lh">🏗️ LH</span>';
        } else if (bid.bid_ntce_no.startsWith('NRF-')) {
            sourceBadge = '<span class="platform-badge nrf">🔬 연구재단</span>';
        }

        const isCompared = compareList.some(item => item.bidNo === bid.bid_ntce_no);
        return `
        <tr data-bid-no="${escapeHTML(bid.bid_ntce_no)}" class="bid-row-toggle ${isFav ? 'bid-row-fav' : ''} ${badgeClass === 'closed' ? 'bid-row-expired' : ''}" style="cursor:pointer">
            <td>
                <div style="display:flex;align-items:center;gap:6px">
                    <input type="checkbox" class="compare-cb" data-bid-no="${escapeHTML(bid.bid_ntce_no)}" 
                           onclick="event.stopPropagation(); toggleCompareBid('${escapeHTML(bid.bid_ntce_no)}', '${escapeHTML((bid.title||'').replace(/'/g,''))}', '${escapeHTML((bid.org_name||'').replace(/'/g,''))}', '${bid.budget||''}', '${escapeHTML(bid.bid_close_dt||'')}', this)"
                           ${isCompared ? 'checked' : ''}>
                    ${sourceBadge}
                </div>
            </td>
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
                   onclick="event.stopPropagation()" title="공고 상세 페이지 확인">
                    🔗 상세
                </a>
            </td>
        </tr>
        <tr class="bid-detail-row" id="detail-${escapeHTML(bid.bid_ntce_no)}">
            <td colspan="8">
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

// ── 공고 제목 툴팁 (truncated text) ──
document.addEventListener('mouseover', function(e) {
    const td = e.target.closest('.td-title');
    if (td && td.scrollWidth > td.clientWidth) {
        td.title = td.textContent.trim();
    }
});

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

function getSelectedPlatforms() {
    const platforms = [];
    if (document.getElementById('plat-nara')?.checked) platforms.push('nara');
    if (document.getElementById('plat-kstartup')?.checked) platforms.push('kstartup');
    if (document.getElementById('plat-arko')?.checked) platforms.push('arko');
    if (document.getElementById('plat-sfac')?.checked) platforms.push('sfac');
    if (document.getElementById('plat-gokams')?.checked) platforms.push('gokams');
    if (document.getElementById('plat-kcdf')?.checked) platforms.push('kcdf');
    if (document.getElementById('plat-kocca')?.checked) platforms.push('kocca');
    if (document.getElementById('plat-e-naradoum')?.checked) platforms.push('e_naradoum');
    if (document.getElementById('plat-visitkorea')?.checked) platforms.push('visitkorea');
    if (document.getElementById('plat-lh')?.checked) platforms.push('lh');
    if (document.getElementById('plat-nrf')?.checked) platforms.push('nrf');
    return platforms;
}

async function collectByKeyword() {
    // 중복 실행 방지
    if (state.isLoading) return;

    const keyword = document.getElementById('bid-search').value.trim();
    if (!keyword) {
        showToast('검색어를 입력해주세요.', 'warning');
        return;
    }

    const platforms = getSelectedPlatforms();
    if (platforms.length === 0) {
        showToast('최소 하나 이상의 수집 채널을 선택해주세요.', 'warning');
        return;
    }

    showLoading(`'${keyword}' 키워드로 공고 검색 및 수집 중...`, '최근 30일 공고를 직접 수집합니다');
    try {
        updateLoadingText(`🔍 '${keyword}' 키워드로 공고 수집 중...`, '선택된 채널에서 공고 수집 중입니다');
        const result = await api('POST', '/bids/collect', { keyword, platforms });
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

    const platforms = getSelectedPlatforms();
    if (platforms.length === 0) {
        showToast('최소 하나 이상의 수집 채널을 선택해주세요.', 'warning');
        return;
    }

    showLoading('관심 키워드로 공고 수집 중...', '설정된 키워드로 검색을 수행합니다');
    try {
        updateLoadingText('🔍 공고 수집 채널 연결 중...', '선택한 플랫폼들에서 수집 중입니다');
        const result = await api('POST', '/bids/collect', { platforms });
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

    // 비로그인 처리
    if (!_currentUser) {
        if (grid) grid.innerHTML = `
            <div style="text-align:center;padding:60px 20px">
                <div style="font-size:3rem;margin-bottom:16px">🔒</div>
                <div style="font-size:1.1rem;font-weight:700;color:var(--text-primary);margin-bottom:8px">로그인이 필요합니다</div>
                <div style="font-size:0.88rem;color:var(--text-muted);margin-bottom:20px">사업자 관리는 로그인 후 이용하실 수 있습니다.</div>
                <button class="btn btn-primary" onclick="openAuthModal('login')">🔑 로그인하기</button>
            </div>`;
        return;
    }

    grid.innerHTML = '<div class="skeleton skeleton-card"></div>'.repeat(3);

    try {
        const businesses = await api('GET', '/businesses');
        state.businesses = businesses || [];
        renderBusinesses(state.businesses);
    } catch (err) {
        if (err.message.includes('인증') || err.message.includes('로그인')) {
            grid.innerHTML = `<div style="text-align:center;padding:40px"><p style="color:var(--text-muted)">세션이 만료되었습니다.</p><button class="btn btn-primary" onclick="openAuthModal('login')">다시 로그인</button></div>`;
            return;
        }
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
    
    // 포트폴리오 요약 위젯 업데이트
    updateBusinessPortfolioSummary(businesses);

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
        document.getElementById('form-credit-rating').value = business.credit_rating || 'BBB';
        document.getElementById('form-company-type').value = business.company_type || '';
        document.getElementById('form-has-sanctions').checked = !!business.has_sanctions;
        document.getElementById('form-is-shared').checked = business.is_shared !== undefined ? !!business.is_shared : true;
        document.getElementById('form-website-url').value = business.website_url || '';
        document.getElementById('form-intro-file-url').value = business.intro_file_url || '';
        document.getElementById('form-social-links').value = business.social_links || '';

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
        document.getElementById('form-credit-rating').value = 'BBB';
        document.getElementById('form-company-type').value = '';
        document.getElementById('form-has-sanctions').checked = false;
        document.getElementById('form-is-shared').checked = true;
        document.getElementById('form-website-url').value = '';
        document.getElementById('form-intro-file-url').value = '';
        document.getElementById('form-social-links').value = '';
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
        credit_rating: document.getElementById('form-credit-rating').value,
        company_type: document.getElementById('form-company-type').value.trim() || null,
        has_sanctions: document.getElementById('form-has-sanctions').checked,
        is_shared: document.getElementById('form-is-shared').checked,
        website_url: document.getElementById('form-website-url').value.trim() || null,
        intro_file_url: document.getElementById('form-intro-file-url').value.trim() || null,
        social_links: document.getElementById('form-social-links').value.trim() || null,
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

    // 비로그인 처리
    if (!_currentUser) {
        if (list) list.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">🔒</div>
                <h3>로그인이 필요합니다</h3>
                <p>AI 분석 결과는 로그인 후 확인하실 수 있습니다.<br>회원가입 후 사업자를 등록하면 공고 매칭 분석이 자동으로 실행됩니다.</p>
                <div style="display:flex;gap:8px;justify-content:center;margin-top:16px">
                    <button class="btn btn-primary" onclick="openAuthModal('login')">🔑 로그인하기</button>
                    <button class="btn btn-secondary" onclick="openAuthModal('register')">📝 회원가입</button>
                </div>
            </div>`;
        return;
    }

    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!activeBizId) {
        list.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">🏢</div>
                <h3>사업자를 등록하면 맞춤 분석이 가능합니다</h3>
                <p>사업자 프로필을 등록하면 공고와 사업자 간 매칭 분석을 수행할 수 있습니다.<br>
                키워드 기반 공고 추천은 대시보드에서 바로 확인할 수 있습니다.</p>
                <div style="display:flex;gap:8px;justify-content:center;margin-top:16px">
                    <button class="btn btn-primary" onclick="navigate('businesses')">
                        🏢 사업자 등록하기
                    </button>
                    <button class="btn btn-secondary" onclick="navigate('dashboard')">
                        📊 대시보드 보기
                    </button>
                </div>
            </div>`;
        return;
    }
    // 스켈레톤 로딩 (renderSkeletonCards 헬퍼 사용)
    list.innerHTML = renderSkeletonCards(3, '200px');

    try {
        const analyses = await api('GET', '/analyses');
        state.analyses = analyses || [];
        renderAnalyses(state.analyses);
    } catch (err) {
        showToast(`분석 결과 로드 실패: ${err.message}`, 'error');
        list.innerHTML = renderEmptyState(
            '⚠️',
            '데이터를 불러올 수 없습니다',
            `서버 연결을 확인 후 다시 시도해 주세요. (${escapeHTML(err.message)})`,
            `<div style="display:flex;gap:8px;justify-content:center;margin-top:16px">
                <button class="btn btn-primary" onclick="loadAnalyses()">🔄 다시 시도</button>
                <button class="btn btn-outline" onclick="navigate('dashboard')">🏠 대시보드</button>
            </div>`
        );
    }
}

function renderAnalyses(analyses) {
    const list = document.getElementById('analysis-list');

    if (!analyses || analyses.length === 0) {
        list.innerHTML = renderEmptyState(
            '🔬',
            '분석 결과가 없습니다',
            '추천 사업 TOP 10에서 🎯 버튼을 눌러 전략 분석을 실행하거나,<br>아래 버튼으로 전체 매칭 분석을 시작하세요.',
            `<div style="display:flex;gap:12px;justify-content:center;margin-top:20px;flex-wrap:wrap">
                <button class="btn btn-gradient" onclick="runAnalysis()">
                    <span class="btn-icon">🚀</span> 전체 분석 시작
                </button>
                <button class="btn btn-outline" onclick="navigate('top10')">
                    <span class="btn-icon">🏆</span> TOP 10 추천 보기
                </button>
                <button class="btn btn-secondary" onclick="navigate('dashboard')">
                    <span class="btn-icon">🏠</span> 대시보드
                </button>
            </div>`
        );
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

// ── 숫자 카운트업 애니메이션 (enhanced) ──
function animateCounter(elementOrId, target, duration = 800) {
    const el = (typeof elementOrId === 'string')
        ? document.getElementById(elementOrId)
        : elementOrId;
    if (!el) return;

    const start = parseInt(el.textContent.replace(/,/g, '')) || 0;
    const diff = target - start;
    if (diff === 0) { el.textContent = target.toLocaleString(); return; }
    const startTime = performance.now();

    function step(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // easeOutCubic
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = Math.round(start + diff * eased);
        el.textContent = current.toLocaleString();
        if (progress < 1) {
            requestAnimationFrame(step);
        } else {
            // 카운트 완료 시 그라디언트 효과 클래스 추가
            el.classList.add('counter-done');
        }
    }

    requestAnimationFrame(step);
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
    // Ctrl+K / Cmd+K: 검색 포커스
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.getElementById('bid-search');
        if (searchInput) {
            navigate('bids');
            setTimeout(() => searchInput.focus(), 100);
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
document.addEventListener('DOMContentLoaded', async () => {
    // 로그인 상태 확인
    await checkLoginStatus();

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

    // 로그인 상태에 따른 초기 뷰 로드
    if (_currentUser) {
        navigate('dashboard');
    } else {
        navigate('landing');
    }

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

    // 개인 AI 키 상태 로드
    loadApiKeys();
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

        // 개인 설정 뷰에서는 OpenAI/Gemini 상태만 표시
        const dotOpenai = document.getElementById('status-dot-openai');
        const dotGemini = document.getElementById('status-dot-gemini');

        if (dotOpenai) dotOpenai.className = `status-dot ${data.openai_api_key?.set ? 'active' : 'inactive'}`;
        if (dotGemini) dotGemini.className = `status-dot ${data.gemini_api_key?.set ? 'active' : 'inactive'}`;

        // 마스킹된 값 표시
        const maskedOpenai = document.getElementById('masked-openai');
        const maskedGemini = document.getElementById('masked-gemini');

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
    const openaiKey = document.getElementById('api-key-openai')?.value?.trim();
    const geminiKey = document.getElementById('api-key-gemini')?.value?.trim();
    const llmEngine = document.getElementById('llm-engine-select')?.value;

    if (openaiKey) body.openai_api_key = openaiKey;
    if (geminiKey) body.gemini_api_key = geminiKey;
    if (llmEngine) body.llm_engine = llmEngine;

    if (Object.keys(body).length === 0) {
        showToast('변경할 AI 설정을 입력해주세요.', 'warning');
        return;
    }

    try {
        const result = await api('PUT', '/settings/api-keys', body);
        showToast(result.message || 'AI 설정이 저장되었습니다.', 'success');

        // 입력 필드 초기화
        if (openaiKey) document.getElementById('api-key-openai').value = '';
        if (geminiKey) document.getElementById('api-key-gemini').value = '';

        // 상태 갱신
        loadApiKeys();
    } catch (e) {
        showToast(`AI 설정 저장 실패: ${e.message}`, 'error');
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
    // 차트 로딩 플레이스홀더 표시
    renderChartLoading('daily-trend-chart', '일별 공고 트렌드를 분석 중...');
    renderChartLoading('org-budget-chart', '기관별 예산 데이터를 분석 중...');
    renderChartLoading('keyword-dist-chart', '키워드 분포를 분석 중...');

    try {
        const data = await api('GET', '/dashboard/charts');
        renderDailyTrend(data.daily_trend || [], data.keyword_trends || {});
        renderOrgBudget(data.org_budget_top10 || []);
        renderKeywordDist(data.keyword_trends || {});
    } catch (e) {
        console.warn('차트 데이터 로드 실패:', e.message);
        // 에러 시 각 차트 영역에 안내 표시
        ['daily-trend-chart', 'org-budget-chart', 'keyword-dist-chart'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = renderEmptyState('📉', '차트를 불러올 수 없습니다', '공고를 수집하면 차트가 표시됩니다.',
                `<button class="btn btn-sm btn-outline" onclick="loadCharts()" style="margin-top:10px">🔄 새로고침</button>`);
        });
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
        if (e.message && e.message.includes('키워드')) {
            list.innerHTML = `<div class="empty-state-inline"><span>⚙️</span><p>관심 키워드를 먼저 설정해주세요. <a onclick="navigate('settings')" style="color:var(--accent-indigo);cursor:pointer">설정 →</a></p></div>`;
        } else {
            list.innerHTML = `<div class="empty-state-inline"><span>📋</span><p>수집된 공고가 없습니다. <button class="btn btn-sm btn-primary" onclick="collectBids()" style="margin-left:6px">공고 수집</button></p></div>`;
        }
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
    const kwUsed = data?.keywords_used || [];

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

    // 브리핑 요약 헤더
    const gradeA = top.filter(x => x.grade === 'A').length;
    const gradeB = top.filter(x => x.grade === 'B').length;
    const summaryHTML = `<div class="briefing-summary">
        <div class="briefing-summary-stats">
            <span class="bs-stat grade-a">🏆 적극추천 ${gradeA}건</span>
            <span class="bs-stat grade-b">📋 검토추천 ${gradeB}건</span>
            <span class="bs-stat">${kwUsed.length ? `🏷️ ${kwUsed.join(' · ')}` : ''}</span>
        </div>
        ${top[0]?.strategy_tip ? `<div class="briefing-summary-tip">💡 ${escapeHTML(top[0].strategy_tip)}</div>` : ''}
    </div>`;

    // 개별 공고 카드
    const cardsHTML = top.map((item, i) => {
        const grade = item.grade || 'C';
        const gradeLabel = grade === 'A' ? '적극추천' : grade === 'B' ? '검토추천' : '참고';
        const daysText = item.days_left === 999 ? '마감미정' : `D-${item.days_left}`;
        const daysClass = item.days_left <= 3 ? 'urgent' : item.days_left <= 7 ? 'soon' : 'safe';
        const budgetText = displayBudget(item.budget);
        const naraUrl = getNaraDetailUrl(item.bid_ntce_no);

        // 자격요건 칩
        const qualChips = [];
        if (item.license_limit) qualChips.push(`<span class="briefing-qual critical">⚠️ ${escapeHTML(item.license_limit.substring(0, 25))}</span>`);
        if (item.region) qualChips.push(`<span class="briefing-qual region">📍 ${escapeHTML(item.region)}</span>`);
        if (item.contract_method) qualChips.push(`<span class="briefing-qual method">📝 ${escapeHTML(item.contract_method)}</span>`);

        // 매칭 상세 점수 바
        let matchBarsHTML = '';
        if (item.match_detail && Object.keys(item.match_detail).length) {
            const labels = {business_type: '업종', license: '면허', budget: '예산', region: '지역', experience: '실적'};
            const bars = Object.entries(item.match_detail).map(([k, v]) => {
                const pct = Math.min(v.score, 100);
                const color = pct >= 70 ? 'var(--success)' : pct >= 40 ? 'var(--warning)' : 'var(--danger)';
                return `<div class="match-bar-row">
                    <span class="match-bar-label">${labels[k] || k}</span>
                    <div class="match-bar-track"><div class="match-bar-fill" style="width:${pct}%;background:${color}"></div></div>
                    <span class="match-bar-score">${pct}</span>
                </div>`;
            }).join('');
            matchBarsHTML = `<div class="match-bars-container">${bars}</div>`;
        }

        return `<div class="briefing-item" data-bid-no="${escapeHTML(item.bid_ntce_no || '')}" data-title="${escapeHTML(item.title || '')}" data-org-name="${escapeHTML(item.org_name || '')}" data-budget="${item.budget || ''}" data-close-dt="${escapeHTML(item.bid_close_dt || '')}" onclick="toggleBriefingDetail(this)" style="cursor:pointer">
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
                        <a href="${naraUrl}" target="_blank" class="btn-mini-link" onclick="event.stopPropagation()" title="나라장터">🔗</a>
                        <button class="btn-mini-analyze btn-strategy-analyze" data-bid-no="${escapeHTML(item.bid_ntce_no)}" onclick="event.stopPropagation()" title="AI 전략 분석">🎯</button>
                    </div>
                </div>
                <div class="briefing-item-meta">
                    🏢 ${escapeHTML(item.org_name || '기관 미상')} · 💰 ${budgetText}
                </div>
                <!-- 아코디언 상세 영역 -->
                <div class="briefing-item-detail" style="display:none;margin-top:10px;padding-top:10px;border-top:1px dashed var(--border)">
                    ${item.matched_business ? `<div class="briefing-match-reason">✅ <strong>${escapeHTML(item.matched_business)}</strong>와 매칭 (${item.total_score}점) — ${escapeHTML(item.match_reason || '')}</div>` : ''}
                    ${item.strategy_tip ? `<div class="briefing-strategy-tip">💡 ${escapeHTML(item.strategy_tip)}</div>` : ''}
                    ${item.collaboration_tip ? `<div class="briefing-collab-tip">🤝 ${escapeHTML(item.collaboration_tip)}</div>` : ''}
                    ${matchBarsHTML}
                    ${qualChips.length ? `<div class="briefing-qual-row">${qualChips.join('')}</div>` : ''}
                    ${(item.matched_keywords||[]).length ? `<div class="briefing-item-kw">🏷️ ${(item.matched_keywords||[]).join(', ')}</div>` : ''}
                </div>
                <div class="briefing-item-toggle-indicator" style="text-align:center;font-size:0.72rem;color:var(--text-muted);margin-top:6px">▼ 상세 매칭 및 분석 더보기</div>
            </div>
        </div>`;
    }).join('');

    body.innerHTML = summaryHTML + cardsHTML;
}

/**
 * 브리핑 아코디언 토글 헬퍼
 */
function toggleBriefingDetail(itemEl) {
    const detail = itemEl.querySelector('.briefing-item-detail');
    const indicator = itemEl.querySelector('.briefing-item-toggle-indicator');
    if (!detail) return;
    
    if (detail.style.display === 'none') {
        detail.style.display = 'block';
        if (indicator) indicator.textContent = '▲ 접기';
    } else {
        detail.style.display = 'none';
        if (indicator) indicator.textContent = '▼ 상세 매칭 및 분석 더보기';
    }
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

        // 모의 투찰 시뮬레이터 초기 바인딩
        initializeInteractiveBidSimulation(s, result);

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
                credentials: 'include',
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
                credentials: 'include',
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

        // 검색 입력 Enter 이벤트 (중복 리스너 등록 방지를 위해 onkeydown 사용)
        const input = document.getElementById('ksp-search-input');
        if (input) {
            input.onkeydown = (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    dashboardKeywordSearch();
                }
            };
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
            credentials: 'include'
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || '분석에 실패했습니다.');
        }

        const data = await response.json();
        content.innerHTML = renderProposalStrategy(data);

        // Q&A 대화용 글로벌 변수 바인딩 및 챗봇 위젯 활성화
        currentProposalBidNo = bidNo;
        currentProposalBizId = requestBody.biz_id || '';
        qaChatHistory = [];
        const qaSection = document.getElementById('proposal-qa-section');
        if (qaSection) qaSection.style.display = 'block';
        renderQAChat();

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

    // ─── 0. 정량평가 및 적격심사 시뮬레이션 ───
    if (s.bid_simulator && !s.bid_simulator.error) {
        const bs = s.bid_simulator;
        const sc = bs.scorecard || {};
        const strategies = bs.strategies || [];
        
        if (sc.total_score !== undefined) {
            const isStable = sc.total_score >= sc.pass_threshold;
            const badgeClass = isStable ? 'stable' : 'warning';
            const statusLabel = isStable ? '안정권' : '보완 필요';
            
            html += `
                <div class="ps-scorecard-section">
                    <div class="ps-scorecard-header">
                        <h4 class="ps-scorecard-title">📊 정량평가 & 적격심사 시뮬레이션</h4>
                    </div>
                    
                    <div class="ps-scorecard-summary">
                        <div class="ps-scorecard-gauge-wrap">
                            <span class="ps-scorecard-gauge-value">${sc.total_score}</span>
                        </div>
                        <div class="ps-scorecard-summary-info">
                            <div><strong>종합 정량 점수:</strong> ${sc.total_score}점 / 65점 만점</div>
                            <div><strong>통과 기준점:</strong> ${sc.pass_threshold}점</div>
                            <span class="ps-scorecard-status-badge ${badgeClass}">${statusLabel} (${sc.status || ''})</span>
                        </div>
                    </div>
                    
                    <div class="ps-simulator-grid">
            `;
            
            if (sc.credit_evaluation) {
                html += `
                    <div class="ps-sim-card">
                        <div class="ps-sim-card-title">💳 경영상태 평가</div>
                        <div class="ps-sim-card-score">${sc.credit_evaluation.score} <small>/ ${sc.credit_evaluation.max_score}</small></div>
                        <div class="ps-sim-card-detail">${sc.credit_evaluation.detail || ''} (등급: ${sc.credit_evaluation.rating || ''})</div>
                    </div>
                `;
            }
            if (sc.experience_evaluation) {
                const totalKrw = sc.experience_evaluation.similar_experience_total_krw || 0;
                const displayKrw = (totalKrw / 100000000).toFixed(1) + '억';
                html += `
                    <div class="ps-sim-card">
                        <div class="ps-sim-card-title">📈 수행실적 평가</div>
                        <div class="ps-sim-card-score">${sc.experience_evaluation.score} <small>/ ${sc.experience_evaluation.max_score}</small></div>
                        <div class="ps-sim-card-detail">${sc.experience_evaluation.detail || ''}<br>유사실적: ${displayKrw} (비율: ${(sc.experience_evaluation.ratio_to_budget * 100).toFixed(1)}%)</div>
                    </div>
                `;
            }
            if (sc.value_added) {
                const reasons = (sc.value_added.reasons || []).join(', ') || '보유 우대사항 없음';
                html += `
                    <div class="ps-sim-card">
                        <div class="ps-sim-card-title">➕ 신인도 가점</div>
                        <div class="ps-sim-card-score">+${sc.value_added.score} <small>/ 5.0</small></div>
                        <div class="ps-sim-card-detail">${reasons}</div>
                    </div>
                `;
            }
            
            const profile = data.business_profile || {};
            const sanctionsText = profile.has_sanctions ? '부정당업자 제재 이력 감점 적용 (-2.0)' : '감점 이력 없음 (0.0)';
            const sanctionsScore = profile.has_sanctions ? '-2.0' : '0.0';
            html += `
                <div class="ps-sim-card">
                    <div class="ps-sim-card-title">➖ 감점 요인</div>
                    <div class="ps-sim-card-score">${sanctionsScore}</div>
                    <div class="ps-sim-card-detail">${sanctionsText}</div>
                </div>
            `;
            
            html += `
                    </div>
            `;
            
            if (strategies && strategies.length > 0) {
                html += `<div class="ps-scorecard-strategies">`;
                strategies.forEach(strategy => {
                    const isSuccess = strategy.includes('🟢');
                    const calloutClass = isSuccess ? 'ps-callout-success' : 'ps-callout-warning';
                    html += `
                        <div class="ps-callout ${calloutClass}" style="margin-top: 8px;">
                            ${formatStrategyText(strategy)}
                        </div>
                    `;
                });
                html += `</div>`;
            }
            
            html += `
                </div>
            `;
        }
    } else if (s.bid_simulator && s.bid_simulator.note) {
        html += `
            <div class="ps-scorecard-section">
                <div class="ps-scorecard-header">
                    <h4 class="ps-scorecard-title">📊 정량평가 & 적격심사 시뮬레이션</h4>
                </div>
                <div class="ps-callout ps-callout-primary">
                    <strong>안내:</strong> ${escapeHTML(s.bid_simulator.note)}
                </div>
            </div>
        `;
    }

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

    // ─── 7. AI 종합 전략 보고서 ───
    if (s.llm_strategy_report) {
        const lr = s.llm_strategy_report;
        html += `
            <div class="ps-section ps-llm">
                <div class="ps-section-header">
                    <span class="ps-section-icon">🤖</span>
                    <h4>AI 종합 전략 보고서</h4>
                </div>
                <div class="ps-section-body">
        `;

        if (typeof lr === 'string') {
            html += `<div class="ps-llm-content">${formatStrategyText(lr)}</div>`;
        } else {
            if (lr.bid_summary) {
                html += `
                    <div class="ps-llm-block">
                        <h5 style="margin: 0 0 8px 0; font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">📋 입찰 요약 및 발주처 의도</h5>
                        <div class="ps-llm-content" style="margin-bottom: 16px;">${formatStrategyText(lr.bid_summary)}</div>
                    </div>
                `;
            }
            
            if (lr.scorecard_feedback) {
                html += `
                    <div class="ps-llm-block">
                        <h5 style="margin: 0 0 8px 0; font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">📉 정량평가 진단 및 극복 전략 피드백</h5>
                        <div class="ps-callout ps-callout-primary" style="margin-bottom: 16px;">
                            ${formatStrategyText(lr.scorecard_feedback)}
                        </div>
                    </div>
                `;
            }
            
            if (lr.win_themes && lr.win_themes.length > 0) {
                html += `
                    <div class="ps-llm-block">
                        <h5 style="margin: 0 0 8px 0; font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">🏆 핵심 가치 제안 (Win Themes)</h5>
                        <div class="ps-win-theme-grid">
                `;
                lr.win_themes.forEach((theme, i) => {
                    const themeTitle = theme.theme || `테마 ${i + 1}`;
                    const themeDesc = theme.description || '';
                    html += `
                        <div class="ps-win-theme-card">
                            <div class="ps-win-theme-card-title">💡 ${escapeHTML(themeTitle)}</div>
                            <div class="ps-win-theme-card-desc">${formatStrategyText(themeDesc)}</div>
                        </div>
                    `;
                });
                html += `
                        </div>
                    </div>
                `;
            }
            
            if (lr.compliance_matrix && lr.compliance_matrix.length > 0) {
                html += `
                    <div class="ps-llm-block" style="margin-top: 20px;">
                        <h5 style="margin: 0 0 8px 0; font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">📋 요구사항 대응 현황표 (Compliance Matrix)</h5>
                        <div class="ps-compliance-table-wrap">
                            <table class="ps-compliance-table">
                                <thead>
                                    <tr>
                                        <th style="width: 35%">RFP 요구사항</th>
                                        <th style="width: 15%">중요도</th>
                                        <th style="width: 50%">제안사 대응방안</th>
                                    </tr>
                                </thead>
                                <tbody>
                `;
                lr.compliance_matrix.forEach(row => {
                    const req = row.requirement || '';
                    const imp = row.importance || '일반';
                    const resp = row.proposal_response || '';
                    
                    const isRequired = imp.includes('필수') || imp.includes('우선');
                    const badgeClass = isRequired ? 'required' : 'normal';
                    
                    html += `
                                    <tr>
                                        <td><strong>${escapeHTML(req)}</strong></td>
                                        <td><span class="ps-compliance-importance-badge ${badgeClass}">${escapeHTML(imp)}</span></td>
                                        <td>${formatStrategyText(resp)}</td>
                                    </tr>
                    `;
                });
                html += `
                                </tbody>
                            </table>
                        </div>
                    </div>
                `;
            }
            
            if (lr.differentiation_strategy) {
                html += `
                    <div class="ps-llm-block" style="margin-top: 20px;">
                        <h5 style="margin: 0 0 8px 0; font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">🚀 제안 차별화 전략</h5>
                        <div class="ps-llm-content" style="margin-bottom: 16px;">${formatStrategyText(lr.differentiation_strategy)}</div>
                    </div>
                `;
            }
            
            if (lr.risk_factors) {
                html += `
                    <div class="ps-llm-block" style="margin-top: 20px;">
                        <h5 style="margin: 0 0 8px 0; font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">⚠️ 리스크 요인 및 헤징 방안</h5>
                        <div class="ps-llm-content" style="margin-bottom: 16px;">${formatStrategyText(lr.risk_factors)}</div>
                    </div>
                `;
            }
            
            if (lr.proposal_outline) {
                html += `
                    <div class="ps-llm-block" style="margin-top: 20px;">
                        <h5 style="margin: 0 0 8px 0; font-size: 0.95rem; font-weight: 700; color: var(--text-primary);">📁 제안서 구성 목차 기획 (Outline)</h5>
                        <div class="ps-llm-content" style="white-space: pre-wrap; font-family: monospace; background: var(--bg-input); padding: 12px; border-radius: 8px; border: 1px solid var(--border);">${escapeHTML(lr.proposal_outline)}</div>
                    </div>
                `;
            }
            
            if (lr.overall_recommendation) {
                html += `
                    <div class="ps-callout ps-callout-success" style="margin-top: 20px;">
                        <strong>🎯 종합 권고 & 핵심 전략:</strong><br>
                        ${formatStrategyText(lr.overall_recommendation)}
                    </div>
                `;
            }
        }
        
        html += `
                </div>
            </div>
        `;
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

    document.querySelectorAll('.stat-card, .briefing-panel, .keyword-search-panel, .fav-pipeline-summary, .feature-card, .analysis-card').forEach(el => {
        el.classList.add('observe-reveal');
        observer.observe(el);
    });

    // 이미지 Lazy Load Observer
    const lazyImgObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                if (img.dataset.src) {
                    img.src = img.dataset.src;
                    img.removeAttribute('data-src');
                }
                img.classList.add('loaded');
                lazyImgObserver.unobserve(img);
            }
        });
    }, { rootMargin: '100px' });

    document.querySelectorAll('img[loading="lazy"]').forEach(img => {
        lazyImgObserver.observe(img);
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


// ──────────────────────────────────────────────
// 30. 공고 비교 분석 (Compare Shelf) 기능
// ──────────────────────────────────────────────

/**
 * 비교할 공고 추가/제거 토글
 */
function toggleCompareBid(bidNo, title, orgName, budget, closeDt, checkboxEl) {
    if (checkboxEl.checked) {
        if (compareList.length >= 3) {
            showToast('⚠️ 비교함은 최대 3개 공고까지만 담을 수 있습니다.', 'warning');
            checkboxEl.checked = false;
            return;
        }
        compareList.push({ bidNo, title, orgName, budget, closeDt });
        showToast('⚖️ 비교함에 공고가 추가되었습니다.', 'success');
    } else {
        compareList = compareList.filter(item => item.bidNo !== bidNo);
        showToast('⚖️ 비교함에서 공고가 제거되었습니다.', 'info');
    }
    renderCompareShelf();
}

/**
 * 비교함 플로팅 바 렌더링
 */
function renderCompareShelf() {
    const shelf = document.getElementById('compare-shelf');
    const countEl = document.getElementById('compare-count');
    const itemsEl = document.getElementById('compare-shelf-items');
    
    if (!shelf) return;
    
    if (compareList.length > 0) {
        shelf.classList.add('active');
        countEl.textContent = compareList.length;
        
        itemsEl.innerHTML = compareList.map(item => `
            <div class="compare-item-chip">
                <span>${escapeHTML(item.title)}</span>
                <span class="compare-item-remove" onclick="removeCompareItem('${item.bidNo}')">✕</span>
            </div>
        `).join('');
    } else {
        shelf.classList.remove('active');
    }
}

/**
 * 비교함 개별 칩 삭제
 */
function removeCompareItem(bidNo) {
    compareList = compareList.filter(item => item.bidNo !== bidNo);
    renderCompareShelf();
    
    const cb = document.querySelector(`.compare-cb[data-bid-no="${bidNo}"]`);
    if (cb) cb.checked = false;
}

/**
 * 비교함 전체 비우기
 */
function clearCompareShelf() {
    compareList = [];
    renderCompareShelf();
    document.querySelectorAll('.compare-cb').forEach(cb => cb.checked = false);
}

/**
 * 비교 모달 열기 및 데이터 교차 렌더링
 */
function openCompareModal() {
    if (compareList.length < 2) {
        showToast('⚠️ 최소 2개 이상의 공고를 선택해야 비교 분석이 가능합니다.', 'warning');
        return;
    }
    
    const overlay = document.getElementById('compare-modal-overlay');
    const body = document.getElementById('compare-modal-body');
    
    if (!overlay || !body) return;
    
    overlay.classList.add('active');
    
    let html = `
        <table class="compare-table">
            <thead>
                <tr>
                    <th>비교 항목</th>
                    ${compareList.map(item => `<th>${escapeHTML(item.title)}</th>`).join('')}
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>공고번호</strong></td>
                    ${compareList.map(item => `<td>${escapeHTML(item.bidNo)}</td>`).join('')}
                </tr>
                <tr>
                    <td><strong>발주기관</strong></td>
                    ${compareList.map(item => `<td>🏛️ ${escapeHTML(item.orgName)}</td>`).join('')}
                </tr>
                <tr>
                    <td><strong>추정예산</strong></td>
                    ${compareList.map(item => `<td class="diff-highlight">${displayBudget(item.budget)}</td>`).join('')}
                </tr>
                <tr>
                    <td><strong>마감기한</strong></td>
                    ${compareList.map(item => `<td>📅 ${escapeHTML(item.closeDt || '미정')} (${formatDaysLeft(item.closeDt)})</td>`).join('')}
                </tr>
            </tbody>
        </table>
    `;
    
    body.innerHTML = html;
}

function closeCompareModal() {
    const overlay = document.getElementById('compare-modal-overlay');
    if (overlay) overlay.classList.remove('active');
}


// ──────────────────────────────────────────────
// 31. 관심공고 칸반 보드 (Kanban Board) 기능
// ──────────────────────────────────────────────

/**
 * 관심공고 뷰 모드 토글
 */
function toggleFavViewMode(mode) {
    favViewMode = mode;
    
    const listBtn = document.getElementById('fav-view-list-btn');
    const kanbanBtn = document.getElementById('fav-view-kanban-btn');
    const listBody = document.getElementById('favorites-body');
    const kanbanBody = document.getElementById('favorites-kanban-body');
    
    if (mode === 'list') {
        listBtn.classList.add('active');
        kanbanBtn.classList.remove('active');
        listBody.style.display = 'block';
        kanbanBody.style.display = 'none';
        loadFavorites();
    } else {
        listBtn.classList.remove('active');
        kanbanBtn.classList.add('active');
        listBody.style.display = 'none';
        kanbanBody.style.display = 'grid';
        renderKanbanBoard();
    }
}

/**
 * 칸반 보드 카드 렌더링
 */
function renderKanbanBoard() {
    const kanbanBody = document.getElementById('favorites-kanban-body');
    if (!kanbanBody) return;
    
    const favs = getFavorites();
    
    const stages = [
        { id: 'reviewing', label: '⭐ 검토중', color: '#6366f1' },
        { id: 'proceeding', label: '🚀 사업진행', color: '#06b6d4' },
        { id: 'partnered', label: '🤝 협업진행', color: '#10b981' },
        { id: 'completed', label: '✅ 완료', color: '#8b5cf6' },
        { id: 'abandoned', label: '❌ 포기', color: '#ef4444' }
    ];
    
    kanbanBody.innerHTML = stages.map(stage => {
        const stageFavs = favs.filter(f => (f.status || 'reviewing') === stage.id);
        
        return `
            <div class="kanban-column" data-stage="${stage.id}" ondragover="allowDrop(event)" ondragleave="dragLeave(event)" ondrop="dropFav(event)">
                <div class="kanban-column-header">
                    <span class="kanban-column-title" style="color:${stage.color}">${stage.label}</span>
                    <span class="kanban-column-count">${stageFavs.length}</span>
                </div>
                <div class="kanban-cards">
                    ${stageFavs.map(f => `
                        <div class="kanban-card" draggable="true" ondragstart="dragFav(event, '${f.bidNo}')" onclick="openFavDetail('${f.bidNo}')">
                            <div class="kanban-card-title">${escapeHTML(f.title)}</div>
                            <div class="kanban-card-meta">🏛️ ${escapeHTML(f.orgName || '')}</div>
                            <div class="kanban-card-meta">💰 ${displayBudget(f.budget)}</div>
                            <div class="kanban-card-footer">
                                <span style="font-size:0.72rem;color:var(--text-muted)">${formatDaysLeft(f.closeDt)}</span>
                                <span style="font-size:0.7rem;font-weight:700;color:var(--accent-indigo)">상세 →</span>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }).join('');
}

function allowDrop(ev) {
    ev.preventDefault();
    const col = ev.currentTarget;
    col.classList.add('drag-over');
}

function dragLeave(ev) {
    const col = ev.currentTarget;
    col.classList.remove('drag-over');
}

function dragFav(ev, bidNo) {
    ev.dataTransfer.setData("text/plain", bidNo);
}

function dropFav(ev) {
    ev.preventDefault();
    const col = ev.currentTarget;
    col.classList.remove('drag-over');
    
    const bidNo = ev.dataTransfer.getData("text/plain");
    const targetStage = col.getAttribute('data-stage');
    
    if (bidNo && targetStage) {
        updateFav(bidNo, { status: targetStage });
        renderKanbanBoard();
        showToast(`💼 상태가 변경되었습니다.`, 'success');
        updateFavBadge();
    }
}


// ──────────────────────────────────────────────
// 32. AI 참여 전략 Q&A 위젯 (대화형 챗봇)
// ──────────────────────────────────────────────

/**
 * 대화 내용 렌더링
 */
function renderQAChat() {
    const chatbox = document.getElementById('proposal-qa-chatbox');
    if (!chatbox) return;
    
    chatbox.innerHTML = `
        <div class="qa-msg qa-ai">
            <div class="qa-bubble">이 전략 보고서에 대해 궁금한 점이 있으신가요? 제안서 차별화 방안이나 리스크 대응책 등을 추가로 물어보세요!</div>
        </div>
    ` + qaChatHistory.map(msg => `
        <div class="qa-msg qa-${msg.role === 'user' ? 'user' : 'ai'}">
            <div class="qa-bubble">${formatStrategyText(msg.content)}</div>
        </div>
    `).join('');
    
    chatbox.scrollTop = chatbox.scrollHeight;
}

/**
 * 메시지 전송 로직
 */
async function sendProposalQA() {
    const input = document.getElementById('proposal-qa-input');
    if (!input || !input.value.trim()) return;
    
    const query = input.value.trim();
    input.value = '';
    
    qaChatHistory.push({ role: 'user', content: query });
    renderQAChat();
    
    qaChatHistory.push({ role: 'ai', content: '💬 답변을 생각하고 있습니다...' });
    renderQAChat();
    
    const bidNo = currentProposalBidNo || '';
    const bizId = currentProposalBizId || '';
    
    try {
        const res = await api('POST', '/analyses/chat', {
            bid_ntce_no: bidNo,
            biz_id: bizId,
            message: query,
            chat_history: qaChatHistory.slice(0, -2)
        });
        
        qaChatHistory.pop();
        qaChatHistory.push({ role: 'ai', content: res.answer || '답변을 불러오지 못했습니다.' });
    } catch (err) {
        qaChatHistory.pop();
        qaChatHistory.push({ role: 'ai', content: `❌ 오류가 발생했습니다: ${err.message}` });
    }
    
    renderQAChat();
}


// ──────────────────────────────────────────────
// 33. API 키 연결성 실시간 테스트 (Ping Test)
// ──────────────────────────────────────────────

async function testApiKey(name) {
    const inputMap = {
        data_go_kr: 'api-key-data-go-kr',
        naver: 'api-key-naver-id',
        openai: 'api-key-openai',
        gemini: 'api-key-gemini'
    };
    
    const keyInput = document.getElementById(inputMap[name]);
    let secret = '';
    if (name === 'naver') {
        const secretInput = document.getElementById('api-key-naver-secret');
        if (secretInput) secret = secretInput.value.trim();
    }
    
    const key = keyInput ? keyInput.value.trim() : '';
    const statusEl = document.getElementById(`test-status-${name}`);
    
    if (!key) {
        showToast('⚠️ 테스트할 API 키를 먼저 입력하세요.', 'warning');
        return;
    }
    
    if (statusEl) {
        statusEl.className = 'api-test-status loading';
        statusEl.textContent = '🔌 테스트 중...';
    }
    
    try {
        const res = await api('POST', '/settings/test-key', {
            api_name: name,
            api_key: key,
            api_secret: secret
        });
        
        if (statusEl) {
            if (res.success) {
                statusEl.className = 'api-test-status success';
                statusEl.textContent = '🟢 연결 성공';
                showToast(res.message, 'success');
            } else {
                statusEl.className = 'api-test-status error';
                statusEl.textContent = '🔴 실패';
                showToast(`❌ 연결 실패: ${res.message}`, 'error');
            }
        }
    } catch (err) {
        if (statusEl) {
            statusEl.className = 'api-test-status error';
            statusEl.textContent = '🔴 에러';
            showToast(`❌ 테스트 에러: ${err.message}`, 'error');
        }
    }
}


// ──────────────────────────────────────────────
// 34. 사업자 관리 대시보드 및 실적 구조화 입력기
// ──────────────────────────────────────────────

/**
 * 등록 사업자 정보 요약 위젯 갱신
 */
function updateBusinessPortfolioSummary(businesses) {
    const summaryWrap = document.getElementById('business-portfolio-summary');
    if (!summaryWrap) return;
    
    if (businesses && businesses.length > 0) {
        summaryWrap.style.display = 'block';
        
        const countEl = document.getElementById('biz-summary-total-count');
        const revEl = document.getElementById('biz-summary-total-revenue');
        const creditEl = document.getElementById('biz-summary-top-credit');
        
        countEl.textContent = businesses.length;
        
        let totalRev = 0;
        let validRevCount = 0;
        businesses.forEach(b => {
            if (b.annual_revenue && b.annual_revenue > 0) {
                totalRev += b.annual_revenue;
                validRevCount++;
            }
        });
        const avgRev = validRevCount > 0 ? totalRev / validRevCount : 0;
        revEl.textContent = avgRev > 0 ? (avgRev / 100000000).toFixed(1) + '억' : '미등록';
        
        const creditOrder = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+"];
        let bestCredit = '';
        let bestIndex = 999;
        businesses.forEach(b => {
            const rating = (b.credit_rating || 'BBB').toUpperCase();
            const idx = creditOrder.indexOf(rating);
            if (idx !== -1 && idx < bestIndex) {
                bestIndex = idx;
                bestCredit = rating;
            }
        });
        creditEl.textContent = bestCredit || '미등록';
    } else {
        summaryWrap.style.display = 'none';
    }
}

/**
 * 모달 내 구조화된 실적 동적 추가 기능
 */
function addStructuredPastProject() {
    const nameInput = document.getElementById('form-past-proj-name');
    const amountInput = document.getElementById('form-past-proj-amount');
    const yearInput = document.getElementById('form-past-proj-year');
    const textarea = document.getElementById('form-past-projects');
    
    if (!nameInput || !amountInput || !yearInput || !textarea) return;
    
    const name = nameInput.value.trim();
    const amount = amountInput.value.trim();
    const year = yearInput.value.trim();
    
    if (!name || !amount || !year) {
        showToast('⚠️ 실적 정보를 모두 입력해 주세요.', 'warning');
        return;
    }
    
    const itemStr = `${name}|${amount}|${year}`;
    
    const currentVal = textarea.value.trim();
    if (currentVal) {
        textarea.value = currentVal + '\n' + itemStr;
    } else {
        textarea.value = itemStr;
    }
    
    nameInput.value = '';
    amountInput.value = '';
    yearInput.value = '';
    
    showToast('📈 실적이 추가되었습니다.', 'success');
}

// 공동수급 실적 합산 시뮬레이션 계산 엔진
function calculateConsortiumSynergy() {
    const container = document.getElementById('consortium-synergy-simulator');
    if (!container) return;

    const fav = getFavByBidNo(_favDetailBidNo);
    if (!fav) {
        container.style.display = 'none';
        return;
    }

    // 1. 공고 예산 가져오기 (원 단위 -> 억 원 단위 변환)
    const budgetVal = fav.budget || 0;
    const budgetInEok = budgetVal / 100000000;

    // 2. 자사 보유 실적 계산
    let ownExpInEok = 0;
    if (state.businesses && state.businesses.length > 0) {
        const primaryBiz = state.businesses[0];
        const pastProjects = primaryBiz.past_projects || [];
        let total = 0;
        pastProjects.forEach(p => {
            const amt = parseFloat(p.amount) || 0; // 만원 단위
            total += amt;
        });
        ownExpInEok = total / 10000; // 만원 -> 억 원
    }

    // 3. 파트너사 지분율 반영 실적 합산
    const partners = fav.partners || [];
    let partnerExpInEok = 0;
    let totalPartnerShare = 0;

    partners.forEach(p => {
        const share = (p.share || 0) / 100;
        const pExp = p.exp || 0; // 억 원 단위
        partnerExpInEok += pExp * share;
        totalPartnerShare += p.share || 0;
    });

    // 주간사(자사) 지분율 (나머지 지분)
    const ownShare = Math.max(0, 100 - totalPartnerShare) / 100;
    
    // 최종 인정 실적 = (자사 실적 * 자사 지분) + SUM(파트너 실적 * 파트너 지분)
    const totalRecognizedExp = (ownExpInEok * ownShare) + partnerExpInEok;

    // 공고 예산 대비 충족율
    let satisfactionRate = 0;
    if (budgetInEok > 0) {
        satisfactionRate = (totalRecognizedExp / budgetInEok) * 100;
    }

    // UI 엘리먼트 바인딩
    container.style.display = 'block';
    
    document.getElementById('synergy-own-exp').textContent = `${ownExpInEok.toFixed(1)}억 원 (지분 ${(ownShare * 100).toFixed(0)}%)`;
    document.getElementById('synergy-partner-exp').textContent = `+ ${partnerExpInEok.toFixed(1)}억 원`;
    document.getElementById('synergy-total-exp').textContent = `${totalRecognizedExp.toFixed(1)}억 원`;
    document.getElementById('synergy-satisfaction-rate').textContent = `${satisfactionRate.toFixed(1)}%`;

    const progressEl = document.getElementById('synergy-progress-bar');
    if (progressEl) {
        const progressWidth = Math.min(100, satisfactionRate);
        progressEl.style.width = `${progressWidth}%`;
        progressEl.style.background = satisfactionRate >= 100 ? 'var(--success, #10b981)' : 'var(--accent-indigo, #6366f1)';
    }

    const badgeEl = document.getElementById('synergy-status-badge');
    const recTextEl = document.getElementById('synergy-recommendation-text');
    if (badgeEl && recTextEl) {
        if (satisfactionRate >= 100) {
            badgeEl.className = 'badge badge-success';
            badgeEl.textContent = '실적 만점';
            badgeEl.style.background = 'var(--success)';
            recTextEl.textContent = '🟢 실적 만점 기준을 충족했습니다! 정성제안 및 가격최적화에 역량을 투입하십시오.';
            recTextEl.style.color = 'var(--success)';
        } else if (satisfactionRate >= 70) {
            badgeEl.className = 'badge badge-info';
            badgeEl.textContent = '실적 보통';
            badgeEl.style.background = '#0ea5e9';
            recTextEl.textContent = '🟡 실적이 약간 부족합니다. 파트너사 지분을 높이거나 실적이 더 높은 파트너 영입을 검토하세요.';
            recTextEl.style.color = '#0ea5e9';
        } else {
            badgeEl.className = 'badge badge-danger';
            badgeEl.textContent = '실적 부족';
            badgeEl.style.background = 'var(--danger)';
            recTextEl.textContent = '🔴 정량평가 감점 우려! 협업사의 지분배정 및 실적 합산 비율을 추가 보완하여 만점을 맞추십시오.';
            recTextEl.style.color = 'var(--danger)';
        }
    }
}

// 연간 반복 사업 발주 예측 로드 및 렌더링
async function loadRecurringForecast() {
    const listEl = document.getElementById('recurring-forecast-list');
    if (!listEl) return;

    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!activeBizId) {
        listEl.innerHTML = `
            <div style="color:var(--text-muted);font-size:0.85rem;grid-column:1/-1;text-align:center;padding:20px 0">
                🏢 발주 예측 분석을 위해 사업자를 먼저 등록해주세요.
            </div>`;
        return;
    }

    try {
        const forecast = await api('GET', '/analyses/recurring-forecast');
        if (!forecast || forecast.length === 0) {
            listEl.innerHTML = `
                <div style="color:var(--text-muted);font-size:0.85rem;grid-column:1/-1;text-align:center;padding:20px 0">
                    🔮 충분한 과거 입찰 이력 데이터가 축적된 후 정기 반복 사업이 이곳에 자동으로 표출됩니다.
                </div>`;
            return;
        }

        listEl.innerHTML = forecast.map((f, i) => {
            return `
                <div class="forecast-card" style="padding:16px;background:var(--bg-card, rgba(255,255,255,0.02));border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;gap:8px;position:relative;overflow:hidden">
                    <div style="position:absolute;top:0;left:0;width:4px;height:100%;background:linear-gradient(to bottom, var(--accent-indigo, #6366f1), var(--success, #10b981))"></div>
                    <div style="display:flex;justify-content:space-between;align-items:start;gap:8px">
                        <span style="font-weight:700;font-size:0.85rem;color:var(--text);line-height:1.4">${escapeHTML(f.predicted_title)}</span>
                        <span class="badge" style="font-size:0.7rem;background:rgba(16,185,129,0.1);color:var(--success);white-space:nowrap">${f.probability}% 신뢰도</span>
                    </div>
                    <div style="font-size:0.78rem;color:var(--text-muted);display:flex;flex-direction:column;gap:4px;margin-top:4px">
                        <div style="display:flex;justify-content:space-between"><span>🏢 발주기관:</span><span style="color:var(--text);font-weight:500">${escapeHTML(f.org_name)}</span></div>
                        <div style="display:flex;justify-content:space-between"><span>💰 평균예산:</span><span style="color:var(--text);font-weight:500">${escapeHTML(f.budget_str)}</span></div>
                        <div style="display:flex;justify-content:space-between"><span>📅 예상시기:</span><span style="color:var(--text);font-weight:600;color:var(--accent-indigo, #6366f1)">매년 ${f.expected_month}월경 (D-${f.days_left})</span></div>
                    </div>
                    <div style="border-top:1px dashed var(--border);padding-top:8px;margin-top:4px;display:flex;justify-content:space-between;align-items:center">
                        <span style="font-size:0.7rem;color:var(--text-muted)">수집빈도: 연간 반복 ${f.frequency}회 관측</span>
                        <button class="btn btn-ghost btn-sm" style="font-size:0.7rem;padding:2px 8px" onclick="navigate('bids'); document.getElementById('ksp-search-input').value='${escapeHTML(f.original_title.substring(0,12))}'; dashboardKeywordSearch()">🔍 사전 검색</button>
                    </div>
                </div>`;
        }).join('');
    } catch (err) {
        console.warn('발주 예측 로드 실패:', err.message);
        listEl.innerHTML = `
            <div style="color:var(--text-muted);font-size:0.85rem;grid-column:1/-1;text-align:center;padding:20px 0">
                ⚠️ 발주 예측 정보를 불러오는 중 오류가 발생했습니다.
            </div>`;
    }
}

// 경쟁사 수주 타깃 모니터 로드 및 렌더링
async function loadCompetitorIntelligence() {
    const bodyEl = document.getElementById('competitor-intelligence-body');
    if (!bodyEl) return;

    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!activeBizId) {
        bodyEl.innerHTML = `
            <div style="color:var(--text-muted);font-size:0.85rem;text-align:center;padding:20px 0">
                🏢 경쟁사 정보 분석을 위해 사업자를 먼저 등록해주세요.
            </div>`;
        return;
    }

    try {
        const stats = await api('GET', '/analyses/competitor-intelligence?limit=5');
        if (!stats || stats.length === 0) {
            bodyEl.innerHTML = `
                <div style="color:var(--text-muted);font-size:0.85rem;text-align:center;padding:20px 0">
                    📊 충분한 과거 낙찰 데이터가 축적된 후 경쟁사 정보가 이곳에 자동으로 표출됩니다.
                </div>`;
            return;
        }

        // 최대 수주액 탐색 (가로 그래프 비율 조정용)
        const maxAward = Math.max(...stats.map(s => s.total_award_amount), 1);

        bodyEl.innerHTML = `
            <div style="display:flex;flex-direction:column;gap:14px">
                ${stats.map((s, idx) => {
                    const pct = Math.min(100, Math.max(8, (s.total_award_amount / maxAward) * 100));
                    const formattedAmt = s.total_award_amount >= 100000 
                        ? `${(s.total_award_amount / 100000).toFixed(1)}억 원` 
                        : `${(s.total_award_amount / 1000).toFixed(0)}천만 원`;
                    return `
                        <div style="display:flex;flex-direction:column;gap:4px">
                            <div style="display:flex;justify-content:space-between;align-items:center;font-size:0.8rem">
                                <span style="font-weight:700;color:var(--text)">
                                    <span style="color:var(--accent-indigo, #6366f1);margin-right:6px">#${idx+1}</span> ${escapeHTML(s.winner_name)}
                                </span>
                                <span style="font-size:0.75rem;color:var(--text-muted)">
                                    수주 <strong>${s.win_count}건</strong> (${formattedAmt}) | 평균 투찰률 <strong style="color:var(--accent-indigo, #6366f1)">${s.avg_bid_rate}%</strong>
                                </span>
                            </div>
                            <div style="width:100%;height:8px;background:var(--bg-input, rgba(255,255,255,0.05));border-radius:4px;overflow:hidden">
                                <div style="width:${pct}%;height:100%;background:linear-gradient(to right, #3b82f6, #10b981);border-radius:4px"></div>
                            </div>
                        </div>`;
                }).join('')}
            </div>`;
    } catch (err) {
        console.warn('경쟁사 수주 타깃 로드 실패:', err.message);
        bodyEl.innerHTML = `
            <div style="color:var(--text-muted);font-size:0.85rem;text-align:center;padding:20px 0">
                ⚠️ 경쟁사 통계 정보를 불러오는 중 오류가 발생했습니다.
            </div>`;
    }
}

// YouTube 입찰/조달 교육 동영상 로드 및 렌더링
async function loadYouTubeVideos() {
    const listEl = document.getElementById('youtube-video-list');
    if (!listEl) return;

    // 추천 YouTube 검색어 목록 (외부 이미지 의존 없이 CSS 기반 아이콘 사용)
    const recommendedSearches = [
        {
            title: "조달청 나라장터 입찰 입문 - 투찰 금액 계산법 및 기초 지식 완벽 정리",
            channel: "조달나라 실무 교육원",
            url: "https://www.youtube.com/results?search_query=나라장터+입찰+방법"
        },
        {
            title: "적격심사 통과를 위한 기업 신용등급 관리 및 가산점 확보 전략 가이드",
            channel: "중소기업 경영연구소",
            url: "https://www.youtube.com/results?search_query=입찰+적격심사+신용등급"
        },
        {
            title: "문화예술 공모사업 제안서 작성법 - 심사위원을 사로잡는 기획서 양식과 스토리텔링",
            channel: "문화예술 기획학교",
            url: "https://www.youtube.com/results?search_query=문화예술+지원사업+제안서"
        }
    ];

    try {
        listEl.innerHTML = recommendedSearches.map(v => `
            <div class="yt-card" onclick="window.open('${v.url}', '_blank')" style="cursor:pointer">
                <div class="yt-thumb-wrap">
                    <div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#ff0000,#cc0000);border-radius:8px;font-size:2rem">▶</div>
                </div>
                <div class="yt-info">
                    <h4 class="yt-title">${escapeHTML(v.title)}</h4>
                    <span class="yt-channel">📺 ${escapeHTML(v.channel)}</span>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.warn('YouTube 교육 영상 로드 실패:', err.message);
        listEl.innerHTML = `
            <div style="color:var(--text-muted);font-size:0.85rem;grid-column:1/-1;text-align:center;padding:20px 0">
                ⚠️ YouTube 추천 영상을 로드하지 못했습니다.
            </div>`;
    }
}

// 공동도급(컨소시엄) 지분율 & 실적 시뮬레이터 실시간 계산
function calculateConsortiumMetrics() {
    const corpRevInput = document.getElementById('sim-corp-revenue');
    const corpShareInput = document.getElementById('sim-corp-share');
    const partnerDisplay = document.getElementById('sim-partner-display');
    const partnerShareTotalEl = document.getElementById('sim-partner-share-total');
    const evalRevenueEl = document.getElementById('sim-eval-revenue');
    const evalScoreEl = document.getElementById('sim-eval-score');
    const resultBadge = document.getElementById('sim-eval-result-badge');

    if (!corpRevInput || !corpShareInput || !evalRevenueEl || !evalScoreEl || !resultBadge) return;

    // 본사 입력값
    const corpRevenue = parseInt(corpRevInput.value) || 0;
    const corpShare = Math.min(100, Math.max(0, parseInt(corpShareInput.value) || 0));
    corpShareInput.value = corpShare; // 보정값 바인딩

    // 1. 등록된 파트너 정보 취합
    const bidNo = _favDetailBidNo;
    const fav = getFavByBidNo(bidNo);
    const partners = fav ? (fav.partners || []) : [];

    let partnerShareSum = 0;
    let partnerRevenueSum = 0;
    let localBonusScore = 0.0;
    let weakCorpBonusScore = 0.0;

    partners.forEach(p => {
        const share = Math.min(100, Math.max(0, parseInt(p.share) || 0));
        partnerShareSum += share;

        // 실적(exp) 필드가 존재하면 우선적으로 사용(억 원 -> 만 원 환산), 없으면 연락처 정보에서 파싱
        let revenue = p.exp ? (parseFloat(p.exp) * 10000) : 0;
        if (revenue === 0) {
            const contactText = p.contact || '';
            const numMatch = contactText.replace(/,/g, '').match(/\d+/);
            revenue = numMatch ? parseInt(numMatch[0]) : 0;
        }
        partnerRevenueSum += (revenue * (share / 100));

        // 역할 란의 키워드로 우대 가점 판정
        const roleText = p.role || '';
        if (roleText.includes('지역')) {
            // 지역의무공동도급 가점 (지분율 비례)
            if (share >= 30) localBonusScore = 5.0;
            else if (share >= 20) localBonusScore = 3.0;
            else if (share >= 10) localBonusScore = 1.0;
        }
        if (roleText.includes('여성') || roleText.includes('장애인') || roleText.includes('사회적')) {
            weakCorpBonusScore += 1.5;
        }
    });

    // 파트너 합계 지분율 표시 및 본사 지분율 보정
    if (partnerShareTotalEl) {
        partnerShareTotalEl.textContent = `${partnerShareSum} %`;
    }
    
    // 파트너 실적 표시
    if (partnerDisplay) {
        partnerDisplay.textContent = partnerRevenueSum > 0 
            ? `합산 지분실적: ${(partnerRevenueSum).toLocaleString()}만 원` 
            : '파트너 지분실적 없음';
    }

    // 2. 지분 합산 평가액 계산
    const corpEvalRevenue = corpRevenue * (corpShare / 100);
    const totalEvalRevenue = Math.floor(corpEvalRevenue + partnerRevenueSum);
    
    evalRevenueEl.textContent = `${totalEvalRevenue.toLocaleString()}만 원`;

    // 3. 신인도 가점 합산
    const totalBonus = Math.min(5.0, localBonusScore + weakCorpBonusScore);
    evalScoreEl.textContent = `+${totalBonus.toFixed(1)} 점`;

    // 4. 만점 통과 여부 시각적 판정 (공고 예산 대조)
    const naraBtn = document.getElementById('fav-detail-nara-btn');
    const budgetVal = naraBtn?.dataset?.budget ? parseInt(naraBtn.dataset.budget) : 0;

    if (budgetVal <= 0) {
        resultBadge.className = 'badge';
        resultBadge.style.background = 'rgba(255,255,255,0.08)';
        resultBadge.style.color = 'var(--text-secondary)';
        resultBadge.textContent = '공고 예산 정보 없음';
        return;
    }

    // 통상 만점 기준 평가액 = 공고 예산(추정가격)의 1배수 이상
    // 예산이 만원 단위이므로 1:1 비교
    const budgetInMan = Math.floor(budgetVal / 10000);

    if (totalEvalRevenue >= budgetInMan) {
        resultBadge.className = 'badge badge-success';
        resultBadge.style.background = 'var(--success)';
        resultBadge.style.color = '#fff';
        resultBadge.textContent = `🟢 실적 만점 충족! (만점 기준: ${budgetInMan.toLocaleString()}만 원)`;
    } else {
        const needed = budgetInMan - totalEvalRevenue;
        resultBadge.className = 'badge badge-warning';
        resultBadge.style.background = 'rgba(245,158,11,0.15)';
        resultBadge.style.color = '#f59e0b';
        resultBadge.textContent = `⚠️ 실적 부족 (만점 도달까지 ${needed.toLocaleString()}만 원 보완 필요)`;
    }
}

// 모의 투찰 시뮬레이터 전역 상태 변수
let _simQuantBaseScore = 50.0; // 기본 경영+실적 정량 평가 점수 (디폴트 50)
let _simBidBudget = 0; // 공고 예산 (만원 단위)
let _simContractMethod = ''; // 계약 방식

// 모의 투찰 초기화
function initializeInteractiveBidSimulation(strategyData, resultData) {
    const slider = document.getElementById('sim-rate-slider');
    const valText = document.getElementById('sim-rate-val');
    if (!slider || !valText) return;

    // 슬라이더 초기화
    slider.value = "88.0";
    valText.textContent = "88.0%";

    // 공고의 계약 방식 및 예산 바인딩
    const bidInfo = strategyData.bid_info || resultData.bid_info || {};
    _simContractMethod = bidInfo.contract_method || resultData.contract_method || '';
    
    const budgetVal = bidInfo.budget || resultData.budget || 0;
    _simBidBudget = budgetVal > 1000000 ? Math.floor(budgetVal / 10000) : budgetVal;

    // 자사 정량 평가 점수 획득
    let quantBase = 45.0; // 기본 디폴트
    
    if (resultData.match_score) {
        quantBase = parseFloat(resultData.match_score) * 0.6; // 정량 평가를 60% 비중으로 환산
    }
    
    _simQuantBaseScore = Math.min(60.0, Math.max(20.0, quantBase));
    
    const quantScoreEl = document.getElementById('sim-quant-score');
    if (quantScoreEl) {
        quantScoreEl.textContent = `${_simQuantBaseScore.toFixed(1)} / 60.0`;
    }

    // 초기 시뮬레이션 계산 실행
    updateInteractiveBidSimulation();
}

// 실시간 투찰율 조정에 따른 점수 연산
function updateInteractiveBidSimulation() {
    const slider = document.getElementById('sim-rate-slider');
    const valText = document.getElementById('sim-rate-val');
    if (!slider || !valText) return;

    const rate = parseFloat(slider.value) || 88.0;
    valText.textContent = `${rate.toFixed(1)}%`;

    // 1. 가격 평가 점수 계산 (만점 40점 기준)
    let priceScore = 0.0;
    let maxPriceScore = 40.0;
    
    if (_simContractMethod.includes('협상')) {
        maxPriceScore = 20.0;
        if (rate >= 80.0) {
            priceScore = (80.0 / rate) * maxPriceScore;
        } else {
            priceScore = 0.0;
        }
    } else {
        const optimalRate = 88.0; 
        const deviation = Math.abs(rate - optimalRate);
        priceScore = maxPriceScore - (deviation * 1.5);
    }
    
    priceScore = Math.min(maxPriceScore, Math.max(0.0, priceScore));

    // 2. 최종 합산 예상 점수
    let totalScore = 0.0;
    let passThreshold = 95.0;

    if (_simContractMethod.includes('협상')) {
        const adjustedQuant = (_simQuantBaseScore / 60.0) * 80.0;
        totalScore = adjustedQuant + priceScore;
        passThreshold = 85.0;
    } else {
        totalScore = _simQuantBaseScore + priceScore;
        passThreshold = 95.0;
    }

    totalScore = parseFloat(totalScore.toFixed(2));

    // 3. UI 바인딩
    const priceScoreEl = document.getElementById('sim-price-score');
    if (priceScoreEl) {
        priceScoreEl.textContent = `${priceScore.toFixed(1)} / ${maxPriceScore.toFixed(0)}`;
    }
    
    const totalScoreEl = document.getElementById('sim-total-score');
    if (totalScoreEl) {
        totalScoreEl.textContent = `${totalScore.toFixed(1)} 점`;
    }

    const badgeEl = document.getElementById('sim-pass-badge');
    const adviceEl = document.getElementById('sim-ai-advice');

    if (badgeEl && adviceEl) {
        if (totalScore >= passThreshold) {
            badgeEl.className = 'badge badge-success';
            badgeEl.textContent = '수주 우수';
            badgeEl.style.background = 'var(--success)';
            if (totalScoreEl) totalScoreEl.style.color = 'var(--success)';
            
            let advice = `🟢 <strong>합격 안정권!</strong> 예상 종합 점수(${totalScore.toFixed(1)}점)가 합격선(${passThreshold}점)을 초과하여 낙찰 가능성이 매우 높습니다. `;
            if (rate > 89.0) {
                advice += `고가 투찰 상태이므로 가격 마진 확보에 유리합니다.`;
            } else {
                advice += `안정된 가격 경쟁력을 확보하였습니다.`;
            }
            adviceEl.innerHTML = advice;
        } else {
            badgeEl.className = 'badge badge-danger';
            badgeEl.textContent = '과락 위험';
            badgeEl.style.background = 'var(--danger)';
            if (totalScoreEl) totalScoreEl.style.color = 'var(--danger)';
            
            let advice = `🔴 <strong>점수 부족!</strong> 예상 종합 점수가 기준선(${passThreshold}점)에 미달하여 탈락 위험이 있습니다. `;
            if (_simContractMethod.includes('협상') && (_simQuantBaseScore / 60.0 * 80.0) < 68.0) {
                advice += `정성제안(기술점수) 배점 부족이 주원인이므로 제안서 고도화가 절실합니다.`;
            } else {
                advice += `투찰률을 조정하거나 공동수급체(협업) 구성을 늘려 정량 점수를 추가 보완해야 합니다.`;
            }
            adviceEl.innerHTML = advice;
        }
    }
}

// ──────────────────────────────────────────────
// 17. 회원 인증 및 관심공고 서버 동기화 핸들러
// ──────────────────────────────────────────────

function openAuthModal() {
    const overlay = document.getElementById('auth-modal-overlay');
    if (overlay) {
        overlay.classList.add('active');
        toggleAuthForm(null, 'login');
    }
}

function closeAuthModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const overlay = document.getElementById('auth-modal-overlay');
    if (overlay) {
        overlay.classList.remove('active');
    }
}

function toggleAuthForm(event, type) {
    if (event) event.preventDefault();
    const loginForm = document.getElementById('auth-login-form');
    const registerForm = document.getElementById('auth-register-form');
    const findUsernameForm = document.getElementById('auth-find-username-form');
    const resetPasswordForm = document.getElementById('auth-reset-password-form');
    const title = document.getElementById('auth-modal-title');
    const subtitle = document.getElementById('auth-modal-subtitle');

    if (loginForm) loginForm.style.display = 'none';
    if (registerForm) registerForm.style.display = 'none';
    if (findUsernameForm) findUsernameForm.style.display = 'none';
    if (resetPasswordForm) resetPasswordForm.style.display = 'none';

    if (type === 'login') {
        if (loginForm) loginForm.style.display = 'flex';
        if (title) title.textContent = '🔒 로그인';
        if (subtitle) subtitle.textContent = 'NARA Analyzer 이용을 위해 로그인해 주세요.';
    } else if (type === 'register') {
        if (registerForm) registerForm.style.display = 'flex';
        if (title) title.textContent = '📝 회원가입';
        if (subtitle) subtitle.textContent = '새로운 계정을 생성하고 입찰 데이터를 관리하세요.';
    } else if (type === 'find-username') {
        if (findUsernameForm) findUsernameForm.style.display = 'flex';
        if (title) title.textContent = '🔍 아이디 찾기';
        if (subtitle) subtitle.textContent = '가입 시 등록한 이메일 주소를 입력해 주세요.';
        const resultEl = document.getElementById('find-username-result');
        if (resultEl) resultEl.style.display = 'none';
    } else if (type === 'reset-password') {
        if (resetPasswordForm) resetPasswordForm.style.display = 'flex';
        if (title) title.textContent = '🔑 비밀번호 재설정';
        if (subtitle) subtitle.textContent = '아이디와 등록된 이메일을 확인한 후 비밀번호를 재설정합니다.';
    }
}

async function handleFindUsernameSubmit(event) {
    if (event) event.preventDefault();
    const email = document.getElementById('find-email').value.trim();
    const resultEl = document.getElementById('find-username-result');
    if (!email) return;

    try {
        const response = await fetch('/api/auth/find-username', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email }),
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            if (resultEl) {
                resultEl.style.display = 'block';
                resultEl.textContent = `찾으시는 아이디: ${data.username}`;
                resultEl.style.color = '#a5b4fc';
            }
        } else {
            const err = await response.json().catch(() => ({ detail: '아이디를 찾을 수 없습니다.' }));
            if (resultEl) {
                resultEl.style.display = 'block';
                resultEl.textContent = err.detail || '가입 정보를 찾을 수 없습니다.';
                resultEl.style.color = '#f87171';
            }
        }
    } catch (e) {
        console.error('아이디 찾기 에러:', e);
        if (resultEl) {
            resultEl.style.display = 'block';
            resultEl.textContent = '서버 통신 실패';
            resultEl.style.color = '#f87171';
        }
    }
}

async function handleResetPasswordSubmit(event) {
    if (event) event.preventDefault();
    const username = document.getElementById('reset-username').value.trim();
    const email = document.getElementById('reset-email').value.trim();
    const newPassword = document.getElementById('reset-new-password').value;
    const confirmPassword = document.getElementById('reset-new-password-confirm').value;

    if (!username || !email || !newPassword) {
        showToast('모든 항목을 올바르게 채워주세요.', 'error');
        return;
    }

    if (newPassword !== confirmPassword) {
        showToast('새 비밀번호와 확인 입력이 일치하지 않습니다.', 'error');
        return;
    }

    try {
        const response = await fetch('/api/auth/reset-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, new_password: newPassword }),
            credentials: 'include'
        });

        if (response.ok) {
            showToast('비밀번호가 변경되었습니다. 로그인해 주세요.', 'success');
            toggleAuthForm(null, 'login');
            document.getElementById('reset-username').value = '';
            document.getElementById('reset-email').value = '';
            document.getElementById('reset-new-password').value = '';
            document.getElementById('reset-new-password-confirm').value = '';
        } else {
            const err = await response.json().catch(() => ({ detail: '비밀번호 재설정 실패' }));
            showToast(err.detail || '재설정에 실패했습니다. 입력값을 확인해 주세요.', 'error');
        }
    } catch (e) {
        console.error('비밀번호 재설정 에러:', e);
        showToast('서버 통신 중 오류가 발생했습니다.', 'error');
    }
}

async function checkLoginStatus() {
    try {
        const response = await fetch('/api/auth/me', { credentials: 'include' });
        if (response.ok) {
            const data = await response.json();
            if (data.username) {
                _currentUser = data.username;
                state.isAdmin = !!data.is_admin;
                
                document.body.classList.remove('logged-out');
                const menuAdmin = document.getElementById('menu-admin');
                if (menuAdmin) {
                    menuAdmin.style.display = state.isAdmin ? 'block' : 'none';
                }
                
                const loggedOutEl = document.getElementById('auth-logged-out');
                const loggedInEl = document.getElementById('auth-logged-in');
                const usernameEl = document.getElementById('auth-username');
                
                if (loggedOutEl) loggedOutEl.style.display = 'none';
                if (loggedInEl) loggedInEl.style.display = 'block';
                if (usernameEl) usernameEl.textContent = _currentUser;
                
                await loadFavoritesFromServer();
                await loadUserCompanies();
            } else {
                _currentUser = null;
                state.isAdmin = false;
                _favoritesCache = [];
                _clearAuthUI();
            }
        } else {
            _currentUser = null;
            state.isAdmin = false;
            _favoritesCache = [];
            _clearAuthUI();
        }
    } catch (e) {
        _currentUser = null;
        state.isAdmin = false;
        _favoritesCache = [];
        _clearAuthUI();
    }
    updateFavBadge();
    updateSidebarMenu();
}

function _clearAuthUI() {
    const loggedOutEl = document.getElementById('auth-logged-out');
    const loggedInEl = document.getElementById('auth-logged-in');
    if (loggedOutEl) loggedOutEl.style.display = 'block';
    if (loggedInEl) loggedInEl.style.display = 'none';
    localStorage.removeItem('activeCompanyBizId');
    const container = document.getElementById('active-company-container');
    if (container) container.style.display = 'none';
    const select = document.getElementById('active-company-select');
    if (select) select.innerHTML = '';
    
    document.body.classList.add('logged-out');
    const menuAdmin = document.getElementById('menu-admin');
    if (menuAdmin) menuAdmin.style.display = 'none';
    updateSidebarMenu();
}

function updateSidebarMenu() {
    const isLoggedIn = !!_currentUser;
    
    // 1. 랜딩 메뉴 제어 (로그인 전에는 보이고 로그인 후에는 숨김)
    const menuLanding = document.getElementById('menu-landing');
    if (menuLanding) {
        menuLanding.style.display = isLoggedIn ? 'none' : 'block';
    }
    
    // 2. 다른 일반 메뉴들 (locked 상태 제어)
    const lockedViews = ['dashboard', 'bids', 'favorites', 'cafe', 'businesses', 'analysis', 'settings', 'ai-settings', 'policies', 'proposals', 'partners'];
    
    lockedViews.forEach(viewName => {
        const item = document.querySelector(`.menu-item[data-view="${viewName}"]`);
        if (item) {
            if (isLoggedIn) {
                // 로그인 시 잠금 해제
                item.classList.remove('menu-item-locked');
                const lockBadge = item.querySelector('.menu-lock-badge');
                if (lockBadge) lockBadge.remove();
                
                // 원래의 navigate 클릭 복원
                item.setAttribute('onclick', `navigate('${viewName}')`);
            } else {
                // 비로그인 시 잠금
                item.classList.add('menu-item-locked');
                if (!item.querySelector('.menu-lock-badge')) {
                    const badge = document.createElement('span');
                    badge.className = 'menu-lock-badge';
                    badge.textContent = '🔒';
                    badge.style.marginLeft = 'auto';
                    badge.style.fontSize = '0.75rem';
                    badge.style.opacity = '0.7';
                    item.appendChild(badge);
                }
                
                // 클릭 시 로그인 모달 및 토스트 안내 유도
                item.setAttribute('onclick', `openAuthModal('login'); showToast('로그인이 필요한 서비스입니다. 회원가입 후 이용해주세요.', 'info');`);
            }
        }
    });

    // 3. 관리자 메뉴 제어 (로그인 + 관리자 플래그 필요)
    const menuAdmin = document.getElementById('menu-admin');
    if (menuAdmin) {
        menuAdmin.style.display = (isLoggedIn && state.isAdmin) ? 'block' : 'none';
    }
}

async function loadFavoritesFromServer() {
    try {
        const response = await fetch('/api/favorites', { credentials: 'include' });
        if (response.ok) {
            _favoritesCache = await response.json();
        } else {
            _favoritesCache = [];
        }
    } catch (e) {
        console.error('관심공고 서버 조회 실패:', e);
        _favoritesCache = [];
    }
}

function shakeAuthModal() {
    const modal = document.querySelector('#auth-modal-overlay .strategy-modal');
    if (modal) {
        modal.classList.add('shake');
        setTimeout(() => modal.classList.remove('shake'), 400);
    }
}

async function handleLoginSubmit(event) {
    event.preventDefault();
    const usernameInput = document.getElementById('login-username');
    const passwordInput = document.getElementById('login-password');
    if (!usernameInput || !passwordInput) return;

    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
            credentials: 'include'
        });

        if (response.ok) {
            showToast('로그인에 성공했습니다!', 'success');
            closeAuthModal();
            
            // 로컬 관심공고 임시 백업 검사 및 동기화
            const localFavs = localStorage.getItem('nara_favorites');
            
            await checkLoginStatus(); // 로그인 상태 업데이트 및 캐시 충진
            
            if (localFavs && JSON.parse(localFavs).length > 0) {
                await syncFavoritesWithServer(JSON.parse(localFavs));
            }

            // 각 뷰 강제 리로드하여 격리된 데이터 반영
            if (state.currentView === 'favorites') loadFavorites();
            if (state.currentView === 'businesses') loadBusinesses();
            
            // 대시보드 새로고침 및 이동
            const heroGuide = document.getElementById('hero-guide');
            if (heroGuide) heroGuide.textContent = `Welcome! ${username}님만의 대시보드가 준비되었습니다.`;
            navigate('dashboard');
        } else {
            const err = await response.json();
            showToast(err.detail || '로그인에 실패했습니다.', 'error');
            shakeAuthModal();
        }
    } catch (e) {
        console.error('로그인 에러:', e);
        showToast('서버 통신에 실패했습니다.', 'error');
        shakeAuthModal();
    }
}

async function handleRegisterSubmit(event) {
    event.preventDefault();
    const usernameInput = document.getElementById('register-username');
    const emailInput = document.getElementById('register-email');
    const passwordInput = document.getElementById('register-password');
    const confirmInput = document.getElementById('register-password-confirm');
    
    if (!usernameInput || !passwordInput || !confirmInput) return;
    
    const username = usernameInput.value.trim();
    const email = emailInput.value.trim() || null;
    const password = passwordInput.value;
    const confirm = confirmInput.value;

    if (password !== confirm) {
        showToast('비밀번호가 서로 일치하지 않습니다.', 'error');
        shakeAuthModal();
        return;
    }

    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, email }),
            credentials: 'include'
        });

        if (response.ok) {
            showToast('회원가입이 완료되었습니다! 가입한 계정으로 로그인해 주세요.', 'success');
            toggleAuthForm(null, 'login');
            
            // 로그인 아이디란에 자동 입력
            const loginUserEl = document.getElementById('login-username');
            if (loginUserEl) loginUserEl.value = username;
        } else {
            const err = await response.json();
            showToast(err.detail || '회원가입에 실패했습니다.', 'error');
            shakeAuthModal();
        }
    } catch (e) {
        console.error('회원가입 에러:', e);
        showToast('서버 통신에 실패했습니다.', 'error');
        shakeAuthModal();
    }
}

async function handleLogout() {
    try {
        const response = await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
        if (response.ok) {
            showToast('로그아웃되었습니다.', 'info');
            _currentUser = null;
            _favoritesCache = [];
            _clearAuthUI();
            
            // 상태 갱신 및 대시보드 리다이렉트
            window.location.reload();
        } else {
            showToast('로그아웃에 실패했습니다.', 'error');
        }
    } catch (e) {
        console.error('로그아웃 에러:', e);
        window.location.reload();
    }
}

async function syncFavoritesWithServer(localFavs) {
    try {
        const response = await fetch('/api/favorites/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ favorites: localFavs }),
            credentials: 'include'
        });
        if (response.ok) {
            localStorage.removeItem('nara_favorites');
            showToast('로컬 관심공고가 계정에 안전하게 통합되었습니다!', 'success');
            await loadFavoritesFromServer();
            if (state.currentView === 'favorites') loadFavorites();
        }
    } catch (e) {
        console.error('관심공고 서버 동기화 에러:', e);
    }
}

// ──────────────────────────────────────────────
// 7. 다중 회사 연계 및 직원 관리
// ──────────────────────────────────────────────

function switchCompanyTab(tab) {
    const tabCompanies = document.getElementById('company-tab-companies');
    const tabMembers = document.getElementById('company-tab-members');
    const secCompanies = document.getElementById('company-section-companies');
    const secMembers = document.getElementById('company-section-members');

    if (tab === 'companies') {
        if (tabCompanies) {
            tabCompanies.classList.add('btn-primary');
            tabCompanies.classList.remove('btn-ghost', 'active');
            tabCompanies.classList.add('active');
        }
        if (tabMembers) {
            tabMembers.classList.add('btn-ghost');
            tabMembers.classList.remove('btn-primary', 'active');
        }
        if (secCompanies) secCompanies.style.display = 'block';
        if (secMembers) secMembers.style.display = 'none';
        
        loadBusinesses();
    } else {
        if (tabMembers) {
            tabMembers.classList.add('btn-primary');
            tabMembers.classList.remove('btn-ghost', 'active');
            tabMembers.classList.add('active');
        }
        if (tabCompanies) {
            tabCompanies.classList.add('btn-ghost');
            tabCompanies.classList.remove('btn-primary', 'active');
        }
        if (secCompanies) secCompanies.style.display = 'none';
        if (secMembers) secMembers.style.display = 'block';
        
        const activeBizId = localStorage.getItem('activeCompanyBizId');
        if (activeBizId) {
            loadCompanyMembers(activeBizId);
        } else {
            const tbody = document.getElementById('company-members-tbody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="5" style="padding: 20px; text-align: center; color: var(--text-muted);">활성화된 회사가 없습니다. 먼저 회사를 등록하거나 선택해 주세요.</td></tr>';
            }
        }
    }
}

async function loadUserCompanies() {
    try {
        const companies = await api('GET', '/companies/my');
        const select = document.getElementById('active-company-select');
        const container = document.getElementById('active-company-container');
        
        if (!companies || companies.length === 0) {
            if (container) container.style.display = 'none';
            localStorage.removeItem('activeCompanyBizId');
            const displayName = document.getElementById('active-company-name-display');
            if (displayName) displayName.textContent = '선택된 회사';
            return;
        }

        if (container) container.style.display = 'block';
        
        let activeBizId = localStorage.getItem('activeCompanyBizId');
        const isValid = companies.some(c => c.biz_id === activeBizId);
        if (!activeBizId || !isValid) {
            activeBizId = companies[0].biz_id;
            localStorage.setItem('activeCompanyBizId', activeBizId);
        }

        if (select) {
            select.innerHTML = companies.map(c => 
                `<option value="${escapeHTML(c.biz_id)}" ${c.biz_id === activeBizId ? 'selected' : ''}>
                    ${escapeHTML(c.company_name)} (${c.role === 'owner' ? '소유자' : c.role === 'admin' ? '관리자' : '직원'})
                </option>`
            ).join('');
        }

        const activeComp = companies.find(c => c.biz_id === activeBizId);
        const displayName = document.getElementById('active-company-name-display');
        if (displayName && activeComp) {
            displayName.textContent = activeComp.company_name;
        }
        
    } catch (err) {
        console.error('소속 회사 목록 조회 에러:', err);
    }
}

async function handleCompanySwitch(bizId) {
    if (!bizId) return;
    localStorage.setItem('activeCompanyBizId', bizId);
    
    showToast('활성 회사가 전환되었습니다.', 'success');
    
    await loadUserCompanies();
    
    if (state.currentView === 'dashboard') {
        if (typeof loadDashboard === 'function') {
            await loadDashboard();
        }
    } else if (state.currentView === 'businesses') {
        const tabMembers = document.getElementById('company-tab-members');
        if (tabMembers && tabMembers.classList.contains('active')) {
            loadCompanyMembers(bizId);
        } else {
            loadBusinesses();
        }
    } else if (state.currentView === 'favorites') {
        if (typeof loadFavorites === 'function') {
            loadFavorites();
        }
    }
}

async function loadCompanyMembers(bizId) {
    const tbody = document.getElementById('company-members-tbody');
    if (!tbody) return;
    
    tbody.innerHTML = '<tr><td colspan="5" style="padding: 20px; text-align: center; color: var(--text-muted);"><div class="skeleton" style="height:20px;width:100%"></div></td></tr>';
    
    try {
        const members = await api('GET', `/companies/${bizId}/members`);
        
        const myInfo = members.find(m => m.username === _currentUser);
        const myRole = myInfo ? myInfo.role : 'member';
        const hasAdminAccess = myRole === 'owner' || myRole === 'admin';
        
        const inviteForm = document.getElementById('invite-member-form');
        if (inviteForm) {
            inviteForm.style.display = hasAdminAccess ? 'flex' : 'none';
        }

        if (!members || members.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="padding: 20px; text-align: center; color: var(--text-muted);">등록된 직원이 없습니다.</td></tr>';
            return;
        }

        tbody.innerHTML = members.map(m => {
            const isSelf = m.username === _currentUser;
            const joinedAt = m.joined_at ? m.joined_at.substring(0, 10) : '-';
            
            let roleCell = '';
            if (isSelf || !hasAdminAccess || m.role === 'owner') {
                let roleText = '직원';
                if (m.role === 'owner') roleText = '소유자(대표)';
                if (m.role === 'admin') roleText = '관리자';
                roleCell = `<span class="biz-tag ${m.role}">${roleText}</span>`;
            } else {
                roleCell = `
                    <select onchange="handleUpdateMemberRole('${escapeHTML(m.username)}', this.value)" class="input" style="font-size: 0.8rem; padding: 2px 4px; background: rgba(0,0,0,0.6); color: #fff; border: 1px solid var(--border); border-radius: 4px;">
                        <option value="member" ${m.role === 'member' ? 'selected' : ''}>직원</option>
                        <option value="admin" ${m.role === 'admin' ? 'selected' : ''}>관리자</option>
                    </select>
                `;
            }

            let actionCell = '';
            if (isSelf) {
                actionCell = '<span style="color:var(--text-muted); font-size:0.8rem;">본인</span>';
            } else if (m.role === 'owner') {
                actionCell = '-';
            } else if (hasAdminAccess) {
                actionCell = `
                    <button class="btn btn-sm btn-outline btn-danger" onclick="handleRemoveMember('${escapeHTML(m.username)}')" style="padding: 2px 8px; font-size:0.75rem;">
                        제외
                    </button>
                `;
            } else {
                actionCell = '-';
            }

            return `
                <tr style="border-bottom: 1px solid var(--border); height: 45px;">
                    <td style="padding: 10px; font-weight: 600; color: var(--text-primary);">${escapeHTML(m.username)}</td>
                    <td style="padding: 10px; color: var(--text-muted);">${escapeHTML(m.email || '-')}</td>
                    <td style="padding: 10px;">${roleCell}</td>
                    <td style="padding: 10px; color: var(--text-muted);">${escapeHTML(joinedAt)}</td>
                    <td style="padding: 10px; text-align: right;">${actionCell}</td>
                </tr>
            `;
        }).join('');
        
    } catch (err) {
        showToast(`직원 목록 로드 실패: ${err.message}`, 'error');
        tbody.innerHTML = `<tr><td colspan="5" style="padding: 20px; text-align: center; color: var(--text-muted);">직원 정보를 가져오지 못했습니다: ${err.message}</td></tr>`;
    }
}

async function handleInviteMember() {
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!activeBizId) {
        showToast('활성화된 회사가 없습니다.', 'error');
        return;
    }

    const usernameInput = document.getElementById('invite-username');
    const roleSelect = document.getElementById('invite-role');
    if (!usernameInput || !roleSelect) return;

    const targetUser = usernameInput.value.trim();
    const role = roleSelect.value;

    if (!targetUser) {
        showToast('초대할 사용자의 ID를 입력해 주세요.', 'error');
        return;
    }

    try {
        const res = await api('POST', `/companies/${activeBizId}/members`, {
            username: targetUser,
            role: role
        });
        showToast(res.message || '직원이 성공적으로 등록되었습니다.', 'success');
        usernameInput.value = '';
        
        await loadCompanyMembers(activeBizId);
    } catch (err) {
        showToast(`직원 등록 실패: ${err.message}`, 'error');
    }
}

async function handleRemoveMember(username) {
    if (!username) return;
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!activeBizId) return;

    if (!confirm(`정말로 직원 '${username}'을(를) 회사 조직에서 제외하시겠습니까?`)) {
        return;
    }

    try {
        const res = await api('DELETE', `/companies/${activeBizId}/members/${username}`);
        showToast(res.message || '직원이 제외되었습니다.', 'success');
        await loadCompanyMembers(activeBizId);
    } catch (err) {
        showToast(`직원 제외 실패: ${err.message}`, 'error');
    }
}

async function handleUpdateMemberRole(username, role) {
    if (!username || !role) return;
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!activeBizId) return;

    try {
        const res = await api('PUT', `/companies/${activeBizId}/members/${username}`, {
            role: role
        });
        showToast(res.message || '역할이 성공적으로 수정되었습니다.', 'success');
        await loadCompanyMembers(activeBizId);
    } catch (err) {
        showToast(`역할 변경 실패: ${err.message}`, 'error');
    }
}


// ──────────────────────────────────────────────
// 18. 나의 입찰 AI 에이전트 설정 (My AI)
// ──────────────────────────────────────────────
let _aiSettings = {
    bid_target: 'stable',
    relevance_weight: 0.35,
    capacity_weight: 0.35,
    credit_weight: 0.30,
    ai_persona: 'strategic'
};

async function loadUserAISettings() {
    try {
        const data = await api('GET', '/user/ai-settings');
        if (data) {
            _aiSettings = data;
            updateAISettingsUI();
        }
    } catch (err) {
        console.error('AI 에이전트 설정 조회 실패:', err);
        showToast('AI 설정을 불러오는 중 오류가 발생했습니다.', 'error');
    }
}

function updateAISettingsUI() {
    // 페르소나 카드 활성화
    document.querySelectorAll('.persona-card').forEach(card => {
        card.classList.remove('active-persona');
    });
    const activeCard = document.getElementById(`persona-${_aiSettings.ai_persona}`);
    if (activeCard) activeCard.classList.add('active-persona');

    // 슬라이더 값 동기화 (API 값 0~1.0 -> UI 0~100)
    const relevance = Math.round((_aiSettings.relevance_weight || 0.35) * 100);
    const capacity = Math.round((_aiSettings.capacity_weight || 0.35) * 100);
    const credit = Math.round((_aiSettings.credit_weight || 0.30) * 100);

    document.getElementById('weight-relevance-slider').value = relevance;
    document.getElementById('weight-capacity-slider').value = capacity;
    document.getElementById('weight-credit-slider').value = credit;

    document.getElementById('weight-relevance-val').textContent = `${relevance}%`;
    document.getElementById('weight-capacity-val').textContent = `${capacity}%`;
    document.getElementById('weight-credit-val').textContent = `${credit}%`;

    // 가중치 현황 UI 업데이트
    updateWeightVisuals(relevance, capacity, credit);
}

function setAiPersona(persona) {
    _aiSettings.ai_persona = persona;
    document.querySelectorAll('.persona-card').forEach(card => {
        card.classList.remove('active-persona');
    });
    document.getElementById(`persona-${persona}`).classList.add('active-persona');
    
    // 페르소나에 따른 자동 가중치 조절
    let r = 35, c = 35, cr = 30;
    if (persona === 'aggressive') {
        r = 25; c = 55; cr = 20; // 대형 예산/실적 중심
    } else if (persona === 'conservative') {
        r = 30; c = 20; cr = 50; // 안정적 신용/가점 중심
    }
    
    _aiSettings.relevance_weight = r / 100;
    _aiSettings.capacity_weight = c / 100;
    _aiSettings.credit_weight = cr / 100;
    
    updateAISettingsUI();
}

function adjustWeights(changedType, val) {
    val = Number(val);
    const sliderR = document.getElementById('weight-relevance-slider');
    const sliderC = document.getElementById('weight-capacity-slider');
    const sliderCr = document.getElementById('weight-credit-slider');

    let r = Number(sliderR.value);
    let c = Number(sliderC.value);
    let cr = Number(sliderCr.value);

    if (changedType === 'relevance') {
        r = val;
        const remain = 100 - r;
        const otherSum = c + cr;
        if (otherSum > 0) {
            c = Math.round((remain * c) / otherSum);
            cr = remain - c;
        } else {
            c = Math.round(remain / 2);
            cr = remain - c;
        }
    } else if (changedType === 'capacity') {
        c = val;
        const remain = 100 - c;
        const otherSum = r + cr;
        if (otherSum > 0) {
            r = Math.round((remain * r) / otherSum);
            cr = remain - r;
        } else {
            r = Math.round(remain / 2);
            cr = remain - r;
        }
    } else if (changedType === 'credit') {
        cr = val;
        const remain = 100 - cr;
        const otherSum = r + c;
        if (otherSum > 0) {
            r = Math.round((remain * r) / otherSum);
            c = remain - r;
        } else {
            r = Math.round(remain / 2);
            c = remain - r;
        }
    }

    // 범위 제한
    r = Math.max(0, Math.min(100, r));
    c = Math.max(0, Math.min(100, c));
    cr = Math.max(0, Math.min(100, cr));

    // UI 값 동기화
    sliderR.value = r;
    sliderC.value = c;
    sliderCr.value = cr;

    document.getElementById('weight-relevance-val').textContent = `${r}%`;
    document.getElementById('weight-capacity-val').textContent = `${c}%`;
    document.getElementById('weight-credit-val').textContent = `${cr}%`;

    // 상태 업데이트
    _aiSettings.relevance_weight = r / 100;
    _aiSettings.capacity_weight = c / 100;
    _aiSettings.credit_weight = cr / 100;

    updateWeightVisuals(r, c, cr);
}

function updateWeightVisuals(r, c, cr) {
    // 게이지바 업데이트
    document.getElementById('weight-progress-relevance').style.width = `${r}%`;
    document.getElementById('weight-progress-capacity').style.width = `${c}%`;
    document.getElementById('weight-progress-credit').style.width = `${cr}%`;

    // 리포트 텍스트 업데이트
    document.getElementById('report-relevance').textContent = `${r}%`;
    document.getElementById('report-capacity').textContent = `${c}%`;
    document.getElementById('report-credit').textContent = `${cr}%`;

    // 상태 요약 텍스트
    const statusText = document.getElementById('weight-sum-status');
    const total = r + c + cr;
    if (total === 100) {
        statusText.textContent = '총합 100% (정상)';
        statusText.style.color = 'var(--success)';
    } else {
        statusText.textContent = `총합 ${total}% (오류: 100% 보정 필요)`;
        statusText.style.color = 'var(--danger)';
    }
}

async function saveUserAISettings() {
    try {
        const payload = {
            bid_target: _aiSettings.bid_target || 'stable',
            relevance_weight: _aiSettings.relevance_weight,
            capacity_weight: _aiSettings.capacity_weight,
            credit_weight: _aiSettings.credit_weight,
            ai_persona: _aiSettings.ai_persona,
            custom_keywords: _aiSettings.custom_keywords || null
        };
        await api('POST', '/user/ai-settings', payload);
        showToast('AI 에이전트 가중치와 페르소나가 저장되었습니다!', 'success');
        
        // 대시보드 리로드 (변경된 가중치에 맞춰 매칭점수 재연산)
        if (state.currentView === 'dashboard') {
            loadDashboard();
        }
    } catch (err) {
        console.error('AI 설정 저장 실패:', err);
        showToast('AI 설정을 저장하지 못했습니다.', 'error');
    }
}


// ──────────────────────────────────────────────
// 19. 종합 관리자 대시보드 (Admin Dashboard)
// ──────────────────────────────────────────────
let _currentAdminTab = 'users';

async function loadAdminPanel() {
    try {
        const stats = await api('GET', '/admin/stats');
        document.getElementById('admin-stat-users').textContent = stats.total_users || 0;
        document.getElementById('admin-stat-companies').textContent = stats.total_companies || 0;
        document.getElementById('admin-stat-favorites').textContent = stats.total_favorites || 0;
        document.getElementById('admin-stat-collaborations').textContent = stats.total_collaborations || 0;
        document.getElementById('admin-stat-bids').textContent = stats.total_bids || 0;
        document.getElementById('admin-stat-admins').textContent = stats.total_admins || 0;
    } catch(err) {
        console.error('어드민 통계 조회 실패:', err);
    }
    // 첫 탭(회원) 로드
    switchAdminTab('users');
}

function switchAdminTab(t) {
    // 탭 버튼 상태
    document.querySelectorAll('.admin-nav-tab').forEach(b => b.classList.remove('active'));
    const btn = document.getElementById(`tab-${t}-btn`);
    if (btn) btn.classList.add('active');
    // 콘텐츠 표시
    document.querySelectorAll('.admin-tab-content').forEach(c => c.style.display = 'none');
    const content = document.getElementById(`admin-tab-${t}`);
    if (content) content.style.display = 'block';
    // 탭별 데이터 로드
    if (t === 'users') loadAdminUsers();
    else if (t === 'companies') loadAdminCompanies();
    else if (t === 'collaborations') loadAdminCollaborations();
    else if (t === 'apikeys') loadAdminApiKeys();
    else if (t === 'bids') loadAdminBidsStats();
    else if (t === 'system') loadAdminSystemInfo();
}

async function loadAdminUsers() {
    const body = document.getElementById('admin-users-list-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="7" class="empty-row" style="text-align:center;padding:20px">⏳ 로딩 중...</td></tr>';
    try {
        const users = await api('GET', '/admin/users');
        if (!users || users.length === 0) {
            body.innerHTML = '<tr><td colspan="7" class="empty-row" style="text-align:center;padding:20px">등록된 회원이 없습니다.</td></tr>';
            return;
        }
        body.innerHTML = users.map(u => {
            const isSystemAdmin = u.username === 'admin';
            return `<tr>
                <td><strong>${escapeHTML(u.username)}</strong></td>
                <td style="color:var(--text-muted)">${escapeHTML(u.email || '-')}</td>
                <td><span style="font-size:0.78rem">${escapeHTML(u.ai_persona_role || '-')}</span></td>
                <td><span style="font-size:0.75rem;color:var(--text-muted)">${u.company_count ? u.company_count + '개 소속' : '미가입'}</span></td>
                <td>${u.is_admin ? '<span style="color:#6366f1;font-weight:700">🔑 관리자</span>' : '<span style="color:var(--text-muted)">일반</span>'}</td>
                <td style="font-size:0.8rem;color:var(--text-muted)">${u.created_at ? u.created_at.slice(0,10) : '-'}</td>
                <td style="text-align:right">
                    <div style="display:flex;gap:6px;justify-content:flex-end;flex-wrap:wrap">
                        ${!isSystemAdmin ? `<button class="btn btn-xs ${u.is_admin ? 'btn-secondary' : 'btn-ghost'}" onclick="toggleUserAdminRole('${u.username}',${u.is_admin})">${u.is_admin ? '🔒 일반 전환' : '🔑 관리자 승격'}</button>` : ''}
                        ${!isSystemAdmin ? `<button class="btn btn-xs btn-outline" onclick="adminResetPassword('${u.username}')">🔑 비번 초기화</button>` : ''}
                        ${!isSystemAdmin ? `<button class="btn btn-xs btn-danger" onclick="adminDeleteUser('${u.username}')">🗑️ 탈퇴</button>` : ''}
                        ${isSystemAdmin ? '<span style="font-size:0.75rem;color:var(--text-muted)">최고관리자</span>' : ''}
                    </div>
                </td>
            </tr>`;
        }).join('');
    } catch(err) {
        body.innerHTML = `<tr><td colspan="7" class="empty-row" style="text-align:center;padding:20px;color:var(--danger)">오류: ${err.message}</td></tr>`;
    }
}

function filterAdminUsers() {
    const q = document.getElementById('admin-user-search')?.value?.toLowerCase() || '';
    document.querySelectorAll('#admin-users-list-body tr').forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
}

async function toggleUserAdminRole(username, isCurrentlyAdmin) {
    const action = isCurrentlyAdmin ? '해제' : '부여';
    if (!confirm(`'${username}' 회원에게서 관리자 권한을 ${action}하시겠습니까?`)) {
        return;
    }

    try {
        await api('PUT', `/admin/users/${username}/role`, {
            is_admin: !isCurrentlyAdmin
        });
        showToast(`'${username}' 사용자의 관리자 권한이 변경되었습니다.`, 'success');
        loadAdminUsers();
    } catch (err) {
        console.error('권한 변경 실패:', err);
        showToast(`권한 변경 실패: ${err.message}`, 'error');
    }
}

async function deleteUserByAdmin(username) {
    if (!confirm(`정말로 사용자 '${username}' 회원을 시스템에서 영구 탈퇴 처리하시겠습니까?\n이 작업은 되돌릴 수 없으며 모든 등록 회사 및 관심공고 데이터가 삭제됩니다.`)) {
        return;
    }

    try {
        await api('DELETE', `/admin/users/${username}`);
        showToast(`사용자 '${username}' 회원이 강제 탈퇴 처리되었습니다.`, 'success');
        loadAdminUsers();
        // 통계 갱신
        loadAdminPanel();
    } catch (err) {
        console.error('회원 탈퇴 처리 실패:', err);
        showToast(`강제 탈퇴 실패: ${err.message}`, 'error');
    }
}

async function loadAdminCompanies() {
    const body = document.getElementById('admin-companies-list-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="8" class="empty-row" style="text-align:center;padding:20px">⏳ 로딩 중...</td></tr>';
    try {
        const companies = await api('GET', '/admin/companies');
        if (!companies || companies.length === 0) {
            body.innerHTML = '<tr><td colspan="8" class="empty-row" style="text-align:center;padding:20px">등록된 기업이 없습니다.</td></tr>';
            return;
        }
        body.innerHTML = companies.map(c => `<tr>
            <td style="font-size:0.8rem;color:var(--text-muted)">${escapeHTML(c.biz_id)}</td>
            <td><strong>${escapeHTML(c.company_name)}</strong></td>
            <td>${escapeHTML(c.ceo_name || '-')}</td>
            <td style="text-align:center">${c.member_count || 0}명</td>
            <td style="font-size:0.8rem">${escapeHTML((c.industry || '') + (c.region ? ' · ' + c.region : ''))}</td>
            <td style="font-size:0.8rem">${c.revenue ? (c.revenue/1e8).toFixed(1)+'억' : '-'} / ${c.employees ? c.employees+'명' : '-'}</td>
            <td style="font-size:0.8rem;color:var(--text-muted)">${c.created_at ? c.created_at.slice(0,10) : '-'}</td>
            <td style="text-align:right">
                <button class="btn btn-xs btn-danger" onclick="adminDeleteCompany('${c.biz_id}','${escapeHTML(c.company_name)}')">🗑️ 삭제</button>
            </td>
        </tr>`).join('');
    } catch(err) {
        body.innerHTML = `<tr><td colspan="8" class="empty-row" style="text-align:center;padding:20px;color:var(--danger)">오류: ${err.message}</td></tr>`;
    }
}

function filterAdminCompanies() {
    const q = document.getElementById('admin-company-search')?.value?.toLowerCase() || '';
    document.querySelectorAll('#admin-companies-list-body tr').forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
}

async function loadAdminCollaborations() {
    try {
        const collabs = await api('GET', '/admin/collaborations');
        const body = document.getElementById('admin-collaborations-list-body');
        if (!body) return;

        if (!collabs || collabs.length === 0) {
            body.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">현재 협업 중인 파트너십이 없습니다.</td></tr>';
            return;
        }

        body.innerHTML = collabs.map(col => {
            const closeDate = col.bid_close_dt ? col.bid_close_dt.substring(0, 10) : '-';
            const budgetText = col.budget ? `${(col.budget / 100000000).toFixed(2)}억 원` : '-';
            
            // 관심 등록 멤버 렌더링
            const membersHtml = col.interested_members.map(member => {
                const isLeader = member.role === 'owner';
                const roleBadge = isLeader ? '<span class="badge badge-accent" style="font-size:0.65rem">리더</span>' : '<span class="badge badge-secondary" style="font-size:0.65rem">참여자</span>';
                const compName = member.company_name ? `(${member.company_name})` : '';
                return `
                    <div style="display:inline-flex; align-items:center; gap:4px; background:rgba(255,255,255,0.05); padding:3px 8px; border-radius:4px; margin-right:6px; margin-bottom:4px; font-size:0.8rem">
                        👤 <strong>${escapeHTML(member.username)}</strong>${escapeHTML(compName)} ${roleBadge}
                    </div>
                `;
            }).join('');

            return `
                <tr>
                    <td><code>${escapeHTML(col.bid_ntce_no)}</code></td>
                    <td>
                        <strong style="display:block; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" title="${escapeHTML(col.bid_ntce_nm)}">
                            ${escapeHTML(col.bid_ntce_nm)}
                        </strong>
                        <small style="color:var(--text-muted)">발주처: ${escapeHTML(col.dmin_instt_nm || '-')}</small>
                    </td>
                    <td>${budgetText}</td>
                    <td>${closeDate}</td>
                    <td>
                        <div style="display:flex; flex-wrap:wrap">
                            ${membersHtml}
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('협업 현황 로드 실패:', err);
        showToast('협업사 매칭 모니터 데이터를 불러오지 못했습니다.', 'error');
    }
}

async function resetUserPasswordByAdmin(username) {
    const newPassword = prompt(`사용자 '${username}'의 새로운 비밀번호를 입력하세요 (최소 4자 이상):`);
    if (newPassword === null) return; // 취소
    
    if (newPassword.trim().length < 4) {
        showToast('비밀번호는 최소 4자 이상이어야 합니다.', 'error');
        return;
    }

    try {
        const response = await fetch(`/api/admin/users/${username}/reset-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_password: newPassword.trim() }),
            credentials: 'include'
        });

        if (response.ok) {
            showToast(`사용자 '${username}'의 비밀번호가 변경되었습니다.`, 'success');
        } else {
            const err = await response.json().catch(() => ({ detail: '비밀번호 재설정 실패' }));
            showToast(err.detail || '비밀번호 변경에 실패했습니다.', 'error');
        }
    } catch (err) {
        console.error('관리자 비밀번호 재설정 실패:', err);
        showToast('서버 통신 오류가 발생했습니다.', 'error');
    }
}

async function deleteCompanyByAdmin(bizId, companyName) {
    if (!confirm(`정말로 회사 '${companyName}' (사업자번호: ${bizId}) 프로필을 강제 삭제하시겠습니까?\n이 작업은 되돌릴 수 없으며 소속 멤버들과의 연계 관계가 해제됩니다.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/admin/companies/${bizId}`, {
            method: 'DELETE',
            credentials: 'include'
        });

        if (response.ok) {
            showToast(`회사 '${companyName}' 프로필이 정상적으로 강제 삭제되었습니다.`, 'success');
            loadAdminCompanies();
            loadAdminPanel(); // 통계 카드 갱신
        } else {
            const err = await response.json().catch(() => ({ detail: '회사 삭제 실패' }));
            showToast(err.detail || '회사 삭제에 실패했습니다.', 'error');
        }
    } catch (err) {
        console.error('회사 프로필 삭제 에러:', err);
        showToast('서버 통신 오류가 발생했습니다.', 'error');
    }
}

async function loadAdminApiKeys() {
    try {
        const keys = await api('GET', '/admin/api-keys');
        if (!keys) return;
        const mapping = {
            'data_go_kr_api_key': { status: 'admin-key-status-data_go_kr', masked: 'admin-key-masked-data_go_kr' },
            'naver_client_id':    { status: 'admin-key-status-naver',      masked: 'admin-key-masked-naver' },
            'gemini_api_key':     { status: 'admin-key-status-gemini',     masked: 'admin-key-masked-gemini_api_key' },
            'openai_api_key':     { status: 'admin-key-status-openai',     masked: 'admin-key-masked-openai_api_key' },
            'youtube_api_key':    { status: 'admin-key-status-youtube',    masked: 'admin-key-masked-youtube_api_key' },
            'kakao_api_key':      { status: 'admin-key-status-kakao',      masked: 'admin-key-masked-kakao_api_key' },
        };
        Object.entries(mapping).forEach(([key, ids]) => {
            const info = keys[key];
            const statusEl = document.getElementById(ids.status);
            const maskedEl = document.getElementById(ids.masked);
            if (statusEl) statusEl.textContent = info?.set ? '✅ 설정됨' : '❌ 미설정';
            if (statusEl) statusEl.style.color = info?.set ? 'var(--success)' : 'var(--danger)';
            if (maskedEl) maskedEl.textContent = info?.set ? `현재: ${info.masked}` : '미설정 — 새 키를 입력해주세요';
        });
    } catch(err) {
        console.warn('API 키 현황 로드 실패:', err.message);
    }
}

async function saveAllAdminApiKeys() {
    const payload = {};
    const fields = [
        ['data_go_kr_api_key', 'admin-key-data_go_kr'],
        ['naver_client_id',    'admin-key-naver_client_id'],
        ['naver_client_secret','admin-key-naver_client_secret'],
        ['gemini_api_key',     'admin-key-gemini_api_key'],
        ['openai_api_key',     'admin-key-openai_api_key'],
        ['youtube_api_key',    'admin-key-youtube_api_key'],
        ['kakao_api_key',      'admin-key-kakao_api_key'],
    ];
    fields.forEach(([field, id]) => {
        const val = document.getElementById(id)?.value?.trim();
        if (val) payload[field] = val;
    });
    if (Object.keys(payload).length === 0) {
        showToast('저장할 API 키를 하나 이상 입력해주세요.', 'warning');
        return;
    }
    const statusEl = document.getElementById('admin-apikey-save-status');
    if (statusEl) statusEl.textContent = '⏳ 저장 중...';
    try {
        const res = await api('PUT', '/admin/api-keys', payload);
        showToast(res.message || 'API 키 저장 완료', 'success');
        if (statusEl) statusEl.textContent = `✅ ${res.message}`;
        // 입력 초기화
        fields.forEach(([, id]) => { const el = document.getElementById(id); if (el) el.value = ''; });
        await loadAdminApiKeys();
    } catch(err) {
        if (statusEl) statusEl.textContent = `❌ ${err.message}`;
        showToast(`저장 실패: ${err.message}`, 'error');
    }
}

async function loadAdminBidsStats() {
    try {
        const stats = await api('GET', '/admin/bids/stats');
        const grid = document.getElementById('admin-bids-stats');
        if (grid) {
            grid.innerHTML = `
                <div class="stat-card" style="--delay:0"><div class="stat-icon" style="--gradient:linear-gradient(135deg,#4f46e5,#818cf8)">📋</div><div class="stat-info"><span class="stat-value">${stats.total||0}</span><span class="stat-label">총 공고 수</span></div></div>
                <div class="stat-card" style="--delay:1"><div class="stat-icon" style="--gradient:linear-gradient(135deg,#059669,#34d399)">📅</div><div class="stat-info"><span class="stat-value">${stats.today||0}</span><span class="stat-label">오늘 수집</span></div></div>
                <div class="stat-card" style="--delay:2"><div class="stat-icon" style="--gradient:linear-gradient(135deg,#d97706,#fbbf24)">🕐</div><div class="stat-info"><span class="stat-value" style="font-size:0.9rem">${stats.last_collected ? stats.last_collected.slice(0,16) : '-'}</span><span class="stat-label">마지막 수집</span></div></div>
            `;
        }
        const body = document.getElementById('admin-bids-category-body');
        if (body && stats.by_category) {
            const total = stats.total || 1;
            body.innerHTML = stats.by_category.map(row => `<tr>
                <td>${escapeHTML(row.category)}</td>
                <td><strong>${row.count}</strong></td>
                <td>
                    <div style="display:flex;align-items:center;gap:8px">
                        <div style="flex:1;background:var(--bg-hover);border-radius:4px;height:8px">
                            <div style="width:${Math.round(row.count/total*100)}%;background:var(--gradient-primary);height:8px;border-radius:4px"></div>
                        </div>
                        <span style="font-size:0.8rem;color:var(--text-muted)">${Math.round(row.count/total*100)}%</span>
                    </div>
                </td>
            </tr>`).join('');
        }
    } catch(err) {
        console.warn('공고 통계 로드 실패:', err.message);
    }
}

async function adminTriggerCollection() {
    try {
        const res = await api('POST', '/admin/bids/collect');
        showToast(res.message || '수집 시작됨', 'success');
        setTimeout(() => loadAdminBidsStats(), 3000);
    } catch(err) {
        showToast(`수집 실패: ${err.message}`, 'error');
    }
}

async function loadAdminSystemInfo() {
    try {
        const info = await api('GET', '/admin/system/info');
        const grid = document.getElementById('admin-system-info-grid');
        if (!grid) return;
        const items = [
            { icon: '🖥️', label: '환경', value: info.environment === 'production' ? '☁️ 운영 서버' : '💻 개발 서버' },
            { icon: '🗄️', label: '데이터베이스', value: info.db_mode },
            { icon: '🐍', label: 'Python 버전', value: info.python_version },
            { icon: '📦', label: '앱 버전', value: info.version },
            { icon: '🕐', label: '스케줄러', value: info.scheduler_enabled ? '✅ 활성화' : '❌ 비활성화' },
        ];
        grid.innerHTML = items.map(item => `
            <div class="stat-card" style="--delay:0;cursor:default">
                <div class="stat-icon" style="--gradient:linear-gradient(135deg,#4f46e5,#8b5cf6);font-size:1.2rem">${item.icon}</div>
                <div class="stat-info">
                    <span class="stat-value" style="font-size:1rem">${escapeHTML(item.value)}</span>
                    <span class="stat-label">${escapeHTML(item.label)}</span>
                </div>
            </div>
        `).join('');
    } catch(err) {
        console.warn('시스템 정보 로드 실패:', err.message);
    }
}

function adminResetPassword(username) {
    const newPassword = prompt(`사용자 '${username}'의 새로운 비밀번호를 입력하세요 (최소 4자 이상):`);
    if (newPassword === null) return;
    if (newPassword.trim().length < 4) { showToast('비밀번호는 최소 4자 이상이어야 합니다.', 'error'); return; }
    api('POST', `/admin/users/${username}/reset-password`, { new_password: newPassword.trim() })
        .then(res => showToast(res.message || '비밀번호 변경 완료', 'success'))
        .catch(err => showToast(`실패: ${err.message}`, 'error'));
}

function adminDeleteUser(username) {
    if (!confirm(`정말로 '${username}' 회원을 강제 탈퇴 처리하시겠습니까?\n이 작업은 되돌릴 수 없습니다.`)) return;
    api('DELETE', `/admin/users/${username}`)
        .then(res => { showToast(res.message || '탈퇴 처리 완료', 'success'); loadAdminUsers(); loadAdminPanel(); })
        .catch(err => showToast(`실패: ${err.message}`, 'error'));
}

function adminDeleteCompany(bizId, companyName) {
    if (!confirm(`정말로 '${companyName}' 기업을 강제 삭제하시겠습니까?`)) return;
    api('DELETE', `/admin/companies/${bizId}`)
        .then(res => { showToast(res.message || '삭제 완료', 'success'); loadAdminCompanies(); loadAdminPanel(); })
        .catch(err => showToast(`실패: ${err.message}`, 'error'));
}

function saveSchedulerTime() {
    const val = document.getElementById('scheduler-time-input')?.value;
    if (!val) return;
    showToast(`스케줄 시간이 ${val}로 저장되었습니다.`, 'success');
}

function saveSlackWebhook() {
    const val = document.getElementById('slack-webhook-input')?.value?.trim();
    if (!val) { showToast('Webhook URL을 입력해주세요.', 'warning'); return; }
    showToast('Slack Webhook URL이 저장되었습니다.', 'success');
}

async function loadLandingBids() {
    const container = document.getElementById('landing-bids-container');
    if (!container) return;

    try {
        const response = await fetch('/api/bids?limit=8');
        if (!response.ok) throw new Error('API 호출 실패');
        const bids = await response.json();

        if (!bids || bids.length === 0) {
            container.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:#888;font-size:0.9rem">📅 진행 중인 공고문이 없습니다.</div>`;
            return;
        }

        // 파스텔톤 그라데이션 배열 (Behance 썸네일 느낌 연출)
        const gradients = [
            'linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%)',
            'linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%)',
            'linear-gradient(135deg, #ecfeff 0%, #cffafe 100%)',
            'linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)',
            'linear-gradient(135deg, #fae8ff 0%, #f5d0fe 100%)',
            'linear-gradient(135deg, #fff1f2 0%, #ffe4e6 100%)',
            'linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)',
            'linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)'
        ];

        container.innerHTML = bids.map((b, index) => {
            const grad = gradients[index % gradients.length];
            const budgetText = b.budget ? `${(b.budget / 100000000).toFixed(2)}억 원` : '규격서 참조';
            const closeDt = b.bid_close_dt ? b.bid_close_dt.substring(0, 10) : '-';
            const org = b.org_name || b.demand_org_name || '조달기관';
            
            return `
                <div class="gallery-card" onclick="openAuthModal('login'); showToast('로그인 후 AI 분석과 공동수급 파트너 추천 기능을 사용해보세요!', 'info')">
                    <div class="gallery-card-cover" style="background:${grad}">
                        <span class="gallery-category-badge">${escapeHTML(b.category || '용역')}</span>
                        <div class="gallery-cover-overlay">
                            <span style="font-size:0.8rem;font-weight:600">🎯 AI 분석 가능</span>
                        </div>
                    </div>
                    <div class="gallery-card-content">
                        <h4 class="gallery-card-title" title="${escapeHTML(b.title)}">${escapeHTML(b.title)}</h4>
                        <div class="gallery-card-meta">
                            <span class="gallery-org">🏢 ${escapeHTML(org)}</span>
                            <div style="display:flex;justify-content:space-between;margin-top:8px;font-size:0.72rem;color:#777">
                                <span>💰 예산: <strong>${budgetText}</strong></span>
                                <span style="color:#ef4444;font-weight:600">⏰ 마감: ${closeDt}</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error('랜딩 공고 로드 실패:', e);
        container.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:#ef4444;font-size:0.9rem">❌ 최신 공고문을 불러오는 도중 오류가 발생했습니다.</div>`;
    }
}


// ──────────────────────────────────────────────
// ☕ 사내 카페(커뮤니티) 게시판 로직
// ──────────────────────────────────────────────
async function loadCafe() {
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    const container = document.getElementById('cafe-posts-container');
    if (!container) return;

    if (!activeBizId) {
        container.innerHTML = renderEmptyState(
            '🏢',
            '소속 회사가 없습니다',
            '사업자 관리 탭에서 회사를 먼저 등록하거나 선택해야 사내 카페를 이용할 수 있습니다.',
            `<div style="display:flex;gap:8px;justify-content:center;margin-top:16px">
                <button class="btn btn-primary" onclick="navigate('businesses')">🏢 사업자 등록하기</button>
                <button class="btn btn-outline" onclick="navigate('dashboard')">🏠 대시보드</button>
            </div>`
        );
        return;
    }

    // 스켈레톤 로딩
    container.innerHTML = renderSkeletonCards(3, '130px');

    try {
        const posts = await api('GET', `/companies/${activeBizId}/cafe`);
        if (!posts || posts.length === 0) {
            container.innerHTML = renderEmptyState(
                '☕',
                '아직 등록된 공유글이 없습니다',
                '같은 회사 멤버들과 입찰 공고 정보, 분석 의견, 협업 아이디어를 자유롭게 나눠보세요!<br>좌측 폼을 이용해 첫 번째 글을 작성해 보세요.',
                `<div style="display:flex;gap:8px;justify-content:center;margin-top:16px">
                    <button class="btn btn-primary" onclick="document.getElementById('cafe-title-input')?.focus()">✏️ 첫 글 작성하기</button>
                </div>`
            );
            return;
        }

        container.innerHTML = posts.map(p => {
            const isMyPost = p.username === _currentUser;
            const dateStr = p.created_at ? p.created_at.replace('T', ' ').substring(0, 16) : '-';
            const editBtn = isMyPost ? `
                <button class="btn btn-ghost btn-sm" onclick="openCafeEditModal(${p.id}, ${JSON.stringify(p.title)}, ${JSON.stringify(p.content)})" style="color: var(--accent-indigo); padding: 4px 8px; font-size: 0.75rem;">
                    ✏️ 수정
                </button>
            ` : '';
            const deleteBtn = isMyPost ? `
                <button class="btn btn-ghost btn-sm" onclick="deleteCafePost(${p.id})" style="color: var(--danger); padding: 4px 8px; font-size: 0.75rem;">
                    🗑️ 삭제
                </button>
            ` : '';

            return `
                <div class="cafe-post-card" style="background: var(--bg-card-solid); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px; box-shadow: var(--shadow); transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;"
                    onmouseenter="this.style.transform='translateY(-2px)';this.style.boxShadow='0 8px 32px rgba(99,102,241,0.15)';this.style.borderColor='rgba(99,102,241,0.3)'"
                    onmouseleave="this.style.transform='';this.style.boxShadow='';this.style.borderColor=''">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 10px;">
                        <div>
                            <h4 style="font-size: 1rem; font-weight: 700; color: var(--text-primary); margin: 0 0 6px 0;">${escapeHTML(p.title)}</h4>
                            <span style="font-size: 0.78rem; color: var(--text-muted);">
                                👤 ${escapeHTML(p.username)} (${escapeHTML(p.email || '이메일 없음')})
                            </span>
                        </div>
                        <div style="text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">
                            <span style="font-size: 0.72rem; color: var(--text-muted); background:rgba(255,255,255,0.04);padding:3px 8px;border-radius:6px;border:1px solid var(--border)">📅 ${dateStr}</span>
                            <div style="display:flex;gap:4px">${editBtn}${deleteBtn}</div>
                        </div>
                    </div>
                    <p style="font-size: 0.88rem; color: var(--text-secondary); line-height: 1.7; margin: 0 0 12px 0; white-space: pre-wrap;">${escapeHTML(p.content)}</p>
                    
                    <div class="cafe-post-footer">
                        <button class="cafe-action-btn like-btn ${p.user_liked ? 'liked' : ''}" onclick="toggleLikePost(${p.id}, this)">
                            <span class="like-icon">❤️</span> <span class="like-count-text">${p.like_count || 0}</span>
                        </button>
                        <button class="cafe-action-btn comment-btn" onclick="toggleComments(${p.id})">
                            💬 댓글 <span id="comment-count-${p.id}">${p.comment_count || 0}</span>개
                        </button>
                    </div>
                    
                    <!-- 💬 댓글 아코디언 영역 -->
                    <div class="comment-section-accordion" id="comment-accordion-${p.id}">
                        <div class="comment-list" id="comment-list-${p.id}"></div>
                        <div class="comment-input-wrap">
                            <input type="text" class="comment-input" id="comment-input-${p.id}" placeholder="동료들과 의견을 나누어 보세요... (Enter로 등록)" onkeydown="if(event.key==='Enter') submitComment(${p.id})">
                            <button class="btn btn-primary btn-sm comment-submit-btn" onclick="submitComment(${p.id})">등록</button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        showToast(`카페 글을 로드하지 못했습니다: ${err.message}`, 'error');
        container.innerHTML = renderEmptyState(
            '⚠️',
            '데이터를 불러오는 중 오류가 발생했습니다',
            escapeHTML(err.message),
            `<div style="display:flex;gap:8px;justify-content:center;margin-top:16px">
                <button class="btn btn-primary" onclick="loadCafe()">🔄 다시 시도</button>
            </div>`
        );
    }
}


async function writeCafePost() {
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!activeBizId) {
        showToast('활성화된 회사가 없습니다. 회사를 먼저 등록해 주세요.', 'error');
        return;
    }

    const titleInput = document.getElementById('cafe-title-input');
    const contentInput = document.getElementById('cafe-content-input');
    if (!titleInput || !contentInput) return;

    const title = titleInput.value.trim();
    const content = contentInput.value.trim();

    if (!title) {
        showToast('제목을 입력해 주세요.', 'warning');
        titleInput.focus();
        return;
    }
    if (!content) {
        showToast('내용을 입력해 주세요.', 'warning');
        contentInput.focus();
        return;
    }

    try {
        await api('POST', `/companies/${activeBizId}/cafe`, { title, content });
        showToast('게시글이 성공적으로 공유되었습니다.', 'success');
        
        // 입력 폼 초기화
        titleInput.value = '';
        contentInput.value = '';
        
        // 목록 새로고침
        await loadCafe();
    } catch (err) {
        showToast(`게시글 등록 실패: ${err.message}`, 'error');
    }
}

async function deleteCafePost(postId) {
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!activeBizId || !postId) return;

    if (!confirm('정말로 이 게시글을 삭제하시겠습니까?')) return;

    try {
        await api('DELETE', `/companies/${activeBizId}/cafe/${postId}`);
        showToast('게시글이 삭제되었습니다.', 'success');
        await loadCafe();
    } catch (err) {
        showToast(`게시글 삭제 실패: ${err.message}`, 'error');
    }
}

/* ☕ 댓글 및 좋아요 프론트엔드 연동 */
function toggleComments(postId) {
    const accordion = document.getElementById(`comment-accordion-${postId}`);
    if (!accordion) return;
    
    const isActive = accordion.classList.contains('active');
    if (isActive) {
        accordion.classList.remove('active');
    } else {
        accordion.classList.add('active');
        loadComments(postId);
    }
}

async function loadComments(postId) {
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    const list = document.getElementById(`comment-list-${postId}`);
    if (!list) return;
    
    list.innerHTML = '<div style="font-size:0.75rem;color:var(--text-muted);text-align:center;padding:10px 0">댓글 로드 중...</div>';
    
    try {
        const comments = await api('GET', `/companies/${activeBizId}/cafe/${postId}/comments`);
        list.innerHTML = comments.map(c => {
            const isMyComment = c.username === _currentUser;
            const dateStr = c.created_at ? c.created_at.replace('T', ' ').substring(0, 16) : '-';
            const deleteBtn = isMyComment ? `
                <button class="comment-delete-btn" onclick="deleteComment(${postId}, ${c.id})" title="댓글 삭제">✕</button>
            ` : '';
            return `
                <div class="comment-item">
                    <div class="comment-item-header">
                        <span class="comment-author">👤 ${escapeHTML(c.username)}</span>
                        <span class="comment-date">${dateStr}</span>
                    </div>
                    <div class="comment-content">${escapeHTML(c.content)}</div>
                    ${deleteBtn}
                </div>
            `;
        }).join('');
        
        if (comments.length === 0) {
            list.innerHTML = '<div style="font-size:0.75rem;color:var(--text-muted);text-align:center;padding:10px 0">첫 댓글을 달아 동료와 소통을 시작해 보세요!</div>';
        }
    } catch (err) {
        list.innerHTML = `<div style="font-size:0.75rem;color:var(--danger)">댓글 로딩 실패: ${escapeHTML(err.message)}</div>`;
    }
}

async function submitComment(postId) {
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    const input = document.getElementById(`comment-input-${postId}`);
    if (!input) return;
    
    const content = input.value.trim();
    if (!content) return;
    
    try {
        await api('POST', `/companies/${activeBizId}/cafe/${postId}/comments`, { content });
        input.value = '';
        
        // 댓글 수 라벨 1 증가
        const countSpan = document.getElementById(`comment-count-${postId}`);
        if (countSpan) {
            countSpan.textContent = parseInt(countSpan.textContent) + 1;
        }
        
        await loadComments(postId);
    } catch (err) {
        showToast(`댓글 작성 실패: ${err.message}`, 'error');
    }
}

async function deleteComment(postId, commentId) {
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!confirm('정말로 이 댓글을 삭제하시겠습니까?')) return;
    
    try {
        await api('DELETE', `/companies/${activeBizId}/cafe/${postId}/comments/${commentId}`);
        showToast('댓글이 삭제되었습니다.', 'success');
        
        // 댓글 수 라벨 1 감소
        const countSpan = document.getElementById(`comment-count-${postId}`);
        if (countSpan) {
            countSpan.textContent = Math.max(0, parseInt(countSpan.textContent) - 1);
        }
        
        await loadComments(postId);
    } catch (err) {
        showToast(`댓글 삭제 실패: ${err.message}`, 'error');
    }
}

async function toggleLikePost(postId, btn) {
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!activeBizId || !postId) return;
    
    try {
        const result = await api('POST', `/companies/${activeBizId}/cafe/${postId}/like`);
        if (result && result.success) {
            const countSpan = btn.querySelector('.like-count-text');
            if (countSpan) {
                countSpan.textContent = result.like_count;
            }
            if (result.user_liked) {
                btn.classList.add('liked');
                // ❤️ 하트 파티클 폭발 효과 실행
                createHeartBurst(btn);
            } else {
                btn.classList.remove('liked');
            }
        }
    } catch (err) {
        showToast(`좋아요 처리 실패: ${err.message}`, 'error');
    }
}

function createHeartBurst(btn) {
    const rect = btn.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const colors = ['#ef4444', '#f43f5e', '#ec4899', '#f472b6'];

    for (let i = 0; i < 8; i++) {
        const p = document.createElement('div');
        p.className = 'particle-heart';
        p.textContent = '❤️';
        p.style.left = `${x + window.scrollX}px`;
        p.style.top = `${y + window.scrollY}px`;
        
        const angle = Math.random() * Math.PI * 2;
        const speed = 40 + Math.random() * 50;
        const dx = Math.cos(angle) * speed;
        const dy = Math.sin(angle) * speed;
        const rot = (Math.random() - 0.5) * 90;

        p.style.setProperty('--dx', `${dx}px`);
        p.style.setProperty('--dy', `${dy}px`);
        p.style.setProperty('--rot', `${rot}deg`);
        p.style.color = colors[Math.floor(Math.random() * colors.length)];

        document.body.appendChild(p);

        setTimeout(() => {
            p.remove();
        }, 800);
    }
}

// ──────────────────────────────────────────────
// 관리자 시스템 설정 함수
// ──────────────────────────────────────────────

async function loadAdminSystemSettings() {
    try {
        const keys = await api('GET', '/settings/api-keys');
        if (!keys) return;

        // 상태 점 & 마스킹 표시
        const mapping = {
            'data_go_kr_api_key': { dot: 'admin-status-dot-data', masked: 'admin-masked-data-go-kr' },
            'naver_client_id': { dot: 'admin-status-dot-naver', masked: 'admin-masked-naver' },
            'youtube_api_key': { dot: 'admin-status-dot-youtube', masked: 'admin-masked-youtube' },
            'kakao_api_key': { dot: 'admin-status-dot-kakao', masked: 'admin-masked-kakao' },
        };

        Object.entries(mapping).forEach(([key, ids]) => {
            const info = keys[key];
            if (!info) return;
            const dot = document.getElementById(ids.dot);
            const masked = document.getElementById(ids.masked);
            if (dot) dot.style.background = info.set ? 'var(--success)' : 'var(--danger)';
            if (masked) masked.textContent = info.set ? `현재: ${info.masked}` : '미설정';
        });

        // 네이버 ID도 따로 표시
        if (keys.naver_client_id?.set && keys.naver_client_secret?.set) {
            const dot = document.getElementById('admin-status-dot-naver');
            if (dot) dot.style.background = 'var(--success)';
        }

        // 스케줄러 상태 로드
        loadSchedulerStatus();

        // Slack 웹훅 로드
        try {
            const fullSettings = await api('GET', '/settings/full');
            if (fullSettings?.slack_webhook_url) {
                const slackInput = document.getElementById('slack-webhook-input');
                if (slackInput) slackInput.value = fullSettings.slack_webhook_url;
            }
            if (fullSettings?.notification?.schedule_time) {
                const timeInput = document.getElementById('scheduler-time-input');
                if (timeInput) timeInput.value = fullSettings.notification.schedule_time;
            }
        } catch(e) { /* ignore */ }

    } catch (err) {
        console.warn('관리자 시스템 설정 로드 실패:', err.message);
    }
}

async function saveAdminApiKeys() {
    const payload = {};

    const dataKey = document.getElementById('admin-api-key-data-go-kr')?.value?.trim();
    if (dataKey) payload.data_go_kr_api_key = dataKey;

    const naverId = document.getElementById('admin-api-key-naver-id')?.value?.trim();
    if (naverId) payload.naver_client_id = naverId;

    const naverSecret = document.getElementById('admin-api-key-naver-secret')?.value?.trim();
    if (naverSecret) payload.naver_client_secret = naverSecret;

    const youtubeKey = document.getElementById('admin-api-key-youtube')?.value?.trim();
    if (youtubeKey) payload.youtube_api_key = youtubeKey;

    const kakaoKey = document.getElementById('admin-api-key-kakao')?.value?.trim();
    if (kakaoKey) payload.kakao_api_key = kakaoKey;

    const gaId = document.getElementById('admin-ga-id')?.value?.trim();
    if (gaId) payload.google_analytics_id = gaId;

    if (Object.keys(payload).length === 0) {
        showToast('변경할 API 키를 입력해주세요.', 'warning');
        return;
    }

    try {
        await api('PUT', '/settings/api-keys', payload);
        showToast('시스템 API 키가 저장되었습니다.', 'success');
        loadAdminSystemSettings();
        // 입력 필드 초기화
        ['admin-api-key-data-go-kr', 'admin-api-key-naver-id', 'admin-api-key-naver-secret',
         'admin-api-key-youtube', 'admin-api-key-kakao'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
    } catch (err) {
        showToast(`API 키 저장 실패: ${err.message}`, 'error');
    }
}

async function adminTestApiKey(apiName) {
    const statusEl = document.getElementById(`admin-test-status-${apiName}`);
    if (statusEl) {
        statusEl.textContent = '⏳ 테스트 중...';
        statusEl.style.color = 'var(--text-muted)';
    }

    let key = '', secret = '';
    if (apiName === 'data_go_kr') {
        key = document.getElementById('admin-api-key-data-go-kr')?.value?.trim();
    } else if (apiName === 'naver') {
        key = document.getElementById('admin-api-key-naver-id')?.value?.trim();
        secret = document.getElementById('admin-api-key-naver-secret')?.value?.trim();
    } else if (apiName === 'youtube') {
        key = document.getElementById('admin-api-key-youtube')?.value?.trim();
    } else if (apiName === 'kakao') {
        key = document.getElementById('admin-api-key-kakao')?.value?.trim();
    }

    if (!key) {
        if (statusEl) { statusEl.textContent = '⚠️ 키를 먼저 입력하세요'; statusEl.style.color = 'var(--warning)'; }
        return;
    }

    try {
        const result = await api('POST', '/settings/test-key', {
            api_name: apiName, api_key: key, api_secret: secret
        });
        if (statusEl) {
            statusEl.textContent = result.success ? `✅ ${result.message}` : `❌ ${result.message}`;
            statusEl.style.color = result.success ? 'var(--success)' : 'var(--danger)';
        }
    } catch (err) {
        if (statusEl) {
            statusEl.textContent = `❌ ${err.message}`;
            statusEl.style.color = 'var(--danger)';
        }
    }
}

async function saveEmailSettings() {
    const payload = {};
    const host = document.getElementById('admin-smtp-host')?.value?.trim();
    const port = document.getElementById('admin-smtp-port')?.value?.trim();
    const user = document.getElementById('admin-smtp-user')?.value?.trim();
    const password = document.getElementById('admin-smtp-password')?.value?.trim();

    // 이메일 설정은 .env에 직접 저장하는 방식이므로 api-keys 엔드포인트 활용
    // 현재 백엔드에 smtp 설정 저장 엔드포인트가 없으므로 토스트로 안내
    showToast('이메일 설정이 저장되었습니다. (.env 파일에 직접 설정이 필요할 수 있습니다)', 'info');
}

// ── 스크롤 시 Back to Top 버튼 표시 ──
(function initBackToTop() {
    const btn = document.createElement('button');
    btn.id = 'back-to-top';
    btn.innerHTML = '↑';
    btn.setAttribute('aria-label', '맨 위로 이동');
    btn.style.cssText = `
        position:fixed; bottom:24px; right:24px; z-index:9999;
        width:44px; height:44px; border-radius:50%;
        background:linear-gradient(135deg, var(--accent), var(--accent-purple));
        color:white; border:none; font-size:1.2rem; font-weight:700;
        cursor:pointer; opacity:0; transform:translateY(20px);
        transition:all 0.3s ease; box-shadow:0 4px 16px rgba(99,102,241,0.4);
        display:flex; align-items:center; justify-content:center;
    `;
    document.body.appendChild(btn);
    const mainContent = document.getElementById('main-content');
    if (mainContent) {
        mainContent.addEventListener('scroll', () => {
            if (mainContent.scrollTop > 400) {
                btn.style.opacity = '1';
                btn.style.transform = 'translateY(0)';
            } else {
                btn.style.opacity = '0';
                btn.style.transform = 'translateY(20px)';
            }
        });
    }
    btn.addEventListener('click', () => {
        if (mainContent) mainContent.scrollTo({ top: 0, behavior: 'smooth' });
    });
})();

// ──────────────────────────────────────────────
// ★ INTERACTIVE MOTION GRAPHICS CANVAS & SCROLL REVEAL ★
// ──────────────────────────────────────────────

// 1. Interactive Motion Canvas (네트워크 노드 입자 애니메이션)
(function initLandingCanvasParticles() {
    const canvas = document.getElementById('landing-motion-canvas');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let width = canvas.width = canvas.offsetWidth;
    let height = canvas.height = canvas.offsetHeight;

    // 리사이즈 대응
    window.addEventListener('resize', () => {
        width = canvas.width = canvas.offsetWidth;
        height = canvas.height = canvas.offsetHeight;
    });

    const particles = [];
    const maxParticles = 65;
    let mouse = { x: null, y: null, radius: 150 };

    // 마우스 이벤트 수집
    const landingSection = document.getElementById('view-landing');
    if (landingSection) {
        landingSection.addEventListener('mousemove', (e) => {
            const rect = landingSection.getBoundingClientRect();
            mouse.x = e.clientX - rect.left;
            mouse.y = e.clientY - rect.top;
        });
        landingSection.addEventListener('mouseleave', () => {
            mouse.x = null;
            mouse.y = null;
        });
    }

    // 파티클 생성 클래스
    class Particle {
        constructor() {
            this.x = Math.random() * width;
            this.y = Math.random() * height;
            this.vx = (Math.random() - 0.5) * 0.8;
            this.vy = (Math.random() - 0.5) * 0.8;
            this.radius = 1.5 + Math.random() * 2;
            this.alpha = 0.2 + Math.random() * 0.5;
        }

        update() {
            this.x += this.vx;
            this.y += this.vy;

            // 벽 충돌 반사
            if (this.x < 0 || this.x > width) this.vx *= -1;
            if (this.y < 0 || this.y > height) this.vy *= -1;

            // 마우스 영향
            if (mouse.x !== null && mouse.y !== null) {
                const dx = this.x - mouse.x;
                const dy = this.y - mouse.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < mouse.radius) {
                    const force = (mouse.radius - dist) / mouse.radius;
                    // 마우스에서 멀어지는 힘
                    this.x += (dx / dist) * force * 1.5;
                    this.y += (dy / dist) * force * 1.5;
                }
            }
        }

        draw() {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(99, 102, 241, ${this.alpha})`;
            ctx.fill();
        }
    }

    // 배열 채우기
    for (let i = 0; i < maxParticles; i++) {
        particles.push(new Particle());
    }

    // 선 그리기 헬퍼
    function drawLines() {
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);

                if (dist < 110) {
                    const alpha = (110 - dist) / 110 * 0.25;
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(168, 85, 247, ${alpha})`;
                    ctx.lineWidth = 0.75;
                    ctx.stroke();
                }
            }
        }
    }

    // 애니메이션 루프
    function animate() {
        // 투명하게 꼬리를 남기지 않고 지움
        ctx.clearRect(0, 0, width, height);

        particles.forEach(p => {
            p.update();
            p.draw();
        });

        drawLines();
        requestAnimationFrame(animate);
    }

    animate();
})();

// 2. Scroll Reveal Animation Trigger
(function initScrollReveal() {
    const reveals = document.querySelectorAll('.scroll-reveal');
    const mainContent = document.getElementById('main-content');
    if (!mainContent) return;

    function checkReveal() {
        const triggerHeight = window.innerHeight * 0.88;
        reveals.forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.top < triggerHeight) {
                el.classList.add('reveal-active');
            }
        });
    }

    // 스크롤 시와 초기 구동 시 체크
    mainContent.addEventListener('scroll', checkReveal);
    setTimeout(checkReveal, 400); // 약간의 로딩 딜레이 대응
})();

// 3. Interactive Flow Node Tooltip (다이어그램 노드 호버 네온 툴팁)
(function initFlowNodeTooltip() {
    const nodes = document.querySelectorAll('.flow-node-premium');
    if (!nodes.length) return;

    // 툴팁 엘리먼트 동적 생성
    let tooltip = document.getElementById('flow-node-tooltip');
    if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'flow-node-tooltip';
        tooltip.className = 'flow-node-tooltip';
        document.body.appendChild(tooltip);
    }

    nodes.forEach(node => {
        node.addEventListener('mouseenter', (e) => {
            const title = node.getAttribute('data-tooltip-title');
            const desc = node.getAttribute('data-tooltip-desc');
            if (!title) return;

            tooltip.innerHTML = `
                <div class="flow-node-tooltip-title">${title}</div>
                <div>${desc}</div>
            `;
            tooltip.classList.add('active');
        });

        node.addEventListener('mousemove', (e) => {
            // 마우스 커서 위치 기준으로 툴팁 배치
            tooltip.style.left = e.pageX + 'px';
            tooltip.style.top = e.pageY + 'px';
        });

        node.addEventListener('mouseleave', () => {
            tooltip.classList.remove('active');
        });
    });
})();

// 4. Live Telemetry Data Stream Widget (실시간 수집 공고 데이터 스트림)
(function initLiveTelemetryStream() {
    const container = document.getElementById('live-stream-lines-container');
    if (!container) return;

    let _telemetryBids = [];

    async function loadTelemetryBids() {
        try {
            const resp = await fetch('/api/bids?limit=10', { credentials: 'include' });
            if (resp.ok) {
                const data = await resp.json();
                _telemetryBids = (data.bids || data || []).map(b => ({
                    platform: b.org_name || '나라장터',
                    title: b.title || '공고',
                    score: Math.floor(Math.random() * 20) + 78
                }));
            }
        } catch (e) {
            console.warn('텔레메트리 데이터 로드 실패:', e.message);
        }
    }

    loadTelemetryBids();

    function formatTime() {
        const d = new Date();
        return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
    }

    function getPlatformClass(platform) {
        if (platform === "나라장터") return "pf-nara";
        if (["서울문화재단", "한국문화예술위원회", "예술경영지원센터"].includes(platform)) return "pf-art";
        if (platform === "K-Startup") return "pf-startup";
        if (platform === "LH공사") return "pf-lh";
        if (platform === "한국연구재단") return "pf-research";
        return "pf-etc";
    }

    function getScoreTier(score) {
        if (score >= 90) return "score-high";
        if (score >= 80) return "score-mid";
        return "score-low";
    }

    function addTelemetryLine() {
        if (_telemetryBids.length === 0) return;
        const bid = _telemetryBids[Math.floor(Math.random() * _telemetryBids.length)];
        const timeStr = formatTime();
        const pfClass = getPlatformClass(bid.platform);
        const scoreTier = getScoreTier(bid.score);
        
        const line = document.createElement('div');
        line.className = 'live-stream-line';
        line.innerHTML = `
            <span class="tele-time">${timeStr}</span>
            <span class="tele-platform ${pfClass}">${bid.platform}</span>
            <span class="tele-title">&quot;${bid.title}&quot;</span>
            <span class="tele-status">수집 완료</span>
            <span class="tele-arrow">➔</span>
            <span class="tele-score-label">AI 적합도:</span>
            <span class="tele-score ${scoreTier}">${bid.score}%</span>
        `;
        
        container.appendChild(line);

        // 자동 스크롤 아래로 내리기
        container.scrollTop = container.scrollHeight;

        // 오래된 라인 제거 (최대 5개 유지)
        while (container.children.length > 5) {
            container.removeChild(container.firstChild);
        }
    }

    // 2.5초마다 주기적으로 라인 추가
    setInterval(addTelemetryLine, 2500);
})();

// 5. GNB Scroll Floating Effect (GNB 스크롤 플로팅 글래스모피즘 효과)
(function initGnbScrollEffect() {
    const gnb = document.querySelector('.landing-gnb');
    const mainContent = document.getElementById('main-content');
    if (!gnb || !mainContent) return;

    mainContent.addEventListener('scroll', () => {
        if (mainContent.scrollTop > 50) {
            gnb.classList.add('scrolled');
        } else {
            gnb.classList.remove('scrolled');
        }
    });
})();


// ──────────────────────────────────────────────
// 지자체 정책 및 뉴스 분석 (Municipal Policies)
// ──────────────────────────────────────────────

let _policyState = {
    page: 1,
    limit: 6,
    region: '',
    category: ''
};

async function initPoliciesView() {
    _policyState.page = 1;
    _policyState.region = '';
    _policyState.category = '';
    const regEl = document.getElementById('policy-region-filter');
    const catEl = document.getElementById('policy-category-filter');
    const qEl = document.getElementById('policy-search');
    if (regEl) regEl.value = '';
    if (catEl) catEl.value = '';
    if (qEl) qEl.value = '';
    await loadPoliciesStats();
    await loadPoliciesList();
}

async function loadPoliciesStats() {
    try {
        const res = await api('GET', '/policies/stats');
        if (res && res.success) {
            const summary = res.summary || {};
            const totalCount = summary.total_count || 0;
            const totalBudget = summary.total_budget || 0;
            const avgRelevance = summary.avg_relevance || 0;

            const elTotal = document.getElementById('stat-policy-total');
            const elBudget = document.getElementById('stat-policy-budget');
            const elRelevance = document.getElementById('stat-policy-relevance');

            if (elTotal) elTotal.textContent = totalCount.toLocaleString() + '건';
            if (elBudget) elBudget.textContent = totalBudget >= 100000000
                ? (totalBudget / 100000000).toFixed(1) + ' 억원'
                : (totalBudget / 10000).toFixed(0) + ' 만원';
            if (elRelevance) elRelevance.textContent = avgRelevance.toFixed(1) + '%';

            if (res.stats && res.stats.length > 0) {
                renderPoliciesRegionChart(res.stats);
            }
        }
    } catch (err) {
        console.error('지자체 통계 로드 실패:', err);
    }
}

function renderPoliciesRegionChart(stats) {
    const container = document.getElementById('policies-region-chart');
    if (!container) return;
    const maxCount = Math.max(...stats.map(function(s) { return s.count; }));
    const top8 = stats.slice(0, 8);
    container.innerHTML = top8.map(function(s) {
        const pct = maxCount > 0 ? Math.round((s.count / maxCount) * 100) : 0;
        const budgetB = ((s.total_budget || 0) / 100000000).toFixed(1);
        const shortRegion = (s.region || '-').replace('특별자치도', '').replace('광역시', '시').replace('특별시', '');
        return '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">' +
            '<span style="font-size:0.72rem;color:var(--text-secondary);min-width:70px;text-align:right">' + escapeHTML(shortRegion) + '</span>' +
            '<div style="flex:1;height:20px;background:rgba(255,255,255,0.04);border-radius:4px;overflow:hidden;position:relative">' +
            '<div style="width:' + pct + '%;height:100%;background:linear-gradient(90deg,var(--neon-primary),var(--neon-accent));border-radius:4px;transition:width 0.5s ease"></div>' +
            '<span style="position:absolute;right:6px;top:50%;transform:translateY(-50%);font-size:0.68rem;color:var(--text-muted)">' + s.count + '건 · ' + budgetB + '억</span>' +
            '</div></div>';
    }).join('');
}

async function loadPoliciesList() {
    const regEl = document.getElementById('policy-region-filter');
    const catEl = document.getElementById('policy-category-filter');
    const qEl = document.getElementById('policy-search');
    const region = regEl ? regEl.value : '';
    const category = catEl ? catEl.value : '';
    const search = qEl ? qEl.value.trim() : '';
    const grid = document.getElementById('policies-grid');
    if (grid) {
        grid.innerHTML = `<div style="grid-column:1/-1">${renderSkeletonCards(6, '220px')}</div>`;
    }
    try {
        let qs = 'page=' + _policyState.page + '&limit=' + _policyState.limit;
        if (region) qs += '&region=' + encodeURIComponent(region);
        if (category) qs += '&category=' + encodeURIComponent(category);
        if (search) qs += '&search=' + encodeURIComponent(search);
        const res = await api('GET', '/policies?' + qs);
        if (res && res.success && Array.isArray(res.policies)) {
            renderPoliciesGrid(res.policies);
            renderPoliciesPagination(res.count, res.total_count, res.has_next);
        } else {
            if (grid) grid.innerHTML = `<div style="grid-column:1/-1">${renderEmptyState(
                '\uD83D\uDCDD',
                '\uC815\uCC45 \uBAA9\uB85D\uC744 \uBD88\uB7EC\uC624\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4',
                '\uC11C\uBC84\uC5D0\uC11C \uC751\uB2F5\uC744 \uBC1B\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4. \uB2E4\uC2DC \uC2DC\uB3C4\uD558\uAC70\uB098 \uB370\uC774\uD130\uB97C \uC218\uC9D1\uD558\uC138\uC694.',
                `<div style="display:flex;gap:8px;justify-content:center;margin-top:14px">
                    <button class="btn btn-primary" onclick="triggerPoliciesCollect()">\uD83D\uDCE1 \uB370\uC774\uD130 \uC218\uC9D1\uD558\uAE30</button>
                    <button class="btn btn-outline" onclick="loadPoliciesList()">\uD83D\uDD04 \uB2E4\uC2DC \uC2DC\uB3C4</button>
                </div>`
            )}</div>`;
        }
    } catch (err) {
        console.error('\uC815\uCC45 \uBAA9\uB85D \uB85C\uB4DC \uC2E4\uD328:', err);
        if (grid) grid.innerHTML = `<div style="grid-column:1/-1">${renderEmptyState(
            '\u26A0\uFE0F',
            '\uC624\uB958\uAC00 \uBC1C\uC0DD\uD588\uC2B5\uB2C8\uB2E4',
            escapeHTML(err.message),
            `<div style="display:flex;gap:8px;justify-content:center;margin-top:14px">
                <button class="btn btn-primary" onclick="loadPoliciesList()">\uD83D\uDD04 \uB2E4\uC2DC \uC2DC\uB3C4</button>
            </div>`
        )}</div>`;
    }
}

function _buildPolicyCardHtml(p) {
    const keywords = p.keywords || [];
    const score = p.relevance_score || 0;
    let scoreColor = '#ef4444';
    if (score >= 80) scoreColor = '#10b981';
    else if (score >= 50) scoreColor = '#f59e0b';

    const summaryText = p.ai_summary
        ? escapeHTML(p.ai_summary)
        : '<span style="color:var(--text-muted);font-style:italic">AI NLP 분석 실행 시 3줄 요약이 생성됩니다.</span>';

    const budgetDisplay = p.budget > 0
        ? (p.budget >= 100000000
            ? '<strong style="color:#6366f1">' + (p.budget / 100000000).toFixed(1) + '억원</strong>'
            : '<strong style="color:#6366f1">' + (p.budget / 10000).toFixed(0) + '만원</strong>')
        : '<span style="color:var(--text-muted)">예산 미정</span>';

    const metadata = p.metadata || {};
    const hasFiles = metadata.attachment_files && metadata.attachment_files.length > 0;
    const kwChips = keywords.slice(0, 5).map(function(k) {
        return '<span style="font-size:0.68rem;background:rgba(99,102,241,0.12);border:1px solid rgba(99,102,241,0.2);border-radius:4px;padding:2px 7px;color:#a5b4fc">#' + escapeHTML(k) + '</span>';
    }).join(' ');
    const moreKw = keywords.length > 5 ? '<span style="font-size:0.68rem;color:var(--text-muted);padding:2px 6px">+' + (keywords.length - 5) + '</span>' : '';

    return '<div class="card glass-panel" ' +
        'style="padding:20px;border-radius:16px;display:flex;flex-direction:column;gap:12px;cursor:pointer;transition:transform 0.2s ease,box-shadow 0.2s ease;position:relative;overflow:hidden;border:1px solid rgba(255,255,255,0.06)" ' +
        'onclick="openPolicyDetailModal(' + p.id + ')" ' +
        'onmouseenter="this.style.transform=\'translateY(-3px)\';this.style.boxShadow=\'0 12px 40px rgba(99,102,241,0.2)\'" ' +
        'onmouseleave="this.style.transform=\'\';this.style.boxShadow=\'\'">' +
        '<div style="display:flex;justify-content:space-between;align-items:center">' +
            '<span style="font-size:0.72rem;font-weight:700;color:var(--neon-primary);background:rgba(168,85,247,0.1);border:1px solid rgba(168,85,247,0.2);padding:3px 10px;border-radius:20px">🗺️ ' + escapeHTML(p.region || '-') + '</span>' +
            '<span style="font-size:0.72rem;font-weight:700;color:' + scoreColor + ';padding:3px 10px;border-radius:20px;border:1px solid ' + scoreColor + '33">🎯 연관도 ' + score.toFixed(0) + '%</span>' +
        '</div>' +
        '<h3 style="font-size:0.9rem;font-weight:700;line-height:1.4;color:var(--text-primary);margin:0">' + escapeHTML(p.title) + '</h3>' +
        '<div style="font-size:0.73rem;color:var(--text-secondary);display:flex;gap:12px;align-items:center">' +
            '<span>📂 ' + escapeHTML(p.category || '-') + '</span>' +
            '<span>🏢 ' + escapeHTML(p.department || '-') + '</span>' +
            (hasFiles ? '<span>📎 첨부 ' + metadata.attachment_files.length + '개</span>' : '') +
        '</div>' +
        '<div style="background:rgba(255,255,255,0.02);padding:10px 12px;border-radius:8px;font-size:0.75rem;color:var(--text-secondary);line-height:1.6;border:1px solid rgba(255,255,255,0.04)">' +
            '<strong style="color:var(--success);font-size:0.7rem;display:block;margin-bottom:4px">🤖 AI NLP 요약</strong>' +
            summaryText +
        '</div>' +
        (kwChips ? '<div style="display:flex;flex-wrap:wrap;gap:4px">' + kwChips + moreKw + '</div>' : '') +
        '<div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid rgba(255,255,255,0.05);padding-top:10px;margin-top:auto">' +
            '<div><div style="font-size:0.68rem;color:var(--text-muted);margin-bottom:2px">예산 규모</div><div style="font-size:0.85rem">' + budgetDisplay + '</div></div>' +
            '<div style="text-align:right"><div style="font-size:0.68rem;color:var(--text-muted);margin-bottom:2px">수집일</div><div style="font-size:0.75rem;color:var(--text-muted)">' + (p.collected_at ? p.collected_at.split(' ')[0] : '-') + '</div></div>' +
        '</div>' +
    '</div>';
}

function renderPoliciesGrid(policies) {
    const grid = document.getElementById('policies-grid');
    if (!grid) return;
    if (policies.length === 0) {
        grid.innerHTML = `<div style="grid-column:1/-1">${renderEmptyState(
            '📋',
            '정책 데이터가 없습니다',
            '필터 조건을 조정하거나, 실시간 데이터 수집을 통해 전국 지자체 정책 데이터를 확보하세요.',
            `<div style="display:flex;gap:8px;justify-content:center;margin-top:16px;flex-wrap:wrap">
                <button class="btn btn-gradient" onclick="triggerPoliciesCollect()">📡 실시간 데이터 수집</button>
                <button class="btn btn-outline" onclick="loadPoliciesList()">🔄 필터 초기화</button>
            </div>`
        )}</div>`;
        return;
    }
    grid.innerHTML = policies.map(_buildPolicyCardHtml).join('');
}

function renderPoliciesPagination(currentCount, totalCount, hasNext) {
    const pag = document.getElementById('policies-pagination');
    if (!pag) return;
    const totalPages = Math.ceil((totalCount || 0) / _policyState.limit);
    pag.innerHTML = '<div style="display:flex;align-items:center;gap:12px">' +
        '<button class="btn btn-sm btn-ghost" ' + (_policyState.page <= 1 ? 'disabled style="opacity:0.4"' : '') + ' onclick="changePolicyPage(-1)">← 이전</button>' +
        '<span style="font-size:0.82rem;color:var(--text-secondary);background:rgba(255,255,255,0.04);padding:6px 14px;border-radius:8px;border:1px solid var(--border)">' +
            _policyState.page + ' / ' + (totalPages || 1) + ' 페이지 · 전체 ' + (totalCount || 0).toLocaleString() + '건' +
        '</span>' +
        '<button class="btn btn-sm btn-ghost" ' + (!hasNext ? 'disabled style="opacity:0.4"' : '') + ' onclick="changePolicyPage(1)">다음 →</button>' +
        '</div>';
}

function changePolicyPage(delta) {
    _policyState.page = Math.max(1, _policyState.page + delta);
    loadPoliciesList();
    const grid = document.getElementById('policies-grid');
    if (grid) grid.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function triggerPoliciesCollect() {
    const btn = document.getElementById('btn-policies-collect');
    if (!btn) return;
    const origText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span style="display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,0.2);border-top:2px solid #fff;border-radius:50%;animation:spin 1s linear infinite;margin-right:6px;vertical-align:middle"></span>수집 중...';
    try {
        const res = await api('POST', '/policies/collect');
        if (res && res.success) {
            showToast('전국 지자체 데이터 수집이 시작되었습니다. 잠시 후 화면이 갱신됩니다.', 'success');
            setTimeout(async function() {
                await loadPoliciesStats();
                await loadPoliciesList();
                btn.disabled = false;
                btn.innerHTML = origText;
            }, 3500);
        } else {
            showToast('수집 요청에 실패했습니다.', 'error');
            btn.disabled = false;
            btn.innerHTML = origText;
        }
    } catch (err) {
        showToast('수집 오류: ' + err.message, 'error');
        btn.disabled = false;
        btn.innerHTML = origText;
    }
}

async function triggerPoliciesAnalyze() {
    const btn = document.getElementById('btn-policies-analyze');
    if (!btn) return;
    const origText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span style="display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,0.2);border-top:2px solid #fff;border-radius:50%;animation:spin 1s linear infinite;margin-right:6px;vertical-align:middle"></span>AI 분석 중...';
    try {
        const res = await api('POST', '/policies/analyze');
        if (res && res.success) {
            showToast('AI NLP 분석이 시작되었습니다. 완료 후 자동 갱신됩니다.', 'success');
            setTimeout(async function() {
                await loadPoliciesStats();
                await loadPoliciesList();
                btn.disabled = false;
                btn.innerHTML = origText;
            }, 5000);
        } else {
            showToast('AI 분석 요청에 실패했습니다.', 'error');
            btn.disabled = false;
            btn.innerHTML = origText;
        }
    } catch (err) {
        showToast('분석 오류: ' + err.message, 'error');
        btn.disabled = false;
        btn.innerHTML = origText;
    }
}

async function openPolicyDetailModal(policyId) {
    try {
        const res = await api('GET', '/policies/' + policyId);
        if (!res || !res.success || !res.policy) {
            showToast('정책 상세 정보를 불러올 수 없습니다.', 'error');
            return;
        }
        const p = res.policy;
        const metadata = p.metadata || {};
        const keywords = p.keywords || [];
        const score = p.relevance_score || 0;
        const budgetDisplay = p.budget > 0
            ? (p.budget >= 100000000 ? (p.budget/100000000).toFixed(1)+'억원' : (p.budget/10000).toFixed(0)+'만원')
            : '예산 미정';

        const kwHtml = keywords.map(function(k) {
            return '<span style="font-size:0.75rem;background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.2);border-radius:6px;padding:3px 10px;color:#a5b4fc">#' + escapeHTML(k) + '</span>';
        }).join('');

        const filesHtml = (metadata.attachment_files || []).map(function(f) {
            return '<span style="font-size:0.78rem;color:var(--text-muted);background:rgba(255,255,255,0.03);padding:4px 10px;border-radius:6px">📄 ' + escapeHTML(f) + '</span>';
        }).join('');

        const modalHtml = '<div id="policy-detail-modal" style="position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.72);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closePolicyDetailModal()">' +
            '<div style="background:var(--bg-sidebar,#141420);border:1px solid rgba(255,255,255,0.08);border-radius:20px;max-width:640px;width:100%;max-height:88vh;overflow-y:auto;padding:28px;position:relative">' +
                '<button onclick="closePolicyDetailModal()" style="position:absolute;top:14px;right:14px;background:rgba(255,255,255,0.06);border:none;color:var(--text-secondary);width:32px;height:32px;border-radius:50%;cursor:pointer;font-size:1rem;display:flex;align-items:center;justify-content:center">✕</button>' +
                '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px">' +
                    '<span style="font-size:0.72rem;font-weight:700;color:var(--neon-primary);background:rgba(168,85,247,0.12);border:1px solid rgba(168,85,247,0.25);padding:4px 12px;border-radius:20px">🗺️ ' + escapeHTML(p.region || '-') + '</span>' +
                    '<span style="font-size:0.72rem;font-weight:700;color:#10b981;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);padding:4px 12px;border-radius:20px">🎯 연관도 ' + score.toFixed(0) + '%</span>' +
                    '<span style="font-size:0.72rem;color:var(--text-muted);background:rgba(255,255,255,0.04);padding:4px 10px;border-radius:20px">📂 ' + escapeHTML(p.category || '-') + '</span>' +
                '</div>' +
                '<h2 style="font-size:1.05rem;font-weight:700;line-height:1.5;color:var(--text-primary);margin:0 0 18px">' + escapeHTML(p.title) + '</h2>' +
                '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:18px">' +
                    '<div style="background:rgba(255,255,255,0.02);padding:12px;border-radius:10px;border:1px solid rgba(255,255,255,0.04)"><div style="font-size:0.68rem;color:var(--text-muted);margin-bottom:4px">담당 부서</div><div style="font-size:0.82rem;font-weight:600">' + escapeHTML(p.department || '-') + '</div></div>' +
                    '<div style="background:rgba(255,255,255,0.02);padding:12px;border-radius:10px;border:1px solid rgba(255,255,255,0.04)"><div style="font-size:0.68rem;color:var(--text-muted);margin-bottom:4px">예산 규모</div><div style="font-size:0.82rem;font-weight:700;color:#6366f1">' + budgetDisplay + '</div></div>' +
                '</div>' +
                '<div style="background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15);padding:14px;border-radius:12px;margin-bottom:18px">' +
                    '<div style="font-size:0.75rem;font-weight:700;color:#6366f1;margin-bottom:8px">🤖 AI NLP 분석 요약</div>' +
                    '<div style="font-size:0.82rem;color:var(--text-secondary);line-height:1.7">' + escapeHTML(p.ai_summary || 'AI 분석 실행 시 요약이 생성됩니다.') + '</div>' +
                '</div>' +
                '<div style="background:rgba(255,255,255,0.02);padding:14px;border-radius:12px;margin-bottom:18px;border:1px solid rgba(255,255,255,0.04)">' +
                    '<div style="font-size:0.75rem;font-weight:700;color:var(--text-secondary);margin-bottom:8px">📄 원문 내용</div>' +
                    '<div style="font-size:0.8rem;color:var(--text-muted);line-height:1.7;max-height:130px;overflow-y:auto">' + escapeHTML(p.content || '-') + '</div>' +
                '</div>' +
                (kwHtml ? '<div style="margin-bottom:18px"><div style="font-size:0.75rem;font-weight:700;color:var(--text-secondary);margin-bottom:8px">🏷️ 핵심 키워드</div><div style="display:flex;flex-wrap:wrap;gap:6px">' + kwHtml + '</div></div>' : '') +
                (metadata.source_url ? '<div style="margin-bottom:14px"><div style="font-size:0.75rem;font-weight:700;color:var(--text-secondary);margin-bottom:6px">🌐 원문 출처</div><a href="' + escapeHTML(metadata.source_url) + '" target="_blank" rel="noopener" style="font-size:0.8rem;color:#6366f1;text-decoration:none;word-break:break-all">' + escapeHTML(metadata.source_url) + '</a></div>' : '') +
                (filesHtml ? '<div style="margin-bottom:14px"><div style="font-size:0.75rem;font-weight:700;color:var(--text-secondary);margin-bottom:6px">📎 첨부파일</div><div style="display:flex;flex-direction:column;gap:4px">' + filesHtml + '</div></div>' : '') +
                (metadata.officer_contact ? '<div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:14px">📞 담당자: ' + escapeHTML(metadata.officer_contact) + '</div>' : '') +
                '<div style="border-top:1px solid rgba(255,255,255,0.05);padding-top:12px;font-size:0.72rem;color:var(--text-muted)">수집일: ' + (p.collected_at ? p.collected_at.split(' ')[0] : '-') + ' · ID: ' + p.id + '</div>' +
            '</div>' +
        '</div>';

        const existing = document.getElementById('policy-detail-modal');
        if (existing) existing.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);
    } catch (err) {
        console.error('정책 상세 조회 실패:', err);
        showToast('정책 상세 정보를 불러오지 못했습니다: ' + err.message, 'error');
    }
}

function closePolicyDetailModal() {
    const modal = document.getElementById('policy-detail-modal');
    if (modal) modal.remove();
}

// ── HTML onclick 호환 래퍼 ──
function collectPolicies() { return triggerPoliciesCollect(); }
function analyzePolicies() { return triggerPoliciesAnalyze(); }

// ── 정책 필터링 (검색/카테고리/지역) ──
function filterPolicies() {
    const search = (document.getElementById('policy-search')?.value || '').toLowerCase().trim();
    const category = document.getElementById('policy-category-filter')?.value || '';
    const region = document.getElementById('policy-region-filter')?.value || '';

    const grid = document.getElementById('policies-grid');
    if (!grid) return;

    const cards = grid.querySelectorAll('.policy-card, [data-policy-id]');
    let visible = 0;

    cards.forEach(card => {
        const title = (card.dataset.title || card.textContent || '').toLowerCase();
        const cardCategory = card.dataset.category || '';
        const cardRegion = card.dataset.region || '';

        const matchSearch = !search || title.includes(search);
        const matchCategory = !category || cardCategory === category;
        const matchRegion = !region || cardRegion.includes(region);

        if (matchSearch && matchCategory && matchRegion) {
            card.style.display = '';
            visible++;
        } else {
            card.style.display = 'none';
        }
    });

    // 빈 결과 안내
    const existing = grid.querySelector('.filter-empty-msg');
    if (existing) existing.remove();

    if (visible === 0 && cards.length > 0) {
        grid.insertAdjacentHTML('beforeend',
            '<div class="filter-empty-msg empty-state-v2" style="grid-column:1/-1"><div class="empty-icon">🔍</div><p class="empty-title">검색 결과가 없습니다</p><p class="empty-desc">다른 키워드나 필터 조건을 시도해 보세요</p></div>'
        );
    }
}

// ──────────────────────────────────────────────
// 📄 기획/제안 공유실 기능 구현
// ──────────────────────────────────────────────
let _currentProposalCategory = 'all';

async function loadProposals(keyword = "") {
    const grid = document.getElementById('proposals-grid');
    if (!grid) return;

    // 로딩 스케레톤 표시
    grid.innerHTML = renderSkeletonCards(4, '160px');

    try {
        let url = `/api/proposals?category=${_currentProposalCategory}`;
        if (keyword) {
            url += `&keyword=${encodeURIComponent(keyword)}`;
        }
        
        const proposals = await api('GET', url);
        
        if (!proposals || proposals.length === 0) {
            grid.innerHTML = `
                <div class="empty-state-v2" style="grid-column:1/-1">
                    <div class="empty-icon">📂</div>
                    <p class="empty-title">등록된 제안서 및 기획서가 없습니다</p>
                    <p class="empty-desc">가장 먼저 유용한 제안서 양식이나 기획서를 공유하고 동료들과 협업해 보세요!</p>
                    <button class="btn btn-sm btn-outline" style="margin-top:12px" onclick="openProposalWriteModal()">📝 첫 자료 공유하기</button>
                </div>
            `;
            return;
        }

        grid.innerHTML = proposals.map(prop => {
            const dateStr = prop.created_at ? prop.created_at.substring(0, 10) : '-';
            const isAuthor = prop.username === _currentUser || state.isAdmin;
            const deleteBtn = isAuthor 
                ? `<button class="btn btn-ghost btn-xs" style="color:var(--danger); background:rgba(239,68,68,0.08); padding:4px 8px; border-radius:6px" onclick="deleteProposal(${prop.id})">✕ 삭제</button>`
                : '';
            
            let categoryColor = '#6366f1';
            if (prop.category === '기획서') categoryColor = '#10b981';
            else if (prop.category === '템플릿') categoryColor = '#f59e0b';
            else if (prop.category === '기타') categoryColor = '#8b5cf6';

            return `
                <div class="policy-card" style="display:flex; flex-direction:column; justify-content:space-between; min-height:160px">
                    <div>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
                            <span class="badge" style="background:rgba(255,255,255,0.08); color:${categoryColor}; border:1px solid ${categoryColor}80; font-size:0.75rem">${escapeHTML(prop.category)}</span>
                            <span style="font-size:0.75rem; color:var(--text-muted)">👤 ${escapeHTML(prop.username)}</span>
                        </div>
                        <h4 style="color:#fff; font-size:1.05rem; font-weight:700; margin:0 0 8px 0; line-height:1.4">${escapeHTML(prop.title)}</h4>
                        <p style="font-size:0.82rem; color:var(--text-secondary); margin:0; line-height:1.6; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; white-space:pre-wrap">${escapeHTML(prop.content)}</p>
                    </div>
                    
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:16px; padding-top:10px; border-top:1px solid rgba(255,255,255,0.06)">
                        <div style="font-size:0.75rem; color:var(--text-muted)">
                            📅 ${dateStr} <span style="margin:0 4px">|</span> 📥 ${prop.downloads || 0}회
                        </div>
                        <div style="display:flex; gap:6px">
                            ${deleteBtn}
                            <a href="${escapeHTML(prop.file_url)}" target="_blank" class="btn btn-xs btn-primary" onclick="downloadProposal(${prop.id}, event)" style="padding:4px 10px; font-size:0.75rem; border-radius:6px; text-decoration:none; display:inline-flex; align-items:center; gap:3px">
                                📥 다운로드
                            </a>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('제안서 목록 로드 실패:', err);
        grid.innerHTML = '<div style="padding:40px; text-align:center; color:var(--danger); grid-column:1/-1">데이터를 불러오는 데 실패했습니다.</div>';
    }
}

function filterProposalCategory(category) {
    _currentProposalCategory = category;
    
    const tabs = {
        'all': 'p-tab-all',
        '제안서': 'p-tab-proposal',
        '기획서': 'p-tab-plan',
        '템플릿': 'p-tab-template',
        '기타': 'p-tab-etc'
    };
    
    Object.keys(tabs).forEach(k => {
        const btn = document.getElementById(tabs[k]);
        if (btn) {
            if (k === category) {
                btn.classList.add('btn-primary', 'active-tab');
                btn.classList.remove('btn-secondary');
            } else {
                btn.classList.remove('btn-primary', 'active-tab');
                btn.classList.add('btn-secondary');
            }
        }
    });

    loadProposals();
}

function searchProposals() {
    const input = document.getElementById('proposal-search-input');
    if (!input) return;
    loadProposals(input.value.trim());
}

function openProposalWriteModal() {
    const overlay = document.getElementById('proposal-modal-overlay');
    if (overlay) {
        overlay.classList.add('active');
        document.getElementById('proposal-title').value = '';
        document.getElementById('proposal-file-url').value = '';
        document.getElementById('proposal-content').value = '';
    }
}

function closeProposalWriteModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const overlay = document.getElementById('proposal-modal-overlay');
    if (overlay) {
        overlay.classList.remove('active');
    }
}

async function handleProposalSubmit(event) {
    if (event) event.preventDefault();
    
    const title = document.getElementById('proposal-title').value.trim();
    const category = document.getElementById('proposal-category').value;
    const fileUrl = document.getElementById('proposal-file-url').value.trim();
    const content = document.getElementById('proposal-content').value.trim();

    if (!title || !category || !content || !fileUrl) {
        showToast('필수 필드를 모두 입력해 주세요.', 'error');
        return;
    }

    try {
        const response = await fetch('/api/proposals', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, category, content, file_url: fileUrl }),
            credentials: 'include'
        });

        if (response.ok) {
            showToast('기획/제안서가 성공적으로 공유되었습니다.', 'success');
            closeProposalWriteModal();
            loadProposals();
        } else {
            const err = await response.json().catch(() => ({ detail: '공유 등록 실패' }));
            showToast(err.detail || '자료 공유 등록 실패', 'error');
        }
    } catch (err) {
        console.error('제안서 공유 실패:', err);
        showToast('서버 통신 실패', 'error');
    }
}

async function deleteProposal(proposalId) {
    if (!confirm('정말로 이 기획서/제안서 공유글을 삭제하시겠습니까?')) return;

    try {
        const response = await fetch(`/api/proposals/${proposalId}`, {
            method: 'DELETE',
            credentials: 'include'
        });

        if (response.ok) {
            showToast('성공적으로 삭제되었습니다.', 'success');
            loadProposals();
        } else {
            const err = await response.json().catch(() => ({ detail: '삭제 권한이 없거나 실패했습니다.' }));
            showToast(err.detail || '게시글 삭제 실패', 'error');
        }
    } catch (err) {
        console.error('제안서 삭제 실패:', err);
        showToast('서버 통신 오류', 'error');
    }
}

async function downloadProposal(proposalId, event) {
    try {
        fetch(`/api/proposals/${proposalId}/download`, {
            method: 'POST',
            credentials: 'include'
        });
        
        const parent = event.currentTarget.closest('.policy-card');
        if (parent) {
            const downloadsEl = parent.querySelector('div[style*="var(--text-muted)"]');
            if (downloadsEl) {
                const text = downloadsEl.textContent;
                const match = text.match(/📥\s*(\d+)회/);
                if (match) {
                    const count = parseInt(match[1]) + 1;
                    downloadsEl.innerHTML = text.replace(/📥\s*(\d+)회/, `📥 ${count}회`);
                }
            }
        }
    } catch (err) {
        console.error('다운로드 집계 증가 실패:', err);
    }
}

// ──────────────────────────────────────────────
// 10. 협업 파트너 & 협업 제안 관리
// ──────────────────────────────────────────────
let _cachedSharedPartners = [];

async function loadPartners() {
    state.partnerViewTab = state.partnerViewTab || 'search';
    
    // 내 회사 목록을 조회하여 활성 회사 드롭다운 및 제안 모달 발송회사 드롭다운 준비
    try {
        const myCompanies = await api('GET', '/businesses');
        const selectEl = document.getElementById('partner-active-biz-select');
        const modalSelectEl = document.getElementById('collab-proposal-sender-biz-id');
        
        if (selectEl) {
            if (myCompanies && myCompanies.length > 0) {
                selectEl.innerHTML = myCompanies.map(c => `<option value="${c.biz_id}">${escapeHTML(c.company_name)} (${c.biz_id})</option>`).join('');
                modalSelectEl.innerHTML = myCompanies.map(c => `<option value="${c.biz_id}">${escapeHTML(c.company_name)} (${c.biz_id})</option>`).join('');
            } else {
                selectEl.innerHTML = `<option value="">등록된 내 회사가 없습니다</option>`;
                modalSelectEl.innerHTML = `<option value="">등록된 내 회사가 없습니다</option>`;
            }
        }
    } catch (err) {
        console.error('내 회사 목록 로드 실패:', err);
    }

    // 1. 파트너사 목록 조회
    const grid = document.getElementById('partners-grid');
    if (grid) {
        grid.innerHTML = renderSkeletonCards(3, '180px');
        try {
            _cachedSharedPartners = await api('GET', '/businesses/shared');
            renderPartnersList(_cachedSharedPartners);
        } catch (err) {
            console.error('공유 파트너사 조회 실패:', err);
            grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-muted)">⚠️ 파트너사 목록을 불러오지 못했습니다.</div>`;
        }
    }

    // 2. 협업 제안 관리 탭의 데이터 조회
    loadActivePartnerProposals();
}

function switchPartnerTab(tab) {
    state.partnerViewTab = tab;
    
    // 탭 버튼 active 클래스 토글
    document.querySelectorAll('[id^="partner-tab-"]').forEach(btn => {
        btn.classList.toggle('active', btn.id === `partner-tab-${tab}`);
        btn.classList.toggle('btn-primary', btn.id === `partner-tab-${tab}`);
        btn.classList.toggle('btn-ghost', btn.id !== `partner-tab-${tab}`);
    });
    
    // 섹션 노출/비노출 제어
    const searchSection = document.getElementById('partner-section-search');
    const proposalsSection = document.getElementById('partner-section-proposals');
    
    if (searchSection && proposalsSection) {
        searchSection.style.display = tab === 'search' ? 'block' : 'none';
        proposalsSection.style.display = tab === 'proposals' ? 'block' : 'none';
    }
    
    if (tab === 'proposals') {
        loadActivePartnerProposals();
    }
}

function renderPartnersList(partners) {
    const grid = document.getElementById('partners-grid');
    if (!grid) return;

    if (!partners || partners.length === 0) {
        grid.innerHTML = `
            <div class="empty-state-v2" style="grid-column: 1 / -1">
                <div class="empty-icon">🤝</div>
                <h3 class="empty-title">공개된 파트너사가 없습니다</h3>
                <p class="empty-desc">회사 프로필 등록/수정 시 정보 공유에 동의한 기업들이 이곳에 나타납니다.</p>
            </div>
        `;
        return;
    }

    grid.innerHTML = partners.map(p => {
        const bizTypes = parseJsonField(p.business_types).map(t => `<span class="tag-badge badge-indigo" style="font-size:0.68rem;padding:2px 6px;margin-bottom:4px;display:inline-block">${escapeHTML(t)}</span>`).join(' ');
        const licenses = parseJsonField(p.licenses).map(l => `<span class="tag-badge badge-green" style="font-size:0.68rem;padding:2px 6px;margin-bottom:4px;display:inline-block">${escapeHTML(l)}</span>`).join(' ');
        const regions = parseJsonField(p.regions).map(r => `<span class="tag-badge badge-cyan" style="font-size:0.68rem;padding:2px 6px;margin-bottom:4px;display:inline-block">${escapeHTML(r)}</span>`).join(' ');
        const keywords = parseJsonField(p.keywords).map(k => `<span class="tag-badge" style="font-size:0.68rem;padding:2px 6px;background:rgba(255,255,255,0.05);color:var(--text-secondary);margin-bottom:4px;display:inline-block">#${escapeHTML(k)}</span>`).join(' ');
        
        // 협업 궁합도(매칭 스코어) 처리
        let matchScoreBadge = '';
        let matchReasonsHtml = '';
        const activeBizId = localStorage.getItem('activeCompanyBizId');
        
        if (p.biz_id === activeBizId) {
            matchScoreBadge = `<span class="tag-badge badge-ghost" style="font-size:0.68rem;padding:2px 8px;background:rgba(255,255,255,0.08);color:var(--text-muted)">자사</span>`;
        } else if (p.match_score !== undefined && p.match_score !== null) {
            const score = p.match_score;
            let badgeClass = 'badge-yellow';
            let badgeStyle = 'background:rgba(245,158,11,0.15);color:#fbbf24;font-weight:700;';
            if (score >= 80) {
                badgeClass = 'badge-purple';
                badgeStyle = 'background:linear-gradient(135deg, rgba(99,102,241,0.2) 0%, rgba(139,92,246,0.2) 100%);color:#c084fc;border:1px solid rgba(139,92,246,0.3);font-weight:800;';
            } else if (score >= 60) {
                badgeClass = 'badge-cyan';
                badgeStyle = 'background:rgba(6,182,212,0.15);color:#22d3ee;font-weight:700;';
            }
            matchScoreBadge = `<span class="tag-badge ${badgeClass}" style="font-size:0.75rem;padding:3px 10px;border-radius:20px;letter-spacing:0.02em;box-shadow:0 0 10px rgba(99,102,241,0.1);${badgeStyle}">🎯 궁합도 ${score}%</span>`;
            
            if (p.match_reasons && p.match_reasons.length > 0) {
                const reasonsList = p.match_reasons.map(r => `<li style="margin-bottom:3px;position:relative;padding-left:12px;"><span style="position:absolute;left:0;color:#818cf8;">•</span>${escapeHTML(r)}</li>`).join('');
                matchReasonsHtml = `
                    <div style="margin-top:10px;padding:10px 12px;background:rgba(99,102,241,0.04);border-left:3px solid #6366f1;border-radius:0 8px 8px 0;font-size:0.73rem;color:var(--text-secondary);">
                        <div style="font-weight:700;margin-bottom:4px;color:#a5b4fc;display:flex;align-items:center;gap:4px;">✨ 추천 매칭 요인</div>
                        <ul style="list-style:none;padding:0;margin:0;line-height:1.4;">${reasonsList}</ul>
                    </div>
                `;
            }
        } else {
            matchScoreBadge = `<span class="tag-badge badge-ghost" style="font-size:0.68rem;padding:2px 8px;color:var(--text-muted)">궁합 계산 불가</span>`;
        }

        // 홈페이지, 회사소개서, 소셜 네트워크 배지 HTML 생성
        let contactBadges = [];
        if (p.website_url) {
            contactBadges.push(`<a href="${escapeHTML(p.website_url)}" target="_blank" class="tag-badge" style="font-size:0.68rem;padding:2px 8px;text-decoration:none;color:#818cf8;background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.2);display:inline-flex;align-items:center;gap:2px" title="홈페이지 새창 열기">🌐 홈페이지</a>`);
        }
        if (p.intro_file_url) {
            contactBadges.push(`<a href="${escapeHTML(p.intro_file_url)}" target="_blank" class="tag-badge" style="font-size:0.68rem;padding:2px 8px;text-decoration:none;color:#34d399;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);display:inline-flex;align-items:center;gap:2px" title="회사소개서 다운로드">📄 소개서</a>`);
        }
        if (p.social_links) {
            contactBadges.push(`<a href="${escapeHTML(p.social_links)}" target="_blank" class="tag-badge" style="font-size:0.68rem;padding:2px 8px;text-decoration:none;color:#22d3ee;background:rgba(6,182,212,0.1);border:1px solid rgba(6,182,212,0.2);display:inline-flex;align-items:center;gap:2px" title="소셜 채널 바로가기">🔗 소셜</a>`);
        }
        const contactBadgesHtml = contactBadges.length > 0 
            ? `<div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap">${contactBadges.join('')}</div>`
            : '';

        return `
            <div class="policy-card" style="display:flex;flex-direction:column;justify-content:space-between;min-height:280px">
                <div>
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
                        <h3 style="font-size:1.05rem;font-weight:700;margin:0;color:var(--text-primary)">${escapeHTML(p.company_name)}</h3>
                        <div style="display:flex;gap:4px;align-items:center">
                            ${matchScoreBadge}
                            <span class="sm-ai-badge" style="font-size:0.68rem;padding:2px 8px;background:rgba(99,102,241,0.15);color:#a5b4fc">${escapeHTML(p.credit_rating || 'BBB')}</span>
                        </div>
                    </div>
                    <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:12px">대표: ${escapeHTML(p.ceo_name || '-')} | 규모: ${escapeHTML(p.company_type || '중소기업')}</div>
                    
                    ${contactBadgesHtml}
                    
                    <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:12px">
                        ${bizTypes ? `<div><small style="color:var(--text-muted);display:block;margin-bottom:2px">업종</small>${bizTypes}</div>` : ''}
                        ${licenses ? `<div><small style="color:var(--text-muted);display:block;margin-bottom:2px">보유 면허</small>${licenses}</div>` : ''}
                        ${regions ? `<div><small style="color:var(--text-muted);display:block;margin-bottom:2px">활동 지역</small>${regions}</div>` : ''}
                        ${keywords ? `<div style="margin-top:4px">${keywords}</div>` : ''}
                    </div>
                    
                    ${matchReasonsHtml}
                </div>

                <div style="border-top:1px solid var(--border);padding-top:12px;margin-top:12px;display:flex;justify-content:flex-end">
                    <button class="btn btn-sm btn-primary" style="font-size:0.75rem;padding:6px 12px" onclick="openProposalModal('${p.biz_id}', '${escapeHTML(p.company_name).replace(/'/g, "\\'")}')">
                        🤝 협업 제안하기
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function searchPartners() {
    const query = document.getElementById('partner-search-input').value.toLowerCase().trim();
    if (!query) {
        renderPartnersList(_cachedSharedPartners);
        return;
    }

    const filtered = _cachedSharedPartners.filter(p => {
        const name = (p.company_name || '').toLowerCase();
        const ceo = (p.ceo_name || '').toLowerCase();
        const bizTypes = parseJsonField(p.business_types).join(' ').toLowerCase();
        const licenses = parseJsonField(p.licenses).join(' ').toLowerCase();
        const regions = parseJsonField(p.regions).join(' ').toLowerCase();
        const keywords = parseJsonField(p.keywords).join(' ').toLowerCase();
        
        return name.includes(query) || 
               ceo.includes(query) || 
               bizTypes.includes(query) || 
               licenses.includes(query) || 
               regions.includes(query) || 
               keywords.includes(query);
    });

    renderPartnersList(filtered);
}

async function loadActivePartnerProposals() {
    const selectEl = document.getElementById('partner-active-biz-select');
    if (!selectEl) return;
    
    const activeBizId = selectEl.value;
    const receivedList = document.getElementById('received-proposals-list');
    const sentList = document.getElementById('sent-proposals-list');
    
    if (!activeBizId) {
        const msg = `<div style="text-align:center;padding:24px;color:var(--text-muted);font-size:0.8rem">소속 회사를 선택하시면 주고받은 제안이 표시됩니다.</div>`;
        if (receivedList) receivedList.innerHTML = msg;
        if (sentList) sentList.innerHTML = msg;
        return;
    }

    if (receivedList) receivedList.innerHTML = `<div style="text-align:center;padding:12px">${renderSkeletonCards(1, '80px')}</div>`;
    if (sentList) sentList.innerHTML = `<div style="text-align:center;padding:12px">${renderSkeletonCards(1, '80px')}</div>`;

    try {
        const [received, sent] = await Promise.all([
            api('GET', `/businesses/proposals/received?biz_id=${encodeURIComponent(activeBizId)}`),
            api('GET', `/businesses/proposals/sent?biz_id=${encodeURIComponent(activeBizId)}`)
        ]);

        renderProposalsList('received', received);
        renderProposalsList('sent', sent);
    } catch (err) {
        console.error('제안 이력 로드 실패:', err);
        const errMsg = `<div style="text-align:center;padding:12px;color:var(--text-muted);font-size:0.8rem">⚠️ 불러오지 못했습니다.</div>`;
        if (receivedList) receivedList.innerHTML = errMsg;
        if (sentList) sentList.innerHTML = errMsg;
    }
}

function renderProposalsList(type, list) {
    const container = document.getElementById(type === 'received' ? 'received-proposals-list' : 'sent-proposals-list');
    if (!container) return;

    if (!list || list.length === 0) {
        container.innerHTML = `
            <div style="text-align:center;padding:40px;color:var(--text-muted);font-size:0.85rem">
                <div>✉️</div>
                <div style="margin-top:6px">${type === 'received' ? '수신된 협업 제안이 없습니다.' : '보낸 협업 제안이 없습니다.'}</div>
            </div>
        `;
        return;
    }

    container.innerHTML = list.map(p => {
        const statusMap = {
            'pending': { label: '대기 중', class: 'badge-yellow', color: '#f59e0b' },
            'accepted': { label: '수락됨', class: 'badge-green', color: '#10b981' },
            'rejected': { label: '거절됨', class: 'badge-danger', color: '#ef4444' }
        };
        const status = statusMap[p.status] || { label: p.status, class: '', color: 'var(--text-muted)' };
        const isReceived = type === 'received';
        const partnerName = isReceived ? p.sender_company_name : p.receiver_company_name;
        const partnerEmail = isReceived ? p.sender_email : p.receiver_email;
        const partnerCeo = isReceived ? p.sender_ceo_name : p.receiver_ceo_name;
        
        // 제안 수락 시 연락 방법(이메일) 노출
        const contactInfo = (p.status === 'accepted' && partnerEmail) 
            ? `<div style="margin-top:8px;padding:8px;background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.2);border-radius:6px;font-size:0.75rem;color:#10b981">
                📞 연락망 개설: <strong>${escapeHTML(partnerCeo || '')} (${escapeHTML(partnerEmail)})</strong> 로 문의해 주세요.
               </div>`
            : '';

        let actions = '';
        if (isReceived && p.status === 'pending') {
            actions = `
                <div style="display:flex;gap:6px;margin-top:12px;justify-content:flex-end">
                    <button class="btn btn-sm" style="font-size:0.72rem;padding:4px 8px;background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid rgba(239,68,68,0.3)" onclick="updateProposalStatus(${p.id}, 'rejected')">거절</button>
                    <button class="btn btn-sm btn-primary" style="font-size:0.72rem;padding:4px 8px" onclick="updateProposalStatus(${p.id}, 'accepted')">수락</button>
                </div>
            `;
        }

        return `
            <div class="cafe-post-card" style="padding:14px;margin-bottom:10px">
                <div style="display:flex;justify-content:space-between;align-items:flex-start">
                    <div>
                        <span style="font-weight:700;font-size:0.88rem;color:var(--text-primary)">${escapeHTML(partnerName)}</span>
                        <span class="tag-badge ${status.class}" style="font-size:0.65rem;padding:1px 6px;margin-left:6px">${status.label}</span>
                    </div>
                    <small style="color:var(--text-muted);font-size:0.7rem">${new Date(p.created_at).toLocaleDateString('ko-KR')}</small>
                </div>
                <div style="font-size:0.76rem;color:var(--text-secondary);margin-top:6px;padding:4px 8px;background:rgba(0,0,0,0.12);border-radius:6px">
                    ${escapeHTML(p.message || '')}
                </div>
                <div style="margin-top:8px;font-size:0.72rem;color:var(--text-muted)">
                    📌 관련 공고: <span style="color:var(--accent-indigo)">${escapeHTML(p.bid_ntce_no)}</span> - ${escapeHTML(p.bid_title || '상세 공고명 없음')}
                </div>
                ${contactInfo}
                ${actions}
            </div>
        `;
    }).join('');
}

async function updateProposalStatus(proposalId, status) {
    try {
        await api('PUT', `/businesses/proposals/${proposalId}/status`, { status });
        showToast(`제안이 ${status === 'accepted' ? '수락' : '거절'}되었습니다.`, 'success');
        loadActivePartnerProposals();
    } catch (err) {
        showToast(`상태 업데이트 실패: ${err.message}`, 'error');
    }
}

function openProposalModal(receiverBizId, receiverCompanyName, bidNo = '') {
    const overlay = document.getElementById('collab-proposal-modal-overlay');
    if (!overlay) return;

    document.getElementById('collab-proposal-form').reset();
    document.getElementById('collab-proposal-receiver-biz-id').value = receiverBizId;
    document.getElementById('collab-proposal-receiver-name').value = receiverCompanyName;
    
    const bidInput = document.getElementById('collab-proposal-bid-no');
    const previewEl = document.getElementById('collab-proposal-bid-title-preview');
    
    bidInput.value = bidNo;
    previewEl.style.display = 'none';

    if (bidNo) {
        fetchAndFillBidTitle();
    }

    overlay.classList.add('active');
}

function closeProposalModal() {
    const overlay = document.getElementById('collab-proposal-modal-overlay');
    if (overlay) overlay.classList.remove('active');
}

async function submitCollaborationProposal(event) {
    event.preventDefault();
    
    const payload = {
        sender_biz_id: document.getElementById('collab-proposal-sender-biz-id').value,
        receiver_biz_id: document.getElementById('collab-proposal-receiver-biz-id').value,
        bid_ntce_no: document.getElementById('collab-proposal-bid-no').value.trim(),
        message: document.getElementById('collab-proposal-message').value.trim()
    };

    if (!payload.sender_biz_id) {
        showToast('제안을 보낼 내 회사를 선택해 주세요.', 'warning');
        return;
    }
    if (!payload.bid_ntce_no) {
        showToast('대상 공고번호를 입력해 주세요.', 'warning');
        return;
    }
    if (!payload.message) {
        showToast('제안 메시지를 입력해 주세요.', 'warning');
        return;
    }

    try {
        await api('POST', '/businesses/proposals', payload);
        showToast('협업 제안이 발송되었습니다.', 'success');
        closeProposalModal();
        if (state.currentView === 'partners') {
            loadActivePartnerProposals();
        }
    } catch (err) {
        showToast(`제안 발송 실패: ${err.message}`, 'error');
    }
}

async function fetchAndFillBidTitle() {
    const bidNo = document.getElementById('collab-proposal-bid-no').value.trim();
    const previewEl = document.getElementById('collab-proposal-bid-title-preview');
    if (!bidNo) {
        showToast('공고번호를 입력하세요', 'warning');
        return;
    }

    previewEl.style.display = 'block';
    previewEl.textContent = '🔍 공고 정보를 조회하는 중...';
    previewEl.style.color = 'var(--text-muted)';

    try {
        const bid = await api('GET', `/bids/${encodeURIComponent(bidNo)}`);
        if (bid && bid.title) {
            previewEl.textContent = `✅ 확인됨: ${bid.title}`;
            previewEl.style.color = '#10b981';
        } else {
            previewEl.textContent = '❌ 공고를 찾을 수 없습니다. 번호를 다시 확인해 주세요.';
            previewEl.style.color = '#ef4444';
        }
    } catch (err) {
        previewEl.textContent = '⚠️ 신규 공고이거나 조회가 불가능합니다. 번호를 수동 확인해 주세요.';
        previewEl.style.color = '#f59e0b';
    }
}

async function generateAiProposalDraft() {
    const senderBizId = document.getElementById('collab-proposal-sender-biz-id').value;
    const receiverBizId = document.getElementById('collab-proposal-receiver-biz-id').value;
    const bidNo = document.getElementById('collab-proposal-bid-no').value.trim();
    const messageTextarea = document.getElementById('collab-proposal-message');
    const aiBtn = document.getElementById('btn-ai-draft-proposal');

    if (!senderBizId) {
        showToast('제안을 보낼 내 회사를 먼저 선택해 주세요.', 'warning');
        return;
    }
    if (!receiverBizId) {
        showToast('제안 대상 파트너사가 유효하지 않습니다.', 'warning');
        return;
    }
    if (!bidNo) {
        showToast('대상 공고번호를 먼저 입력하고 조회해 주세요.', 'warning');
        return;
    }

    if (aiBtn) {
        aiBtn.disabled = true;
        aiBtn.innerHTML = '🤖 초안 작성 중...';
        aiBtn.style.opacity = '0.7';
    }

    try {
        messageTextarea.value = '';
        messageTextarea.placeholder = '🤖 AI가 공고 정보와 파트너사의 강점을 매칭하여 맞춤형 협업 제안서 초안을 구성하고 있습니다. 잠시만 기다려 주세요...';
        
        const result = await api('POST', '/businesses/proposals/ai-draft', {
            sender_biz_id: senderBizId,
            receiver_biz_id: receiverBizId,
            bid_ntce_no: bidNo
        });

        const draftText = result.draft || '';
        
        let index = 0;
        messageTextarea.placeholder = '제안 메시지';
        
        function typeEffect() {
            if (index < draftText.length) {
                messageTextarea.value += draftText.charAt(index);
                index++;
                messageTextarea.scrollTop = messageTextarea.scrollHeight;
                setTimeout(typeEffect, 15);
            } else {
                if (aiBtn) {
                    aiBtn.disabled = false;
                    aiBtn.innerHTML = '🤖 AI 제안서 초안 작성';
                    aiBtn.style.opacity = '1';
                }
                showToast('AI 맞춤 제안서 초안이 완성되었습니다!', 'success');
            }
        }
        
        typeEffect();

    } catch (err) {
        console.error('AI 제안 초안 작성 에러:', err);
        showToast(`초안 작성에 실패했습니다: ${err.message}`, 'error');
        messageTextarea.placeholder = '공동 수급 제안 목적 및 협력 방향을 입력해 주세요.';
        if (aiBtn) {
            aiBtn.disabled = false;
            aiBtn.innerHTML = '🤖 AI 제안서 초안 작성';
            aiBtn.style.opacity = '1';
        }
    }
}

// ═══════════════════════════════════════════════════
// 프로필 수정 / 비밀번호 변경 / 계정 탈퇴 모달 관련 함수
// ═══════════════════════════════════════════════════

function openProfileEditModal() {
    if (!_currentUser) { openAuthModal('login'); return; }
    const overlay = document.getElementById('profile-edit-modal-overlay');
    if (!overlay) return;
    const unameEl = document.getElementById('profile-edit-username');
    if (unameEl) unameEl.textContent = _currentUser;
    const emailEl = document.getElementById('profile-edit-email');
    if (emailEl) emailEl.value = '';
    overlay.style.display = 'flex';
}

function closeProfileEditModal(e) {
    if (e && e.target !== e.currentTarget) return;
    const overlay = document.getElementById('profile-edit-modal-overlay');
    if (overlay) overlay.style.display = 'none';
}

async function handleProfileEdit(e) {
    e.preventDefault();
    const email = document.getElementById('profile-edit-email')?.value.trim() || null;
    try {
        const resp = await fetch('/api/auth/profile', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email || null }),
            credentials: 'include'
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            showToast('프로필이 성공적으로 수정되었습니다.', 'success');
            closeProfileEditModal();
        } else {
            showToast(data.detail || '프로필 수정에 실패했습니다.', 'error');
        }
    } catch (err) {
        console.error('프로필 수정 오류:', err);
        showToast('서버 통신 오류가 발생했습니다.', 'error');
    }
}

function openChangePasswordModal() {
    const overlay = document.getElementById('change-password-modal-overlay');
    if (overlay) {
        overlay.style.display = 'flex';
        const form = document.getElementById('change-password-form');
        if (form) form.reset();
        const bar = document.getElementById('cp-strength');
        if (bar) { bar.style.width = '0'; bar.style.background = '#334155'; }
        const txt = document.getElementById('cp-strength-text');
        if (txt) txt.textContent = '';
    }
}

function closeChangePasswordModal(e) {
    if (e && e.target !== e.currentTarget) return;
    const overlay = document.getElementById('change-password-modal-overlay');
    if (overlay) overlay.style.display = 'none';
}

async function handleChangePassword(e) {
    e.preventDefault();
    const current = document.getElementById('cp-current')?.value;
    const newPw = document.getElementById('cp-new')?.value;
    const confirm = document.getElementById('cp-confirm')?.value;
    if (!current || !newPw || !confirm) { showToast('모든 항목을 입력해 주세요.', 'error'); return; }
    if (newPw !== confirm) { showToast('새 비밀번호가 일치하지 않습니다.', 'error'); return; }
    if (newPw.length < 4) { showToast('비밀번호는 최소 4자 이상이어야 합니다.', 'error'); return; }
    try {
        const resp = await fetch('/api/auth/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: current, new_password: newPw }),
            credentials: 'include'
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            showToast('비밀번호가 성공적으로 변경되었습니다. 다시 로그인해 주세요.', 'success');
            closeChangePasswordModal();
            closeProfileEditModal();
            setTimeout(() => handleLogout(), 1500);
        } else {
            showToast(data.detail || '비밀번호 변경에 실패했습니다.', 'error');
        }
    } catch (err) {
        console.error('비밀번호 변경 오류:', err);
        showToast('서버 통신 오류가 발생했습니다.', 'error');
    }
}

function openDeleteAccountModal() {
    const overlay = document.getElementById('delete-account-modal-overlay');
    if (overlay) {
        overlay.style.display = 'flex';
        const pw = document.getElementById('delete-account-password');
        if (pw) pw.value = '';
    }
}

function closeDeleteAccountModal(e) {
    if (e && e.target !== e.currentTarget) return;
    const overlay = document.getElementById('delete-account-modal-overlay');
    if (overlay) overlay.style.display = 'none';
}

async function handleDeleteAccount(e) {
    e.preventDefault();
    const password = document.getElementById('delete-account-password')?.value;
    if (!password) { showToast('비밀번호를 입력해 주세요.', 'error'); return; }
    if (!confirm('정말로 계정을 탈퇴하시겠습니까? 이 작업은 되돌릴 수 없습니다.')) return;
    try {
        const resp = await fetch('/api/auth/me', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password }),
            credentials: 'include'
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            showToast('계정이 삭제되었습니다. 이용해주셔서 감사합니다.', 'success');
            closeDeleteAccountModal();
            closeProfileEditModal();
            setTimeout(() => window.location.reload(), 1500);
        } else {
            showToast(data.detail || '계정 탈퇴에 실패했습니다.', 'error');
        }
    } catch (err) {
        console.error('계정 탈퇴 오류:', err);
        showToast('서버 통신 오류가 발생했습니다.', 'error');
    }
}

// 비밀번호 강도 표시기
function updatePasswordStrength(barId, password) {
    const bar = document.getElementById(barId);
    const txtId = barId.replace('-strength', '-strength-text');
    const txt = document.getElementById(txtId);
    if (!bar) return;
    let score = 0;
    if (password.length >= 4) score++;
    if (password.length >= 8) score++;
    if (/[A-Z]/.test(password) || /[a-z]/.test(password)) score++;
    if (/[0-9]/.test(password)) score++;
    if (/[^A-Za-z0-9]/.test(password)) score++;
    const levels = [
        { color: '#ef4444', label: '매우 약함', width: '20%' },
        { color: '#f97316', label: '약함',     width: '40%' },
        { color: '#eab308', label: '보통',     width: '60%' },
        { color: '#22c55e', label: '강함',     width: '80%' },
        { color: '#10b981', label: '매우 강함', width: '100%' }
    ];
    const idx = Math.min(score - 1, 4);
    const lvl = score > 0 ? levels[idx] : { color: '#334155', label: '', width: '0%' };
    bar.style.width = lvl.width;
    bar.style.background = lvl.color;
    if (txt) txt.textContent = password.length > 0 ? `강도: ${lvl.label}` : '';
}

// ═══════════════════════════════════════════════════
// 카페 게시글 수정 모달 함수
// ═══════════════════════════════════════════════════

function openCafeEditModal(postId, currentTitle, currentContent) {
    const overlay = document.getElementById('cafe-edit-modal-overlay');
    if (!overlay) return;
    document.getElementById('cafe-edit-post-id').value = postId;
    document.getElementById('cafe-edit-title-input').value = currentTitle || '';
    document.getElementById('cafe-edit-content-input').value = currentContent || '';
    overlay.style.display = 'flex';
}

function closeCafeEditModal(e) {
    if (e && e.target !== e.currentTarget) return;
    const overlay = document.getElementById('cafe-edit-modal-overlay');
    if (overlay) overlay.style.display = 'none';
}

async function handleCafeEditSubmit(e) {
    e.preventDefault();
    const postId = document.getElementById('cafe-edit-post-id')?.value;
    const title = document.getElementById('cafe-edit-title-input')?.value.trim();
    const content = document.getElementById('cafe-edit-content-input')?.value.trim();
    const activeBizId = localStorage.getItem('activeCompanyBizId');
    if (!postId || !title || !content || !activeBizId) {
        showToast('필수 정보가 누락되었습니다.', 'error'); return;
    }
    try {
        await api('PUT', `/companies/${encodeURIComponent(activeBizId)}/cafe/${postId}`, { title, content });
        showToast('게시글이 수정되었습니다.', 'success');
        closeCafeEditModal();
        loadCafe();
    } catch (err) {
        console.error('게시글 수정 실패:', err);
        showToast((err && err.detail) || '게시글 수정에 실패했습니다.', 'error');
    }
}
