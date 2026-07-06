// ==========================================
// MT 國考刷題 - 極簡行動端重構版
// ==========================================

const SUBJECTS = [
    "臨床生理學與病理學",
    "臨床血液學與血庫學",
    "醫學分子檢驗學與臨床鏡檢學",
    "微生物學與臨床微生物學",
    "生物化學與臨床生化學",
    "臨床血清免疫學與臨床病毒學"
];

// --- 狀態管理 ---
let currentSubject = null; // 'all' 或 單一科目名稱
let currentTopic = null;
let filteredData = [];
let topicGroups = {};
let currentPracticeQuestions = [];
let currentQuestionIndex = 0;

// 將作答紀錄存在 localStorage
const STORAGE_KEY = 'mt_answers_v3';
let userAnswers = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};

function saveAnswer(qid, answer, isCorrect) {
    userAnswers[qid] = { answer, isCorrect };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(userAnswers));
}

// --- DOM 元素 ---
const viewHome = document.getElementById('view-home');
const viewTopicList = document.getElementById('view-topic-list');
const viewPractice = document.getElementById('view-practice');
const btnBack = document.getElementById('btn-back');

const bcHome = document.getElementById('bc-home');
const bcSepSub = document.getElementById('bc-sep-sub');
const bcSubject = document.getElementById('bc-subject');
const bcSepTopic = document.getElementById('bc-sep-topic');
const bcTopic = document.getElementById('bc-topic');
const listAccuracy = document.getElementById('list-accuracy');

// --- 初始化 ---
async function init() {
    renderHomeSubjectGrid();
    setupEventListeners();
    handleRoute(window.location.hash);
}

function renderHomeSubjectGrid() {
    const grid = document.getElementById('subject-grid');
    // 保留全科，加入其他單科
    SUBJECTS.forEach(sub => {
        const btn = document.createElement('button');
        btn.className = 'subject-card';
        btn.innerHTML = `<h2>📚 ${sub}</h2><p>針對單一科目進行地毯式複習</p>`;
        btn.onclick = () => navigateTo(`subject`, sub);
        grid.appendChild(btn);
    });

    document.querySelector('.all-subjects').onclick = () => navigateTo(`subject`, 'all');
}

function setupEventListeners() {
    window.addEventListener('popstate', () => handleRoute(window.location.hash));
    
    btnBack.onclick = () => window.history.back();
    bcHome.onclick = () => navigateTo('home');
    bcSubject.onclick = () => { if(currentSubject) navigateTo('subject', currentSubject); };

    // 排序按鈕
    document.querySelectorAll('.btn-sort').forEach(btn => {
        btn.onclick = (e) => {
            document.querySelectorAll('.btn-sort').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            const sortType = e.target.getAttribute('data-sort');
            renderTopicList(sortType);
        };
    });

    // 練習區導覽按鈕
    document.getElementById('btn-prev').onclick = () => {
        if (currentQuestionIndex > 0) {
            currentQuestionIndex--;
            renderQuestionCard();
        }
    };
    document.getElementById('btn-next').onclick = () => {
        if (currentQuestionIndex < currentPracticeQuestions.length - 1) {
            currentQuestionIndex++;
            renderQuestionCard();
        }
    };

    // 滑動手勢 (Swipe)
    let touchStartX = 0;
    let touchEndX = 0;
    const practiceArea = document.getElementById('question-card');
    
    practiceArea.addEventListener('touchstart', e => {
        touchStartX = e.changedTouches[0].screenX;
    }, {passive: true});

    practiceArea.addEventListener('touchend', e => {
        touchEndX = e.changedTouches[0].screenX;
        handleSwipe();
    }, {passive: true});

    function handleSwipe() {
        const swipeThreshold = 50;
        if (touchEndX < touchStartX - swipeThreshold) {
            // 左滑 -> 下一題
            document.getElementById('btn-next').click();
        }
        if (touchEndX > touchStartX + swipeThreshold) {
            // 右滑 -> 上一題
            document.getElementById('btn-prev').click();
        }
    }
}

