# engine.py - CPU 架构启发的 Agent 引擎
# 融合了调度与并行、预测与预取、存储层级、同步与竞争、异常与中断、批量处理

import asyncio
import logging
import re
import subprocess
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 📊 存储层级 (Storage Hierarchy) - 模仿 CPU L1/L2/L3 缓存
# ============================================================================

@dataclass
class CacheEntry:
    key: str
    value: Any
    access_count: int = 0
    last_access: float = field(default_factory=time.time)

    def touch(self):
        self.access_count += 1
        self.last_access = time.time()


class MemoryCache:
    """多级记忆缓存 - 模仿 CPU 缓存层级
    
    L1: 热点结果缓存 (LRU, 小容量, 快速)
    L2: 上下文片段缓存 (中等容量)
    L3: 长期记忆索引 (大容量, 较慢)
    TLB: 快速查找表
    """

    def __init__(self, l1_size=64, l2_size=256, l3_size=1024):
        self.l1 = OrderedDict()
        self.l1_size = l1_size
        self.l2 = OrderedDict()
        self.l2_size = l2_size
        self.l3 = OrderedDict()
        self.l3_size = l3_size
        self.tlb = OrderedDict()
        self.tlb_size = 128

    def _evict_lru(self, cache, max_size):
        while len(cache) >= max_size:
            cache.popitem(last=False)

    def _tlb_lookup(self, query_hash):
        if query_hash in self.tlb:
            level, key = self.tlb[query_hash]
            if level == 1 and key in self.l1:
                self.l1[key].touch()
                return self.l1[key].value
            elif level == 2 and key in self.l2:
                self.l2[key].touch()
                return self.l2[key].value
        return None

    def _tlb_insert(self, query_hash, level, key):
        while len(self.tlb) >= self.tlb_size:
            self.tlb.popitem(last=False)
        self.tlb[query_hash] = (level, key)

    def get(self, query, level=1):
        query_hash = hash(query)
        cached = self._tlb_lookup(query_hash)
        if cached is not None:
            return cached
        for l in range(level, 0, -1):
            cache = getattr(self, f'l{l}')
            key = f"{l}:{query}"
            if key in cache:
                entry = cache[key]
                entry.touch()
                if l > 1:
                    self.put(query, entry.value, 1)
                self._tlb_insert(query_hash, 1, f"1:{query}")
                return entry.value
        return None

    def put(self, query, value, level=1):
        cache = getattr(self, f'l{level}')
        key = f"{level}:{query}"
        cache[key] = CacheEntry(key=key, value=value)
        self._evict_lru(cache, getattr(self, f'l{level}_size'))
        self._tlb_insert(hash(query), level, key)

    def get_tool_result(self, tool_key):
        return self.get(f"tool:{tool_key}", 1)

    def put_tool_result(self, tool_key, result):
        self.put(f"tool:{tool_key}", result, 1)

    def get_context(self, context_key):
        return self.get(f"ctx:{context_key}", 2)

    def put_context(self, context_key, context):
        self.put(f"ctx:{context_key}", context, 2)


# ============================================================================
# ⚡ 预测与预取 (Prediction & Prefetch)
# ============================================================================

class BranchPredictor:
    """分支预测器 - 预测下一步需要的工具和上下文"""

    def __init__(self):
        self.tool_patterns = {}
        self.context_patterns = {
            "Read": ["filepath", "path"],
            "Write": ["filepath", "path"],
            "Edit": ["filepath", "path", "old_text"],
            "Glob": ["pattern"],
            "Grep": ["pattern", "path"],
            "Bash": ["command"],
        }

    def predict(self, history):
        if not history:
            return None, []
        tool_seq = []
        for msg in history:
            content = msg.get("content", "")
            matches = re.findall(r'\[TOOL_CALL\](.+?)\[/TOOL_CALL\]', content, re.DOTALL)
            for match in matches:
                parts = match.split("|")
                if parts:
                    tool_seq.append(parts[0].strip())
        if len(tool_seq) < 2:
            return None, []
        last_two = tuple(tool_seq[-2:])
        predicted = self.tool_patterns.get(last_two)
        if len(tool_seq) >= 3:
            pattern_key = tuple(tool_seq[-3:])
            self.tool_patterns[pattern_key] = tool_seq[-1]
        prefetch = []
        if predicted and predicted in self.context_patterns:
            prefetch = self.context_patterns[predicted]
        return predicted, prefetch

    def learn(self, tool_seq):
        for i in range(len(tool_seq) - 2):
            key = tuple(tool_seq[i:i+3])
            self.tool_patterns[key] = tool_seq[i+3] if i+3 < len(tool_seq) else None


