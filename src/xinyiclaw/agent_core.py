# agent.py - 真正的 Agent 架构
# 自主规划 + 反思环 + 自修正 + 动态工具选择

import asyncio
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional


# ============================================================================
# 📊 状态 (State) - Agent 的观测
# ============================================================================

@dataclass
class AgentState:
    """Agent 状态"""
    original_task: str = ""
    current_plan: list = field(default_factory=list)
    completed_steps: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    observations: str = ""
    iterations: int = 0
    max_iterations: int = 10
    is_done: bool = False
    final_response: str = ""


# ============================================================================
# 🔧 工具注册表 (Tool Registry) - 动态工具选择
# ============================================================================

class ToolRegistry:
    """工具注册表 - 动态管理和选择工具"""
    
    def __init__(self):
        self.tools = {}  # name -> (func, description, parameters)
        self.tool_aliases = {}  # 别名 -> 正式名称
    
    def register(self, name: str, func: callable, description: str, parameters: list = None):
        self.tools[name] = {
            "func": func,
            "description": description,
            "parameters": parameters or [],
            "usage_count": 0,
        }
    
    def register_alias(self, alias: str, tool_name: str):
        self.tool_aliases[alias] = tool_name
    
    async def call(self, name: str, **kwargs) -> str:
        """调用工具"""
        # 解析别名
        if name in self.tool_aliases:
            name = self.tool_aliases[name]
        
        if name not in self.tools:
            return f"Error: Tool '{name}' not found"
        
        tool = self.tools[name]
        tool["usage_count"] += 1
        
        try:
            result = await tool["func"](**kwargs)
            return result
        except Exception as e:
            return f"Error: {str(e)}"
    
    def select_tools(self, task: str, n: int = 3) -> list:
        """根据任务描述选择最合适的工具"""
        task_lower = task.lower()
        scored = []
        
        for name, tool in self.tools.items():
            score = 0
            desc_lower = tool["description"].lower()
            
            # 关键词匹配
            for keyword in task_lower.split():
                if keyword in desc_lower:
                    score += 1
            
            # 任务类型匹配
            if "read" in task_lower and "read" in name.lower():
                score += 2
            if "write" in task_lower and "write" in name.lower():
                score += 2
            if "search" in task_lower and "search" in name.lower():
                score += 2
            if "code" in task_lower and "code" in name.lower():
                score += 2
            
            # 使用频率加成
            score += min(tool["usage_count"] * 0.1, 1)
            
            scored.append((score, name, tool))
        
        # 按分数排序，返回最高的 n 个
        scored.sort(reverse=True)
        return [(name, tool["description"]) for score, name, tool in scored[:n]]


# ============================================================================
# 🧠 Planner - 自主规划子任务
# ============================================================================

class Planner:
    """Planner - 将大任务分解为子任务"""
    
    def __init__(self, llm_func):
        self.llm_func = llm_func  # LLM 调用函数
    
    async def plan(self, task: str, context: str = "") -> list:
        """将任务分解为子任务列表
        
        Returns:
            list of subtasks, each with {task, tool?, expected_output?}
        """
        prompt = f"""将以下任务分解为具体的子任务步骤：

任务: {task}

{context}

请按顺序列出子任务，每个子任务应该：
1. 清晰具体，可执行
2. 有明确的完成标准
3. 按逻辑顺序排列

格式：
1. [子任务描述]
2. [子任务描述]
...

只输出子任务列表，不要其他内容。"""
        
        response = await self.llm_func(prompt)
        
        # 解析子任务
        subtasks = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if line and line[0].isdigit():
                # 去掉序号
                subtask = line.split(".", 1)[1].strip() if "." in line else line
                # 移除 markdown 格式
                subtask = re.sub(r"^\s*[-*]\s*", "", subtask)
                if subtask:
                    subtasks.append(subtask)
        
        return subtasks
    
    async def refine_plan(self, task: str, failed_step: str, error: str, context: str) -> list:
        """失败后重新规划"""
        prompt = f"""任务: {task}
已完成: {context}
失败步骤: {failed_step}
错误: {error}

请重新规划剩余步骤，考虑：
1. 为什么之前的步骤失败了
2. 如何避免同样的错误
3. 是否有更简单的替代方案

格式：
1. [新子任务描述]
2. [子任务描述]
...
"""
        response = await self.llm_func(prompt)
        
        subtasks = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if line and line[0].isdigit():
                subtask = line.split(".", 1)[1].strip() if "." in line else line
                subtask = re.sub(r"^\s*[-*]\s*", "", subtask)
                if subtask:
                    subtasks.append(subtask)
        
        return subtasks


