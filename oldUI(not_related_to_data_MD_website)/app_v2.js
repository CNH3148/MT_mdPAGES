const subjects = [
    "臨床生理學與病理學",
    "臨床血液學與血庫學",
    "醫學分子檢驗學與臨床鏡檢學",
    "微生物學與臨床微生物學",
    "生物化學與臨床生化學",
    "臨床血清免疫學與臨床病毒學"
];

let currentData = [];
let filteredData = [];
let topicGroups = {}; // { "TopicName": [q1, q2] }
let aiTopicSummaries = {}; // { "TopicName": "Markdown explanation..." }
let currentActiveTopicData = []; // The questions for the currently viewed topic
let currentTopicName = "";

let currentIndex = 0;
let isPdfViewActive = false;

let currentSaveSlot = null;
let globalAnsweredState = {}; // { id: { current_answer: 'B', is_fixed: false } }
let globalBookmarks = []; // [ "id1", "id2" ]
let globalCustomTags = {}; // { "tag_name": ["id1", "id2"] }
let globalExplanations = {};
let globalTopicNotes = {}; // { "id1": "user explanation" }
let globalPinnedTopics = []; // [ "topic1", "topic2" ]

let globalSaveData = {}; // Stores all subjects' states: { "SubjectA": { answers: {}, bookmarks: [], ... } }
const subjectDataCache = {}; // Cache fetched subject data to prevent network overload
const globalUncheckedYears = new Set(); // Remember user's unselected years across mode/subject switches

async function fetchSubjectData(sub) {
    if (subjectDataCache[sub]) return subjectDataCache[sub];
    try {
        const res = await fetch(`../data_cache/${sub}.json?v=${Date.now()}`);
        if (!res.ok) return [];
        const data = await res.json();
        data.forEach(q => q.subject = sub);
        subjectDataCache[sub] = data;
        return data;
    } catch(e) {
        console.error("Fetch err", sub, e);
        return [];
    }
}
let currentActiveSubject = ''; // Tracks the subject whose state is currently loaded in the globals

let currentPracticeMode = 'normal';
let globalMode = 'general'; // 'general', 'wrong', 'bookmark', 'search' // 'normal', 'wrong', 'bookmark'

let isAnalyticsExpanded = false;
let coverageSortMode = 'frequency';

window.safeMarkdown = function(mdText) {
    if (!mdText) return '';
    
    // 1. Extract and protect LaTeX formulas
    const mathTokens = [];
    let text = mdText;
    
    // Protect block math: $$ ... $$
    text = text.replace(/(?<!\\)\$\$(.*?)(?<!\\)\$\$/gs, function(match, p1) {
        mathTokens.push(p1);
        return `%%%MATHBLOCK_${mathTokens.length - 1}%%%`;
    });
    
    // Protect inline math: $ ... $
    text = text.replace(/(?<!\\)\$(.*?)(?<!\\)\$/g, function(match, p1) {
        // Prevent matching empty $$, which was already handled by block
        if (p1 === '') return match; 
        mathTokens.push(p1);
        return `%%%MATHINLINE_${mathTokens.length - 1}%%%`;
    });

    // Disable single tilde strikethrough (escape ~ to \~, but preserve ~~)
    text = text.replace(/(?<![\\~])~(?!~)/g, '\\~');

    // 2. Render Markdown to HTML
    let html = '';
    if (typeof window.marked !== 'undefined') {
        html = window.marked.parse(text);
    } else {
        html = text;
    }

    // 3. Sanitize HTML (prevents XSS)
    if (typeof window.DOMPurify !== 'undefined') {
        html = window.DOMPurify.sanitize(html, { 
            FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed'] 
        });
    }

    // 4. Restore and render KaTeX formulas
    if (typeof window.katex !== 'undefined') {
        html = html.replace(/%%%MATHBLOCK_(\d+)%%%/g, function(match, i) {
            try {
                return window.katex.renderToString(mathTokens[i], { displayMode: true, throwOnError: false });
            } catch (e) { return `$$${mathTokens[i]}$$`; }
        });
        html = html.replace(/%%%MATHINLINE_(\d+)%%%/g, function(match, i) {
            try {
                return window.katex.renderToString(mathTokens[i], { displayMode: false, throwOnError: false });
            } catch (e) { return `$${mathTokens[i]}$`; }
        });
    } else {
        // Fallback if KaTeX failed to load
        html = html.replace(/%%%MATHBLOCK_(\d+)%%%/g, function(match, i) { return `$$${mathTokens[i]}$$`; });
        html = html.replace(/%%%MATHINLINE_(\d+)%%%/g, function(match, i) { return `$${mathTokens[i]}$`; });
    }

    return html;
};

// === State Routing Helpers (Directly mapped to Markdown JSON Cache) ===
function getSubStore(q) {
    return null; // Deprecated
}

window.showSaveToast = function(btnElement) {
    if (!btnElement) return;
    let toast = btnElement.querySelector('.save-toast');
    if (!toast) {
        toast = document.createElement('span');
        toast.className = 'save-toast';
        toast.textContent = '已同步至 Markdown';
        toast.style.cssText = 'position:absolute; right:32px; top:50%; transform:translateY(-50%); font-size:12px; color:var(--success); opacity:0; transition:opacity 0.3s; pointer-events:none; white-space:nowrap;';
        btnElement.appendChild(toast);
    }
    void toast.offsetWidth;
    toast.style.opacity = '1';
    setTimeout(() => { toast.style.opacity = '0'; }, 2000);
};

function getAnswerState(q) {
    if (!q.current_answer && q.is_fixed === null) return undefined;
    return {
        current_answer: q.current_answer,
        is_fixed: !!q.is_fixed
    };
}

function setAnswerState(q, state) {
    q.current_answer = state.current_answer;
    q.is_fixed = state.is_fixed;
    
    // PATCH to backend
    fetch(`/api/q/${encodeURIComponent(q.subject)}/${q.year}_${q.exam_id}_${q.no}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            current_answer: state.current_answer,
            is_fixed: state.is_fixed
        })
    }).catch(e => console.error(e));
}

function getBookmarkState(q) {
    return !!q.bookmarked;
}

function setBookmarkState(q, isBookmarked) {
    q.bookmarked = isBookmarked;
    fetch(`/api/q/${encodeURIComponent(q.subject)}/${q.year}_${q.exam_id}_${q.no}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bookmarked: isBookmarked })
    }).catch(e => console.error(e));
}

function getExplanationState(q) {
    return q.explanation || "";
}

function setExplanationState(q, val) {
    // Read-only in frontend, managed via Obsidian
    console.warn("Explanation editing from frontend is disabled.");
}

function getCustomTagIncludes(q, tag) {
    if (!q.tags) return false;
    return q.tags.includes(tag);
}

function addCustomTagState(q, tag) {
    // Disabled in frontend
}

function removeCustomTagState(q, tag) {
    // Disabled in frontend
}

function loadSlotUI() {
    // Deprecated
}

window.selectSlot = async function(slot) {
    // Legacy function, bypass it
    document.getElementById('slot-selection-modal').style.display = 'none';
    
    // Default subject initialization
    const fallbackSubject = '臨床生理學與病理學';
    filterSubject.value = fallbackSubject;
    await onSubjectChange();
    
    if (currentMode === 'card') renderCardView();
    else renderListView();
    
    const sidebarTitle = document.getElementById('sidebar-title');
    if (sidebarTitle) sidebarTitle.innerText = "MT 刷題小幫手";
};

function loadSubjectState(sub) {
    // Deprecated, state is now loaded per-question directly from the JSON cache
}

window.openSavesFolder = async function() {
    // Deprecated
    alert("此功能已廢棄，請直接透過 Obsidian 開啟 Markdown 筆記庫。");
};

function saveProgress() {
    // Deprecated, handled automatically by PATCH requests per action
}

let answeredState = {}; // maps currentActiveTopicData index to selected option
let currentMode = 'card'; // 'card' or 'list'

// DOM Elements

let globalPracticeMode = 'general'; // 'general', 'wrong', 'bookmark', 'search'

// New Sidebar Elements
const modeBtnGeneral = document.getElementById('mode-general');
const modeBtnWrong = document.getElementById('mode-wrong');
const modeBtnBookmark = document.getElementById('mode-bookmark');
const modeBtnSearch = document.getElementById('mode-search');
const filterSubjectMulti = document.getElementById('filter-subject-multi');
const searchModeTools = document.getElementById('search-mode-tools');
const customTagsCheckboxes = document.getElementById('custom-tags-checkboxes');
const regexSearchInput = document.getElementById('regex-search-input');
const regexHistoryToggle = document.getElementById('regex-history-toggle');
const regexHistoryDropdown = document.getElementById('regex-history-dropdown');
const batchTagInput = document.getElementById('batch-tag-input');
const btnExecuteSearch = document.getElementById('btn-execute-search');

// We will use advancedSearchRules for regex history
let regexHistory = [];
try {
    const saved = localStorage.getItem('advancedSearchRules');
    if (saved) regexHistory = JSON.parse(saved).map(r => r.regex);
} catch(e) {}

const filterSubject = document.getElementById('filter-subject');
const filterYearContainer = document.getElementById('filter-year-container');

const savedSearchesList = document.getElementById('saved-searches-list');

const currentSubjectTitle = document.getElementById('current-subject-title');
const listAccuracy = document.getElementById('list-accuracy');
let accuracyCalcMode = 'session';
listAccuracy.addEventListener('click', () => {
    accuracyCalcMode = accuracyCalcMode === 'session' ? 'overall' : 'session';
    updateAccuracy();
});
const viewToggleContainer = document.getElementById('view-toggle-container');
// Mode buttons removed
const statTotalQ = document.getElementById('stat-total-q');

// Breadcrumbs
const bcSubject = document.getElementById('bc-subject');
const bcSepTopic = document.getElementById('bc-sep-topic');
const bcTopic = document.getElementById('bc-topic');
const bcSepPractice = document.getElementById('bc-sep-practice');
const bcPractice = document.getElementById('bc-practice');

// Views
const viewTopicList = document.getElementById('view-topic-list');
const topicCardsContainer = document.getElementById('topic-cards-container');

const viewTopicDetail = document.getElementById('view-topic-detail');

let breadcrumbObserver = null;
function initBreadcrumbObserver() {
    if (breadcrumbObserver) return;
    breadcrumbObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const sub = entry.target.getAttribute('data-subject');
                const topic = entry.target.getAttribute('data-topic');
                if (sub && topic) {
                    // currentActiveSubject = sub; // DO NOT MUTATE GLOBAL STATE
                    currentTopicName = topic;
                    bcSubject.innerHTML = (globalMode === 'general' ? '🏠 ' : '📚 ') + sub;
                    bcSubject.setAttribute('data-current-sub', sub);
                    bcSubject.style.display = 'inline';
                    bcSepTopic.style.display = 'inline';
                    bcTopic.textContent = `🏷️ ${topic}`;
                    bcTopic.setAttribute('data-current-topic', topic);
                    bcTopic.style.display = 'inline';
                }
                
                // 同步更新 currentIndex，使清單→卡片切換時能定位到相同題目
                const cardId = entry.target.id; // e.g. 'list-card-5'
                if (cardId && cardId.startsWith('list-card-')) {
                    const idx = parseInt(cardId.replace('list-card-', ''), 10);
                    if (!isNaN(idx) && idx >= 0 && idx < currentActiveTopicData.length) {
                        currentIndex = idx;
                    }
                }
            }
        });
    }, { root: null, rootMargin: '-20% 0px -70% 0px' });
}

const detailTopicTitle = document.getElementById('detail-topic-title');
const detailTopicDesc = document.getElementById('detail-topic-desc');
const btnStartPracticeTop = document.getElementById('btn-start-practice-top');

const viewPractice = document.getElementById('view-practice');
const viewList = document.getElementById('view-list');
const listContainer = document.getElementById('list-container');

// Practice DOM (Card Mode)
const qNo = document.getElementById('q-no');
const qText = document.getElementById('q-text');
const qOptions = document.getElementById('q-options');
const qTags = document.getElementById('q-tags');
const btnPrev = document.getElementById('btn-prev');
const btnNext = document.getElementById('btn-next');
const btnNote = document.getElementById('btn-note');
const explanationPanel = document.getElementById('explanation-panel');
const qExplanation = document.getElementById('q-explanation');
const progressFill = document.getElementById('progress-fill');

// Modal DOM
const advModal = document.getElementById('advanced-search-modal');
const advRegex = document.getElementById('adv-regex');
const advTagName = document.getElementById('adv-tag-name');
const advPreview = document.getElementById('adv-preview');
const btnAdvCancel = document.getElementById('btn-adv-cancel');
const btnAdvSave = document.getElementById('btn-adv-save');

async function init() {
    document.getElementById('slot-selection-modal').style.display = 'none';
    
    // Set default subject to 臨床生理學與病理學 as requested
    filterSubject.value = '臨床生理學與病理學';
    // Populate Subjects
    subjects.forEach(sub => {
        const opt = document.createElement('option');
        opt.value = sub;
        opt.textContent = sub;
        filterSubject.appendChild(opt);
    });

    // Listeners
    filterSubject.addEventListener('change', onSubjectChange);

    // mode button click events removed
    btnStartPracticeTop.onclick = () => { currentMode = 'list'; startPractice(); };

    bcSubject.onclick = async () => {
        let targetSub = null;
        if (globalMode !== 'general') {
            if (currentMode === 'card' && currentActiveTopicData[currentIndex]) {
                targetSub = currentActiveTopicData[currentIndex].subject;
            } else if (currentMode === 'list') {
                targetSub = bcSubject.getAttribute('data-current-sub');
            }
            if (targetSub && filterSubject.value !== targetSub) {
                filterSubject.value = targetSub;
            }
        }
        
        if (globalMode !== 'general') {
            await switchGlobalMode('general');
        }
        if (filterSubject.value) {
            await onSubjectChange();
        } else {
            applyFilters();
        }
    };
    bcTopic.onclick = async () => {
        let targetTopic = currentTopicName;
        let targetSub = null;
        
        if (globalMode !== 'general') {
            if (currentMode === 'card' && currentActiveTopicData[currentIndex]) {
                targetSub = currentActiveTopicData[currentIndex].subject;
                targetTopic = currentActiveTopicData[currentIndex].topic || currentTopicName;
            } else if (currentMode === 'list') {
                targetSub = bcSubject.getAttribute('data-current-sub');
                targetTopic = bcTopic.getAttribute('data-current-topic') || currentTopicName;
            }
            if (targetSub && filterSubject.value !== targetSub) {
                filterSubject.value = targetSub;
            }
        }
        
        if (globalMode !== 'general') {
            await switchGlobalMode('general');
        }
        if (filterSubject.value) {
            await onSubjectChange();
        } else {
            applyFilters();
        }
        if (targetTopic) openTopicDetail(targetTopic);
    };




    loadSavedRules();
}

