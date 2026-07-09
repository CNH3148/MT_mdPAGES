// ==========================================
// MT 國考刷題 - 極簡行動端重構版
// ==========================================

// 註冊 marked-katex-extension
if (typeof marked !== 'undefined' && typeof markedKatex !== 'undefined') {
    marked.use(markedKatex({ throwOnError: false, nonStandard: true }));
}

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
let aiTopicSummaries = {};
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
const viewTopicDetail = document.getElementById('view-topic-detail');
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
}

// --- 路由管理 (History API) ---
function navigateTo(view, param = null) {
    let hash = '#';
    if (view === 'home') hash = '';
    else if (view === 'subject') hash = `#sub=${encodeURIComponent(param)}`;
    else if (view === 'detail') hash = `#sub=${encodeURIComponent(currentSubject)}&topic=${encodeURIComponent(param)}`;
    else if (view === 'practice') hash = `#sub=${encodeURIComponent(currentSubject)}&topic=${encodeURIComponent(param)}&mode=practice`;
    
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
    const mode = params.get('mode');

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
    else if (sub && topic && mode !== 'practice') {
        // Level 3: 顯示主題詳細資料與卡片
        currentSubject = sub;
        currentTopic = topic;
        updateHeaderUI('detail');
        viewTopicDetail.classList.add('active');
        
        if (filteredData.length === 0) {
            await loadSubjectData(sub);
        }
        
        renderTopicDetail(topic);
    }
    else if (sub && topic && mode === 'practice') {
        // Level 4: 進入特定主題練習
        currentSubject = sub;
        currentTopic = topic;
        updateHeaderUI('practice');
        viewPractice.classList.add('active');
        
        if (filteredData.length === 0) {
            await loadSubjectData(sub);
        }
        
        currentPracticeQuestions = topicGroups[topic] || [];
        currentQuestionIndex = 0;
        renderQuestionCard();
    }
}

function hideAllViews() {
    viewHome.classList.remove('active');
    viewTopicList.classList.remove('active');
    viewTopicDetail.classList.remove('active');
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
    } else if (level === 'detail') {
        btnBack.style.display = 'flex';
        bcHome.classList.remove('bc-active');
        bcSepSub.style.display = 'inline';
        bcSubject.style.display = 'inline';
        bcSubject.classList.remove('bc-active');
        bcSepTopic.style.display = 'inline';
        bcTopic.style.display = 'inline';
        bcTopic.textContent = currentTopic;
        bcTopic.classList.add('bc-active');
        listAccuracy.style.display = 'none';
    } else if (level === 'practice') {
        btnBack.style.display = 'flex';
        bcHome.classList.remove('bc-active');
        bcSepSub.style.display = 'inline';
        bcSubject.style.display = 'inline';
        bcSubject.classList.remove('bc-active');
        bcSepTopic.style.display = 'inline';
        bcTopic.style.display = 'inline';
        bcTopic.textContent = currentTopic + " (練習)";
        bcTopic.classList.add('bc-active');
        listAccuracy.style.display = 'block';
    }
}