# ============================================================================
# ⚖️ Evaluator - 评估是否完成
# ============================================================================

class Evaluator:
    """Evaluator - 评估当前状态是否达到目标"""
    
    def __init__(self, llm_func):
        self.llm_func = llm_func
    
    async def evaluate(self, task: str, state: AgentState) -> tuple[bool, str]:
        """评估是否完成
        
        Returns:
            (is_done, evaluation_reason)
        """
        # 检查是否超时
        if state.iterations >= state.max_iterations:
            return True, "达到最大迭代次数"
        
        # 检查是否已有明确完成
        prompt = f"""评估以下任务的完成情况：

原始任务: {task}
已完成步骤:
{chr(10).join(state.completed_steps)}

最终响应: {state.final_response}

请判断：
A. 已完成 - 任务达到了预期目标
B. 未完成 - 还需要更多步骤

只回答 A 或 B，以及简短理由。"""
        
        response = await self.llm_func(prompt)

        is_done = response.strip().startswith("A") or response.strip().startswith("a")
        reason = response.strip()

        return is_done, reason
    
    async def evaluate_step(self, step: str, result: str, expected: str = None) -> tuple[bool, str]:
        """评估单个步骤是否成功"""
        prompt = f"""评估以下步骤执行情况：

步骤: {step}
执行结果: {result}
{('预期: ' + expected) if expected else ''}

判断：
1. 成功 - 达到了步骤目标
2. 部分成功 - 有问题但可以继续
3. 失败 - 需要重试或更换方法

只回答数字和简短理由。"""
        
        response = await self.llm_func(prompt)
        
        if response.startswith("1"):
            return True, "成功"
        elif response.startswith("2"):
            return True, "部分成功"
        else:
            return False, response


# ============================================================================
# 🔄 Self-Corrector - 自修正
# ============================================================================

class SelfCorrector:
    """Self-Corrector - 自我修正机制"""
    
    def __init__(self, llm_func):
        self.llm_func = llm_func
        self.error_patterns = {}  # 记录错误模式
    
    async def diagnose(self, step: str, error: str, result: str) -> dict:
        """诊断问题"""
        prompt = f"""分析以下失败案例：

步骤: {step}
错误: {error}
执行结果: {result}

请诊断问题：
1. 是什么导致了失败？
2. 应该使用什么工具或方法？
3. 如何避免类似错误？

格式：
原因: xxx
建议: xxx
"""
        response = await self.llm_func(prompt)
        
        # 解析建议
        diagnosis = {"cause": "", "suggestion": ""}
        for line in response.split("\n"):
            if "原因:" in line:
                diagnosis["cause"] = line.split("原因:", 1)[1].strip()
            if "建议:" in line:
                diagnosis["suggestion"] = line.split("建议:", 1)[1].strip()
        
        return diagnosis
    
    async def suggest_alternative(self, failed_step: str, diagnosis: dict, tools: list) -> str:
        """建议替代方案"""
        prompt = f"""为以下失败步骤寻找替代方案：

原始步骤: {failed_step}
问题诊断: {diagnosis.get('cause', '未知')}
建议: {diagnosis.get('suggestion', '未知')}

可用工具:
{chr(10).join([f"- {t}" for t in tools])}

请提出一个新的替代步骤，要求：
1. 解决原问题
2. 可执行
3. 简洁明确

只输出替代步骤，不要其他内容。"""
        
        response = await self.llm_func(prompt)
        return response.strip()
    
    def learn_from_error(self, step: str, error: str):
        """从错误中学习"""
        if error not in self.error_patterns:
            self.error_patterns[error] = {"count": 0, "steps": []}
        self.error_patterns[error]["count"] += 1
        if step not in self.error_patterns[error]["steps"]:
            self.error_patterns[error]["steps"].append(step)


# ============================================================================
# 🤖 Agent - 真正的 Agent 架构
# ============================================================================