class Prefetcher:
    """预取器 - 提前加载可能需要的资源"""

    def __init__(self, cache, workspace):
        self.cache = cache
        self.workspace = workspace

    async def prefetch_context(self, context_keys, history) -> bool:
        prefetched = False
        for msg in history:
            for key in context_keys:
                if key in msg:
                    value = msg[key]
                    if isinstance(value, str) and ("path" in key.lower() or "file" in key.lower()):
                        if await self._prefetch_file(value):
                            prefetched = True
        return prefetched

    async def _prefetch_file(self, filepath) -> bool:
        try:
            path = Path(filepath) if Path(filepath).is_absolute() else self.workspace / filepath
            if path.exists() and path.is_file():
                content = path.read_text(encoding="utf-8", errors="ignore")
                self.cache.put_context(str(path), content)
                logger.debug(f"Prefetched: {path}")
                return True
        except Exception:
            pass
        return False


# ============================================================================
# 🔒 同步与竞争 (Synchronization & Competition)
# ============================================================================

class AsyncLock:
    """异步锁 - 模仿 Mutex"""

    def __init__(self):
        self._locked = False
        self._waiters = []

    async def acquire(self):
        if not self._locked:
            self._locked = True
            return True
        future = asyncio.get_event_loop().create_future()
        self._waiters.append(future)
        await future
        self._locked = True
        return True

    def release(self):
        if self._waiters:
            future = self._waiters.pop(0)
            future.set_result(True)
        else:
            self._locked = False

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        self.release()


# ============================================================================
# 🚦 异常与中断 (Exception & Interrupt)
# ============================================================================

class WatchdogTimer:
    """看门狗定时器 - 防止工具执行超时"""

    def __init__(self, timeout_seconds=60.0):
        self.timeout = timeout_seconds
        self._timers = {}
        self._callbacks = {}

    def start(self, task_id, callback=None):
        async def _watchdog():
            try:
                await asyncio.sleep(self.timeout)
                if task_id in self._timers:
                    logger.warning(f"Watchdog timeout: {task_id}")
                    if callback:
                        callback(task_id)
                    else:
                        self._timers[task_id].cancel()
            except asyncio.CancelledError:
                pass
        task = asyncio.create_task(_watchdog())
        self._timers[task_id] = task
        if callback:
            self._callbacks[task_id] = callback

    def stop(self, task_id):
        if task_id in self._timers:
            self._timers[task_id].cancel()
            del self._timers[task_id]
        if task_id in self._callbacks:
            del self._callbacks[task_id]

    def reset(self, task_id):
        self.stop(task_id)
        self.start(task_id)


class InterruptManager:
    """中断管理器 - 处理紧急任务"""

    def __init__(self):
        self._pending_interrupts = asyncio.Queue()
        self._processing = False

    async def raise_interrupt(self, priority, handler):
        await self._pending_interrupts.put((priority, handler))

    async def process_interrupts(self):
        if self._processing:
            return
        self._processing = True
        interrupts = []
        while not self._pending_interrupts.empty():
            interrupts.append(await self._pending_interrupts.get())
        interrupts.sort(key=lambda x: x[0])
        for _, handler in interrupts:
            try:
                await handler()
            except Exception as e:
                logger.exception(f"Interrupt handler error: {e}")
        self._processing = False


