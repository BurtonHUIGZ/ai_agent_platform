let token = localStorage.getItem("token");
let currentWs = null;
let currentTaskId = null;

window.onload = function () {
    const savedToken = localStorage.getItem("token");
    if (savedToken) {
        token = savedToken;
        showMain();
    } else {
        showLogin();
    }
};

function showLogin() {
    document.getElementById("loginPage").style.display = "flex";
    document.getElementById("mainPage").style.display = "none";
}

function showMain() {
    document.getElementById("loginPage").style.display = "none";
    document.getElementById("mainPage").style.display = "block";
}

function switchTab(tabName) {
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
            document.getElementById("statTotal").textContent = data.data.total || 0;
            document.getElementById("statTask").textContent = data.data.by_type?.task || 0;
            document.getElementById("statKnowledge").textContent = data.data.by_type?.knowledge || 0;
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
                html += `
                    <div class="memory-item">
                        <div class="memory-item-header">
                            <span class="memory-badge ${m.metadata?.memory_type || 'general'}">${m.metadata?.memory_type || 'general'}</span>
                            <span class="memory-score">${score}% 相似</span>
                        </div>
                        <div class="memory-content-text">${m.content}</div>
                    </div>
                `;
            });
            resultsEl.innerHTML = html;
        } else {
            resultsEl.innerHTML = '<div class="memory-item"><p style="color:#8a8a8a">没有找到相关记忆</p></div>';
        }
    } catch (e) {
        resultsEl.innerHTML = `<div class="memory-item"><p style="color:#cc0000">搜索失败：${e.message}</p></div>`;
    }
}

async function loadMemories() {
    const listEl = document.getElementById("memoryList");
    listEl.innerHTML = '<div class="memory-item"><p>加载中...</p></div>';

    try {
        const res = await fetch("/api/memory/list/default", {
            headers: { token: token }
        });

        if (res.status === 401) {
            localStorage.removeItem("token");
            token = null;
            showLogin();
            return;
        }

        const data = await res.json();
        if (data.data && data.data.length > 0) {
            let html = '';
            data.data.forEach(m => {
                const time = m.metadata?.created_at ? new Date(m.metadata.created_at).toLocaleString() : '';
                html += `
                    <div class="memory-item">
                        <div class="memory-item-header">
                            <span class="memory-badge ${m.metadata?.memory_type || 'general'}">${m.metadata?.memory_type || 'general'}</span>
                            <span class="memory-time">${time}</span>
                        </div>
                        <div class="memory-content-text">${m.content}</div>
                        <div class="memory-actions">
                            <button class="btn-delete" onclick="deleteMemory('${m.id}')">
                                <i class="fa-solid fa-trash"></i> 删除
                            </button>
                        </div>
                    </div>
                `;
            });
            listEl.innerHTML = html;
        } else {
            listEl.innerHTML = '<div class="memory-item"><p style="color:#8a8a8a">暂无记忆</p></div>';
        }
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
