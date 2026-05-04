let token = localStorage.getItem("token");
let currentWs = null;
let currentTaskId = null;

window.onload = function () {
    checkAuthAndShow();
};

async function checkAuthAndShow() {
    const savedToken = localStorage.getItem("token");
    if (!savedToken) {
        showLogin();
        return;
    }
    try {
        const res = await fetch("/api/user/me", {
            headers: { token: savedToken }
        });
        if (!res.ok) {
            localStorage.removeItem("token");
            showLogin();
            return;
        }
        token = savedToken;
        showMain();
    } catch (e) {
        localStorage.removeItem("token");
        showLogin();
    }
}

function showLogin() {
    document.getElementById("loginPage").style.display = "flex";
    document.getElementById("mainPage").style.display = "none";
}

function showMain() {
    document.getElementById("loginPage").style.display = "none";
    document.getElementById("mainPage").style.display = "block";
}

function switchTab(tabName) {
    const savedToken = localStorage.getItem("token");
    if (!savedToken) {
        showLogin();
        return;
    }
    
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        if (item.getAttribute('data-tab') === tabName) {
            item.classList.add('active');
        }
    });

    document.querySelectorAll('.content-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    document.getElementById(`tab-${tabName}`).classList.add('active');

    if (tabName === 'memory') {
        loadMemoryStats();
        loadMemories();
    } else if (tabName === 'monitor') {
        loadMonitorStats();
    } else if (tabName === 'eval') {
        loadEvalStats();
    }
}