async function loadSavedRules() {
    try {
        const res = await fetch('/api/get_search_rules');
        const rules = await res.json();
        // Clear previous
        savedSearchesList.innerHTML = '';
        
        // Hardcoded basic rules
        const builtIns = [];
        
        window.deleteSearchRule = async function(e, ruleName) {
            e.stopPropagation();
            if (!confirm(`確定要刪除規則「${ruleName}」嗎？`)) return;
            try {
                await fetch('/api/delete_search_rule/' + encodeURIComponent(ruleName), { method: 'DELETE' });
                loadSavedRules();
            } catch(err) { alert('刪除失敗'); }
        };

        [...builtIns, ...rules].forEach(r => {
            const isBuiltIn = builtIns.some(b => b.name === r.name);
            const div = document.createElement('div');
            div.className = 'nav-item';
            div.style.paddingLeft = '8px';
            div.style.display = 'flex';
            div.style.justifyContent = 'space-between';
            div.style.alignItems = 'center';
            div.title = `Regex: ${r.query}`;
            
            div.innerHTML = `
                <span style="flex:1;">📌 ${r.name}</span>
                ${!isBuiltIn ? `<span class="del-tag" style="display:none; color:#ffb3b3; font-weight:bold; cursor:pointer; padding:0 8px;">✕</span>` : ''}
            `;
            
            div.onclick = () => {
                document.getElementById('adv-regex').value = r.query;
                document.getElementById('adv-tag-name').value = r.name;
            };
            
            if (!isBuiltIn) {
                div.onmouseover = () => { const d = div.querySelector('.del-tag'); if(d) d.style.display='inline'; };
                div.onmouseout = () => { const d = div.querySelector('.del-tag'); if(d) d.style.display='none'; };
                const delBtn = div.querySelector('.del-tag');
                if (delBtn) delBtn.onclick = (e) => deleteSearchRule(e, r.name);
            }
            
            savedSearchesList.appendChild(div);
        });
    } catch(e) {
        console.error("Failed to load rules", e);
    }
}

async function onSubjectChange() {
    const sub = filterSubject.value;
    
    // Save current subject state to the global mapping before switching
    if (currentActiveSubject) {
        globalSaveData[currentActiveSubject] = {
            answers: globalAnsweredState,
            bookmarks: globalBookmarks,
            customTags: globalCustomTags,
            explanations: globalExplanations,
            topicNotes: globalTopicNotes,
            pinnedTopics: globalPinnedTopics
        };
    }
    
    currentActiveSubject = sub;
    loadSubjectState(sub);

    if (!sub) {
        currentData = [];
        filterYearContainer.style.display = 'none';
        document.getElementById('filter-year-wrapper').style.display = 'none';
        filterYearContainer.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">請先選擇科目...</div>';
        return;
    }
    
    currentSubjectTitle.textContent = sub;
    try {
        currentData = await fetchSubjectData(sub);
        
        try {
            const sumRes = await fetch(`../data_cache/topics_${sub}.json?v=${Date.now()}`);
            aiTopicSummaries = await sumRes.json();
        } catch(e) {
            aiTopicSummaries = {};
        }
        
        const yearMap = new Set();
        currentData.forEach(q => {
            if (q.year) {
                yearMap.add(q.year);
            }
        });
        
        const yrWrap = document.getElementById('filter-year-wrapper');
        if (yrWrap) yrWrap.style.display = 'block';
        filterYearContainer.innerHTML = '';
        
        const topControls = document.createElement('div');
        topControls.style.borderBottom = '1px solid rgba(255,255,255,0.1)';
        topControls.style.paddingBottom = '8px';
        topControls.style.marginBottom = '8px';
        topControls.style.display = 'flex';
        topControls.style.flexDirection = 'column';
        topControls.style.gap = '6px';
        
        const selectAllLbl = document.createElement('label');
        selectAllLbl.style.cursor = 'pointer';
        selectAllLbl.style.fontWeight = '600';
        selectAllLbl.innerHTML = `<input type="checkbox" id="year-select-all" checked style="margin-right:8px;"> 全選 / 全不選`;
        selectAllLbl.querySelector('input').addEventListener('change', (e) => {
            const isChecked = e.target.checked;
            document.querySelectorAll('.year-checkbox').forEach(cb => { 
                cb.checked = isChecked;
                if (isChecked) globalUncheckedYears.delete(cb.value);
                else globalUncheckedYears.add(cb.value);
            });
            const l5 = document.getElementById('year-last-5');
            const l10 = document.getElementById('year-last-10');
            if(l5) l5.checked = false;
            if(l10) l10.checked = false;
            if (globalPracticeMode !== 'search') applyFilters();
        });
        topControls.appendChild(selectAllLbl);

        const createRecentYearsCb = (yearsCount, id, labelText) => {
            const lbl = document.createElement('label');
            lbl.style.cursor = 'pointer';
            lbl.style.fontWeight = '600';
            lbl.innerHTML = `<input type="checkbox" id="${id}" style="margin-right:8px;"> ${labelText}`;
            lbl.querySelector('input').addEventListener('change', (e) => {
                const isChecked = e.target.checked;
                let maxYear = 0;
                document.querySelectorAll('.year-checkbox').forEach(cb => {
                    const yr = parseInt(cb.value.split('-')[0]);
                    if (!isNaN(yr) && yr > maxYear) maxYear = yr;
                });
                document.querySelectorAll('.year-checkbox').forEach(cb => {
                    const yr = parseInt(cb.value.split('-')[0]);
                    if (!isNaN(yr) && yr >= maxYear - yearsCount + 1) {
                        cb.checked = isChecked;
                        if (isChecked) globalUncheckedYears.delete(cb.value);
                        else globalUncheckedYears.add(cb.value);
                    }
                });
                if (isChecked) {
                    const otherId = id === 'year-last-5' ? 'year-last-10' : 'year-last-5';
                    const other = document.getElementById(otherId);
                    if (other) other.checked = false;
                }
                const allChecked = Array.from(document.querySelectorAll('.year-checkbox')).every(cb => cb.checked);
                const selectAll = document.getElementById('year-select-all');
                if (selectAll) selectAll.checked = allChecked;
                if (globalPracticeMode !== 'search') applyFilters();
            });
            return lbl;
        };
        topControls.appendChild(createRecentYearsCb(5, 'year-last-5', '近五年'));
        topControls.appendChild(createRecentYearsCb(10, 'year-last-10', '近十年'));
        filterYearContainer.appendChild(topControls);

        Array.from(yearMap).sort((a,b) => b.localeCompare(a)).forEach(y => {
            const lbl = document.createElement('label');
            lbl.style.display = 'block';
            lbl.style.marginBottom = '6px';
            lbl.style.cursor = 'pointer';
            const isChecked = !globalUncheckedYears.has(y) ? 'checked' : '';
            lbl.innerHTML = `<input type="checkbox" value="${y}" class="year-checkbox" ${isChecked} style="margin-right:8px;"> ${y}`;
            lbl.querySelector('input').addEventListener('change', (e) => {
                if (e.target.checked) globalUncheckedYears.delete(y);
                else globalUncheckedYears.add(y);
                const allChecked = Array.from(document.querySelectorAll('.year-checkbox')).every(cb => cb.checked);
                document.getElementById('year-select-all').checked = allChecked;
                if (globalPracticeMode !== 'search') applyFilters();
            });
            filterYearContainer.appendChild(lbl);
        });
        
        applyFilters();
    } catch (e) {
        bcSubject.textContent = `❌ ${sub} 載入失敗`;
        currentData = [];
        applyFilters();
        console.error(e);
    }
}


async function loadMultiSubjectData() {
    let selectedSubs = Array.from(document.querySelectorAll('.multi-subject-cb:checked')).map(cb => cb.value);
    if (selectedSubs.length === 0) selectedSubs = [...subjects];
    let allQuestions = [];
    
    // Disable UI or show loading
    const oldTitle = currentSubjectTitle.textContent;
    // Loading handled by breadcrumb
    // currentSubjectTitle.style.display = 'none';
    
    for (const sub of selectedSubs) {
        const data = await fetchSubjectData(sub);
        if (data.length > 0) {
            allQuestions = allQuestions.concat(data.map(q => ({...q, subject: sub})));
        }
    }
    
    currentSubjectTitle.textContent = oldTitle;
    return allQuestions;
}

async function applyFilters() {
    bcTopic.style.display = 'none';
    bcSepTopic.style.display = 'none';
    bcPractice.style.display = 'none';
    bcSepPractice.style.display = 'none';
    viewToggleContainer.style.display = 'none';
    listAccuracy.style.display = 'none';
    
    const checkedYears = Array.from(document.querySelectorAll('.year-checkbox:checked')).map(cb => cb.value);
    
    if (globalMode === 'general') {
        const sub = filterSubject.value;
        if (!sub) {
            filteredData = [];
            topicGroups = {};
            switchView('topic-list');
            return;
        }
        
        bcSubject.textContent = `🏠 ${sub}`;
        currentSubjectTitle.style.display = 'none';
        
        filteredData = currentData.filter(q => {
            return (q.year && checkedYears.includes(q.year.toString())) || checkedYears.length === 0;
        });
        
        topicGroups = {};
        filteredData.forEach(q => {
            const t = q.topic || '未分類';
            if (!topicGroups[t]) topicGroups[t] = [];
            topicGroups[t].push(q);
        });
        
        renderTopicList();
        switchView('topic-list');
        
    } else {
        // Multi-subject modes: wrong, bookmark, search
        let multiData = await loadMultiSubjectData();
        
        // 1. Year filter
        multiData = multiData.filter(q => {
            return (q.year && checkedYears.includes(q.year.toString())) || checkedYears.length === 0;
        });
        
        // 2. Mode specific filter
        if (globalMode === 'wrong') {
            bcSubject.textContent = '❌ 跨科錯題';
            multiData = multiData.filter(q => {
                const state = getAnswerState(q);
                if (!state) return false;
                return !q.answer.includes(state.current_answer) && !state.is_fixed;
            });
        } else if (globalMode === 'bookmark') {
            bcSubject.textContent = '⭐ 跨科收藏';
            multiData = multiData.filter(q => getBookmarkState(q));
        } else if (globalMode === 'search') {
            bcSubject.textContent = '🔍 搜尋與標籤';
            const regexInput = document.getElementById('regex-search-input');
            const query = regexInput ? regexInput.value.trim() : '';
            
            // Selected custom tags (union)
            const checkedTags = Array.from(document.querySelectorAll('.custom-tag-cb:checked')).map(cb => cb.value);
            
            let regex = null;
            if (query) { try { regex = new RegExp(query, 'i'); } catch(e){} }
            
            multiData = multiData.filter(q => {
                // Check custom tags (Union logic)
                let hasTag = false;
                if (checkedTags.length > 0) {
                    const id = q.year + '_' + q.exam_id + '_' + q.no;
                    const subStore = getSubStore(q);
                    for (let tag of checkedTags) {
                        if (subStore.customTags && subStore.customTags[tag] && subStore.customTags[tag].includes(id)) {
                            hasTag = true;
                            break;
                        }
                    }
                    if (!hasTag) return false;
                }
                
                // Check Regex/Keyword
                if (query) {
                    const text = (q.question + " " + q.choices.join(" ") + " " + (q.tags ? q.tags.join(" ") : ""));
                    if (regex) {
                        if (!regex.test(text)) return false;
                    } else {
                        if (!text.toLowerCase().includes(query.toLowerCase())) return false;
                    }
                }
                return true;
            });
        }
        
        currentActiveTopicData = multiData;
        currentPracticeMode = globalMode === 'search' ? 'custom_tag' : globalMode; 
        
        switchView('practice');
        switchMode('list');
        startPractice();
    }
}

function toggleAnalytics() {
    isAnalyticsExpanded = !isAnalyticsExpanded;
    renderTopicList();
}

function setCoverageSort(mode) {
    coverageSortMode = mode;
    renderTopicList();
}

function togglePinTopic(topic, event) {
    if (event) event.stopPropagation();
    if (globalPinnedTopics.includes(topic)) {
        globalPinnedTopics = globalPinnedTopics.filter(t => t !== topic);
    } else {
        globalPinnedTopics.push(topic);
    }
    saveProgress();
    renderTopicList();
}