// --- 路由管理 (History API) ---
function navigateTo(view, param = null) {
    let hash = '#';
    if (view === 'home') hash = '';
    else if (view === 'subject') hash = `#sub=${encodeURIComponent(param)}`;
    else if (view === 'practice') hash = `#sub=${encodeURIComponent(currentSubject)}&topic=${encodeURIComponent(param)}`;
    
    window.history.pushState({ view, param }, '', hash || window.location.pathname);
    handleRoute(hash);
}

async function handleRoute(hash) {
    hideAllViews();
    
    if (!hash || hash === '#' || hash === '#home') {
        currentSubject = null;
        currentTopic = null;
        updateHeaderUI('home');
        viewHome.classList.add('active');
        return;
    }

    const params = new URLSearchParams(hash.replace('#', ''));
    const sub = params.get('sub');
    const topic = params.get('topic');

    if (sub && !topic) {
        // Level 2: 選擇科目後，載入該科主題清單
        currentSubject = sub;
        currentTopic = null;
        updateHeaderUI('subject');
        viewTopicList.classList.add('active');
        document.getElementById('current-subject-title').textContent = sub === 'all' ? '🌟 全科綜合' : sub;
        document.getElementById('topic-list-container').innerHTML = '<div style="text-align:center; padding: 40px; color: var(--text-muted);">資料載入中...</div>';
        
        await loadSubjectData(sub);
        renderTopicList('cp');
    } 
    else if (sub && topic) {
        // Level 3: 進入特定主題練習
        currentSubject = sub;
        currentTopic = topic;
        updateHeaderUI('practice');
        viewPractice.classList.add('active');
        
        if (filteredData.length === 0) {
            await loadSubjectData(sub); // 處理直接貼網址進來的狀況
        }
        
        currentPracticeQuestions = topicGroups[topic] || [];
        currentQuestionIndex = 0;
        renderQuestionCard();
    }
}

function hideAllViews() {
    viewHome.classList.remove('active');
    viewTopicList.classList.remove('active');
    viewPractice.classList.remove('active');
}

function updateHeaderUI(level) {
    if (level === 'home') {
        btnBack.style.display = 'none';
        bcHome.classList.add('bc-active');
        bcSepSub.style.display = 'none';
        bcSubject.style.display = 'none';
        bcSepTopic.style.display = 'none';
        bcTopic.style.display = 'none';
        listAccuracy.style.display = 'none';
    } else if (level === 'subject') {
        btnBack.style.display = 'flex';
        bcHome.classList.remove('bc-active');
        bcSepSub.style.display = 'inline';
        bcSubject.style.display = 'inline';
        bcSubject.textContent = currentSubject === 'all' ? '全科綜合' : currentSubject;
        bcSubject.classList.add('bc-active');
        bcSepTopic.style.display = 'none';
        bcTopic.style.display = 'none';
        listAccuracy.style.display = 'none';
    } else if (level === 'practice') {
        btnBack.style.display = 'flex';
        bcHome.classList.remove('bc-active');
        bcSepSub.style.display = 'inline';
        bcSubject.style.display = 'inline';
        bcSubject.classList.remove('bc-active');
        bcSepTopic.style.display = 'inline';
        bcTopic.style.display = 'inline';
        bcTopic.textContent = currentTopic;
        listAccuracy.style.display = 'block';
    }
}

// --- 資料載入與計算 ---
async function loadSubjectData(sub) {
    let rawData = [];
    if (sub === 'all') {
        const promises = SUBJECTS.map(s => fetch(`./data_cache/${s}.json?v=${Date.now()}`).then(r => r.json()).catch(() => []));
        const results = await Promise.all(promises);
        results.forEach((data, idx) => {
            data.forEach(q => q.subject = SUBJECTS[idx]);
            rawData = rawData.concat(data);
        });
    } else {
        try {
            const res = await fetch(`./data_cache/${sub}.json?v=${Date.now()}`);
            rawData = await res.json();
            rawData.forEach(q => q.subject = sub);
        } catch(e) { console.error("Fetch failed", e); }
    }

    // 關鍵過濾：只保留 110 ~ 115 年的題目
    filteredData = rawData.filter(q => {
        const yearInt = parseInt(q.year.split('-')[0]);
        return yearInt >= 110 && yearInt <= 115;
    });

    document.getElementById('stat-total-q').textContent = `共 ${filteredData.length} 題`;

    // 分群與計算
    topicGroups = {};
    filteredData.forEach(q => {
        const t = q.topic || '未分類';
        if (!topicGroups[t]) topicGroups[t] = [];
        topicGroups[t].push(q);
    });
}

