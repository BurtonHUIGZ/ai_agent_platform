let token = localStorage.getItem("token");

// 页面加载 —— 强制显示登录页，不会空白
window.onload = function () {
    showLogin();
};

// ------------------------------
// 页面切换（登录 / 主页）
// ------------------------------
function showLogin() {
    document.getElementById("loginPage").style.display = "flex";
    document.getElementById("mainPage").style.display = "none";
}

function showMain() {
    document.getElementById("loginPage").style.display = "none";
    document.getElementById("mainPage").style.display = "block";
}

// ------------------------------
// 登录功能
// ------------------------------
async function login() {
    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;

    try {
        const res = await fetch("/api/user/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                username: username,
                password: password
            })
        });

        const data = await res.json();
        if (data.token) {
            token = data.token;
            localStorage.setItem("token", token);
            alert("登录成功！");
            showMain();
        } else {
            alert("登录失败：" + (data.msg || "密码错误"));
        }
    } catch (e) {
        alert("请求失败：" + e.message);
    }
}

// ------------------------------
// 🚀 运行任务 + 实时显示 AGENT 执行过程（完整保留！）
// ------------------------------
async function runTask() {
    const task = document.getElementById("taskInput").value.trim();
    if (!task) return alert("请输入任务内容！");

    const logEl = document.getElementById("log");
    const reportEl = document.getElementById("reportArea");

    // 清空
    logEl.innerText = "✅ 任务已提交，等待执行...\n";
    reportEl.innerText = "";

    // 1. 创建任务
    const res = await fetch("/api/task/create", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            token: token
        },
        body: JSON.stringify({ task })
    });

    const data = await res.json();
    const task_id = data.task_id;

    // 2. 轮询 —— 实时获取 AGENT 日志（完整保留）
    const interval = setInterval(async () => {
        try {
            const ret = await fetch(`/api/task/${task_id}`, {
                headers: { token: token }
            });
            const data = await ret.json();

            // ========================
            // 🔥 这里实时显示所有 Agent 过程
            // ========================
            if (data.logs) {
                logEl.innerText = data.logs.join("\n");
            }

            // 任务完成
            if (data.status === "completed") {
                clearInterval(interval);
                reportEl.innerText = data.result;
            }
        } catch (e) {
            console.error(e);
        }
    }, 600);
}

// ------------------------------
// 清空
// ------------------------------
function clearAll() {
    document.getElementById("taskInput").value = "";
    document.getElementById("log").innerText = "";
    document.getElementById("reportArea").innerText = "";
}

// 兼容你原来的按钮
function manualRefresh() {}