function renderTopicList() {
    topicCardsContainer.innerHTML = '';
    statTotalQ.textContent = `${filteredData.length} 題`;
    
    // Completion Meter logic
    let correctCount = 0;
    filteredData.forEach(q => {
        const id = q.year + '_' + q.exam_id + '_' + q.no;
        const ans = getAnswerState(q);
        if (ans && q.answer.includes(ans.current_answer)) {
            correctCount++;
        }
    });
    const completionMeterContainer = document.getElementById('completion-meter-container');
    const dashboardProgressFill = document.getElementById('dashboard-progress-fill');
    const dashboardProgressText = document.getElementById('dashboard-progress-text');
    
    if (filteredData.length > 0) {
        completionMeterContainer.style.display = 'flex';
        const pct = Math.round((correctCount / filteredData.length) * 100);
        dashboardProgressFill.style.width = pct + '%';
        dashboardProgressText.textContent = `${pct}% (${correctCount}/${filteredData.length})`;
    } else {
        completionMeterContainer.style.display = 'none';
    }

    const baseTopics = Object.keys(topicGroups).sort((a, b) => {
        const isUncategorizedA = a.includes('未分類') || a.includes('等待 AI 進行');
        const isUncategorizedB = b.includes('未分類') || b.includes('等待 AI 進行');
        if (isUncategorizedA) return 1;
        if (isUncategorizedB) return -1;

        if (coverageSortMode === 'frequency') {
            return topicGroups[b].length - topicGroups[a].length;
        } else {
            const meanA = topicGroups[a].reduce((sum, q) => sum + parseInt(q.no), 0) / topicGroups[a].length;
            const meanB = topicGroups[b].reduce((sum, q) => sum + parseInt(q.no), 0) / topicGroups[b].length;
            if (meanA === meanB) {
                return topicGroups[b].length - topicGroups[a].length;
            }
            return meanA - meanB;
        }
    });

    let totalQuestions = 0;
    baseTopics.forEach(t => totalQuestions += topicGroups[t].length);

    let analyticsHTML = `<table style="width:100%; border-collapse: collapse; margin-top:12px;">
        <tr style="border-bottom: 1px solid var(--glass-border);">
            <th style="text-align:left; padding:8px;">類別 (${coverageSortMode === 'frequency' ? '依頻率' : '依平均落點'})</th>
            <th style="text-align:center; padding:8px;">題數</th>
            <th style="text-align:center; padding:8px; cursor:pointer; user-select:none; color:${coverageSortMode === 'frequency' ? 'var(--accent)' : 'inherit'};" onclick="setCoverageSort('frequency')" title="點擊以依頻率排序">
                佔比 ${coverageSortMode === 'frequency' ? '↓' : ''}
            </th>
            <th style="text-align:center; padding:8px;">累積掌握</th>
            <th style="text-align:left; padding:8px; cursor:pointer; user-select:none; color:${coverageSortMode === 'position' ? 'var(--accent)' : 'inherit'};" onclick="setCoverageSort('position')" title="點擊以依落點排序">
                出題落點分佈熱圖 (1~80題) ${coverageSortMode === 'position' ? '↓' : ''}
            </th>
        </tr>`;
    
    let cumulative = 0;
    let analyticsRows = [];

    baseTopics.forEach(t => {
        const count = topicGroups[t].length;
        cumulative += count;
        const pct = ((count / totalQuestions) * 100).toFixed(1);
        const cumPct = ((cumulative / totalQuestions) * 100).toFixed(1);
        
        
        // Heatmap generation
        let noCounts = {};
        topicGroups[t].forEach(q => {
            let n = parseInt(q.no);
            noCounts[n] = (noCounts[n] || 0) + 1;
        });
        let maxCount = Math.max(1, ...Object.values(noCounts));
        let heatmapBlocks = '';
        for(let i=1; i<=80; i++) {
            const count = noCounts[i] || 0;
            let bg = 'var(--bg-lighter)';
            if (count > 0) {
                const alpha = Math.max(0.3, count / maxCount);
                bg = `rgba(239, 68, 68, ${alpha})`;
            }
            let borderRight = (i % 5 === 0) ? 'border-right: 1px solid rgba(255,255,255,0.1);' : '';
            heatmapBlocks += `<div style="width:3px; height:12px; background:${bg}; flex-shrink:0; ${borderRight}" title="題號: ${i} (共 ${count} 題)"></div>`;
        }
        let axisHtml = '<div style="display:flex; width:100%; max-width:320px; position:relative; height:15px; margin-top:2px;">';
        for(let i=5; i<=80; i+=5) {
            axisHtml += `<div style="position:absolute; left:${(i/80)*100}%; font-size:9px; color:var(--text-muted); transform:translateX(-50%);">${i}</div>`;
        }
        axisHtml += '</div>';
        
        let cumColor = "var(--text-main)";
        if (cumPct >= 60 && cumPct < 80) cumColor = "#4ade80";
        if (cumPct >= 80) cumColor = "#facc15";
        
        const rowHTML = `
        <tr style="border-bottom: 1px solid var(--glass-border); font-size:13px;">
            <td style="padding:8px; color:var(--primary); cursor:pointer; text-decoration:underline;" onclick="openTopicDetail('${t}')">${t}</td>
            <td style="text-align:center; padding:8px;">${count}</td>
            <td style="text-align:center; padding:8px;">${pct}%</td>
            <td style="text-align:center; padding:8px; color:${cumColor}; font-weight:bold;">${cumPct}%</td>
            <td style="padding:8px; padding-bottom:12px;">
                <div style="display:flex; gap:1px; width:100%; max-width:320px; border-radius:2px; overflow:hidden;">
                    ${heatmapBlocks}
                </div>
                ${axisHtml}
            </td>
        </tr>`;
        
        analyticsRows.push(rowHTML);
    });

    const cardTopics = [...baseTopics].sort((a, b) => {
        const isPinnedA = globalPinnedTopics.includes(a);
        const isPinnedB = globalPinnedTopics.includes(b);
        if (isPinnedA && !isPinnedB) return -1;
        if (!isPinnedA && isPinnedB) return 1;
        return 0; // retain baseTopics order for the rest
    });

    cardTopics.forEach(t => {
        const count = topicGroups[t].length;
        const isPinned = globalPinnedTopics.includes(t);
        const pinIconColor = isPinned ? 'var(--accent)' : 'var(--text-muted)';
        const pinIconFill = isPinned ? 'currentColor' : 'none';

        const card = document.createElement('div');
        card.className = 'topic-card';
        card.style.position = 'relative';
        card.innerHTML = `
            <div style="position: absolute; top: 12px; right: 12px; cursor: pointer; color: ${pinIconColor}; transition: color 0.2s, transform 0.2s;" onclick="togglePinTopic('${t}', event)" title="釘選/取消釘選" onmouseover="this.style.transform='scale(1.2)'" onmouseout="this.style.transform='scale(1)'">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="${pinIconFill}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="12" y1="17" x2="12" y2="22"></line>
                    <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 11.2V6a3 3 0 0 0-6 0v5.2a2 2 0 0 1-1.11 1.35l-1.78.9A2 2 0 0 0 5 15.24Z"></path>
                </svg>
            </div>
            <h3 style="margin-right: 24px;">${t}</h3>
            <div class="topic-meta">${count} 題</div>
        `;
        card.onclick = () => openTopicDetail(t);
        topicCardsContainer.appendChild(card);
    });

    
    const limit = isAnalyticsExpanded ? analyticsRows.length : Math.min(5, analyticsRows.length);
    analyticsHTML += analyticsRows.slice(0, limit).join('');
    analyticsHTML += `</table>`;
    
    if (analyticsRows.length > 5) {
        const btnText = isAnalyticsExpanded ? "⬆️ 收合表格" : "⬇️ 展開全部";
        analyticsHTML += `<div style="text-align:center; margin-top:12px;"><button class="btn btn-secondary btn-small" onclick="toggleAnalytics()">${btnText}</button></div>`;
    }
    
    const analyticsChart = document.getElementById('coverage-chart');
    if(analyticsChart) analyticsChart.innerHTML = analyticsHTML;
    const analyticsContainer = document.getElementById('subject-analytics');
    if(analyticsContainer) analyticsContainer.style.display = baseTopics.length > 0 ? 'block' : 'none';

}

function openTopicDetail(topicName) {
    currentTopicName = topicName;
    currentActiveTopicData = topicGroups[topicName] || [];
    
    bcTopic.style.display = 'inline';
    bcSepTopic.style.display = 'inline';
    bcTopic.textContent = `🏷️ ${topicName}`;
    
    bcPractice.style.display = 'none';
    bcSepPractice.style.display = 'none';
    viewToggleContainer.style.display = 'none';
    listAccuracy.style.display = 'none';
    currentSubjectTitle.textContent = topicName;

    detailTopicTitle.textContent = topicName;
    
      // Extract topic-note-container if it's currently inside detailTopicDesc
      const topicNoteContainer = document.getElementById('topic-note-container');
      if (topicNoteContainer && topicNoteContainer.parentNode.closest('#detail-topic-desc')) {
          detailTopicDesc.parentNode.insertBefore(topicNoteContainer, detailTopicDesc.nextSibling);
      }
      
      // Render AI Summaries if available
      if (aiTopicSummaries[topicName]) {
        let summaryText = aiTopicSummaries[topicName]?.summary_markdown || "";
        
        // Strip out dataview blocks, 包含題庫, and Anki 聯想卡
        // Strip out dataview blocks, 包含題庫, and Anki 聯想卡
        summaryText = summaryText.replace(/```dataview[\s\S]*?```/gi, '');
        summaryText = summaryText.replace(/#+\s*包含題庫\s*$/gm, '');
        summaryText = summaryText.replace(/#+\s*Anki\s*聯想卡\s*$/gm, '');
        
        detailTopicDesc.innerHTML = `<div class="markdown-body">${safeMarkdown(summaryText)}</div>`;

        refreshAnkiCardWall();
    } else if (topicName.includes('未分類')) {
        detailTopicDesc.innerHTML = "這些題目目前尚未被 AI 賦予專屬類群。<br><br>建議等候 AI 分析完成後，再進行知識點的系統性複習。";
    } else {
        detailTopicDesc.innerHTML = "<em>(AI 正在背景為此類群撰寫專屬說明與關鍵字清單，如果剛生成完畢，請重新整理網頁。)</em>";
    }

    // Add Key Concepts section
    const keyConceptsList = document.createElement('div');
    keyConceptsList.style.marginTop = '30px';
    keyConceptsList.style.borderTop = '1px solid var(--glass-border)';
    keyConceptsList.style.paddingTop = '20px';
    
    const totalQuestions = currentActiveTopicData.length;
    const summarizeCount = currentActiveTopicData.filter(q => q.summarize_including).length;
    const supportRatio = totalQuestions > 0 ? Math.round((summarizeCount / totalQuestions) * 100) : 0;

    const conceptHeading = document.createElement('h3');
    conceptHeading.style.cursor = 'pointer';
    conceptHeading.style.userSelect = 'none';
    conceptHeading.style.display = 'flex';
    conceptHeading.style.alignItems = 'center';
    conceptHeading.style.color = 'var(--accent)';
    conceptHeading.style.fontSize = '1.2rem';
    conceptHeading.innerHTML = `<span style="margin-right:8px; font-size:0.8em;">▶</span> 本類題目 &amp; 核心考點（支持度：${supportRatio}% = ${summarizeCount}/${totalQuestions}）`;
    
    const conceptContent = document.createElement('div');
    conceptContent.style.marginTop = '16px';
    conceptContent.style.flexDirection = 'column';
    conceptContent.style.gap = '12px';
    conceptContent.style.display = 'none';
    
    currentActiveTopicData.forEach((q, idx) => {
        const item = document.createElement('div');
        item.className = 'concept-table-item';
        
        const qLabel = `${q.year}-${q.no}`;
        
        const tagDiv = document.createElement('div');
        tagDiv.className = 'concept-tag-col';
        tagDiv.innerHTML = `
            <span class="tag native-tag" style="cursor:pointer; white-space:nowrap;" title="跳轉至此題練習" onclick="currentPracticeMode='general'; startPractice(${idx});">
                <span class="tag-text">${qLabel}</span>
            </span>
        `;
        
        const difficultyDiv = document.createElement('div');
        difficultyDiv.className = 'concept-diff-col';
        if (q.difficulty) {
            let diffClass = '';
            if (q.difficulty.includes('簡單')) diffClass = 'diff-easy';
            else if (q.difficulty.includes('適中')) diffClass = 'diff-medium';
            else if (q.difficulty.includes('困難')) diffClass = 'diff-hard';
            
            difficultyDiv.innerHTML = `<span class="difficulty-indicator ${diffClass}" style="margin-left:0;">${q.difficulty}</span>`;
        } else {
            difficultyDiv.textContent = '未知';
        }
        
        const conceptContainer = document.createElement('div');
        conceptContainer.className = 'concept-content-container';
        
        const conceptDiv = document.createElement('div');
        conceptDiv.className = 'concept-text' + (!q.key_concept ? ' empty' : '');
        conceptDiv.textContent = q.key_concept || '（尚未建立核心概念，請雙擊編輯）';
        
        conceptContainer.appendChild(conceptDiv);

        const emojiDiv = document.createElement('div');
        emojiDiv.className = 'concept-emoji-col';
        emojiDiv.textContent = q.summarize_including ? '📎' : '';
        
        item.appendChild(tagDiv);
        item.appendChild(difficultyDiv);
        item.appendChild(conceptContainer);
        item.appendChild(emojiDiv);

        // Double click to edit logic
        let isEditing = false;
        conceptDiv.addEventListener('dblclick', () => {
            if (isEditing) return;
            isEditing = true;
            
            const originalText = q.key_concept || '';
            
            const input = document.createElement('input');
            input.type = 'text';
            input.value = originalText;
            input.className = 'concept-input';
            
            const saveBtn = document.createElement('button');
            saveBtn.textContent = '✅';
            saveBtn.className = 'concept-save-btn';
            saveBtn.title = '儲存';
            
            conceptContainer.innerHTML = '';
            conceptContainer.appendChild(input);
            conceptContainer.appendChild(saveBtn);
            
            input.focus();
            
            const cancelEdit = () => {
                isEditing = false;
                conceptContainer.innerHTML = '';
                conceptDiv.className = 'concept-text' + (!q.key_concept ? ' empty' : '');
                conceptDiv.textContent = q.key_concept || '（尚未建立核心概念，請雙擊編輯）';
                conceptContainer.appendChild(conceptDiv);
            };
            
            const clickOutsideHandler = (e) => {
                if (!conceptContainer.contains(e.target)) {
                    cancelEdit();
                    document.removeEventListener('mousedown', clickOutsideHandler);
                }
            };
            
            setTimeout(() => {
                document.addEventListener('mousedown', clickOutsideHandler);
            }, 10);
            
            saveBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const newText = input.value.trim();
                
                try {
                    const response = await fetch('/api/update_key_concept', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            subject: q.subject || currentActiveSubject,
                            year: q.year,
                            exam_id: q.exam_id,
                            no: q.no,
                            new_key_concept: newText
                        })
                    });
                    const result = await response.json();
                    
                    if (response.ok && result.status === 'success') {
                        q.key_concept = newText;
                        document.removeEventListener('mousedown', clickOutsideHandler);
                        cancelEdit();
                    } else {
                        alert('儲存失敗，請重試: ' + (result.message || '未知錯誤'));
                    }
                } catch (err) {
                    console.error('Update key concept failed:', err);
                    alert('網路錯誤，儲存失敗');
                }
            });
        });

        conceptContent.appendChild(item);
    });
    
    if (totalQuestions > 0) {
        conceptHeading.onclick = () => {
            const isCollapsed = conceptContent.style.display === 'none';
            conceptContent.style.display = isCollapsed ? 'flex' : 'none';
            conceptHeading.querySelector('span').textContent = isCollapsed ? '▼' : '▶';
        };
        
        keyConceptsList.appendChild(conceptHeading);
        keyConceptsList.appendChild(conceptContent);
        detailTopicDesc.appendChild(keyConceptsList);
    }

    // Populate topic notes from globalTopicNotes
    const noteKey = filterSubject.value + '_' + topicName;
    const existingNote = globalTopicNotes[noteKey] || '';
    const textarea = document.getElementById('topic-note-input');
    const preview = document.getElementById('topic-md-preview');
    if (textarea) textarea.value = existingNote;
    if (preview) preview.innerHTML = existingNote ? safeMarkdown(existingNote) : '*尚無筆記*';

    switchView('topic-detail');
}