class Agent:
    """真正的 Agent - 带反思环的自主控制器
    
    架构：
    ┌─────────────────────────────────────────────────────┐
    │                    observe()                        │
    │              观测当前状态                           │
    └────────────────────────┬────────────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────┐
    │                    reason()                         │
    │              规划子任务（自主决定做什么）              │
    └────────────────────────┬────────────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────┐
    │                     act()                          │
    │           执行工具（动态选择）                       │
    └────────────────────────┬────────────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────┐
    │                   evaluate()                        │
    │              评估是否完成（自检）                    │
    └────────────────────────┬────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
           done?                     not done
              │                         │
              ▼                         ▼
         return                      self_correct()
                                    refine_plan()
                                        retry
    """
    
    def __init__(self, llm_func: callable):
        self.llm_func = llm_func  # LLM 调用函数
        
        # 核心组件
        self.planner = Planner(llm_func)
        self.evaluator = Evaluator(llm_func)
        self.corrector = SelfCorrector(llm_func)
        self.tools = ToolRegistry()
        
        # 状态
        self.state: Optional[AgentState] = None
    
    def register_tool(self, name: str, func: callable, description: str, parameters: list = None):
        """注册工具"""
        self.tools.register(name, func, description, parameters)
    
    async def run(self, task: str) -> str:
        """运行 Agent - 反思环主循环"""
        # 初始化状态
        self.state = AgentState(original_task=task)
        
        # ========== observe() ==========
        self.state.observations = f"Task received: {task}"
        
        while not self.state.is_done:
            self.state.iterations += 1
            
            # ========== reason() - 自主规划 ==========
            if not self.state.current_plan:
                # 首次规划：分解任务
                self.state.current_plan = await self.planner.plan(
                    task,
                    context=f"已完成: {self.state.completed_steps}"
                )
                self.state.observations += f"\nPlan created with {len(self.state.current_plan)} steps"
            
            # ========== act() - 执行 ==========
            if self.state.current_plan:
                current_step = self.state.current_plan[0]
                
                # 选择工具
                selected_tools = self.tools.select_tools(current_step, n=1)
                tool_name = selected_tools[0][0] if selected_tools else None
                
                # 执行
                if tool_name:
                    # 模拟工具执行（实际应该传参）
                    result = await self.tools.call(tool_name, task=current_step)
                else:
                    result = await self.llm_func(f"Execute: {current_step}")
                
                self.state.tool_results.append({
                    "step": current_step,
                    "tool": tool_name,
                    "result": result
                })
                self.state.completed_steps.append(current_step)
                
                # 移除已完成的步骤
                self.state.current_plan = self.state.current_plan[1:]
            
            # ========== evaluate() - 评估 ==========
            is_done, reason = await self.evaluator.evaluate(task, self.state)
            
            if is_done:
                self.state.is_done = True
                self.state.final_response = await self._generate_response(task)
            else:
                # ========== self_correct() - 自修正 ==========
                if self.state.current_plan:
                    failed_step = self.state.completed_steps[-1] if self.state.completed_steps else ""
                    last_result = self.state.tool_results[-1]["result"] if self.state.tool_results else ""
                    
                    diagnosis = await self.corrector.diagnose(
                        failed_step,
                        last_result if "Error" in last_result else "",
                        last_result
                    )
                    
                    # 建议替代方案
                    alternative = await self.corrector.suggest_alternative(
                        failed_step,
                        diagnosis,
                        list(self.tools.tools.keys())
                    )
                    
                    # 学习错误
                    if "Error" in last_result:
                        self.corrector.learn_from_error(failed_step, last_result)
                    
                    # 将替代方案加入计划
                    if alternative and alternative != failed_step:
                        self.state.current_plan.insert(0, alternative)
        
        return self.state.final_response
    
    async def _generate_response(self, task: str) -> str:
        """生成最终响应"""
        prompt = f"""基于以下执行记录，生成最终响应：

任务: {task}
执行步骤:
{chr(10).join([f"{i+1}. {s}" for i, s in enumerate(self.state.completed_steps)])}

执行结果:
{chr(10).join([f"- {r['result'][:200]}" for r in self.state.tool_results[-3:]])}

请生成一个完整、清晰的最终响应。"""
        
        return await self.llm_func(prompt)


# ============================================================================
# 🔧 内置工具
# ============================================================================

async def builtin_read(path: str) -> str:
    """读取文件"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


async def builtin_write(path: str, content: str) -> str:
    """写入文件"""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Written to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def builtin_search(query: str) -> str:
    """搜索"""
    # 模拟搜索
    return f"Search results for '{query}': [result1, result2, result3]"


async def builtin_code(code: str) -> str:
    """执行代码"""
    # 模拟代码执行
    return f"Code executed: {code[:100]}..."