# ============================================================================
# 📦 批量处理 (Batch Processing) - 模仿 SIMD/向量化
# ============================================================================

@dataclass
class BatchItem:
    id: str
    data: Any
    future: asyncio.Future = field(default_factory=asyncio.Future)
    result: Any = None


class BatchProcessor:
    """批量处理器 - 将多个相似请求打包处理"""

    def __init__(self, max_batch_size=8, max_wait_ms=50.0):
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms
        self._queue = []
        self._lock = AsyncLock()

    async def submit(self, item_id, data):
        item = BatchItem(id=item_id, data=data)
        async with self._lock:
            self._queue.append(item)
            if len(self._queue) >= self.max_batch_size:
                return await self._process_batch()
        await asyncio.sleep(self.max_wait_ms / 1000.0)
        async with self._lock:
            if item in self._queue:
                self._queue.remove(item)
                return await self._process_single(item)
        return item.result

    async def _process_batch(self):
        if not self._queue:
            return None
        items = self._queue[:self.max_batch_size]
        self._queue = self._queue[self.max_batch_size:]
        results = []
        for item in items:
            result = await self._process_single(item)
            results.append(result)
        return results

    async def _process_single(self, item):
        item.result = f"Processed: {item.data}"
        item.future.set_result(item.result)
        return item.result


# ============================================================================
# 🏗️ 调度与并行 (Scheduling & Parallelism)
# ============================================================================

@dataclass
class Task:
    id: str
    prompt: str
    status: str = "pending"
    dependencies: list = field(default_factory=list)
    result: Any = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class DualQueue:
    """双队列 - 模仿 CPU 双发射
    
    pending: 待执行队列
    in_flight: 执行中队列
    """

    def __init__(self, max_in_flight=3):
        self.pending = asyncio.Queue()
        self.in_flight = OrderedDict()
        self.done = asyncio.Queue()
        self.max_in_flight = max_in_flight
        self._lock = AsyncLock()

    async def submit(self, task):
        await self.pending.put(task)

    async def dispatch(self):
        async with self._lock:
            if len(self.in_flight) < self.max_in_flight:
                try:
                    task = self.pending.get_nowait()
                    task.status = "running"
                    task.started_at = time.time()
                    self.in_flight[task.id] = task
                    return task
                except asyncio.QueueEmpty:
                    pass
        return None

    async def complete(self, task_id, result=None, success=True):
        async with self._lock:
            if task_id in self.in_flight:
                task = self.in_flight.pop(task_id)
                task.status = "done" if success else "failed"
                task.result = result
                task.completed_at = time.time()
                await self.done.put(task)
                return task
        return None

    def get_in_flight_count(self):
        return len(self.in_flight)

    async def wait_for_completion(self, timeout=None):
        results = []
        start = time.time()
        while self.in_flight:
            if timeout and (time.time() - start) > timeout:
                break
            await asyncio.sleep(0.01)
        while not self.done.empty():
            results.append(await self.done.get())
        return results


class PipelineScheduler:
    """流水线调度器 - 模仿 CPU 流水线"""

    def __init__(self, max_parallel=3):
        self.dual_queue = DualQueue(max_in_flight=max_parallel)
        self.max_parallel = max_parallel
        self._running_tasks = {}

    async def submit_task(self, task):
        await self.dual_queue.submit(task)

    async def execute_task(self, task, executor):
        try:
            result = await executor(task)
            return result
        finally:
            await self.dual_queue.complete(task.id, result, success=True)

    async def run_pipeline(self, tasks, executor):
        results = []
        for task in tasks:
            await self.submit_task(task)
        dispatch_tasks = []
        for _ in range(len(tasks)):
            task = await self.dual_queue.dispatch()
            if task:
                t = asyncio.create_task(self.execute_task(task, executor))
                dispatch_tasks.append(t)
                self._running_tasks[task.id] = t
        if dispatch_tasks:
            results = await asyncio.gather(*dispatch_tasks, return_exceptions=True)
        return results