function startPractice(jumpToIndex = null) {
    bcPractice.style.display = 'inline';
    bcSepPractice.style.display = 'inline';
    if (currentPracticeMode === 'wrong') bcPractice.innerHTML = '❌ 錯題模式';
    else if (currentPracticeMode === 'bookmark') bcPractice.innerHTML = '⭐ 收藏模式';
    else if (currentPracticeMode === 'custom_tag') bcPractice.innerHTML = '🔍 標籤模式';
    else bcPractice.innerHTML = '📝 一般模式';

    if (currentActiveTopicData.length === 0) return;
    
    viewToggleContainer.style.display = 'flex';
    bcSepPractice.style.display = 'inline';
    viewToggleContainer.style.display = 'flex';
    listAccuracy.style.display = 'block';
    
    if (currentPracticeMode === 'wrong') bcPractice.innerHTML = '📝 錯題練習';
    else if (currentPracticeMode === 'bookmark') bcPractice.innerHTML = '📝 收藏練習';
    else if (currentPracticeMode === 'custom_tag') bcPractice.innerHTML = '📝 標籤練習';
    else bcPractice.innerHTML = '📝 一般練習';

    answeredState = {};
    currentIndex = 0;
    
    if (jumpToIndex !== null && jumpToIndex >= 0 && jumpToIndex < currentActiveTopicData.length) {
        currentIndex = jumpToIndex;
    } else if (globalMode === 'general') {
        // 找到第一個「未做答」的題目（getAnswerState 回傳 undefined，代表存檔中無紀錄）
        // 題目已按 year 降序、no 升序排列，所以直接找第一個即可
        let foundUnanswered = false;
        for (let i = 0; i < currentActiveTopicData.length; i++) {
            const savedState = getAnswerState(currentActiveTopicData[i]);
            if (savedState === undefined) {
                currentIndex = i;
                foundUnanswered = true;
                break;
            }
        }
        // 若所有題目都已做答，保持 currentIndex = 0
    }
    progressFill.style.width = '0%';
    
    switchMode(currentMode);
    updateAccuracy();
}

function switchView(viewName) {
    viewTopicList.classList.remove('active');
    viewTopicDetail.classList.remove('active');
    viewPractice.classList.remove('active');
    viewList.classList.remove('active');
    
    // Req 1: Only show practice buttons on topic list
    const pBtns = document.getElementById('header-practice-actions');
    if (pBtns) {
        pBtns.style.display = (viewName === 'topic-list') ? 'flex' : 'none';
    }
    
    if (viewName === 'topic-list') viewTopicList.classList.add('active');
    else if (viewName === 'topic-detail') viewTopicDetail.classList.add('active');
    else if (viewName === 'practice') viewPractice.classList.add('active');
    else if (viewName === 'list') viewList.classList.add('active');
}

function switchMode(mode) {
    currentMode = mode;
    
    // Update toggle switch UI
    const modeCheckbox = document.getElementById('mode-toggle-checkbox');
    const lblCard = document.getElementById('label-mode-card');
    const lblList = document.getElementById('label-mode-list');
    
    if (modeCheckbox) {
        modeCheckbox.checked = (mode === 'list');
        if (mode === 'list') {
            if (lblList) lblList.style.color = 'var(--text-main)';
            if (lblCard) lblCard.style.color = 'var(--text-secondary)';
        } else {
            if (lblCard) lblCard.style.color = 'var(--text-main)';
            if (lblList) lblList.style.color = 'var(--text-secondary)';
        }
    }
    
    if (currentActiveTopicData.length === 0) {
        if (mode === 'card') {
            switchView('practice');
            const qTextEl = document.getElementById('q-text');
            if (qTextEl) qTextEl.textContent = '沒有符合條件的題目，請在左側選擇科目或調整過濾條件。';
        } else {
            switchView('list');
            const lc = document.getElementById('list-container');
            if (lc) lc.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);">沒有符合條件的題目，請在左側選擇科目或調整過濾條件。</div>';
        }
        return;
    }
    
    // Remember current question index for scrolling after switch
    const prevIndex = currentIndex;
    
    if (mode === 'card') {
        switchView('practice');
        renderCardView();
    } else {
        switchView('list');
        renderListView();
        setTimeout(() => {
            const el = document.getElementById('list-card-' + prevIndex);
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
    }
}

window.togglePdfView = function(idx = null) {
    const isListMode = (idx !== null && idx !== undefined);
    const q = isListMode ? currentActiveTopicData[idx] : currentActiveTopicData[currentIndex];
    if (!q) return;

    const qOptions = isListMode ? document.getElementById(`list-options-${idx}`) : document.getElementById('q-options');
    const pdfContainer = isListMode ? document.getElementById(`list-pdf-container-${idx}`) : document.getElementById('q-pdf-container');
    const pdfIframe = isListMode ? document.getElementById(`list-pdf-iframe-${idx}`) : document.getElementById('q-pdf-iframe');
    const qImages = isListMode ? document.getElementById(`list-images-${idx}`) : document.querySelector('#q-text .question-images');

    if (!pdfContainer || !qOptions) return;

    const isActive = pdfContainer.style.display === 'block';

    if (!isActive) {
        // --- Activate PDF mode ---
        // 1. Switch options to ABCD-only circle buttons
        qOptions.classList.add('pdf-mode');
        qOptions.style.cssText = 'display: flex; flex-direction: row; justify-content: center; gap: 16px; flex-wrap: wrap;';
        qOptions.querySelectorAll('.option, .list-option').forEach(opt => {
            opt.style.cssText = 'width:50px; height:50px; display:flex; justify-content:center; align-items:center; border-radius:50%; padding:0;';
            const content = opt.querySelector('.option-content');
            if (content) content.style.display = 'none';
            const letter = opt.querySelector('.option-letter');
            if (letter) {
                letter.style.cssText = 'margin:0; font-size:20px; font-weight:bold;';
                letter.textContent = letter.textContent.replace('.', '');
            }
        });

        // 2. Hide question images
        if (qImages) qImages.style.display = 'none';
        // 3. Show PDF container
        pdfContainer.style.display = 'block';

        // Build search text from question body (longest Chinese string)
        const subject = q.subject || currentActiveSubject;
        const year = q.year;
        let rawText = (q.question || '').replace(/<[^>]*>/gm, '').trim();
        let searchText = '';
        const matches = rawText.match(/[\u4e00-\u9fff]+/g);
        if (matches && matches.length > 0) {
            searchText = matches.reduce((a, b) => a.length >= b.length ? a : b);
            if (searchText.length > 15) searchText = searchText.substring(0, 15);
        } else {
            searchText = rawText.substring(0, 12);
        }

        // Use pdf.js viewer — supports #search= in ALL browsers (Chrome, Firefox, Edge)
        const pdfPath = `/pdfs/${encodeURIComponent(subject)}/${year}.pdf`;
        const viewerUrl = `/pdfjs/web/viewer.html?file=${encodeURIComponent(pdfPath)}#search=${encodeURIComponent(searchText)}&pagemode=none`;
        pdfIframe.src = viewerUrl;

    } else {
        // --- Deactivate PDF mode ---
        qOptions.classList.remove('pdf-mode');
        qOptions.style.cssText = '';
        qOptions.querySelectorAll('.option, .list-option').forEach(opt => {
            opt.style.cssText = '';
            const content = opt.querySelector('.option-content');
            if (content) content.style.display = '';
            const letter = opt.querySelector('.option-letter');
            if (letter) {
                letter.style.cssText = '';
                if (!letter.textContent.includes('.')) letter.textContent += '.';
            }
        });
        pdfContainer.style.display = 'none';
        pdfIframe.onload = null;
        pdfIframe.src = '';
        if (qImages) qImages.style.display = 'block';
    }
};

// --- Card View Logic ---
function renderCardView(preservePdfMode = false) {
    isPdfViewActive = preservePdfMode;
    if (!preservePdfMode) {
        const qOptions = document.getElementById('q-options');
        qOptions.classList.remove('pdf-mode');
        qOptions.style.cssText = '';
        document.getElementById('q-pdf-container').style.display = 'none';
        document.getElementById('q-pdf-iframe').src = '';
    }

    if (currentActiveTopicData.length === 0) return;
    const q = currentActiveTopicData[currentIndex];
    
    const savedState = getAnswerState(q);
    let leftBorderColor = 'var(--primary)';
    if (savedState) {
        if (savedState.is_fixed) leftBorderColor = '#10b981';
        else leftBorderColor = '#ef4444';
    }
    const qContainer = document.querySelector('#view-practice .question-container');
    if (qContainer) {
        qContainer.style.borderLeft = `6px solid ${leftBorderColor}`;
    }
    
    // Update breadcrumb and title dynamically for card mode (crucial for cross-subject custom tags)
    const sub = q.subject || currentActiveSubject;
    const top = q.topic || currentTopicName;
    bcSubject.innerHTML = (globalMode === 'general' ? '🏠 ' : '📚 ') + sub;
    bcSubject.style.display = 'inline';
    bcSepTopic.style.display = 'inline';
    bcTopic.textContent = `🏷️ ${top}`;
    bcTopic.style.display = 'inline';
    if (currentPracticeMode === 'custom_tag') {
        currentSubjectTitle.textContent = top;
    }

    let diffHtml = '';
    if (q.difficulty) {
        let diffClass = 'diff-unknown';
        if (q.difficulty.includes('簡單')) diffClass = 'diff-easy';
        else if (q.difficulty.includes('適中')) diffClass = 'diff-medium';
        else if (q.difficulty.includes('困難')) diffClass = 'diff-hard';
        diffHtml = `<span class="difficulty-indicator ${diffClass}">${q.difficulty}</span>`;
    }
    qNo.innerHTML = `Q ${currentIndex + 1} / ${currentActiveTopicData.length} ${diffHtml}`;
    const starBtn = document.getElementById('q-bookmark');
    if (starBtn) {
        const isBookmarked = getBookmarkState(q);
        starBtn.className = isBookmarked ? 'star-icon active' : 'star-icon inactive';
        starBtn.textContent = isBookmarked ? '★' : '☆';
        starBtn.onclick = (e) => toggleBookmark(e, q.exam_id, q.no, q.year);
    }
    
    qTags.innerHTML = '';
    const qidStr = `${q.year}-${q.subject}-${q.no}`;
    const btn = document.createElement('button');
    btn.className = 'btn btn-secondary';
    btn.style.padding = '4px 8px';
    btn.style.fontSize = '12px';
    btn.title = '點擊查看原始 PDF';
    btn.onclick = () => togglePdfView();
    btn.innerHTML = qidStr;
    qTags.appendChild(btn);
    
    let safeQuestion = q.question.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    let htmlContent = safeQuestion.replace(/^\s*\d+\.\s*/, '');
    if (q.images && q.images.length > 0) {
        htmlContent += `<div class="question-images">`;
        q.images.forEach(imgSrc => {
            htmlContent += `<img src="${imgSrc}" class="question-image" alt="img" />`;
        });
        htmlContent += `</div>`;
    }
    qText.innerHTML = htmlContent;
    
    const progress = ((currentIndex + 1) / currentActiveTopicData.length) * 100;
    progressFill.style.width = `${progress}%`;
    
    qOptions.innerHTML = '';
    const letters = ['A', 'B', 'C', 'D'];
    q.choices.forEach((choiceText, i) => {
        const letter = letters[i];
        const div = document.createElement('div');
        div.className = 'option';
        
        const hasAnswered = answeredState[currentIndex] !== undefined;
        const isSelected = answeredState[currentIndex] && answeredState[currentIndex].current_answer === letter;
        const isCorrect = q.answer.includes(letter);
        
        if (hasAnswered) {
            if (isSelected && isCorrect) div.classList.add('correct');
            if (isSelected && !isCorrect) div.classList.add('wrong');
            if (!isSelected && isCorrect) div.classList.add('correct');
        } else {
            div.onclick = () => {
                const wasPdfMode = document.getElementById('q-options').classList.contains('pdf-mode');
                const qid = q.year + '_' + q.exam_id + '_' + q.no;
                let state = getAnswerState(q);
                if (!state) {
                    state = { current_answer: letter, is_fixed: false };
                } else {
                    state.current_answer = letter;
                }
                
                state.is_fixed = q.answer.includes(letter);
                
                setAnswerState(q, state);
                answeredState[currentIndex] = state;
                saveProgress();
                renderCardView(wasPdfMode);
            };
        }
        
        let safeChoiceText = choiceText.replace(/</g, '&lt;').replace(/>/g, '&gt;');
        safeChoiceText = safeChoiceText.replace(/^\s*\(?[A-D]\)?[\.\s]+/i, '');
        div.innerHTML = `<span class="option-letter">${letter}.</span> <span class="option-content">${safeChoiceText}</span>`;
        qOptions.appendChild(div);
    });
    
    if (answeredState[currentIndex] !== undefined) {
        const doubtBtn = document.createElement('div');
        doubtBtn.style.cssText = "text-align:right; margin-top:8px;";
        doubtBtn.innerHTML = `<span style="color:var(--text-muted); font-size:12px; cursor:pointer; text-decoration:none;" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'" onclick="window.openOverrideModal(currentActiveTopicData[currentIndex], null)">不信？</span>`;
        qOptions.appendChild(doubtBtn);
    }
    
    if (answeredState[currentIndex] !== undefined || (savedState && savedState.is_fixed)) {
        explanationPanel.style.display = 'block';
        document.getElementById('q-tags').style.display = 'flex';
        const userExp = getExplanationState(q) || q.explanation || '';
        let topicTagHtml = '';
        if (q.topic) topicTagHtml = `<span class="tag" style="background:rgba(59,130,246,0.1); color:#3b82f6; border-color:rgba(59,130,246,0.3);">🏷️ ${q.topic}</span>`;

        qExplanation.innerHTML = `
            <div style="margin-bottom: 12px; display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
                ${topicTagHtml}
                ${(q.tags || []).map(t => `<span class="tag">#${t}</span>`).join('')}
            </div>
            
            ${q.key_concept ? `<div style="margin: 12px 0; color: var(--text-main); line-height: 1.6; font-size: 0.95em;"><span>🤖：</span><span>${q.key_concept}</span></div>` : ''}
            
            <div style="margin-top:8px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                    <span style="font-size:0.9em; font-weight:bold;">🤓<span style="color:white;">：</span></span>
                </div>
                <div id="md-preview-card-${q.year}-${q.exam_id}-${q.no}" class="markdown-body" style="background:var(--bg-lighter); padding:12px; border-radius:6px; min-height:60px; word-wrap:break-word;">${safeMarkdown(userExp || '*尚無筆記*')}</div>
                <div id="md-editor-card-${q.year}-${q.exam_id}-${q.no}" style="display:none;">
                    <textarea id="user-exp-card-${q.year}-${q.exam_id}-${q.no}" oninput="this.style.height='auto';this.style.height=this.scrollHeight+'px'" style="width:100%; min-height:150px; background:var(--bg-lighter); color:var(--text-main); border:1px solid var(--glass-border); padding:8px; border-radius:6px; resize:none; overflow:hidden;">${userExp}</textarea>
                </div>
            </div>
        `;
    } else {
        explanationPanel.style.display = 'none';
    }
    
    btnPrev.disabled = currentIndex === 0;
    btnNext.disabled = currentIndex === currentActiveTopicData.length - 1;
    updateAccuracy();

    if (preservePdfMode) {
        const qOptions = document.getElementById('q-options');
        qOptions.classList.add('pdf-mode');
        qOptions.style.cssText = 'display: flex; flex-direction: row; justify-content: center; gap: 16px; flex-wrap: wrap;';
        qOptions.querySelectorAll('.option').forEach(opt => {
            opt.style.cssText = 'width:50px; height:50px; display:flex; justify-content:center; align-items:center; border-radius:50%; padding:0;';
            const content = opt.querySelector('.option-content');
            if (content) content.style.display = 'none';
            const letter = opt.querySelector('.option-letter');
            if (letter) {
                letter.style.cssText = 'margin:0; font-size:20px; font-weight:bold;';
                letter.textContent = letter.textContent.replace('.', '');
            }
        });
        const qImages = document.querySelector('#q-text .question-images');
        if (qImages) qImages.style.display = 'none';
    }
}

btnPrev.onclick = () => { if (currentIndex > 0) { currentIndex--; renderCardView(); } };
btnNext.onclick = () => { if (currentIndex < currentActiveTopicData.length - 1) { currentIndex++; renderCardView(); } };
btnNote.onclick = () => {
    const q = currentActiveTopicData[currentIndex];
    const savedState = getAnswerState(q);
    if (answeredState[currentIndex] === undefined && !(savedState && savedState.is_fixed)) {
        alert('請先點擊作答後，才能寫筆記喔！');
        return;
    }
    explanationPanel.style.display = explanationPanel.style.display === 'block' ? 'none' : 'block';
};

// --- List View Logic ---
function renderListView() {
    listContainer.innerHTML = '';
    const letters = ['A', 'B', 'C', 'D'];
    initBreadcrumbObserver();
    breadcrumbObserver.disconnect();
    
    currentActiveTopicData.forEach((q, idx) => {
        const card = document.createElement('div');
        card.className = 'list-card';
        card.id = 'list-card-' + idx;
        card.setAttribute('data-subject', q.subject || currentActiveSubject);
        card.setAttribute('data-topic', q.topic || currentTopicName);
        
        const qidStr = `${q.year}-${q.subject || currentActiveSubject}-${q.no}`;
        let questionTagsHtml = `<button class="btn btn-secondary" style="padding: 4px 8px; font-size: 12px;" title="點擊查看原始 PDF" onclick="togglePdfView(${idx})">${qidStr}</button>`;
        let topicTagHtml = q.topic ? `<span class="tag" style="background:rgba(59,130,246,0.1); color:#3b82f6; border-color:rgba(59,130,246,0.3);">🏷️ ${q.topic}</span>` : '';
        
        let imgHtml = '';
        if (q.images && q.images.length > 0) {
            imgHtml = `<div class="question-images" id="list-images-${idx}" style="margin: 12px 0;">` + 
                      q.images.map(imgSrc => `<img src="${imgSrc}" class="question-image" style="max-height:300px; max-width:100%; object-fit:contain;">`).join('') +
                      `</div>`;
        }
        
        let optionsHtml = '<div class="list-card-options" id="list-options-'+idx+'">';
        q.choices.forEach((choice, i) => {
            const letter = letters[i];
            const hasAnswered = answeredState[idx] !== undefined;
            const isSelected = answeredState[idx] && answeredState[idx].current_answer === letter;
            const isCorrect = q.answer.includes(letter);
            
            let extraClass = '';
            if (hasAnswered) {
                if (isSelected && isCorrect) extraClass = 'correct';
                if (isSelected && !isCorrect) extraClass = 'wrong';
                if (!isSelected && isCorrect) extraClass = 'correct';
            }
            
            let safeChoice = choice.replace(/</g, '&lt;').replace(/>/g, '&gt;');
            safeChoice = safeChoice.replace(/^\s*\(?[A-D]\)?[\.\s]+/i, '');
            optionsHtml += `
                <div class="list-option ${extraClass}" onclick="selectListOption(${idx}, '${letter}')">
                    <span class="option-letter">${letter}.</span> <span class="option-content">${safeChoice}</span>
                </div>
            `;
        });
        optionsHtml += '</div>';

        const savedState = getAnswerState(q);
        const isSavedFixed = savedState ? savedState.is_fixed : false;
        
        let answerAreaClass = 'list-answer-area';
        if (isSavedFixed) {
            answerAreaClass += ' answered';
        }
        
        let leftBorderColor = 'var(--primary)';
        if (savedState) {
            if (savedState.is_fixed) leftBorderColor = '#10b981';
            else leftBorderColor = '#ef4444';
        }

        let diffHtml = '';
        if (q.difficulty) {
            let diffClass = 'diff-unknown';
            if (q.difficulty.includes('簡單')) diffClass = 'diff-easy';
            else if (q.difficulty.includes('適中')) diffClass = 'diff-medium';
            else if (q.difficulty.includes('困難')) diffClass = 'diff-hard';
            diffHtml = `<span class="difficulty-indicator ${diffClass}">${q.difficulty}</span>`;
        }

        card.innerHTML = `
            <div class="list-card-left" style="background: ${leftBorderColor};"></div>
            <div class="list-card-main">
                <div class="list-card-header" style="align-items: center;">
                    <span class="badge" style="margin:0;">Q ${idx + 1} / ${currentActiveTopicData.length} ${diffHtml}</span>
                    <div style="display:flex; align-items:center; gap:8px;">
                        ${questionTagsHtml}
                        <span class="${getBookmarkState(q) ? 'star-icon active' : 'star-icon inactive'}" style="cursor:pointer; font-size:18px; display:flex; align-items:center; line-height:1;" onclick="toggleBookmark(event, '${q.exam_id}', '${q.no}', '${q.year}')">
                            ${getBookmarkState(q) ? '★' : '☆'}
                        </span>
                    </div>
                </div>
                <div class="list-card-body">
                    ${q.question.replace(/</g, '&lt;').replace(/>/g, '&gt;')}
                    ${imgHtml}
                </div>
                ${optionsHtml}
                
                <div id="list-pdf-container-${idx}" style="display:none; margin-top:16px;">
                    <iframe id="list-pdf-iframe-${idx}" style="width:100%; height:65vh; border:1px solid var(--glass-border); border-radius:8px; background:#fff;"></iframe>
                </div>
                
                <div class="list-explanation" id="list-exp-${idx}" style="display:none; margin-top:12px; padding:12px; border:1px solid var(--glass-border); border-radius:8px;">
                    <div class="tags-container" style="margin-bottom:12px;">
                        ${topicTagHtml}
                        ${(q.tags || []).map(t => `<span class="tag">#${t}</span>`).join('')}
                    </div>
                    
                    ${q.key_concept ? `<div style="margin: 12px 0; color: var(--text-main); line-height: 1.6; font-size: 0.95em;"><span>🤖：</span><span>${q.key_concept}</span></div>` : ''}
                    
                    <div style="margin-top:8px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                            <span style="font-size:0.9em; font-weight:bold;">🤓<span style="color:white;">：</span></span>
                        </div>
                        <div id="md-preview-list-${q.year}-${q.exam_id}-${q.no}" class="markdown-body" style="background:var(--bg-lighter); padding:12px; border-radius:6px; min-height:60px; max-height:400px; overflow-y:auto; resize:vertical; word-wrap:break-word;">${safeMarkdown(getExplanationState(q) || q.explanation || '*尚無筆記*')}</div>
                        <div id="md-editor-list-${q.year}-${q.exam_id}-${q.no}" style="display:none;">
                            <textarea id="user-exp-list-${q.year}-${q.exam_id}-${q.no}" style="width:100%; height:80px; background:var(--bg-lighter); color:var(--text-main); border:1px solid var(--glass-border); padding:8px; border-radius:6px; resize:vertical;">${getExplanationState(q) || q.explanation || ''}</textarea>
                        </div>
                    </div>
                </div>
                
                <div class="list-card-footer">
                    <div class="${answerAreaClass}" id="list-answer-area-${idx}">
                        答案：<span class="blurred-answer">${q.answer}</span>
                        ${(answeredState[idx] !== undefined) ? `<div style="text-align:right; margin-top:4px;" class="btn-override"><span style="color:var(--text-muted); font-size:12px; cursor:pointer; text-decoration:none;" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'" onclick="window.openOverrideModal(currentActiveTopicData[${idx}], ${idx}); event.stopPropagation();">不信？</span></div>` : ''}
                    </div>
                </div>
            </div>
            <div class="list-card-right" onclick="toggleListExp(${idx})">
                <div class="list-card-right-text">寫筆記</div>
            </div>
        `;
        listContainer.appendChild(card);
        breadcrumbObserver.observe(card);
        // Key concept interactive area removed as requested
    });
    
    progressFill.style.width = '100%';
    updateAccuracy();
}

window.selectListOption = function(idx, selectedLetter) {
    if (answeredState[idx] !== undefined) return;
    
    const qid = currentActiveTopicData[idx].year + '_' + currentActiveTopicData[idx].exam_id + '_' + currentActiveTopicData[idx].no;
    let q = currentActiveTopicData[idx];
    let state = getAnswerState(q);
    if (!state) {
        state = { current_answer: selectedLetter, is_fixed: false };
    } else {
        state.current_answer = selectedLetter;
    }
    
    state.is_fixed = q.answer.includes(selectedLetter);
    
    setAnswerState(q, state);
    answeredState[idx] = state;
    saveProgress();
    updateAccuracy();
    
    // Add correct/wrong classes to options
    const container = document.getElementById('list-options-' + idx);
    if (!container) return;
    
    const options = container.querySelectorAll('.list-option');
    const letters = ['A', 'B', 'C', 'D'];
    options.forEach((opt, i) => {
        const letter = letters[i];
        const isCorrectChoice = q.answer.includes(letter);
        if (letter === selectedLetter && isCorrectChoice) opt.classList.add('correct');
        else if (letter === selectedLetter && !isCorrectChoice) opt.classList.add('wrong');
        else if (letter !== selectedLetter && isCorrectChoice) opt.classList.add('correct');
    });

    // Add answered class to allow hover blur reveal
    const answerArea = document.getElementById('list-answer-area-' + idx);
    if (answerArea) {
        if (state.is_fixed) answerArea.classList.add('answered');
        if (!answerArea.querySelector('.btn-override')) {
            const btnDiv = document.createElement('div');
            btnDiv.style.cssText = "text-align:right; margin-top:4px;";
            btnDiv.className = "btn-override";
            btnDiv.innerHTML = `<span style="color:var(--text-muted); font-size:12px; cursor:pointer; text-decoration:none;" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'" onclick="window.openOverrideModal(currentActiveTopicData[${idx}], ${idx}); event.stopPropagation();">不信？</span>`;
            answerArea.appendChild(btnDiv);
        }
    }
    
    // Update left border color
    const cardLeft = document.querySelector(`#list-card-${idx} .list-card-left`);
    if (cardLeft) {
        cardLeft.style.background = state.is_fixed ? '#10b981' : '#ef4444';
    }
}

