# pipeline_agent.py - CPU 流水线启发的 Agent 引擎
# 真正将 CPU 核心概念融入 Agent 处理流程

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional


# ============================================================================
# 📊 寄存器文件 (Register File) - Agent 短期记忆
# ============================================================================

@dataclass
class Register:
    name: str
    value: Any = None
    valid: bool = False


class RegisterFile:
    """寄存器文件 - CPU 的寄存器堆，存储 Agent 当前任务状态"""
    
    def __init__(self, num_registers=32):
        self.registers = [Register(f"R{i}") for i in range(num_registers)]
        self.named = {}
    
    def allocate(self, name: str, value: Any = None) -> Register:
        if name in self.named:
            reg = self.named[name]
            reg.value = value
            reg.valid = True
            return reg
        for reg in self.registers:
            if not reg.valid:
                reg.name = name
                reg.value = value
                reg.valid = True
                self.named[name] = reg
                return reg
        oldest = self.registers[0]
        if oldest.name in self.named:
            del self.named[oldest.name]
        oldest.name = name
        oldest.value = value
        oldest.valid = True
        self.named[name] = oldest
        return oldest
    
    def read(self, name: str) -> Optional[Any]:
        if name in self.named and self.named[name].valid:
            return self.named[name].value
        return None
    
    def write(self, name: str, value: Any):
        self.allocate(name, value)


# ============================================================================
# 🔄 Reorder Buffer (ROB) - 结果重排
# ============================================================================

@dataclass
class ROBEntry:
    id: int
    instruction: str
    state: str = "pending"
    result: Any = None


class ReorderBuffer:
    """Reorder Buffer - 乱序执行的结果按顺序提交"""
    
    def __init__(self, size=32):
        self.size = size
        self.buffer = OrderedDict()
        self.next_id = 0
    
    def insert(self, instruction: str) -> int:
        if len(self.buffer) >= self.size:
            raise Exception("ROB full")
        entry_id = self.next_id
        self.next_id += 1
        self.buffer[entry_id] = ROBEntry(id=entry_id, instruction=instruction)
        return entry_id
    
    def complete(self, entry_id: int, result: Any):
        if entry_id in self.buffer:
            self.buffer[entry_id].state = "completed"
            self.buffer[entry_id].result = result
    
    def commit(self) -> list:
        committed = []
        while self.buffer:
            first_id = next(iter(self.buffer))
            entry = self.buffer[first_id]
            if entry.state == "completed":
                committed.append(entry)
                del self.buffer[first_id]
            else:
                break
        return committed


# ============================================================================
# ⚡ 保留站 (Reservation Station)
# ============================================================================

@dataclass
class RSEntry:
    id: int
    op: str
    ready: bool = False
    result: Any = None


class ReservationStation:
    """保留站 - 等待操作数就绪后执行"""
    
    def __init__(self, size=16):
        self.size = size
        self.station = []
    
    def add(self, op: str) -> int:
        if len(self.station) >= self.size:
            raise Exception("Reservation station full")
        entry_id = len(self.station)
        self.station.append(RSEntry(id=entry_id, op=op))
        return entry_id
    
    def execute(self, entry_id: int) -> Any:
        if entry_id >= len(self.station):
            return None
        entry = self.station[entry_id]
        entry.result = f"Executed: {entry.op}"
        entry.ready = False
        return entry.result
    
    def clear_executed(self):
        self.station = [e for e in self.station if e.ready]


# ============================================================================
# 🏗️ 流水线 Agent (Pipeline Agent)
# ============================================================================

class PipelineStage:
    DECODE = "decode"
    PLAN = "plan"
    ACT = "act"
    REFLECT = "reflect"


@dataclass
class PipelineInstruction:
    id: int
    prompt: str
    stage: str = PipelineStage.DECODE
    tool_calls: list = field(default_factory=list)