function calculateTopicStats() {
    const totalQuestions = filteredData.length;
    const stats = [];

    const difficultyMap = {
        '非常簡單': 4,
        '簡單': 3,
        '適中': 2,
        '困難': 1,
        '非常困難': 0.5
    };

    for (const [topicName, questions] of Object.entries(topicGroups)) {
        const count = questions.length;
        const proportion = count / totalQuestions;
        
        let diffSum = 0;
        let posSum = 0;
        let answeredCorrect = 0;
        let answeredTotal = 0;

        questions.forEach(q => {
            // 難易度
            let diffScore = 2; // default
            if (q.difficulty) {
                for (const [k, v] of Object.entries(difficultyMap)) {
                    if (q.difficulty.includes(k)) { diffScore = v; break; }
                }
            }
            diffSum += diffScore;

            // 落點 (通常一份考卷 80 題)
            posSum += (q.no || 40);

            // 紀錄
            const ans = userAnswers[q.qid];
            if (ans) {
                answeredTotal++;
                if (ans.isCorrect) answeredCorrect++;
            }
        });

        const avgDiff = diffSum / count;
        const avgPos = posSum / count;
        const cpValue = proportion * avgDiff * 1000; // 放大數值方便看
        const progressPct = count > 0 ? (answeredTotal / count * 100) : 0;

        stats.push({
            name: topicName,
            count,
            proportion: (proportion * 100).toFixed(1),
            avgPos,
            cpValue,
            progressPct
        });
    }

    return stats;
}

function renderTopicList(sortType) {
    let stats = calculateTopicStats();

    if (sortType === 'cp') {
        stats.sort((a, b) => b.cpValue - a.cpValue);
    } else if (sortType === 'freq') {
        stats.sort((a, b) => b.count - a.count);
    } else if (sortType === 'pos') {
        stats.sort((a, b) => a.avgPos - b.avgPos);
    }

    const container = document.getElementById('topic-list-container');
    container.innerHTML = '';

    stats.forEach((s, idx) => {
        const item = document.createElement('div');
        item.className = 'topic-item';
        
        let cpBadgeClass = s.cpValue > 50 ? 'style="background:rgba(16, 185, 129, 0.1); color:var(--accent); border-color:var(--accent);"' : '';
        if(idx < 3 && sortType === 'cp') {
            cpBadgeClass = 'style="background:var(--accent); color:#fff; border-color:var(--accent);"';
        }

        item.innerHTML = `
            <div class="topic-info">
                <div class="topic-title">${idx+1}. ${s.name}</div>
                <div class="topic-meta">
                    <span>題數：${s.count} (${s.proportion}%)</span>
                    <span>完成度：${s.progressPct.toFixed(0)}%</span>
                </div>
            </div>
            <div class="topic-badge" ${cpBadgeClass}>
                CP: ${s.cpValue.toFixed(1)}
            </div>
        `;
        item.onclick = () => navigateTo('practice', s.name);
        container.appendChild(item);
    });

    // 整體完成度
    const overallProgress = stats.reduce((acc, curr) => acc + (curr.count * (curr.progressPct/100)), 0) / filteredData.length * 100;
    document.getElementById('completion-meter-container').style.display = 'flex';
    document.getElementById('dashboard-progress-fill').style.width = `${overallProgress}%`;
    document.getElementById('dashboard-progress-text').textContent = `${overallProgress.toFixed(1)}%`;
}