window.toggleListExp = function(idx) {
    const q = currentActiveTopicData[idx];
    const savedState = getAnswerState(q);
    if (answeredState[idx] === undefined && !(savedState && savedState.is_fixed)) {
        alert('請先點擊作答後，才能寫筆記喔！');
        return;
    }
    const p = document.getElementById('list-exp-' + idx);
    if (p) {
        p.style.display = p.style.display === 'block' ? 'none' : 'block';
    } else {
        alert("此題目前尚無詳解 (背景仍在生成中)");
    }
}

function updateAccuracy() {
    let total = 0;
    let correct = 0;
    
    if (accuracyCalcMode === 'session') {
        Object.keys(answeredState).forEach(idx => {
            total++;
            if (answeredState[idx] && answeredState[idx].current_answer === currentActiveTopicData[idx].answer) correct++;
        });
        if (total === 0) {
            listAccuracy.textContent = "正確率: --%";
        } else {
            const pct = Math.round((correct / total) * 100);
            let emoji = '🤡';
            if (pct >= 90) emoji = '😍';
            else if (pct >= 80) emoji = '😆';
            else if (pct >= 70) emoji = '😊';
            else if (pct >= 60) emoji = '😅';
            else if (pct >= 50) emoji = '😐';
            else if (pct >= 40) emoji = '😑';
            else if (pct >= 30) emoji = '😣';
            else if (pct >= 20) emoji = '😨';
            else if (pct >= 10) emoji = '🤮';
            
            listAccuracy.textContent = `${emoji} ${pct}% (${correct}/${total})`;
        }
    } else {
        const listedTotal = currentActiveTopicData.length;
        currentActiveTopicData.forEach(q => {
            const state = getAnswerState(q);
            if (state && state.is_fixed !== undefined) {
                total++;
                if (state.is_fixed === true) correct++;
            }
        });
        
        let pct = total === 0 ? 0 : Math.round((correct / total) * 100);
        let emoji = '🤡';
        if (pct >= 90) emoji = '😍';
        else if (pct >= 80) emoji = '😆';
        else if (pct >= 70) emoji = '😊';
        else if (pct >= 60) emoji = '😅';
        else if (pct >= 50) emoji = '😐';
        else if (pct >= 40) emoji = '😑';
        else if (pct >= 30) emoji = '😣';
        else if (pct >= 20) emoji = '😨';
        else if (pct >= 10) emoji = '🤮';
        
        listAccuracy.textContent = `${emoji} ${pct}% (${correct}/${total}/${listedTotal})`;
    }
}

// --- Advanced Search Modal ---
function updateAdvPreview() {
    const rxStr = advRegex.value;
    if (!rxStr || !filterSubject.value) {
        advPreview.textContent = '請先選擇科目並輸入 Regex';
        return;
    }
    try {
        const rx = new RegExp(rxStr, 'i');
        let matchCount = 0;
        currentData.forEach(q => {
            const text = q.question + " " + q.choices.join(" ");
            if (rx.test(text)) matchCount++;
        });
        advPreview.textContent = `將會匹配並標記 ${matchCount} 題`;
    } catch(e) {
        advPreview.textContent = 'Regex 語法錯誤';
    }
}