async function login() {
    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;

    try {
        const res = await fetch("/api/user/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        });

        const data = await res.json();
        if (data.token) {
            token = data.token;
            localStorage.setItem("token", token);
            showMain();
            switchTab('task');
        } else {
            alert("登录失败：" + (data.msg || "密码错误"));
        }
    } catch (e) {
        alert("请求失败：" + e.message);
    }
}

async function runTask() {
    const task = document.getElementById("taskInput").value.trim();
    if (!task) return alert("请输入任务内容！");

    const logEl = document.getElementById("log");
    const reportEl = document.getElementById("reportArea");
    const statusEl = document.getElementById("statusIndicator");

    logEl.innerHTML = '';
    reportEl.innerHTML = '';
    statusEl.className = 'status-tag running';
    statusEl.innerHTML = '<span class="status-dot"></span>执行中';

    appendLog(logEl, 'info', '🚀 任务已提交，正在连接...');

    try {
        const res = await fetch("/api/agent/run-stream", {
            method: "POST",
            headers: { 
                "Content-Type": "application/json",
                token: token
            },
            body: JSON.stringify({ task, user_id: "default" })
        });

        const data = await res.json();
        if (data.code !== 200) {
            throw new Error(data.msg || '启动任务失败');
        }

        const { task_id, websocket_url } = data.data;
        currentTaskId = task_id;

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}${websocket_url}`;

        currentWs = new WebSocket(wsUrl);

        currentWs.onopen = () => {
            appendLog(logEl, 'info', '✅ WebSocket连接已建立');
        };

        currentWs.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            handleWebSocketMessage(msg, logEl, reportEl, statusEl);
        };

        currentWs.onerror = (error) => {
            appendLog(logEl, 'error', '❌ WebSocket连接错误');
            statusEl.className = 'status-tag';
            statusEl.innerHTML = '<span class="status-dot"></span>失败';
        };

        currentWs.onclose = () => {
            if (statusEl.className.includes('running')) {
                appendLog(logEl, 'info', '📡 连接已关闭');
            }
        };

    } catch (e) {
        logEl.innerHTML = `<span style="color:#cc0000">❌ 请求失败：${e.message}</span>`;
        statusEl.innerHTML = '<span class="status-dot"></span>失败';
    }
}

function handleWebSocketMessage(msg, logEl, reportEl, statusEl) {
    const data = msg.data || {};
    const content = data.content || '';
    
    switch (msg.type) {
        case 'connected':
            appendLog(logEl, 'info', '✅ ' + msg.message);
            break;
        
        case 'thinking':
            const agentName = getAgentDisplayName(msg.agent);
            if (data.streaming) {
                appendStreamingLog(logEl, msg.agent, content);
            } else {
                appendLog(logEl, 'thinking', `${agentName}: ${content}`);
            }
            break;
        
        case 'agent_start':
            appendLog(logEl, 'agent-start', `🤖 ${data.role || msg.agent} 开始工作`);
            appendLog(logEl, 'thinking', `${data.role || msg.agent}: ${data.content}`);
            break;
        
        case 'agent_end':
            appendLog(logEl, 'agent-end', `✅ ${data.role || msg.agent} 思考完成`);
            break;
        
        case 'complete':
            reportEl.innerText = data.result || data.content || "任务完成";
            statusEl.className = 'status-tag done';
            statusEl.innerHTML = '<span class="status-dot"></span>已完成';
            appendLog(logEl, 'complete', '🎉 任务执行完成！');
            currentWs = null;
            break;
        
        case 'rag_eval':
            displayRagEval(data.eval_result);
            appendLog(logEl, 'eval', `📊 RAG评估完成，总分: ${data.eval_result?.overall_score || 'N/A'}`);
            break;
        
        case 'error':
            appendLog(logEl, 'error', '❌ 错误: ' + (data.error || msg.error || content));
            statusEl.className = 'status-tag';
            statusEl.innerHTML = '<span class="status-dot"></span>失败';
            currentWs = null;
            break;
        
        default:
            if (content) {
                appendLog(logEl, 'log', content);
            }
    }
    
    logEl.scrollTop = logEl.scrollHeight;
}

function displayRagEval(evalResult) {
    if (!evalResult || !evalResult.scores) return;
    let evalDiv = document.getElementById('ragEvalResult');
    if (!evalDiv) {
        evalDiv = document.createElement('div');
        evalDiv.id = 'ragEvalResult';
        evalDiv.className = 'rag-eval-panel';
        const resultPanel = document.querySelector('.result-panel');
        if (resultPanel) {
            resultPanel.insertBefore(evalDiv, document.getElementById('reportArea'));
        }
    }
    const scores = evalResult.scores;
    const overallScore = (evalResult.overall_score || 0) * 100;
    const accuracy = ((scores.accuracy || 0) * 100).toFixed(0);
    const completeness = ((scores.completeness || 0) * 100).toFixed(0);
    const groundedness = ((scores.groundedness || 0) * 100).toFixed(0);
    const helpfulness = ((scores.helpfulness || 0) * 100).toFixed(0);
    
    evalDiv.innerHTML = `
        <div class="panel-title">
            <i class="fa-solid fa-chart-line"></i>
            RAG实时评估
            <span class="eval-overall-score">${overallScore.toFixed(1)}%</span>
        </div>
        <div class="eval-scores">
            <div class="eval-score-item">
                <span class="eval-label">准确性</span>
                <div class="eval-bar-track">
                    <div class="eval-bar-fill" style="width: ${accuracy}%"></div>
                </div>
                <span class="eval-value">${accuracy}%</span>
            </div>
            <div class="eval-score-item">
                <span class="eval-label">完整性</span>
                <div class="eval-bar-track">
                    <div class="eval-bar-fill" style="width: ${completeness}%"></div>
                </div>
                <span class="eval-value">${completeness}%</span>
            </div>
            <div class="eval-score-item">
                <span class="eval-label">有据性</span>
                <div class="eval-bar-track">
                    <div class="eval-bar-fill" style="width: ${groundedness}%"></div>
                </div>
                <span class="eval-value">${groundedness}%</span>
            </div>
            <div class="eval-score-item">
                <span class="eval-label">帮助性</span>
                <div class="eval-bar-track">
                    <div class="eval-bar-fill" style="width: ${helpfulness}%"></div>
                </div>
                <span class="eval-value">${helpfulness}%</span>
            </div>
        </div>
    `;
}

function getAgentDisplayName(agent) {
    const names = {
        'researcher': '🔍 需求分析师',
        'executor': '⚙️ 执行者',
        'validator': '🧪 校验师',
        'manager': '📋 汇总师',
        'memory': '💾 记忆系统',
        'system': '📌 系统'
    };
    return names[agent] || agent || '🤖';
}

const streamingContainers = {};

function appendStreamingLog(container, agent, content) {
    const agentId = agent || 'default';
    
    if (!streamingContainers[agentId]) {
        const wrapper = document.createElement('div');
        wrapper.className = `streaming-wrapper streaming-${agentId}`;
        wrapper.innerHTML = `
            <div class="streaming-header">
                <span class="agent-badge ${agentId}">${getAgentDisplayName(agentId)}</span>
                <span class="streaming-indicator">思考中...</span>
            </div>
            <div class="streaming-content"></div>
        `;
        container.appendChild(wrapper);
        streamingContainers[agentId] = wrapper;
    }
    
    const wrapper = streamingContainers[agentId];
    const contentDiv = wrapper.querySelector('.streaming-content');
    
    contentDiv.textContent += content;
    
    wrapper.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function clearStreamingContainers() {
    for (const key in streamingContainers) {
        delete streamingContainers[key];
    }
}

function appendLog(container, type, content) {
    const div = document.createElement('div');
    div.className = `log-item log-${type}`;

    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    div.innerHTML = `<span class="log-time">${time}</span> ${content}`;

    container.appendChild(div);
}

function clearAll() {
    if (currentWs) {
        currentWs.close();
        currentWs = null;
    }
    currentTaskId = null;
    clearStreamingContainers();
    document.getElementById("taskInput").value = "";
    document.getElementById("log").innerHTML = "";
    document.getElementById("reportArea").innerHTML = "";
    document.getElementById("statusIndicator").innerHTML = '<span class="status-dot"></span>等待中';
}

async function loadMemoryStats() {
    try {
        const res = await fetch("/api/memory/stats/default", {
            headers: { token: token }
        });
        if (res.status === 401) {
            localStorage.removeItem("token");
            token = null;
            showLogin();
            return;
        }
        const data = await res.json();
        if (data.data) {
            document.getElementById("statUserTotal").textContent = data.data.user_total || 0;
            document.getElementById("statTask").textContent = data.data.by_type?.task || 0;
            document.getElementById("statKnowledge").textContent = data.data.knowledge_total || 0;
        }
    } catch (e) {
        console.error(e);
    }
}

async function addMemory() {
    const content = document.getElementById("memoryContent").value.trim();
    const memoryType = document.getElementById("memoryType").value;

    if (!content) return alert("请输入记忆内容！");

    try {
        const res = await fetch("/api/memory/add", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                token: token
            },
            body: JSON.stringify({
                user_id: "default",
                content: content,
                memory_type: memoryType
            })
        });

        const data = await res.json();
        if (data.code === 200) {
            alert("记忆保存成功！");
            document.getElementById("memoryContent").value = "";
            loadMemoryStats();
            loadMemories();
        } else {
            alert("保存失败");
        }
    } catch (e) {
        alert("请求失败：" + e.message);
    }
}

async function searchMemories() {
    const query = document.getElementById("searchQuery").value.trim();
    if (!query) return alert("请输入搜索内容！");

    const resultsEl = document.getElementById("searchResults");
    resultsEl.innerHTML = '<div class="memory-item"><p>搜索中...</p></div>';

    try {
        const res = await fetch("/api/memory/search", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                token: token
            },
            body: JSON.stringify({
                user_id: "default",
                query: query,
                top_k: 10
            })
        });

        const data = await res.json();
        if (data.data && data.data.length > 0) {
            let html = '';
            data.data.forEach(m => {
                const score = (m.similarity * 100).toFixed(0);
                const type = m.metadata?.memory_type || 'general';
                const icons = {
                    'task': 'fa-list-check',
                    'knowledge': 'fa-book',
                    'preference': 'fa-heart',
                    'general': 'fa-note-sticky'
                };
                html += `
                    <div class="memory-item">
                        <div class="memory-thumbnail ${type}">
                            <i class="fa-solid ${icons[type] || 'fa-note-sticky'}"></i>
                            <span class="memory-score-badge">${score}%</span>
                        </div>
                        <div class="memory-card-body">
                            <div class="memory-item-header">
                                <span class="memory-badge ${type}">${type}</span>
                                <span class="memory-score">${score}% 相似</span>
                            </div>
                            <div class="memory-content-text">${m.content}</div>
                        </div>
                    </div>
                `;
            });
            resultsEl.innerHTML = html;
        } else {
            resultsEl.innerHTML = '<div class="empty-state"><i class="fa-solid fa-search"></i><p style="color:#8a8a8a">没有找到相关记忆</p></div>';
        }
    } catch (e) {
        resultsEl.innerHTML = `<div class="memory-item"><p style="color:#cc0000">搜索失败：${e.message}</p></div>`;
    }
}

let memoryPagination = {
    page: 1,
    limit: 10,
    total: 0
};

async function loadMemories() {
    const listEl = document.getElementById("memoryList");
    listEl.innerHTML = '<div class="memory-item"><p>加载中...</p></div>';

    const offset = (memoryPagination.page - 1) * memoryPagination.limit;

    try {
        const res = await fetch(`/api/memory/list/default?limit=${memoryPagination.limit}&offset=${offset}`, {
            headers: { token: token }
        });

        if (res.status === 401) {
            localStorage.removeItem("token");
            token = null;
            showLogin();
            return;
        }

        const data = await res.json();
        memoryPagination.total = data.total || 0;
        
        if (data.data && data.data.length > 0) {
            let html = '';
            data.data.forEach(m => {
                const time = m.metadata?.created_at ? new Date(m.metadata.created_at).toLocaleString() : '';
                const type = m.metadata?.memory_type || 'general';
                const icons = {
                    'task': 'fa-list-check',
                    'knowledge': 'fa-book',
                    'preference': 'fa-heart',
                    'general': 'fa-note-sticky',
                    'question': 'fa-circle-question',
                    'conversation': 'fa-comments'
                };
                html += `
                    <div class="memory-item">
                        <div class="memory-checkbox-wrap">
                            <input type="checkbox" class="memory-checkbox" value="${m.id}">
                        </div>
                        <div class="memory-thumbnail ${type}">
                            <i class="fa-solid ${icons[type] || 'fa-note-sticky'}"></i>
                        </div>
                        <div class="memory-card-body">
                            <div class="memory-item-header">
                                <span class="memory-badge ${type}">${type === 'question' ? '问答' : type === 'conversation' ? '对话' : type}</span>
                                <span class="memory-time">${time}</span>
                            </div>
                            <div class="memory-content-text">${m.content}</div>
                            <div class="memory-meta">
                                <span><i class="fa-regular fa-clock"></i> ${time}</span>
                                <button class="btn-delete" onclick="event.stopPropagation(); deleteMemory('${m.id}')">
                                    <i class="fa-solid fa-trash"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            });
            listEl.innerHTML = html;
        } else {
            listEl.innerHTML = '<div class="empty-state"><i class="fa-solid fa-brain"></i><p style="color:#8a8a8a">暂无记忆</p></div>';
        }

        updatePagination();
    } catch (e) {
        listEl.innerHTML = `<div class="memory-item"><p style="color:#cc0000">加载失败：${e.message}</p></div>`;
    }
}

