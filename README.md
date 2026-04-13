# AI Agent 平台

基于 CrewAI + LangGraph 的企业级多 Agent 协作平台

## 项目架构

```
ai_agent_platform/
├── app/
│   ├── api/                 # API 路由
│   │   ├── websocket_api.py # WebSocket 实时通信
│   │   ├── memory_api.py    # 记忆系统 API
│   │   ├── user_api.py      # 用户认证 API
│   │   └── monitor_api.py   # 系统监控 API
│   ├── agent/               # Agent 核心
│   │   ├── agents.py        # CrewAI Agent 定义
│   │   ├── tasks.py         # 任务定义
│   │   └── streaming_workflow.py  # LangGraph 工作流
│   ├── core/                # 核心模块
│   │   ├── memory.py        # 记忆系统 (短期+长期)
│   │   ├── user_system.py   # 用户权限系统
│   │   ├── task_queue.py    # 任务队列
│   │   └── websocket_manager.py  # WebSocket 管理
│   ├── llm/                 # LLM 配置
│   │   └── model_factory.py # 模型工厂 (支持多 provider)
│   ├── schemas/             # 数据模型
│   └── main.py              # FastAPI 应用入口
├── config/                  # 配置文件
│   ├── agents.yaml          # Agent 配置
│   ├── tasks.yaml           # 任务配置
│   └── prompts.yaml         # Prompt 配置
├── models.json              # 模型配置 (多 provider)
└── requirements.txt         # 依赖
```

## 工作流

```
                           ┌─────────────────────────────────────┐
                           │          recall (记忆召回)             │
                           │  - 短期记忆 + 长期记忆(RAG)         │
                           └──────────────────┬──────────────────┘
                                            │
                                            ▼
                           ┌─────────────────────────────────────┐
                           │           route (意图识别)              │
                           │  - 判断 task_type: chat/simple/        │
                           │    complex/question                 │
                           └──────────────────┬──────────────────┘
                                            │
         ┌──────────────┬──────────────┬───────┴───────┬──────────────┬──────────────┐
         ▼             ▼            ▼             ▼             ▼
    ┌─────────┐  ┌──────────┐ ┌─────────┐ ┌────────────┐ ┌──────────┐
    │  chat   │ │  question │ │ simple  │ │ complex   │ │ complex  │
    │(闲聊)   │ │(问答+投票) │ │(简单任务) │ │ skip_rs=Y │ │skip_rs=N │
    └────┬────┘ └────┬─────┘ └────┬────┘ └─────┬─────┘ └────┬─────┘
         │          │            │            │            │
         │          ▼            │            │            ▼
         │    ┌─────────────────┴───┐       │     ┌──────────────┐
         │    │    rag_vote_node     │       │     │   research   │
         │    │ (多路检索+投票)       │       │     │  (需求分析)  │
         │    │ 1.RAG搜索            │       │     └──────┬───────┘
         │    │ 2.网络搜索           │       │            │
         │    │ 3.直接回答           │       │            ▼
         │    │ → LLM投票选择        │       │     ┌──────────────┐
         │    └─────────┬───────────┘       │     │   execute    │
         │              │                   │     │  (任务执行)  │
         │              ▼                   │     └──────┬───────┘
         │        save_memory               │            │
         │                                   │            ▼
         │                            ┌──────┴───────┐    ┌──────────┐
         │                            │skip_validate│    │ validate │
         │                            │    =Y        │    │ (校验)   │
         │                            └──────┬───────┘    └─────┬────┘
         │                                   │             │
         │                                   ▼             ▼
         │                            ┌──────────────┐ ┌──────┐
         │                            │   manager    │ │manager│
         │                            │ (报告汇总)   │ │      │
         │                            └──────┬───────┘ └──────┘
         │                                   │
         ▼                                   ▼
    ┌──────────────┐                 ┌──────────────┐
    │ save_memory │                 │ save_memory │
    │(保存记忆)  │                 │(保存记忆)   │
    └─────────────┘                 └─────────────┘
```

## 条件边说明

| 路由条件 | 目标节点 | 说明 |
|----------|---------|------|
| task_type=chat | chat | 闲聊，直接回复 |
| task_type=question | rag_vote | 问答，多路检索+投票 |
| task_type=simple + skip_research=Y | execute_skip_research | 简单任务，跳过研究 |
| task_type=simple + skip_research=N | research | 简单任务，需要研究 |
| task_type=complex + skip_research=Y | execute_skip_research | 复杂任务跳研究 |
| task_type=complex + skip_research=N | research | 复杂任务完整流程 |

## 节点说明

| 节点 | Agent | 功能 | 是否校验 |
|------|-------|------|------|
| recall | - | 召回短期/长期记忆 | - |
| route | - | 意图识别，判断task_type | - |
| chat | executor | 闲聊回复 | 跳过 |
| rag_vote | executor | 多路检索+LLM投票 | 跳过 |
| research | researcher | 需求分析 | - |
| execute | executor | 任务执行 | - |
| execute_skip_research | executor | 跳过研究直接执行 | 配置决定 |
| validate | validator | 结果校验 | - |
| manager | manager | 报告汇总 | - |
| save_memory | - | 保存短期/长期记忆 | - |

## 记忆系统

- **ShortTermMemory**: 短期会话记忆，自动管理上下文窗口
- **LongTermMemory**: 长期记忆，基于 ChromaDB 向量存储
- **上下文压缩**: Token > 500 时触发压缩

## 模型配置

支持多 Provider 切换，通过 `models.json` 配置：

```json
{
  "ALIYUN_BAILIAN": {
    "model": "qwen3.6-plus",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
  },
  "OLLAMA": {
    "model": "qwen3:8b",
    "base_url": "http://localhost:11434/v1"
  }
}
```

修改 `settings.py` 中的 `ACTIVE_PROVIDER` 切换模型。

## 技术栈

### 后端框架
- **FastAPI** - 现代 Python Web 框架
- **Uvicorn** - ASGI 服务器

### AI 框架
- **CrewAI** - 多 Agent 协作框架
- **LangGraph** - 工作流编排与状态管理
- **LangChain** - LLM 应用开发框架

### LLM 集成
- **百炼 (DashScope)** - 阿里云 Qwen 系列模型
- **Ollama** - 本地 LLM 推理
- **LangChain Ollama** - 本地模型适配

### 数据存储
- **ChromaDB** - 向量数据库 (RAG 长期记忆)
- **In-memory** - 短期会话记忆

### 实时通信
- **WebSocket** - 实时流式输出
- **SSE** - 服务端推送

### 辅助工具
- **Pydantic** - 数据验证
- **python-dotenv** - 环境变量管理
- **Loguru** - 日志管理

## 启动

```bash
# 激活虚拟环境
source .venv/bin/activate

# 启动服务
python -m app.main
```

访问 http://127.0.0.1:8718