async function saveAdvancedSearch() {
    const rxStr = advRegex.value.trim();
    const tagName = advTagName.value.trim();
    if (!rxStr || !tagName || !filterSubject.value) return alert('請填寫完整條件');
    
    let rx;
    try { rx = new RegExp(rxStr); } 
    catch(e) { return alert('Regex 語法錯誤'); }

    btnAdvSave.disabled = true;
    btnAdvSave.textContent = '處理中...';

    const matchedQs = [];
    currentData.forEach(q => {
        const text = q.question + " " + q.choices.join(" ");
        if (rx.test(text)) {
            matchedQs.push({exam_id: q.exam_id, no: q.no, year: q.year});
        }
    });

    if (matchedQs.length > 0) {
        try {
            // Add to Custom Tags instead of global JSON
            if (!globalCustomTags[tagName]) globalCustomTags[tagName] = [];
            matchedQs.forEach(mq => {
                const id = mq.year + '_' + mq.exam_id + '_' + mq.no;
                if (!globalCustomTags[tagName].includes(id)) {
                    globalCustomTags[tagName].push(id);
                }
            });
            saveProgress();

            await fetch('/api/save_search_rule', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: tagName, query: rxStr })
            });
            
            alert(`成功！已將 ${matchedQs.length} 題標記為自訂標籤「${tagName}」並儲存規則。`);
            await loadSavedRules();
            advModal.style.display = 'none';
            
            // Update custom tags sidebar before switching
            renderCustomTagsCheckboxes();
            
            // Switch to list view with matched questions
            let matchedQuestionsObjects = [];
            currentData.forEach(q => {
                if (matchedQs.some(mq => mq.exam_id === q.exam_id && mq.no === q.no && mq.year === q.year)) {
                    matchedQuestionsObjects.push(q);
                }
            });
            currentActiveTopicData = matchedQuestionsObjects;
            currentPracticeMode = 'normal';
            switchView('practice');
            switchMode('list');
            startPractice();
            
        } catch(e) { alert('儲存失敗'); }
    } else { alert('沒有符合條件的題目'); }
    
    btnAdvSave.disabled = false;
    btnAdvSave.textContent = '儲存並標記';
}

init().then(() => {
    selectSlot('default');
    
    // Live Update Polling Mechanism
    let currentCacheVersion = 0;
    setInterval(async () => {
        if (!currentActiveSubject) return;
        try {
            const res = await fetch(`/api/cache_version`);
            const data = await res.json();
            if (currentCacheVersion === 0) {
                currentCacheVersion = data.version;
            } else if (data.version > currentCacheVersion) {
                currentCacheVersion = data.version;
                console.log("Cache updated in Obsidian. Reloading subject data silently...");
                
                delete subjectDataCache[currentActiveSubject];
                const newData = await fetchSubjectData(currentActiveSubject);
                currentData = newData;
                
                if (currentTopicName) {
                    currentActiveTopicData = currentData.filter(q => q.topic === currentTopicName);
                } else {
                    currentActiveTopicData = currentData;
                }
                
                if (globalMode === 'general') {
                    if (currentMode === 'card') {
                        renderCardView(isPdfViewActive);
                    } else if (currentMode === 'list') {
                        renderListView();
                    } else {
                        openSubjectDashboard(currentActiveSubject);
                    }
                } else {
                    switchGlobalMode(globalMode);
                }
            }
        } catch(e) {}
    }, 2500);
});


window.toggleBookmark = function(e, exam_id, no, year) {
    e.stopPropagation();
    
    const q = currentActiveTopicData.find(x => x.exam_id == exam_id && x.no == no && x.year == year);
    if (!q) return;
    
    const currentState = getBookmarkState(q);
    setBookmarkState(q, !currentState);
    
    saveProgress();
    if (currentMode === 'card') renderCardView();
    else renderListView();
};



window.saveUserExplanation = function(exam_id, no, year, val) {
    const q = currentActiveTopicData.find(x => x.exam_id == exam_id && x.no == no && x.year == year);
    if (!q) return;
    setExplanationState(q, val);
    saveProgress();
};


let globalSlotNames = JSON.parse(localStorage.getItem('slot_names')) || {1: '存檔 1', 2: '存檔 2', 3: '存檔 3'};

async function loadSlotNamesFromServer() {
    try {
        const res = await fetch('/api/slot_names');
        if (res.ok) {
            const names = await res.json();
            for (let i = 1; i <= 3; i++) {
                if (names[i]) globalSlotNames[i] = names[i];
            }
            localStorage.setItem('slot_names', JSON.stringify(globalSlotNames));
            
            for (let i = 1; i <= 3; i++) {
                const el = document.getElementById('slot-' + i + '-title');
                if (el) el.innerText = globalSlotNames[i] || ('存檔 ' + i);
                const el2 = document.getElementById(`slot-name-${i}`);
                if (el2) el2.innerText = globalSlotNames[i] || ('存檔 ' + i);
            }
            
            if (currentSaveSlot) {
                const sidebarTitle = document.getElementById('sidebar-title');
                if (sidebarTitle) sidebarTitle.innerText = globalSlotNames[currentSaveSlot] || ('存檔 ' + currentSaveSlot);
                const bcSubject = document.getElementById('bc-subject');
                if (bcSubject && bcSubject.innerText.includes('選擇科目')) {
                    bcSubject.innerText = `🏠 選擇科目 (${globalSlotNames[currentSaveSlot] || ('存檔 ' + currentSaveSlot)})`;
                }
            }
        }
    } catch(e) {}
}
loadSlotNamesFromServer();

window.editSlotName = function(e, slotId) {
    e.stopPropagation();
    window.renameSlot(slotId);
};

window.toggleSidebar = function() {
    const sidebar = document.getElementById('app-sidebar');
    const main = document.querySelector('.main-content');
    if (sidebar.style.display === 'none') {
        sidebar.style.display = 'flex';
    } else {
        sidebar.style.display = 'none';
    }
};