// --- 卡片練習區 ---
function renderQuestionCard() {
    if (currentPracticeQuestions.length === 0) return;

    const q = currentPracticeQuestions[currentQuestionIndex];
    const card = document.getElementById('question-card');
    const optionsContainer = document.getElementById('q-options');
    const expPanel = document.getElementById('explanation-panel');
    const btnPrev = document.getElementById('btn-prev');
    const btnNext = document.getElementById('btn-next');

    // 重設狀態
    card.style.opacity = 0;
    card.style.transform = 'translateY(10px)';
    
    setTimeout(() => {
        document.getElementById('q-no').textContent = `Q ${currentQuestionIndex + 1} / ${currentPracticeQuestions.length}`;
        document.getElementById('q-tags').innerHTML = `<span class="badge" style="background:var(--bg-hover); color:var(--text-muted);">${q.year} - ${q.no}</span>`;
        
        // 渲染題目文字與圖片
        let htmlContent = safeHTML(q.question).replace(/^\s*\d+\.\s*/, '');
        if (q.images && q.images.length > 0) {
            htmlContent += `<div style="margin-top:16px;">`;
            q.images.forEach(imgSrc => {
                htmlContent += `<img src="${imgSrc}" style="max-width:100%; border-radius:8px; border:1px solid var(--border-color);" />`;
            });
            htmlContent += `</div>`;
        }
        document.getElementById('q-text').innerHTML = htmlContent;

        // 渲染選項
        optionsContainer.innerHTML = '';
        const letters = ['A', 'B', 'C', 'D'];
        const savedState = userAnswers[q.qid];

        q.choices.forEach((choiceText, i) => {
            const letter = letters[i];
            const div = document.createElement('div');
            div.className = 'option';
            
            let safeChoiceText = safeHTML(choiceText).replace(/^\s*\(?[A-D]\)?[\.\s]+/i, '');
            div.innerHTML = `<span class="option-letter">${letter}.</span> <span class="option-content">${safeChoiceText}</span>`;
            
            const isCorrectAnswer = q.answer.includes(letter);

            if (savedState) {
                // 已作答狀態
                if (savedState.answer === letter) {
                    div.classList.add(savedState.isCorrect ? 'correct' : 'wrong');
                } else if (isCorrectAnswer) {
                    div.classList.add('correct');
                }
            } else {
                // 未作答狀態
                div.onclick = () => {
                    const isCorrect = isCorrectAnswer;
                    saveAnswer(q.qid, letter, isCorrect);
                    renderQuestionCard(); // 重新渲染顯示答案
                };
            }

            optionsContainer.appendChild(div);
        });

        // 詳解區域
        if (savedState) {
            expPanel.style.display = 'block';
            let expHtml = '';
            if (q.key_concept) expHtml += `<div style="margin-bottom:12px; color:var(--text-main);"><strong>🤖 AI 提示：</strong>${q.key_concept}</div>`;
            if (q.explanation) {
                expHtml += `<div class="markdown-body" style="font-size:14px;">${safeMarkdown(q.explanation)}</div>`;
            } else {
                expHtml += `<div style="color:var(--text-muted); font-size:14px;">目前尚無詳細解析。</div>`;
            }
            document.getElementById('q-explanation').innerHTML = expHtml;
        } else {
            expPanel.style.display = 'none';
        }

        // 進度條與按鈕
        const progress = ((currentQuestionIndex + 1) / currentPracticeQuestions.length) * 100;
        document.getElementById('progress-fill').style.width = `${progress}%`;
        
        btnPrev.disabled = currentQuestionIndex === 0;
        btnNext.disabled = currentQuestionIndex === currentPracticeQuestions.length - 1;
        btnPrev.style.opacity = currentQuestionIndex === 0 ? '0.5' : '1';
        btnNext.style.opacity = currentQuestionIndex === currentPracticeQuestions.length - 1 ? '0.5' : '1';

        // 更新正確率
        updateAccuracy();

        // 動畫進場
        card.style.opacity = 1;
        card.style.transform = 'translateY(0)';
    }, 150);
}

function updateAccuracy() {
    let total = 0;
    let correct = 0;
    currentPracticeQuestions.forEach(q => {
        const ans = userAnswers[q.qid];
        if (ans) {
            total++;
            if (ans.isCorrect) correct++;
        }
    });

    if (total === 0) {
        listAccuracy.textContent = "正確率: --%";
    } else {
        const pct = Math.round((correct / total) * 100);
        listAccuracy.textContent = `🎯 ${pct}% (${correct}/${total})`;
    }
}

// --- Utility Functions ---
function safeHTML(str) {
    return str.replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

window.safeMarkdown = function(mdText) {
    if (!mdText) return '';
    let html = mdText;
    if (typeof window.marked !== 'undefined') {
        html = window.marked.parse(mdText);
    }
    if (typeof window.DOMPurify !== 'undefined') {
        html = window.DOMPurify.sanitize(html);
    }
    return html;
};

// 啟動
init();
