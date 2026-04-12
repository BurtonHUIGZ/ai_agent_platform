# langchain_agent.py
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
import os

# ==================== 1. 环境配置 ====================
# 清除可能冲突的环境变量
for key in ["OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_BASE_URL"]:
    os.environ.pop(key, None)

# ==================== 2. 配置本地模型 ====================
llm = ChatOpenAI(
    model="qwen3:8b",  # 必须与 ollama list 一致
    base_url="http://localhost:11434/v1",  # 需要 /v1
    api_key="ollama",  # Ollama 不验证，任意字符串
    temperature=0.3,
    request_timeout=180,  # 本地模型需要更长时间
    max_tokens=1024
)
#
# ==================== 3. 定义工具 ====================
# 工具 1: 自定义计算器
@tool
def calculate(expression: str) -> str:
    """计算数学表达式。输入示例：'2 + 3 * 4'"""
    try:
        result = eval(expression)
        return f"结果: {result}"
    except Exception as e:
        return f"计算错误: {e}"


# 工具 2: 当前时间
@tool
def get_current_time(_: str) -> str:
    """获取当前时间"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# 合并所有工具
tools = [calculate, get_current_time]

# ==================== 4. 定义 Prompt ====================
# 针对 Qwen 优化的 ReAct Prompt
prompt = ChatPromptTemplate.from_messages([
    ("system", """你是一个智能助手，可以使用工具帮助用户。

可用工具：
- calculate: 计算数学表达式
- get_current_time: 获取当前时间

使用工具时，请严格按照以下格式：
Thought: 思考下一步该做什么
Action: 工具名称
Action Input: 工具参数
Observation: 工具返回结果
...（可以重复 Thought/Action/Observation 多轮）
Thought: 现在我有了足够信息
Final Answer: 最终回答

如果不需要工具，直接回答。"""),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),  # 存储中间思考过程
])

# ==================== 5. 创建 Agent ====================
agent = create_tool_calling_agent(llm, tools, prompt)

# ==================== 6. 创建执行器 ====================
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,  # 开启日志，观察 ReAct 循环
    max_iterations=5,  # 防止死循环
    max_execution_time=300,  # 5 分钟超时
    handle_parsing_errors=True,  # 自动处理解析错误
)

# ==================== 7. 测试运行 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("🤖 LangChain Agent 测试（本地 Qwen:7b）")
    print("=" * 60)

    # 测试 1: 简单问答（不调用工具）
    print("\n【测试 1】简单问答")
    result = agent_executor.invoke({"input": "你好，请介绍一下你自己"})
    print(f"回答：{result['output']}")

    # 测试 2: 调用计算器工具
    print("\n【测试 2】数学计算")
    result = agent_executor.invoke({"input": "计算 (123 + 456) * 789 的结果"})
    print(f"回答：{result['output']}")

    # 测试 3: 调用时间工具
    print("\n【测试 3】获取时间")
    result = agent_executor.invoke({"input": "现在几点了？"})
    print(f"回答：{result['output']}")

    # 测试 4: 多工具组合
    print("\n【测试 4】多工具组合")
    result = agent_executor.invoke({"input": "现在几点了？然后计算当前小时数乘以 2"})
    print(f"回答：{result['output']}")

    print("\n" + "=" * 60)
    print("✅ 所有测试完成")
    print("=" * 60)
#     print("🤖 LangChain Agent 测试（本地 Qwen:7b）")
#     print("=" * 60)
#
#     # 测试 1: 简单问答（不调用工具）
#     print("\n【测试 1】简单问答")
#     result = agent_executor.invoke({"input": "你好，请介绍一下你自己"})
#     print(f"回答：{result['output']}")
#
#     # 测试 2: 调用计算器工具
#     print("\n【测试 2】数学计算")
#     result = agent_executor.invoke({"input": "计算 (123 + 456) * 789 的结果"})
#     print(f"回答：{result['output']}")
#
#     # 测试 3: 调用搜索工具
#     print("\n【测试 3】网络搜索")
#     result = agent_executor.invoke({"input": "2026 年 AI Agent 的最新发展趋势是什么？"})
#     print(f"回答：{result['output']}")
#
#     # 测试 4: 多工具组合
#     print("\n【测试 4】多工具组合")
#     result = agent_executor.invoke({"input": "现在几点了？然后计算当前小时数乘以 2"})
#     print(f"回答：{result['output']}")
#
#     print("\n" + "=" * 60)
#     print("✅ 所有测试完成")
#     print("=" * 60)