class PipelineAgent:
    """流水线 Agent - CPU 流水线启发的 Agent 执行引擎
    
    流水线阶段：
    1. Decode - 解析用户意图
    2. Plan - 规划工具调用顺序  
    3. Act - 执行工具（可并行）
    4. Reflect - 反思结果，生成最终响应
    """
    
    def __init__(self):
        self.registers = RegisterFile(num_registers=32)
        self.rob = ReorderBuffer(size=32)
        self.rs = ReservationStation(size=16)
        self.max_parallel_tools = 4
        self.tools = {}
        self.pipeline_stalls = 0
    
    def register_tool(self, name: str, func: callable):
        self.tools[name] = func
    
    async def execute(self, prompt: str) -> str:
        """流水线执行"""
        # Stage 1: Decode
        instruction = await self._decode(prompt)
        
        # Stage 2: Plan
        instruction = await self._plan(instruction)
        
        # Stage 3: Act (并行)
        results = await self._act(instruction)
        
        # Stage 4: Reflect
        response = await self._reflect(results)
        
        return response
    
    async def _decode(self, prompt: str) -> PipelineInstruction:
        self.registers.write("input_prompt", prompt)
        self.registers.write("input_time", time.time())
        rob_id = self.rob.insert(f"Decode: {prompt[:50]}")
        self.registers.write("intent", f"Intent: {prompt}")
        return PipelineInstruction(id=rob_id, prompt=prompt)
    
    async def _plan(self, instruction: PipelineInstruction) -> PipelineInstruction:
        intent = self.registers.read("intent")
        # 模拟 LLM 规划：决定调用哪些工具
        instruction.tool_calls = [
            {"tool": "Read", "args": {"path": "example.txt"}},
            {"tool": "Write", "args": {"path": "output.txt"}},
        ]
        self.registers.write("planned_tools", instruction.tool_calls)
        return instruction
    
    async def _act(self, instruction: PipelineInstruction) -> list:
        semaphore = asyncio.Semaphore(self.max_parallel_tools)
        
        async def execute_tool(tool_call):
            async with semaphore:
                tool_name = tool_call["tool"]
                args = tool_call["args"]
                await asyncio.sleep(0.05)
                if tool_name in self.tools:
                    result = await self.tools[tool_name](**args)
                else:
                    result = f"Simulated {tool_name}({args})"
                return {"tool": tool_name, "result": result}
        
        tasks = [execute_tool(tc) for tc in instruction.tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            self.rob.complete(instruction.id + i, result)
        
        self.registers.write("tool_results", results)
        return results
    
    async def _reflect(self, results: list) -> str:
        tool_results = self.registers.read("tool_results") or results
        response = f"Based on {len(tool_results)} tools executed."
        latency = time.time() - self.registers.read("input_time")
        self.registers.write("last_latency", latency)
        self.rob.commit()
        return response
    
    async def execute_with_interrupt(self, prompt: str, timeout: float = 30.0) -> str:
        """带中断机制的执行"""
        try:
            return await asyncio.wait_for(self.execute(prompt), timeout=timeout)
        except asyncio.TimeoutError:
            self.pipeline_stalls += 1
            return "Request timed out."
    
    def get_stats(self) -> dict:
        return {
            "pipeline_stalls": self.pipeline_stalls,
            "rob_size": len(self.rob.buffer),
            "rs_size": len(self.rs.station),
            "registers_used": len(self.registers.named),
        }


# ============================================================================
# 🔀 任务调度器 (Task Scheduler)
# ============================================================================

@dataclass
class Task:
    task_id: str
    prompt: str
    priority: int = 0
    state: str = "ready"


class TaskScheduler:
    """任务调度器 - CPU 调度器启发的任务管理"""
    
    def __init__(self, agent: PipelineAgent):
        self.agent = agent
        self.ready_queue = []
        self.running_tasks = []
        self.completed = []
        self.max_running = 3
    
    def submit(self, task: Task):
        self.ready_queue.append(task)
        self.ready_queue.sort(key=lambda t: -t.priority)
    
    async def run(self):
        while self.ready_queue or self.running_tasks:
            # 调度新任务
            while len(self.running_tasks) < self.max_running and self.ready_queue:
                task = self.ready_queue.pop(0)
                task.state = "running"
                self.running_tasks.append(task)
            
            # 执行任务
            for task in self.running_tasks[:]:
                result = await self.agent.execute_with_interrupt(task.prompt)
                task.state = "completed"
                self.running_tasks.remove(task)
                self.completed.append({"task": task, "result": result})