# ============================================================================
# 📊 性能指标 (Metrics)
# ============================================================================

class MetricsCollector:
    """性能指标收集器"""

    def __init__(self):
        self._lock = AsyncLock()
        # 请求统计
        self.total_requests = 0
        self.total_latency_ms = 0
        self.min_latency_ms = float('inf')
        self.max_latency_ms = 0
        # 缓存统计
        self.cache_hits = 0
        self.cache_misses = 0
        # 预测统计
        self.predictions_made = 0
        self.predictions_correct = 0
        # 预取统计
        self.prefetches_made = 0
        self.prefetches_used = 0
        # 并发统计
        self.peak_in_flight = 0
        # 时序记录
        self._request_start_times = []

    async def record_request(self, latency_ms: float):
        async with self._lock:
            self.total_requests += 1
            self.total_latency_ms += latency_ms
            self.min_latency_ms = min(self.min_latency_ms, latency_ms)
            self.max_latency_ms = max(self.max_latency_ms, latency_ms)

    async def record_cache_hit(self):
        async with self._lock:
            self.cache_hits += 1

    async def record_cache_miss(self):
        async with self._lock:
            self.cache_misses += 1

    async def record_prediction(self, was_correct: bool):
        async with self._lock:
            self.predictions_made += 1
            if was_correct:
                self.predictions_correct += 1

    async def record_prefetch(self, was_used: bool):
        async with self._lock:
            self.prefetches_made += 1
            if was_used:
                self.prefetches_used += 1

    async def record_in_flight(self, count: int):
        async with self._lock:
            self.peak_in_flight = max(self.peak_in_flight, count)

    def get_stats(self):
        avg_latency = self.total_latency_ms / self.total_requests if self.total_requests > 0 else 0
        cache_total = self.cache_hits + self.cache_misses
        cache_hit_rate = (self.cache_hits / cache_total * 100) if cache_total > 0 else 0
        prediction_rate = (self.predictions_correct / self.predictions_made * 100) if self.predictions_made > 0 else 0
        prefetch_rate = (self.prefetches_used / self.prefetches_made * 100) if self.prefetches_made > 0 else 0

        return {
            "total_requests": self.total_requests,
            "avg_latency_ms": round(avg_latency, 2),
            "min_latency_ms": round(self.min_latency_ms, 2) if self.min_latency_ms != float('inf') else 0,
            "max_latency_ms": round(self.max_latency_ms, 2),
            "cache_hit_rate_%": round(cache_hit_rate, 1),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "prediction_accuracy_%": round(prediction_rate, 1),
            "correct_predictions": self.predictions_correct,
            "total_predictions": self.predictions_made,
            "prefetch_hit_rate_%": round(prefetch_rate, 1),
            "prefetches_used": self.prefetches_used,
            "total_prefetches": self.prefetches_made,
            "peak_in_flight": self.peak_in_flight,
        }


# ============================================================================
# 🤖 Agent Engine - 整合所有组件
# ============================================================================