window.addManualTag = function(exam_id, no, year) {
    const input = document.getElementById(`manual-tag-${exam_id}-${no}`);
    let tag = input.value.trim();
    if (/[<>'\"\\]/.test(tag)) {
        alert('標籤不能包含特殊符號 (<, >, \', ", \\)');
        return;
    }
    if (!tag) return;
    const q = currentData.find(x => x.exam_id == exam_id && x.no == no && x.year == year && x.year == year) || currentActiveTopicData.find(x => x.exam_id == exam_id && x.no == no && x.year == year && x.year == year);
    if (!q) return;
    addCustomTagState(q, tag);
    saveProgress();
    renderCustomTagsCheckboxes();
    if (currentMode === 'card') renderCardView();
    else renderListView();
    input.value = '';
};

window.toggleEditUserExp = function(exam_id, no) {
    const viewDiv = document.getElementById(`user-exp-view-${exam_id}-${no}`);
    const editDiv = document.getElementById(`user-exp-edit-container-${exam_id}-${no}`);
    if (editDiv.style.display === 'none') {
        editDiv.style.display = 'block';
        viewDiv.style.display = 'none';
    } else {
        editDiv.style.display = 'none';
        viewDiv.style.display = 'block';
    }
};

window.saveAndRenderUserExp = function(exam_id, no) {
    const textarea = document.getElementById(`user-exp-${exam_id}-${no}`);
    saveUserExplanation(exam_id, no, textarea.value);
    
    const viewDiv = document.getElementById(`user-exp-view-${exam_id}-${no}`);
    if (textarea.value.trim()) {
        viewDiv.innerHTML = safeMarkdown(textarea.value);
    } else {
        viewDiv.innerHTML = '<span style="color:var(--text-muted);">點擊編輯撰寫 Markdown 筆記...</span>';
    }
    toggleEditUserExp(exam_id, no);
};



window.toggleEditTopicNote = function() {
    const viewDiv = document.getElementById('topic-note-view');
    const editDiv = document.getElementById('topic-note-edit-container');
    if (editDiv.style.display === 'none') {
        editDiv.style.display = 'block';
        viewDiv.style.display = 'none';
    } else {
        editDiv.style.display = 'none';
        viewDiv.style.display = 'block';
    }
};



window.toggleMarkdownEdit = function(id, isSave, q_exam_id, q_no, q_year, btnElement) {
    const preview = document.getElementById('md-preview-' + id);
    const editor = document.getElementById('md-editor-' + id);
    const iconPencil = document.getElementById('icon-pencil-' + id);
    const iconBook = document.getElementById('icon-book-' + id);
    const textarea = document.getElementById('user-exp-' + id);

    if (editor.style.display === 'none') {
        editor.style.display = 'block';
        preview.style.display = 'none';
        if(iconPencil) iconPencil.style.display = 'none';
        if(iconBook) iconBook.style.display = 'block';
        if(textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = textarea.scrollHeight + 'px';
        }
    } else {
        if (isSave) {
            saveUserExplanation(q_exam_id, q_no, q_year, textarea.value);
            preview.innerHTML = safeMarkdown(textarea.value || '*尚無筆記*');
            if(btnElement) showSaveToast(btnElement);
        }
        editor.style.display = 'none';
        preview.style.display = 'block';
        if(iconPencil) iconPencil.style.display = 'block';
        if(iconBook) iconBook.style.display = 'none';
    }
};


window.toggleTopicMarkdownEdit = function(isSave, btnElement) {
    const preview = document.getElementById('topic-md-preview');
    const editor = document.getElementById('topic-md-editor');
    const iconPencil = document.getElementById('icon-pencil-topic');
    const iconBook = document.getElementById('icon-book-topic');
    const textarea = document.getElementById('topic-note-input');

    if (editor.style.display === 'none') {
        editor.style.display = 'block';
        preview.style.display = 'none';
        if(iconPencil) iconPencil.style.display = 'none';
        if(iconBook) iconBook.style.display = 'block';
    } else {
        if (isSave) {
            if (!currentActiveTopicData || currentActiveTopicData.length === 0) return;
            const topic = currentActiveTopicData[0].topic || '未分類';
            globalTopicNotes[filterSubject.value + '_' + topic] = textarea.value;
            saveProgress();
            preview.innerHTML = safeMarkdown(textarea.value || '*尚無筆記*');
            if(btnElement) showSaveToast(btnElement);
            refreshAnkiCardWall();
        }
        editor.style.display = 'none';
        preview.style.display = 'block';
        if(iconPencil) iconPencil.style.display = 'block';
        if(iconBook) iconBook.style.display = 'none';
    }
};



document.getElementById('btn-sidebar-toggle').addEventListener('click', () => {
    document.querySelector('.sidebar').classList.toggle('collapsed');
});

window.renameSlot = async function(slot) {
    const el = document.getElementById('slot-' + slot + '-title');
    const oldName = el ? el.innerText : (globalSlotNames[slot] || ('存檔 ' + slot));
    const newName = prompt('請輸入新的存檔名稱：', oldName);
    if (newName !== null && newName.trim() !== '') {
        const trimmed = newName.trim();
        try {
            await fetch(`/api/rename_slot/${slot}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: trimmed})
            });
        } catch(e) {
            console.error("Failed to rename on server", e);
        }
        
        globalSlotNames[slot] = trimmed;
        localStorage.setItem('slot_names', JSON.stringify(globalSlotNames));
        
        if (el) el.innerText = trimmed;
        const el2 = document.getElementById(`slot-name-${slot}`);
        if (el2) el2.innerText = trimmed;
        
        if (currentSaveSlot == slot) {
            const sidebarTitle = document.getElementById('sidebar-title');
            if (sidebarTitle) sidebarTitle.innerText = trimmed;
            const bcSubject = document.getElementById('bc-subject');
            if (bcSubject && bcSubject.innerText.includes('選擇科目')) {
                bcSubject.innerText = `🏠 選擇科目 (${trimmed})`;
            }
            if (!globalSaveData._meta) globalSaveData._meta = {};
            globalSaveData._meta.slotName = trimmed;
        }
    }
};

const slotNames = JSON.parse(localStorage.getItem('slot_names') || '{}');
for (let i=1; i<=3; i++) {
    if (slotNames[i]) {
        const el = document.getElementById('slot-' + i + '-title');
        if (el) el.innerText = slotNames[i];
    }
}


// New Toggle Switch Logic
const _modeCheckbox = document.getElementById('mode-toggle-checkbox');
const _lblCard = document.getElementById('label-mode-card');
const _lblList = document.getElementById('label-mode-list');

if (_modeCheckbox) {
    _modeCheckbox.addEventListener('change', (e) => {
        if (e.target.checked) switchMode('list');
        else switchMode('card');
    });
    _lblCard.addEventListener('click', () => {
        _modeCheckbox.checked = false;
        switchMode('card');
    });
    _lblList.addEventListener('click', () => {
        _modeCheckbox.checked = true;
        switchMode('list');
    });
}


function updateSidebarUI() {
    // This is now handled by switchGlobalMode
    switchGlobalMode(globalPracticeMode);
}

// Mode button clicks are handled by switchGlobalMode (see bottom of file)
// Removed duplicate listeners here to avoid conflicts.

function renderCustomTagsCheckboxes() {
    customTagsCheckboxes.innerHTML = '';
    const allTags = new Set();
    for (let sub in globalSaveData) {
        if (globalSaveData[sub].customTags) {
            Object.keys(globalSaveData[sub].customTags).forEach(t => allTags.add(t));
        }
    }
    Array.from(allTags).forEach(tag => {
        const lbl = document.createElement('label');
        lbl.className = 'filter-dropdown-item';
        
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = tag;
        cb.className = 'custom-tag-cb';
        cb.onchange = () => { if (globalPracticeMode !== 'search') applyFilters(); };
        
        lbl.appendChild(cb);
        lbl.appendChild(document.createTextNode('🏷️ ' + tag));
        customTagsCheckboxes.appendChild(lbl);
    });
}



function populateMultiSelect() {
    if (!filterSubjectMulti) return;
    filterSubjectMulti.innerHTML = '';
    const allOpt = document.createElement('label');
    allOpt.className = 'filter-dropdown-item';
    allOpt.innerHTML = `<input type="checkbox" id="multi-subject-all" checked> <b>全選 / 全不選</b>`;
    filterSubjectMulti.appendChild(allOpt);
    
    const checkboxes = [];
    const subjects = Array.from(filterSubject.options).map(o => o.value).filter(v => v);
    subjects.forEach(sub => {
        const lbl = document.createElement('label');
        lbl.className = 'filter-dropdown-item';
        lbl.innerHTML = `<input type="checkbox" class="multi-subject-cb" value="${sub}" checked> ${sub}`;
        filterSubjectMulti.appendChild(lbl);
        checkboxes.push(lbl.querySelector('input'));
    });
    
    const allCb = document.getElementById('multi-subject-all');
    allCb.onchange = async (e) => {
        checkboxes.forEach(cb => cb.checked = e.target.checked);
        await updateMultiYearCheckboxes();
        if (globalPracticeMode !== 'search') applyFilters();
    };
    checkboxes.forEach(cb => {
        cb.onchange = async () => {
            allCb.checked = checkboxes.every(c => c.checked);
            await updateMultiYearCheckboxes();
            if (globalPracticeMode !== 'search') applyFilters();
        };
    });
}


async function executeMultiModePractice() {
    if (globalPracticeMode === 'general') return;
    
    // Get selected subjects
    const cbs = document.querySelectorAll('.subject-filter-cb:checked');
    const selectedSubjects = Array.from(cbs).map(cb => cb.value);
    
    if (selectedSubjects.length === 0) {
        currentActiveTopicData = [];
        renderCardView();
        renderListView();
        return;
    }

    const bcTopic = document.getElementById('bc-topic');
    const bcSepTopic = document.getElementById('bc-sep-topic');
    bcTopic.style.display = 'inline';
    bcSepTopic.style.display = 'inline';
    bcTopic.textContent = `載入中...`;

    let matchedQuestions = [];

    for (let sub of selectedSubjects) {
        let subQuestions = [];
        if (sub === filterSubject.value && currentData && currentData.length > 0) {
            subQuestions = currentData;
        } else {
            try {
                const res = await fetch(`../data/${sub}.json?v=${Date.now()}`);
                if (res.ok) {
                    subQuestions = await res.json();
                }
            } catch(e) {
                console.error("Failed to fetch subject", sub, e);
            }
        }

        // We need the saved state for this subject to check wrong/bookmark
        const sData = globalSaveData[sub] || { answers: {}, bookmarks: [], customTags: {} };
        const answers = sData.answers || {};
        const bookmarks = sData.bookmarks || [];
        
        subQuestions.forEach(q => {
            const id = q.year + '_' + q.exam_id + '_' + q.no;
            q.subject = sub; // Inject subject!
            
            if (globalPracticeMode === 'wrong') {
                const state = answers[id];
                if (state && !state.isCorrect && !state.is_fixed) {
                    matchedQuestions.push(q);
                }
            } else if (globalPracticeMode === 'bookmark') {
                if (bookmarks.includes(id)) {
                    matchedQuestions.push(q);
                }
            }
        });
    }

    currentActiveTopicData = matchedQuestions;
    switchView('practice');
    switchMode('list');
    startPractice();
    
    if (globalPracticeMode === 'wrong') {
        bcTopic.textContent = `❌ 跨科錯題`;
    } else if (globalPracticeMode === 'bookmark') {
        bcTopic.textContent = `⭐ 跨科收藏`;
    }
}



async function updateMultiYearCheckboxes() {
    filterYearContainer.innerHTML = '';
    const yrWrap = document.getElementById('filter-year-wrapper');
    if (yrWrap) yrWrap.style.display = 'block';
    
    let selectedSubjects = Array.from(document.querySelectorAll('.multi-subject-cb:checked')).map(cb => cb.value);
    if (selectedSubjects.length === 0) {
        selectedSubjects = [...subjects];
    }
    
    filterYearContainer.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">載入年份中...</div>';
    
    const allYears = new Set();
    for (let sub of selectedSubjects) {
        const subQuestions = await fetchSubjectData(sub);
        subQuestions.forEach(q => {
            if (q.year) {
                allYears.add(q.year);
            }
        });
    }
    
    filterYearContainer.innerHTML = '';
    
    const topControls = document.createElement('div');
    topControls.style.borderBottom = '1px solid rgba(255,255,255,0.1)';
    topControls.style.paddingBottom = '8px';
    topControls.style.marginBottom = '8px';
    topControls.style.display = 'flex';
    topControls.style.flexDirection = 'column';
    topControls.style.gap = '6px';
    
    const selectAllLbl = document.createElement('label');
    selectAllLbl.style.cursor = 'pointer';
    selectAllLbl.style.fontWeight = '600';
    selectAllLbl.innerHTML = `<input type="checkbox" id="year-select-all-multi" checked style="margin-right:8px;"> 全選 / 全不選`;
    selectAllLbl.querySelector('input').addEventListener('change', (e) => {
        const isChecked = e.target.checked;
        document.querySelectorAll('.year-checkbox').forEach(cb => { 
            cb.checked = isChecked; 
            if (isChecked) globalUncheckedYears.delete(cb.value);
            else globalUncheckedYears.add(cb.value);
        });
        const l5 = document.getElementById('year-last-5-multi');
        const l10 = document.getElementById('year-last-10-multi');
        if(l5) l5.checked = false;
        if(l10) l10.checked = false;
        if (globalPracticeMode !== 'search') applyFilters();
    });
    topControls.appendChild(selectAllLbl);

    const createRecentYearsCb = (yearsCount, id, labelText) => {
        const lbl = document.createElement('label');
        lbl.style.cursor = 'pointer';
        lbl.style.fontWeight = '600';
        lbl.innerHTML = `<input type="checkbox" id="${id}" style="margin-right:8px;"> ${labelText}`;
        lbl.querySelector('input').addEventListener('change', (e) => {
            const isChecked = e.target.checked;
            let maxYear = 0;
            document.querySelectorAll('.year-checkbox').forEach(cb => {
                const yr = parseInt(cb.value.split('-')[0]);
                if (!isNaN(yr) && yr > maxYear) maxYear = yr;
            });
            document.querySelectorAll('.year-checkbox').forEach(cb => {
                const yr = parseInt(cb.value.split('-')[0]);
                if (!isNaN(yr) && yr >= maxYear - yearsCount + 1) {
                    cb.checked = isChecked;
                    if (isChecked) globalUncheckedYears.delete(cb.value);
                    else globalUncheckedYears.add(cb.value);
                }
            });
            if (isChecked) {
                const otherId = id === 'year-last-5-multi' ? 'year-last-10-multi' : 'year-last-5-multi';
                const other = document.getElementById(otherId);
                if (other) other.checked = false;
            }
            const allChecked = Array.from(document.querySelectorAll('.year-checkbox')).every(cb => cb.checked);
            const selectAll = document.getElementById('year-select-all-multi');
            if (selectAll) selectAll.checked = allChecked;
            if (globalPracticeMode !== 'search') applyFilters();
        });
        return lbl;
    };
    topControls.appendChild(createRecentYearsCb(5, 'year-last-5-multi', '近五年'));
    topControls.appendChild(createRecentYearsCb(10, 'year-last-10-multi', '近十年'));
    filterYearContainer.appendChild(topControls);

    const sortedYears = Array.from(allYears).sort((a,b) => b.toString().localeCompare(a.toString()));
    
    sortedYears.forEach(y => {
        const lbl = document.createElement('label');
        lbl.style.display = 'block';
        lbl.style.marginBottom = '6px';
        lbl.style.cursor = 'pointer';
        const isChecked = !globalUncheckedYears.has(y) ? 'checked' : '';
        lbl.innerHTML = `<input type="checkbox" value="${y}" class="year-checkbox" ${isChecked} style="margin-right:8px;"> ${y}`;
        lbl.querySelector('input').addEventListener('change', (e) => {
            if (e.target.checked) globalUncheckedYears.delete(y);
            else globalUncheckedYears.add(y);
            const allChecked = Array.from(document.querySelectorAll('.year-checkbox')).every(cb => cb.checked);
            const selectAll = document.getElementById('year-select-all-multi');
            if(selectAll) selectAll.checked = allChecked;
            if (globalPracticeMode !== 'search') applyFilters();
        });
        filterYearContainer.appendChild(lbl);
    });
}
// --- Global Mode Logic ---
// filterSubjectMulti and searchModeTools are already declared above


async function switchGlobalMode(mode) {
    globalMode = mode;
    globalPracticeMode = mode; // Keep both in sync
    
    // Update button UI
    if(modeBtnGeneral) modeBtnGeneral.className = mode === 'general' ? 'btn btn-primary active' : 'btn btn-secondary';
    if(modeBtnWrong) modeBtnWrong.className = mode === 'wrong' ? 'btn btn-primary active' : 'btn btn-secondary';
    if(modeBtnBookmark) modeBtnBookmark.className = mode === 'bookmark' ? 'btn btn-primary active' : 'btn btn-secondary';
    if(modeBtnSearch) modeBtnSearch.className = mode === 'search' ? 'btn btn-primary active' : 'btn btn-secondary';
    
    // Update Sidebar UI
    const multiWrapper = document.getElementById('filter-subject-multi-wrapper');
    const yearWrapper = document.getElementById('filter-year-wrapper');
    
    // Always hide dropdown contents when switching modes
    document.querySelectorAll('.filter-dropdown-content').forEach(el => el.style.display = 'none');

    if (mode === 'general') {
        filterSubject.style.display = 'block';
        if(multiWrapper) multiWrapper.style.display = 'none';
        if(searchModeTools) searchModeTools.style.display = 'none';
        // In general mode, the year wrapper doesn't apply (it's handled differently or hidden)
        // Wait, general mode used to show the year filter. Let's keep it visible if there's a subject.
        if(yearWrapper) yearWrapper.style.display = (filterSubject.value) ? 'block' : 'none';
    } else {
        filterSubject.style.display = 'none';
        if(multiWrapper) multiWrapper.style.display = 'block';
        if(searchModeTools) searchModeTools.style.display = (mode === 'search') ? 'flex' : 'none';
        if(yearWrapper) yearWrapper.style.display = 'block';
        if (mode === 'search') renderCustomTagsCheckboxes();
    }
    
    currentSubjectTitle.style.display = 'none';
    
    if (mode !== 'general') {
        await updateMultiYearCheckboxes();
    }

    if (mode === 'search') {
        filteredData = [];
        renderListView(); // Just render empty list, waiting for user to click Search
    } else {
        applyFilters();
    }
}

if (modeBtnGeneral) modeBtnGeneral.onclick = () => switchGlobalMode('general');
if (modeBtnWrong) modeBtnWrong.onclick = () => switchGlobalMode('wrong');
if (modeBtnBookmark) modeBtnBookmark.onclick = () => switchGlobalMode('bookmark');
if (modeBtnSearch) modeBtnSearch.onclick = () => switchGlobalMode('search');


// --- Search Mode Tools Logic ---
// Variables already declared above
const regexInput = document.getElementById('regex-search-input');
const btnBatchTag = document.getElementById('btn-batch-tag');

function loadRegexHistory() {
    if (!regexHistoryDropdown) return;
    const history = JSON.parse(localStorage.getItem('regexHistory') || '[]');
    regexHistoryDropdown.innerHTML = '';
    if (history.length === 0) {
        regexHistoryDropdown.innerHTML = '<div style="padding:8px 12px; color:var(--text-muted); font-size:13px;">無歷史紀錄</div>';
    } else {
        history.forEach((h, i) => {
            const div = document.createElement('div');
            div.className = 'dropdown-item';
            div.innerHTML = `<span>${h}</span><span class="del-btn">✖</span>`;
            div.querySelector('span').onclick = () => {
                if(regexInput) regexInput.value = h;
                regexHistoryDropdown.style.display = 'none';
                applyFilters();
            };
            div.querySelector('.del-btn').onclick = (e) => {
                e.stopPropagation();
                history.splice(i, 1);
                localStorage.setItem('regexHistory', JSON.stringify(history));
                loadRegexHistory();
            };
            regexHistoryDropdown.appendChild(div);
        });
    }
}

if (regexHistoryToggle) {
    regexHistoryToggle.onclick = (e) => {
        e.stopPropagation();
        loadRegexHistory();
        regexHistoryDropdown.style.display = regexHistoryDropdown.style.display === 'none' ? 'block' : 'none';
    };
    document.addEventListener('click', (e) => {
        if (regexHistoryDropdown && !regexHistoryDropdown.contains(e.target) && e.target !== regexHistoryToggle) {
            regexHistoryDropdown.style.display = 'none';
        }
    });
}

if (regexInput) {
    regexInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const val = regexInput.value.trim();
            if (val) {
                const history = JSON.parse(localStorage.getItem('regexHistory') || '[]');
                if (!history.includes(val)) {
                    history.unshift(val);
                    if (history.length > 20) history.pop();
                    localStorage.setItem('regexHistory', JSON.stringify(history));
                }
            }
            applyFilters();
        }
    });
}

const btnSearchExecute = document.getElementById('btn-search-execute');
if (btnSearchExecute) {
    btnSearchExecute.addEventListener('click', () => {
        const val = regexInput ? regexInput.value.trim() : '';
        if (val) {
            const history = JSON.parse(localStorage.getItem('regexHistory') || '[]');
            if (!history.includes(val)) {
                history.unshift(val);
                if (history.length > 20) history.pop();
                localStorage.setItem('regexHistory', JSON.stringify(history));
            }
        }
        applyFilters();
    });
}

if (btnBatchTag) {
    btnBatchTag.onclick = () => {
        const tag = batchTagInput.value.trim();
        if (!tag) { alert("請輸入標籤名稱"); return; }
        if (!currentActiveTopicData || currentActiveTopicData.length === 0) { alert("目前沒有可標記的題目"); return; }
        
        let count = 0;
        currentActiveTopicData.forEach(q => {
            const id = q.year + '_' + q.exam_id + '_' + q.no;
            const subStore = getSubStore(q);
            if (!subStore.customTags) subStore.customTags = {};
            if (!subStore.customTags[tag]) subStore.customTags[tag] = [];
            
            if (!subStore.customTags[tag].includes(id)) {
                subStore.customTags[tag].push(id);
                count++;
            }
        });
        
        saveProgress();
        batchTagInput.value = '';
        alert(`成功標記 ${count} 題為 [${tag}]！`);
        
        // Re-render custom tags in sidebar
        renderCustomTagsCheckboxes();
    };
}

// Dropdown Toggle Logic
function toggleDropdown(dropdownId) {
    const dropdown = document.getElementById(dropdownId);
    if (!dropdown) return;
    
    // Close other dropdowns first
    const allDropdowns = document.querySelectorAll('.filter-dropdown-content');
    allDropdowns.forEach(el => {
        if (el.id !== dropdownId) {
            el.style.display = 'none';
        }
    });

    // Toggle current
    if (dropdown.style.display === 'none' || !dropdown.style.display) {
        dropdown.style.display = 'flex';
        dropdown.style.flexDirection = 'column';
    } else {
        dropdown.style.display = 'none';
    }
}

// Close dropdowns when clicking outside
document.addEventListener('click', function(event) {
    const isClickInside = event.target.closest('.filter-dropdown-wrapper');
    if (!isClickInside) {
        const allDropdowns = document.querySelectorAll('.filter-dropdown-content');
        allDropdowns.forEach(el => {
            el.style.display = 'none';
        });
    }
});

// Override Answer Modal Logic
window.openOverrideModal = function(q, listIdx) {
    document.getElementById('modal-override-answer').style.display = 'flex';
    document.getElementById('override-orig-ans').textContent = q.answer;
    
    // Set up checkboxes
    const checkboxes = document.querySelectorAll('.override-chk');
    checkboxes.forEach(chk => {
        chk.checked = q.answer.includes(chk.value);
    });
    
    const subject = q.subject || currentActiveSubject;
    document.getElementById('override-subject').value = subject;
    document.getElementById('override-year').value = q.year;
    document.getElementById('override-exam-id').value = q.exam_id;
    document.getElementById('override-no').value = q.no;
    document.getElementById('override-list-idx').value = listIdx !== null ? listIdx : '';

    let rawText = (q.question || '').replace(/<[^>]*>/gm, '').trim();
    let searchText = '';
    const matches = rawText.match(/[\u4e00-\u9fff]+/g);
    if (matches && matches.length > 0) {
        searchText = matches.reduce((a, b) => a.length >= b.length ? a : b);
        if (searchText.length > 15) searchText = searchText.substring(0, 15);
    } else {
        searchText = rawText.substring(0, 12);
    }

    const examPdfUrl = `/pdfjs/web/viewer.html?file=${encodeURIComponent('/pdfs/'+subject+'/'+q.year+'.pdf')}#search=${encodeURIComponent(searchText)}&pagemode=none`;
    const ansPdfUrl = `/pdfjs/web/viewer.html?file=${encodeURIComponent('/answer_pdfs/'+subject+'/'+q.year+'.pdf')}#pagemode=none`;
    
    document.getElementById('iframe-override-exam').src = examPdfUrl;
    document.getElementById('iframe-override-ans').src = ansPdfUrl;
};

document.getElementById('btn-override-cancel').onclick = function() {
    document.getElementById('modal-override-answer').style.display = 'none';
    document.getElementById('iframe-override-exam').src = '';
    document.getElementById('iframe-override-ans').src = '';
};

document.getElementById('btn-override-confirm').onclick = function() {
    const checkboxes = document.querySelectorAll('.override-chk');
    const checkedValues = Array.from(checkboxes).filter(chk => chk.checked).map(chk => chk.value);
    
    if (checkedValues.length === 0) {
        alert("請至少選擇一個正確答案！");
        return;
    }
    
    const newAnswer = checkedValues.join('');
    
    const subject = document.getElementById('override-subject').value;
    const year = document.getElementById('override-year').value;
    const exam_id = parseInt(document.getElementById('override-exam-id').value);
    const no = parseInt(document.getElementById('override-no').value);
    const listIdxStr = document.getElementById('override-list-idx').value;
    
    const payload = {
        subject: subject,
        year: year,
        exam_id: exam_id,
        no: no,
        new_answer: newAnswer
    };
    
    fetch('/api/update_correct_answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            alert('標準答案已成功修正！\n\n(若稍後遇到畫面選項顏色異常，請按下 Ctrl+F5 強制重新整理以清除瀏覽器快取)');
            
            // 1. Find the question in current dataset and update its answer
            let targetQ = currentActiveTopicData[listIdxStr !== '' ? parseInt(listIdxStr) : currentIndex];
            
            if (targetQ) {
                targetQ.answer = newAnswer;
                
                // 2. Check if current answer matches the new correct answer
                const state = getAnswerState(targetQ);
                if (state) {
                    const isNowCorrect = newAnswer.includes(state.current_answer);
                    // Update is_fixed
                    state.is_fixed = isNowCorrect;
                    setAnswerState(targetQ, state);
                    if (listIdxStr !== '') {
                        answeredState[parseInt(listIdxStr)] = state;
                    } else {
                        answeredState[currentIndex] = state;
                    }
                    saveProgress();
                }
            }
            
            // 3. Close modal
            document.getElementById('btn-override-cancel').click();
            
            // 4. Re-render UI
            if (globalMode === 'list' || globalMode === 'wrong' || globalMode === 'bookmark' || globalMode === 'search') {
                renderListView();
            } else {
                renderCardView();
            }
            updateAccuracy();
        } else {
            alert('修正失敗：' + (data.message || '未知錯誤'));
        }
    })
    .catch(err => {
        console.error(err);
        alert('修正失敗，請檢查網路連線或伺服器狀態。');
    });
}

window.refreshAnkiCardWall = function() {
    const detailTopicDesc = document.getElementById('detail-topic-desc');
    if (!detailTopicDesc) return;
    
    const preBlocks = detailTopicDesc.querySelectorAll('pre');
    const allCardsData = [];
    const ankiWrappers = [];
    
    preBlocks.forEach((pre) => {
        const codeBlock = pre.querySelector('code.language-Anki') || pre.querySelector('code.language-anki');
        if (codeBlock) {
            const rawText = codeBlock.innerText || codeBlock.textContent;
            let wrapper = pre.closest('.code-block-wrapper');
            if (!wrapper) {
                wrapper = document.createElement('div');
                wrapper.className = 'code-block-wrapper';
                
                const btn = document.createElement('button');
                btn.className = 'copy-obsidian-btn';
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg> 複製'; 
                btn.title = '複製 Anki 題卡';
                btn.onclick = () => {
                    navigator.clipboard.writeText(rawText).then(() => {
                        const orig = btn.innerHTML;
                        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> 已複製';
                        setTimeout(() => { btn.innerHTML = orig; }, 2000);
                    });
                };
                
                pre.parentNode.insertBefore(wrapper, pre);
                wrapper.appendChild(pre);
                wrapper.appendChild(btn);
            }
            
            ankiWrappers.push(wrapper);
            
            const cardsData = rawText.split('\n').filter(line => line.trim() !== '');
            allCardsData.push(...cardsData);
        }
    });
    if (allCardsData.length === 0) {
        let wallOuter = document.getElementById('unified-anki-wall');
        if (wallOuter) wallOuter.remove();
        return;
    }
    
    let wallOuter = document.getElementById('unified-anki-wall');
    if (!wallOuter) {
        wallOuter = document.createElement('div');
        wallOuter.id = 'unified-anki-wall';
        wallOuter.style.marginTop = '30px';
        wallOuter.style.width = '100%';
        wallOuter.innerHTML = '<h3 style="margin-bottom:16px; color:var(--accent); font-size:1.2rem;">✨ 互動式卡片牆</h3>';
        
        // Placement
        const headings = Array.from(detailTopicDesc.querySelectorAll('h1, h2, h3, h4, h5, h6'));
        const aHeading = headings.find(h => h.textContent.toLowerCase().includes('anki'));
        
        if (aHeading) {
            aHeading.parentNode.insertBefore(wallOuter, aHeading);
            // We removed the toggle logic and simply use the heading as a marker.
            // If the heading is hidden by summaryText strip, this won't trigger, 
            // but we fallback to detailTopicDesc.appendChild below if not found.
            aHeading.style.display = 'none'; // hide it just in case
        } else {
            const noteContainer = document.getElementById('topic-note-container');
            if (noteContainer) {
                noteContainer.parentNode.insertBefore(wallOuter, noteContainer);
            } else {
                detailTopicDesc.appendChild(wallOuter);
            }
        }
    }
    
    // Hide all original Anki code blocks permanently as requested
    ankiWrappers.forEach(w => w.style.display = 'none');
    
    let wallContainer = wallOuter.querySelector('.anki-card-wrapper');
    if (wallContainer) wallContainer.remove();
    
    wallContainer = document.createElement('div');
    wallContainer.className = 'anki-card-wrapper';
    
    allCardsData.forEach(line => {
        let front = line;
        let back = '';
        
        let ansIndex = line.indexOf('<ans>');
        if (ansIndex === -1) ansIndex = line.indexOf('&lt;ans&gt;');
        
        if (ansIndex !== -1) {
            let sepIndex = ansIndex;
            if (line[ansIndex - 1] === ';' || line[ansIndex - 1] === '：' || line[ansIndex - 1] === ':' || line[ansIndex - 1] === ' ') {
                sepIndex = ansIndex - 1;
            }
            front = line.substring(0, sepIndex).trim();
            back = line.substring(ansIndex).trim();
        } else {
            const match = line.match(/[;；]/);
            if (match) {
                front = line.substring(0, match.index).trim();
                back = line.substring(match.index + 1).trim();
            }
        }
        
        if (front && back) {
            let mainAnswer = back;
            let explanation = '';
            
            const closeAnsIdx = back.indexOf('</ans>');
            const closeAnsHtmlIdx = back.indexOf('&lt;/ans&gt;');
            
            let splitIdx = -1;
            let splitLen = 0;
            if (closeAnsIdx !== -1) {
                splitIdx = closeAnsIdx;
                splitLen = 6;
            } else if (closeAnsHtmlIdx !== -1) {
                splitIdx = closeAnsHtmlIdx;
                splitLen = 12;
            }
            
            if (splitIdx !== -1) {
                mainAnswer = back.substring(0, splitIdx + splitLen);
                explanation = back.substring(splitIdx + splitLen).trim();
                explanation = explanation.replace(/^(<br\s*\/?>\s*)+/i, '');
            }

            const cardDiv = document.createElement('div');
            cardDiv.className = 'anki-card';
            
            cardDiv.onclick = function(e) { 
                const toggleBtn = e.target.closest('.answer-exp-toggle');
                if (toggleBtn) {
                    e.stopPropagation();
                    const content = cardDiv.querySelector('.answer-exp-content');
                    if (content) {
                        content.style.display = 'block';
                        toggleBtn.style.display = 'none';
                    }
                    return;
                }
                
                this.classList.toggle('flipped'); 
                
                if (!this.classList.contains('flipped')) {
                    const content = cardDiv.querySelector('.answer-exp-content');
                    const toggle = cardDiv.querySelector('.answer-exp-toggle');
                    if (content && toggle) {
                        content.style.display = 'none';
                        toggle.style.display = 'block';
                    }
                }
            };
            
            let explanationHtml = '';
            if (explanation) {
                explanationHtml = `
                    <div class="answer-exp-toggle" style="text-align:center; margin-top:8px; cursor:pointer; color:var(--text-muted);" title="展開說明">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    </div>
                    <div class="answer-exp-content" style="display:none; padding-top:12px; border-top:1px solid var(--glass-border); margin-top:8px;">
                        ${explanation}
                    </div>
                `;
            }

            cardDiv.innerHTML = `
                <div class="card-front">
                    <div class="question">${front}</div>
                </div>
                <div class="card-back">
                    <div class="question-small">${front}</div>
                    <hr class="card-divider">
                    <div class="answer">
                        <div class="answer-main">${mainAnswer}</div>
                        ${explanationHtml}
                    </div>
                </div>
            `;
            wallContainer.appendChild(cardDiv);
        }
    });
    

    wallOuter.appendChild(wallContainer);
};

// --- Card Practice Mode Keyboard Shortcuts ---
document.addEventListener('keydown', (e) => {
    // Only trigger in card mode
    if (typeof currentMode !== 'undefined' && currentMode !== 'card') return;
    const viewPractice = document.getElementById('view-practice');
    if (!viewPractice || viewPractice.style.display === 'none') return;
    
    const activeElem = document.activeElement;
    const activeTag = activeElem ? activeElem.tagName.toLowerCase() : '';
    const isTyping = activeTag === 'input' || activeTag === 'textarea' || (activeElem && activeElem.isContentEditable);
    
    if (isTyping) {
        if (e.key === 'Escape') {
            activeElem.blur();
        } else if (e.key.toLowerCase() === 's' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            const saveBtn = document.querySelector('#view-practice .btn-note-toggle');
            if (saveBtn) {
                const bookIcon = saveBtn.querySelector('svg[id^="icon-book-"]');
                if (bookIcon && bookIcon.style.display !== 'none') saveBtn.click();
            }
        }
        return;
    }

    if (e.key === 'ArrowLeft') {
        e.preventDefault();
        const btnPrev = document.getElementById('btn-prev');
        if (btnPrev && !btnPrev.disabled) btnPrev.click();
    } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        const btnNext = document.getElementById('btn-next');
        if (btnNext && !btnNext.disabled) btnNext.click();
    } else if (e.key === '1') {
        const options = document.querySelectorAll('#q-options .option');
        if (options[0]) options[0].click();
    } else if (e.key === '2') {
        const options = document.querySelectorAll('#q-options .option');
        if (options[1]) options[1].click();
    } else if (e.key === '3') {
        const options = document.querySelectorAll('#q-options .option');
        if (options[2]) options[2].click();
    } else if (e.key === '4') {
        const options = document.querySelectorAll('#q-options .option');
        if (options[3]) options[3].click();
    } else if (e.key === ' ') {
        e.preventDefault();
        const noteBtn = document.getElementById('btn-note');
        if (noteBtn) noteBtn.click();
    } else if (e.key.toLowerCase() === 'n') {
        e.preventDefault();
        const pencilBtn = document.querySelector('#view-practice .btn-note-toggle');
        if (pencilBtn) {
            const bookIcon = pencilBtn.querySelector('svg[id^="icon-book-"]');
            const isEditorOpen = bookIcon && bookIcon.style.display !== 'none';
            
            if (!isEditorOpen) {
                pencilBtn.click();
            }
            
            setTimeout(() => {
                const textareas = document.querySelectorAll('#view-practice textarea[id^="user-exp-"]');
                for (let ta of textareas) {
                    if (ta.parentElement && ta.parentElement.style.display !== 'none') {
                        ta.focus();
                        ta.selectionStart = ta.selectionEnd = ta.value.length;
                        break;
                    }
                }
            }, 50);
        }
    } else if (e.key.toLowerCase() === 't') {
        e.preventDefault();
        const tagInput = document.querySelector('#view-practice .manual-tag-input');
        if (tagInput) {
            tagInput.focus();
        }
    } else if (e.key === '0') {
        e.preventDefault();
        const pdfTag = document.querySelector('#q-tags .native-tag');
        if (pdfTag) pdfTag.click();
    } else if (e.key === '.') {
        e.preventDefault();
        const bookmarkBtn = document.getElementById('q-bookmark');
        if (bookmarkBtn) bookmarkBtn.click();
    }
});