async function deleteMemory(memoryId) {
    if (!confirm("确定删除这条记忆？")) return;

    try {
        const res = await fetch("/api/memory/delete", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                token: token
            },
            body: JSON.stringify({ memory_id: memoryId })
        });

        if (res.ok) {
            loadMemoryStats();
            loadMemories();
        }
    } catch (e) {
        alert("删除失败：" + e.message);
    }
}

function updatePagination() {
    const totalPages = Math.max(1, Math.ceil(memoryPagination.total / memoryPagination.limit));
    document.getElementById("currentPage").textContent = memoryPagination.page;
    document.getElementById("totalPages").textContent = totalPages;
    
    document.getElementById("prevPage").disabled = memoryPagination.page <= 1;
    document.getElementById("nextPage").disabled = memoryPagination.page >= totalPages;
}

function changePage(delta) {
    const totalPages = Math.max(1, Math.ceil(memoryPagination.total / memoryPagination.limit));
    const newPage = memoryPagination.page + delta;
    
    if (newPage >= 1 && newPage <= totalPages) {
        memoryPagination.page = newPage;
        loadMemories();
    }
}

let uploadWs = null;

async function uploadKbFile() {
    const fileInput = document.getElementById("kbFileInput");
    const file = fileInput.files[0];

    if (!file) return;

    const statusEl = document.getElementById("uploadStatus");
    const progressEl = document.getElementById("uploadProgress");
    const progressFill = document.getElementById("progressFill");
    const progressText = document.getElementById("progressText");

    const filename = file.name;
    const extension = filename.split('.').pop().toLowerCase();
    if (!['txt', 'pdf', 'docx'].includes(extension)) {
        statusEl.innerHTML = `<p style="color:#cc0000">❌ 不支持的文件格式</p>`;
        return;
    }

    statusEl.innerHTML = `<p style="color:#ff9500">正在连接...</p>`;
    document.getElementById("uploadProgress").style.display = 'block';
    document.getElementById("progressFill").style.width = '0%';
    document.getElementById("progressText").textContent = '0%';

    try {
        const startRes = await fetch("/api/upload-start", {
            method: "POST",
            headers: { 
                "Content-Type": "application/json",
                token: token
            },
            body: JSON.stringify({
                filename: filename,
                user_id: "default",
                memory_type: "knowledge"
            })
        });
        
        if (startRes.status === 401) {
            localStorage.removeItem("token");
            token = null;
            showLogin();
            return;
        }
        
        if (!startRes.ok) {
            const errorText = await startRes.text();
            statusEl.innerHTML = `<p style="color:#cc0000">❌ 请求失败: ${startRes.status}</p>`;
            progressEl.style.display = 'none';
            return;
        }
        
        const startData = await startRes.json();
        
        if (!startData.data || !startData.data.upload_id) {
            statusEl.innerHTML = `<p style="color:#cc0000">❌ 响应格式错误</p>`;
            progressEl.style.display = 'none';
            return;
        }
        
        const uploadId = startData.data.upload_id;
        const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${startData.data.websocket_url}`;
        
        uploadWs = new WebSocket(wsUrl);
        
        uploadWs.onopen = async () => {
            statusEl.innerHTML = `<p style="color:#ff9500">正在上传文件...</p>`;
            
            const formData = new FormData();
            formData.append("upload_id", uploadId);
            formData.append("file", file);
            formData.append("user_id", "default");
            formData.append("memory_type", "knowledge");
            
            const uploadRes = await fetch("/api/upload-file", {
                method: "POST",
                headers: { token: token },
                body: formData
            });
            
            if (uploadRes.status === 401) {
                localStorage.removeItem("token");
                token = null;
                showLogin();
                return;
            }
        };
        
        uploadWs.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            console.log('WebSocket收到:', msg);
            
            const statusEl = document.getElementById("uploadStatus");
            const progressEl = document.getElementById("uploadProgress");
            const fill = document.getElementById("progressFill");
            const text = document.getElementById("progressText");
            
            if (msg.type === 'connected') {
                statusEl.innerHTML = `<p style="color:#ff9500">连接成功，正在上传...</p>`;
                progressEl.style.display = 'block';
            } else if (msg.type === 'upload_status') {
                fill.style.width = msg.progress + '%';
                text.textContent = msg.message + ` (${msg.progress}%)`;
                statusEl.innerHTML = `<p style="color:#ff9500">${msg.message}</p>`;
            } else if (msg.type === 'upload_progress') {
                fill.style.width = msg.progress + '%';
                text.textContent = `处理中 ${msg.progress}% (${msg.chunk_index + 1}/${msg.total_chunks})`;
                statusEl.innerHTML = `<p style="color:#ff9500">处理中 ${msg.progress}%</p>`;
            } else if (msg.type === 'upload_complete') {
                fill.style.width = '100%';
                fill.style.background = '#2ba640';
                text.textContent = '完成 (100%)';
                statusEl.innerHTML = `<p style="color:#2ba640">✅ 上传成功！已提取 ${msg.chunks} 个知识片段</p>`;
                fileInput.value = "";
                setTimeout(() => {
                    progressEl.style.display = 'none';
                    fill.style.width = '0%';
                    fill.style.background = '';
                    loadMemoryStats();
                    loadMemories();
                }, 2000);
                uploadWs.close();
                uploadWs = null;
            } else if (msg.type === 'upload_error') {
                statusEl.innerHTML = `<p style="color:#cc0000">❌ 错误: ${msg.error}</p>`;
                if (uploadWs) {
                    uploadWs.close();
                    uploadWs = null;
                }
            }
        };
        
        uploadWs.onerror = () => {
            statusEl.innerHTML = `<p style="color:#cc0000">❌ WebSocket连接错误</p>`;
            progressEl.style.display = 'none';
        };
        
    } catch (e) {
        statusEl.innerHTML = `<p style="color:#cc0000">❌ 请求失败: ${e.message}</p>`;
        progressEl.style.display = 'none';
    }
}

let monitorInterval = null;

async function loadMonitorStats() {
    if (!token) {
        showLogin();
        return;
    }
    const loadStats = async () => {
        try {
            const res = await fetch("/api/monitor/metrics", {
                headers: { token: token }
            });
            if (res.status === 401) {
                localStorage.removeItem("token");
                token = null;
                showLogin();
                return;
            }
            const data = await res.json();

            const taskTotal = data.task_counts?.task || 0;
            const taskSuccess = data.task_counts?.success || 0;
            const taskFailed = data.task_counts?.error || 0;
            const avgDuration = data.task_avg_duration_task || 0;

            document.getElementById("monTaskTotal").textContent = taskTotal;
            document.getElementById("monTaskSuccess").textContent = taskSuccess;
            document.getElementById("monTaskFailed").textContent = taskFailed;
            document.getElementById("monAvgDuration").textContent = avgDuration.toFixed(1) + 's';

            document.getElementById("monConcurrent").textContent = data.concurrent_tasks || 0;
            document.getElementById("monSessions").textContent = data.active_sessions || 0;

            const agentStatsEl = document.getElementById("agentStats");
            if (agentStatsEl && data.agent_counts) {
                let html = '<div class="chart-bars">';
                for (const [agent, count] of Object.entries(data.agent_counts)) {
                    const avgDur = data[`agent_avg_duration_${agent}`] || 0;
                    html += `
                        <div class="chart-bar-item">
                            <div class="chart-bar-label">${agent}</div>
                            <div class="chart-bar-track">
                                <div class="chart-bar-fill" style="width: ${Math.min(count * 5, 100)}%"></div>
                            </div>
                            <div class="chart-bar-value">${count} (${avgDur.toFixed(1)}s)</div>
                        </div>
                    `;
                }
                html += '</div>';
                agentStatsEl.innerHTML = html;
            }
        } catch (e) {
            console.error("Load monitor stats failed:", e);
        }
    };

    const loadSystemStats = async () => {
        try {
            const res = await fetch("/api/monitor/status");
            const data = await res.json();
            document.getElementById("monCpu").textContent = (data.cpu || 0).toFixed(0) + '%';
            document.getElementById("monMemory").textContent = (data.memory || 0).toFixed(0) + '%';
        } catch (e) {
            console.error("Load system stats failed:", e);
        }
    };

    await loadStats();
    await loadSystemStats();

    if (monitorInterval) clearInterval(monitorInterval);
    monitorInterval = setInterval(async () => {
        await loadStats();
        await loadSystemStats();
    }, 5000);
}

function unloadMonitor() {
    if (monitorInterval) {
        clearInterval(monitorInterval);
        monitorInterval = null;
    }
}

let evalInterval = null;

async function loadEvalStats() {
    if (!token) {
        showLogin();
        return;
    }
    const loadRagEval = async () => {
        try {
            const res = await fetch("/api/eval/rag?top_k=5", {
                headers: { token: token }
            });
            if (res.status === 401) {
                localStorage.removeItem("token");
                token = null;
                showLogin();
                return;
            }
            const data = await res.json();
            
            const d = data.data || {};
            document.getElementById("evalTotalCases").textContent = d.total_cases || 0;
            document.getElementById("evalRecall").textContent = ((d.avg_recall || 0) * 100).toFixed(1) + '%';
            document.getElementById("evalPrecision").textContent = ((d.avg_precision || 0) * 100).toFixed(1) + '%';
            document.getElementById("evalMRR").textContent = ((d.avg_mrr || 0) * 100).toFixed(1) + '%';
            document.getElementById("evalExplicitAcc").textContent = ((d.explicit_accuracy || 0) * 100).toFixed(1) + '%';
            document.getElementById("evalImplicitAcc").textContent = ((d.implicit_accuracy || 0) * 100).toFixed(1) + '%';
            document.getElementById("evalLatency").textContent = (d.avg_latency_ms || 0).toFixed(0) + 'ms';
            document.getElementById("evalFeedbacks").textContent = d.total_feedbacks || 0;
            
            const byCategory = d.by_category || {};
            const catHtml = Object.entries(byCategory).map(([cat, v]) => `
                <div class="chart-bar-item">
                    <div class="chart-bar-label">${cat}</div>
                    <div class="chart-bar-track">
                        <div class="chart-bar-fill" style="width: ${(v.avg_recall || 0) * 100}%"></div>
                    </div>
                    <div class="chart-bar-value">${((v.avg_recall || 0) * 100).toFixed(1)}%</div>
                </div>
            `).join('');
            document.getElementById("evalByCategory").innerHTML = '<div class="chart-bars">' + catHtml + '</div>';
            
            const byDifficulty = d.by_difficulty || {};
            const diffHtml = Object.entries(byDifficulty).map(([diff, v]) => `
                <div class="chart-bar-item">
                    <div class="chart-bar-label">${diff}</div>
                    <div class="chart-bar-track">
                        <div class="chart-bar-fill" style="width: ${(v.avg_recall || 0) * 100}%"></div>
                    </div>
                    <div class="chart-bar-value">${((v.avg_recall || 0) * 100).toFixed(1)}%</div>
                </div>
            `).join('');
            document.getElementById("evalByDifficulty").innerHTML = '<div class="chart-bars">' + diffHtml + '</div>';
            
        } catch (e) {
            console.error("Load eval stats failed:", e);
        }
    };
    
    const loadFeedbackStats = async () => {
        try {
            const res = await fetch("/api/eval/feedback/stats", {
                headers: { token: token }
            });
            const data = await res.json();
            
            const d = data.data || {};
            const trends = d.trends || [];
            const trendsHtml = trends.map(t => `
                <div class="trend-item">
                    <div class="trend-date">${t.date}</div>
                    <div class="trend-explicit" data-tooltip="用户主动点击👍/👎反馈的准确率">
                        <i class="fa-solid fa-circle-info trend-info-icon"></i>
                        显式:${((t.explicit_accuracy || 0) * 100).toFixed(1)}%
                    </div>
                    <div class="trend-implicit" data-tooltip="系统根据评分阈值自动判断的准确率">
                        <i class="fa-solid fa-circle-info trend-info-icon"></i>
                        隐式:${((t.implicit_accuracy || 0) * 100).toFixed(1)}%
                    </div>
                </div>
            `).join('');
            document.getElementById("evalTrends").innerHTML = trendsHtml || '<div class="empty-text">暂无趋势数据</div>';
            
        } catch (e) {
            console.error("Load feedback stats failed:", e);
        }
    };
    
    await loadRagEval();
    await loadFeedbackStats();
    
    if (evalInterval) clearInterval(evalInterval);
    evalInterval = setInterval(async () => {
        await loadRagEval();
        await loadFeedbackStats();
    }, 10000);
}

function refreshEval() {
    if (evalInterval) {
        clearInterval(evalInterval);
    }
    loadEvalStats();
}

async function searchAllMemories() {
    const query = document.getElementById("searchQuery").value.trim();
    if (!query) return alert("请输入搜索内容！");

    const resultsEl = document.getElementById("searchResults");
    resultsEl.innerHTML = '<div class="memory-item"><p>全局搜索中...</p></div>';

    try {
        const res = await fetch("/api/memory/search_all", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                token: token
            },
            body: JSON.stringify({
                query: query,
                user_id: null,
                memory_type: null,
                page: 1,
                page_size: 20
            })
        });

        const data = await res.json();
        if (data.data && data.data.list && data.data.list.length > 0) {
            let html = `<div style="margin-bottom:10px;color:#666;">全局搜索结果: 共找到 ${data.data.total} 条相关记忆</div>`;
            data.data.list.forEach(m => {
                const score = (m.similarity * 100).toFixed(0);
                const type = m.metadata?.memory_type || 'general';
                const userId = m.metadata?.user_id || 'default';
                const icons = {
                    'task': 'fa-list-check',
                    'knowledge': 'fa-book',
                    'preference': 'fa-heart',
                    'general': 'fa-note-sticky'
                };
                html += `
                    <div class="memory-item">
                        <div class="memory-thumbnail ${type}">
                            <i class="fa-solid ${icons[type] || 'fa-note-sticky'}"></i>
                            <span class="memory-score-badge">${score}%</span>
                        </div>
                        <div class="memory-card-body">
                            <div class="memory-item-header">
                                <span class="memory-badge ${type}">${type}</span>
                                <span class="memory-score">${score}% 相似</span>
                                <span class="memory-user" style="color:#888;font-size:12px;">用户: ${userId}</span>
                            </div>
                            <div class="memory-content-text">${m.content}</div>
                        </div>
                    </div>
                `;
            });
            resultsEl.innerHTML = html;
        } else {
            resultsEl.innerHTML = '<div class="empty-state"><i class="fa-solid fa-search"></i><p style="color:#8a8a8a">没有找到相关记忆</p></div>';
        }
    } catch (e) {
        resultsEl.innerHTML = `<div class="memory-item"><p style="color:#cc0000">搜索失败：${e.message}</p></div>`;
    }
}

function toggleSelectAllMemories() {
    const checked = document.getElementById("selectAllMemories").checked;
    document.querySelectorAll(".memory-checkbox").forEach(cb => {
        cb.checked = checked;
    });
}

async function batchDeleteMemories() {
    const checkboxes = document.querySelectorAll(".memory-checkbox:checked");
    if (checkboxes.length === 0) return alert("请选择要删除的记忆！");

    if (!confirm(`确定删除选中的 ${checkboxes.length} 条记忆？`)) return;

    const ids = Array.from(checkboxes).map(cb => cb.value);

    try {
        const res = await fetch("/api/memory/batch_delete", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                token: token
            },
            body: JSON.stringify({ memory_ids: ids })
        });

        const data = await res.json();
        if (data.code === 200) {
            alert(`成功删除 ${data.deleted_count} 条记忆`);
            document.getElementById("selectAllMemories").checked = false;
            loadMemoryStats();
            loadMemories();
        } else {
            alert("删除失败");
        }
    } catch (e) {
        alert("删除失败：" + e.message);
    }
}

async function clearAllUserMemories() {
    if (!confirm("确定清除当前用户的所有记忆？此操作不可恢复！")) return;

    try {
        const res = await fetch("/api/memory/clear/default", {
            method: "POST",
            headers: { token: token }
        });

        const data = await res.json();
        if (data.code === 200) {
            alert(`成功清除 ${data.deleted_count} 条记忆`);
            loadMemoryStats();
            loadMemories();
        } else {
            alert("清除失败");
        }
    } catch (e) {
        alert("清除失败：" + e.message);
    }
}