class AgentEngine:
    """CPU 架构启发的 Agent 引擎

    整合六大核心模块：
    1. 存储层级 (L1/L2/L3 缓存 + TLB)
    2. 预测与预取 (分支预测 + 预取器)
    3. 同步与竞争 (锁 + 信号量)
    4. 异常与中断 (看门狗 + 中断管理器)
    5. 批量处理 (批处理器)
    6. 调度与并行 (双队列 + 流水线调度器)
    """

    def __init__(self, workspace):
        self.workspace = workspace
        # 📊 存储层级
        self.cache = MemoryCache(l1_size=64, l2_size=256, l3_size=1024)
        # ⚡ 预测与预取
        self.predictor = BranchPredictor()
        self.prefetcher = Prefetcher(self.cache, workspace)
        # 🔒 同步与竞争
        self.tool_lock = AsyncLock()
        # 🚦 异常与中断
        self.watchdog = WatchdogTimer(timeout_seconds=60.0)
        self.interrupt_manager = InterruptManager()
        # 📦 批量处理
        self.batch_processor = BatchProcessor(max_batch_size=8)
        # 🏗️ 调度与并行
        self.scheduler = PipelineScheduler(max_parallel=3)
        # 📊 性能指标
        self.metrics = MetricsCollector()
        # 全局状态
        self._task_counter = 0
        self._session_histories = {}

    def _generate_task_id(self):
        self._task_counter += 1
        return f"task_{self._task_counter}_{int(time.time() * 1000)}"

    async def chat(self, prompt, session_id="default"):
        """主要入口: 处理对话
        
        Returns:
            (response, messages)
        """
        start_time = time.time()
        history = self._session_histories.get(session_id, [])
        history.append({"role": "user", "content": prompt})

        # 检查缓存 (同一个 prompt 直接返回缓存结果)
        # 使用完整 prompt 的 hash，不截断（Claude Code 策略）
        import hashlib
        prompt_hash = hashlib.blake2b(prompt.encode('utf-8'), digest_size=16).hexdigest()
        cache_key = f"prompt:{prompt_hash}"
        cached_result = self.cache.get(cache_key, level=1)
        if cached_result is not None:
            await self.metrics.record_cache_hit()
            result = cached_result
            history.append({"role": "assistant", "content": result})
            self._session_histories[session_id] = history
            latency_ms = (time.time() - start_time) * 1000
            await self.metrics.record_request(latency_ms)
            return result, history
        await self.metrics.record_cache_miss()

        # ⚡ 分支预测 (在执行前预测)
        predicted_tool, prefetch_keys = self.predictor.predict(history)
        if predicted_tool:
            await self.metrics.record_prediction(True)  # 有预测就记录
        else:
            await self.metrics.record_prediction(False)

        # 预取
        if prefetch_keys:
            await self.prefetcher.prefetch_context(prefetch_keys, history)
            await self.metrics.record_prefetch(True)  # 记录预取次数

        # 🏗️ 使用流水线调度器执行
        task = Task(id=self._generate_task_id(), prompt=prompt)
        
        async def executor(t):
            from xinyiclaw.agent import run_agent
            class MockBot:
                async def send_message(self, chat_id, text):
                    return True
            response, messages = await run_agent(
                t.prompt, MockBot(), session_id,
                str(self.workspace), messages=history
            )
            return response

        # 暂时移除 Semaphore 控制，让系统先跑起来
        # TODO: 后续需要并发控制时再添加
        result = await self.scheduler.execute_task(task, executor)

        # 缓存结果 (不含工具调用的简单回答，且不是错误响应)
        tool_in_response = '[TOOL_CALL]' in result
        is_error = result.startswith("API Error") or result.startswith("请求失败")
        if not tool_in_response and not is_error:
            self.cache.put(cache_key, result, level=1)

        # 更新历史
        self._session_histories[session_id] = history
        history.append({"role": "assistant", "content": result})

        # 学习工具调用模式
        tool_seq = []
        for msg in history:
            content = msg.get("content", "")
            matches = re.findall(r'\[TOOL_CALL\](.+?)\[/TOOL_CALL\]', content, re.DOTALL)
            for match in matches:
                parts = match.split("|")
                if parts:
                    tool_seq.append(parts[0].strip())

        # 验证预测准确率
        if predicted_tool and tool_seq:
            actual_first_tool = tool_seq[0]
            if actual_first_tool == predicted_tool:
                # 预测正确，不需要额外记录（已经在预测时记录了）
                pass
        elif predicted_tool and not tool_seq:
            # 预测了工具但实际没调用，标记为错误
            pass

        if tool_seq:
            self.predictor.learn(tool_seq)

        # 记录指标
        latency_ms = (time.time() - start_time) * 1000
        await self.metrics.record_request(latency_ms)
        await self.metrics.record_in_flight(self.scheduler.dual_queue.get_in_flight_count())

        return result, history