// --- 資料載入與計算 ---
async function loadSubjectData(sub) {
    let rawData = [];
    if (sub === 'all') {
        aiTopicSummaries = {}; // Reset summaries
        const promises = SUBJECTS.map(s => fetch(`./data_cache/${s}.json?v=${Date.now()}`).then(r => r.json()).catch(() => []));
        const sumPromises = SUBJECTS.map(s => fetch(`./data_cache/topics_${s}.json?v=${Date.now()}`).then(r => r.json()).catch(() => ({})));
        
        const results = await Promise.all(promises);
        const sumResults = await Promise.all(sumPromises);
        
        results.forEach((data, idx) => {
            data.forEach(q => q.subject = SUBJECTS[idx]);
            rawData = rawData.concat(data);
        });
        
        sumResults.forEach((sumData, idx) => {
            const subjectName = SUBJECTS[idx];
            for (const [topicName, summaryInfo] of Object.entries(sumData)) {
                aiTopicSummaries[subjectName + ' - ' + topicName] = summaryInfo;
            }
        });
    } else {
        try {
            const res = await fetch(`./data_cache/${sub}.json?v=${Date.now()}`);
            rawData = await res.json();
            rawData.forEach(q => q.subject = sub);
            
            const sumRes = await fetch(`./data_cache/topics_${sub}.json?v=${Date.now()}`);
            aiTopicSummaries = await sumRes.json();
        } catch(e) { 
            console.error("Fetch failed", e); 
            if (!aiTopicSummaries) aiTopicSummaries = {};
        }
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
        let t = q.topic || '未分類';
        if (sub === 'all') {
            t = q.subject + ' - ' + t;
        }
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

    let maxRawCp = 0;

    for (const [topicName, questions] of Object.entries(topicGroups)) {
        const count = questions.length;
        const proportion = count / totalQuestions;
        
        let diffSum = 0;
        let posSum = 0;
        let positions = [];

        questions.forEach(q => {
            let diffScore = 2; // default
            if (q.difficulty) {
                for (const [k, v] of Object.entries(difficultyMap)) {
                    if (q.difficulty.includes(k)) { diffScore = v; break; }
                }
            }
            diffSum += diffScore;
            
            const qno = parseInt(q.no) || 40;
            posSum += qno;
            positions.push(qno);
        });

        const avgDiff = diffSum / count;
        const avgPos = posSum / count;
        const rawCp = proportion * avgDiff;
        if (rawCp > maxRawCp) maxRawCp = rawCp;

        let diffText = '適中';
        if (avgDiff >= 3.5) diffText = '非常簡單';
        else if (avgDiff >= 2.5) diffText = '簡單';
        else if (avgDiff >= 1.5) diffText = '適中';
        else if (avgDiff >= 0.8) diffText = '困難';
        else diffText = '非常困難';

        stats.push({
            name: topicName,
            count,
            proportionPct: proportion * 100,
            avgPos,
            positions,
            rawCp,
            diffText
        });
    }

    // 標準化 CP 值 (0-100)
    stats.forEach(s => {
        s.cpValue = maxRawCp > 0 ? (s.rawCp / maxRawCp) * 100 : 0;
    });

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

    let cumulativeProportion = 0;

    stats.forEach((s, idx) => {
        cumulativeProportion += s.proportionPct;
        
        const item = document.createElement('div');
        item.className = 'topic-item';
        // 為了讓 heatmap 能正確排版，改為 flex-column
        item.style.flexDirection = 'column';
        item.style.alignItems = 'stretch';
        
        let cpBadgeClass = s.cpValue > 80 ? 'style="background:var(--accent); color:#fff; border-color:var(--accent);"' : 
                           s.cpValue > 50 ? 'style="background:rgba(16, 185, 129, 0.1); color:var(--accent); border-color:var(--accent);"' : '';

        // 熱圖 HTML
        let noCounts = {};
        s.positions.forEach(pos => {
            noCounts[pos] = (noCounts[pos] || 0) + 1;
        });
        let maxCount = Math.max(1, ...Object.values(noCounts));
        let heatmapBlocks = '';
        for(let i=1; i<=80; i++) {
            const c = noCounts[i] || 0;
            let bg = 'var(--bg-hover)';
            if (c > 0) {
                const alpha = Math.max(0.3, c / maxCount);
                bg = `rgba(239, 68, 68, ${alpha})`;
            }
            let borderRight = (i % 5 === 0) ? 'border-right: 1px solid rgba(128,128,128,0.2);' : '';
            heatmapBlocks += `<div style="flex:1; height:16px; background:${bg}; ${borderRight}" title="題號: ${i} (共 ${c} 題)"></div>`;
        }
        
        let axisHtml = '<div style="display:flex; width:100%; position:relative; height:15px; margin-top:2px;">';
        for(let i=10; i<=80; i+=10) {
            axisHtml += `<div style="position:absolute; left:${(i/80)*100}%; font-size:9px; color:var(--text-muted); transform:translateX(-50%);">${i}</div>`;
        }
        axisHtml += '</div>';

        let heatmapHtml = `
            <div style="margin-top:12px;">
                <div style="display:flex; width:100%; border-radius:2px; overflow:hidden; border: 1px solid var(--border-color);">
                    ${heatmapBlocks}
                </div>
                ${axisHtml}
            </div>
        `;

        item.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div class="topic-info">
                    <div class="topic-title">${idx+1}. ${s.name}</div>
                    <div class="topic-meta">
                        <span>題數：${s.count} (${s.proportionPct.toFixed(1)}%)</span>
                        <span>難度：${s.diffText}</span>
                        <span style="color:var(--primary);">累積佔比：${cumulativeProportion.toFixed(1)}%</span>
                    </div>
                </div>
                <div class="topic-badge" ${cpBadgeClass}>
                    CP: ${s.cpValue.toFixed(0)}
                </div>
            </div>
            ${heatmapHtml}
        `;
        item.onclick = () => navigateTo('detail', s.name);
        container.appendChild(item);
    });
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
            
            // 顯示難易度
            if (q.difficulty) {
                let diffColor = 'var(--text-muted)';
                if (q.difficulty.includes('簡單')) diffColor = '#10b981';
                else if (q.difficulty.includes('困難')) diffColor = '#ef4444';
                else diffColor = '#f59e0b';
                expHtml += `<div style="margin-bottom:8px; font-size:13px; color:${diffColor}; font-weight:600;">${q.difficulty}</div>`;
            }

            if (q.key_concept) expHtml += `<div style="margin-bottom:12px; color:var(--text-main);"><strong>🤖：</strong>${q.key_concept}</div>`;
            if (q.explanation) {
                expHtml += `<div><strong>🤓：</strong><br><div class="markdown-body" style="font-size:14px; margin-top:4px;">${safeMarkdown(q.explanation)}</div></div>`;
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
}

// --- Utility Functions ---
function safeHTML(str) {
    return str.replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

window.safeMarkdown = function(mdText) {
    if (!mdText) return '';
    let text = mdText;
    
    // 避免單一的 ~ 被 marked 誤認為刪除線
    text = text.replace(/(?<!~)~(?!~)/g, '\\~');

    let html = (typeof window.marked !== 'undefined') ? window.marked.parse(text) : text;
    return html;
};


// --- Topic Detail (Layer 3) ---
function renderTopicDetail(topicName) {
    document.getElementById('detail-topic-title').textContent = topicName;
    
    const detailTopicDesc = document.getElementById('detail-topic-desc');
    
    if (aiTopicSummaries[topicName]) {
        let summaryText = aiTopicSummaries[topicName]?.summary_markdown || "";
        
        // Strip out dataview blocks and some unnecessary headers
        summaryText = summaryText.replace(/```dataview[\s\S]*?```/gi, '');
        summaryText = summaryText.replace(/#+\s*包含題庫\s*$/gm, '');
        summaryText = summaryText.replace(/#+\s*Anki\s*聯想卡\s*$/gm, '');
        
        detailTopicDesc.innerHTML = `<div class="markdown-body">${safeMarkdown(summaryText)}</div>`;
        refreshAnkiCardWall();
    } else {
        detailTopicDesc.innerHTML = "<em>此類群暫無總結。</em>";
    }

    const btnStart = document.getElementById('btn-start-practice-top');
    if (btnStart) {
        btnStart.onclick = () => navigateTo('practice', topicName);
    }
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
                pre.parentNode.insertBefore(wrapper, pre);
                wrapper.appendChild(pre);
            }
            
            ankiWrappers.push(wrapper);
            
            const cardsData = rawText.split('\n').filter(line => line.trim() !== '');
            allCardsData.push(...cardsData);
        }
    });
    
    if (allCardsData.length === 0) return;
    
    let wallOuter = document.createElement('div');
    wallOuter.id = 'unified-anki-wall';
    wallOuter.style.marginTop = '20px';
    wallOuter.style.width = '100%';
    wallOuter.innerHTML = '<h3 style="margin-bottom:16px; color:var(--accent); font-size:1.1rem;">✨ 互動式卡片牆 (點擊翻轉)</h3>';
    
    detailTopicDesc.appendChild(wallOuter);
    
    // Hide all original Anki code blocks
    ankiWrappers.forEach(w => w.style.display = 'none');
    
    let wallContainer = document.createElement('div');
    wallContainer.className = 'anki-card-wrapper';
    
    allCardsData.forEach(line => {
        let front = line;
        let back = '';
        
        let ansIndex = line.indexOf('<ans>');
        if (ansIndex === -1) ansIndex = line.indexOf('&lt;ans&gt;');
        
        if (ansIndex !== -1) {
            let sepIndex = ansIndex;
            let ansLength = 5;
            if (line.substring(sepIndex, sepIndex + 11) === '&lt;ans&gt;') {
                ansLength = 11;
            }
            front = line.substring(0, sepIndex);
            
            let endAnsIndex = line.indexOf('</ans>', sepIndex);
            if (endAnsIndex === -1) endAnsIndex = line.indexOf('&lt;/ans&gt;', sepIndex);
            
            if (endAnsIndex !== -1) {
                let endAnsLength = 6;
                if (line.substring(endAnsIndex, endAnsIndex + 12) === '&lt;/ans&gt;') {
                    endAnsLength = 12;
                }
                back = line.substring(sepIndex + ansLength, endAnsIndex);
                let extra = line.substring(endAnsIndex + endAnsLength).trim();
                if (extra) {
                    extra = extra.replace(/^(<br\s*\/?>\s*)+/i, '');
                    let explanationHtml = `
                        <div class="answer-exp-toggle" style="text-align:center; margin-top:8px; cursor:pointer; color:var(--text-muted);" title="展開說明">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                        </div>
                        <div class="answer-exp-content" style="display:none; padding-top:12px; border-top:1px dashed var(--border-color); margin-top:8px; font-size:13px; color:var(--text-muted);">
                            ${extra}
                        </div>
                    `;
                    back += explanationHtml;
                }
            } else {
                back = line.substring(sepIndex + ansLength);
            }
        } else {
            let splitIndex = line.indexOf(';');
            if (splitIndex !== -1) {
                front = line.substring(0, splitIndex);
                back = line.substring(splitIndex + 1);
            } else {
                back = '（請翻面查看解答）';
            }
        }
        
        // Remove semicolon at the end of front if exists
        front = front.replace(/;$/, '').trim();
        
        const cardDiv = document.createElement('div');
        cardDiv.className = 'anki-card';
        cardDiv.innerHTML = `
            <div class="card-front">
                <div class="question">${front}</div>
            </div>
            <div class="card-back">
                <div class="question-small">${front}</div>
                <hr class="card-divider">
                <div class="answer">${back}</div>
            </div>
        `;
        
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
        
        wallContainer.appendChild(cardDiv);
    });
    
    wallOuter.appendChild(wallContainer);
}

// 啟動
init();

// 修正 iOS Safari 旋轉後不會自動重新排版的 Bug
window.addEventListener('orientationchange', function() {
    setTimeout(function() {
        var originalDisplay = document.body.style.display;
        document.body.style.display = 'none';
        document.body.offsetHeight; // 強制重繪
        document.body.style.display = originalDisplay;
        
        // 如果還是沒效，再觸發一次 resize
        window.dispatchEvent(new Event('resize'));
    }, 200);
});
