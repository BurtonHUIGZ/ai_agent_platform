let token = localStorage.getItem("token");
let currentWs = null;
let currentTaskId = null;

// 加载记忆统计数据
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
            showError("登录失败：" + (data.msg || "密码错误"));
        }
    } catch (e) {
showError("请求失败：" + e.message);
    }

    if (!content) return showWarning("请输入记忆内容！");

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
            showSuccess("记忆保存成功！");
            document.getElementById("memoryContent").value = "";
            loadMemoryStats();
            loadMemories();
        } else {
            showError("保存失败");
        }
} catch (e) {
        showError("请求失败：" + e.message);
    }

    if (!query) return showWarning("请输入搜索内容！");

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
    // 使用确认弹窗
    const confirmed = await new Promise(resolve => {
        showModal({
            title: '确认删除',
            message: '确定删除这条记忆？',
            type: 'warning',
            confirmText: '删除',
            onConfirm: () => resolve(true),
            onCancel: () => resolve(false)
        });
    });
    
    if (!confirmed) return;

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
        showError("删除失败：" + e.message);
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
                const docInfo = msg.doc_type ? ` (${msg.doc_type})` : '';
                statusEl.innerHTML = `<p style="color:#2ba640">✅ 上传成功！已提取 ${msg.chunks} 个知识片段${docInfo}</p>`;
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
    if (!query) return showWarning("请输入搜索内容！");

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
    if (checkboxes.length === 0) return showWarning("请选择要删除的记忆！");

    // 自定义确认弹窗
    const count = checkboxes.length;
    const confirmed = await new Promise(resolve => {
        showModal({
            title: '批量删除',
            message: `确定删除选中的 ${count} 条记忆？`,
            type: 'warning',
            confirmText: '删除',
            onConfirm: () => resolve(true),
            onCancel: () => resolve(false)
        });
    });
    if (!confirmed) return;

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
            showSuccess(`成功删除 ${data.deleted_count} 条记忆`);
            document.getElementById("selectAllMemories").checked = false;
            loadMemoryStats();
            loadMemories();
        } else {
            showError("删除失败");
        }
    } catch (e) {
        showError("删除失败：" + e.message);
    }
}

async function clearAllUserMemories() {
    // 危险操作确认
    const confirmed = await new Promise(resolve => {
        showModal({
            title: '清除所有记忆',
            message: '确定清除当前用户的所有记忆？此操作不可恢复！',
            type: 'danger',
            confirmText: '清除',
            onConfirm: () => resolve(true),
            onCancel: () => resolve(false)
        });
    });
    if (!confirmed) return;

    try {
        const res = await fetch("/api/memory/clear/default", {
            method: "POST",
            headers: { token: token }
        });

        const data = await res.json();
        if (data.code === 200) {
            showSuccess(`成功清除 ${data.deleted_count} 条记忆`);
            loadMemoryStats();
            loadMemories();
        } else {
            showError("清除失败");
        }
    } catch (e) {
        showToast("清除失败：" + e.message, "error");
    }
}

// ==================== 自定义弹窗和提示 ====================
let modalCallback = null;

function showModal(options) {
    const { title, message, type = 'info', confirmText = '确定', cancelText = '取消', onConfirm, showCancel = true } = options;
    
    const overlay = document.getElementById('modalOverlay');
    const titleEl = document.getElementById('modalTitle');
    const messageEl = document.getElementById('modalMessage');
    const confirmBtn = document.getElementById('modalConfirmBtn');
    
    // 设置图标和颜色
    const icons = {
        success: '<i class="fa-solid fa-circle-check"></i>',
        error: '<i class="fa-solid fa-circle-xmark"></i>',
        warning: '<i class="fa-solid fa-circle-exclamation"></i>',
        info: '<i class="fa-solid fa-circle-info"></i>'
    };
    
    titleEl.innerHTML = `${icons[type] || icons.info} <span>${title}</span>`;
    titleEl.className = `modal-title ${type}`;
    messageEl.textContent = message;
    
    confirmBtn.textContent = confirmText;
    confirmBtn.className = type === 'danger' ? 'btn btn-danger' : 'btn btn-confirm';
    
    document.querySelector('.btn-cancel').textContent = cancelText;
    document.querySelector('.btn-cancel').style.display = showCancel ? 'block' : 'none';
    
    modalCallback = onConfirm;
    overlay.classList.add('active');
}

function closeModal() {
    document.getElementById('modalOverlay').classList.remove('active');
    modalCallback = null;
}

function confirmModal() {
    if (modalCallback) {
        modalCallback();
    }
    closeModal();
}

function closeModalOverlay(event) {
    if (event && event.target !== event.currentTarget) return;
    closeModal();
}

// 显示确认弹窗
function showConfirm(message, onConfirm) {
    showModal({
        title: '确认操作',
        message: message,
        type: 'warning',
        onConfirm: onConfirm
    });
}

// 显示危险操作确认
function showDangerConfirm(message, onConfirm) {
    showModal({
        title: '危险操作',
        message: message,
        type: 'danger',
        confirmText: '删除',
        onConfirm: onConfirm
    });
}

// Toast 提示
function showToast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toastContainer');
    
    const icons = {
        success: '<i class="fa-solid fa-circle-check"></i>',
        error: '<i class="fa-solid fa-circle-xmark"></i>',
        warning: '<i class="fa-solid fa-circle-exclamation"></i>',
        info: '<i class="fa-solid fa-circle-info"></i>'
    };
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        ${icons[type] || icons.info}
        <span class="toast-message">${message}</span>
    `;
    
    container.appendChild(toast);
    
    // 显示动画
    setTimeout(() => toast.classList.add('show'), 10);
    
    // 自动隐藏
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// 便捷方法
function showSuccess(message) { showToast(message, 'success'); }
function showError(message) { showToast(message, 'error'); }
function showWarning(message) { showToast(message, 'warning'); }
function showInfo(message) { showToast(message, 'info'); }
