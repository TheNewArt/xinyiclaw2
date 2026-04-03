# XinyiClaw 2 - CPU 架构启发的 Agent 引擎

## 核心理念

当我们在设计 LLM Agent 系统时，CPU 几十年的架构演进提供了极其成熟的参考。本项目将 CPU 架构中的核心设计思想融入 Agent 引擎，探索如何构建更高效、更可控的 Agent 系统。

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Agent Engine                                │
├─────────────┬─────────────┬─────────────┬─────────────┬────────────┤
│  存储层级   │  预测与预取  │  同步与竞争  │  异常与中断  │  批量处理  │
│  MemoryCache│ BranchPred  │ AsyncLock   │ Watchdog    │ BatchProc  │
│  L1/L2/L3  │ Prefetcher  │ Semaphore   │ InterruptMgr│            │
│  + TLB      │             │             │             │            │
├─────────────┴─────────────┴─────────────┴─────────────┴────────────┤
│                    调度与并行 PipelineScheduler                      │
│                    DualQueue (双队列)                               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 核心模块详解

### 1. 📊 存储层级 (Storage Hierarchy)

**CPU 启示：** CPU 使用 L1/L2/L3 多级缓存来弥合高速 CPU 与慢速内存之间的速度鸿沟，TLB 提供快速的虚拟地址到物理地址的转换。

**Agent 实现 - MemoryCache：**

```python
class MemoryCache:
    # L1: 热点结果缓存 (LRU, 小容量 64 条, 快速)
    # L2: 上下文片段缓存 (中等容量 256 条)
    # L3: 长期记忆索引 (大容量 1024 条)
    # TLB: 快速查找表 (128 条)
```

**类比：**
| CPU | Agent |
|-----|-------|
| L1 Cache | 工具执行结果缓存 |
| L2 Cache | 对话片段缓存 |
| L3 Cache | 长期记忆索引 |
| TLB | 记忆地址快速查找 |

---

### 2. ⚡ 预测与预取 (Prediction & Prefetch)

**CPU 启示：** 分支预测避免流水线停顿，预取机制在数据被需要之前就将其加载到缓存。

**BranchPredictor - 分支预测：**
```python
# 基于历史工具调用序列学习预测下一个工具
tool_patterns = {
    ("Read", "Edit"): "Write",  # 读完再编辑，然后写
    ("Glob", "Read"): "Bash",   # 查文件再执行命令
}
```

**Prefetcher - 预取器：**
```python
# 预测到下一步需要读取某文件，提前加载到 L2 缓存
async def prefetch_context(self, context_keys, history):
    # 预取可能需要的文件内容
```

**类比：**
| CPU | Agent |
|-----|-------|
| Branch Prediction | 预测下一步工具调用 |
| Pre-fetch | 提前加载可能需要的上下文/文件 |
| Branch Target Buffer | 工具调用模式库 |

---

### 3. 🔒 同步与竞争 (Synchronization)

**CPU 启示：** 多核系统需要锁、信号量来协调并发访问共享资源。

**AsyncLock - 互斥锁：**
```python
async with self.tool_lock:
    # 同一时刻只有一个任务执行关键区域
    await execute_critical_tool()
```

**Semaphore - 信号量：**
```python
# 控制同时执行的任务数量（类似 CPU 的执行单元数量）
self.api_semaphore = Semaphore(3)  # 最多 3 个并发 API 调用
```

**类比：**
| CPU | Agent |
|-----|-------|
| Mutex | 工具互斥访问 |
| Semaphore | 并发数限制 |
| Memory Barrier | 确保工具执行顺序 |

---

### 4. 🚦 异常与中断 (Exception & Interrupt)

**CPU 启示：** 看门狗定时器检测系统异常，中断机制处理紧急任务。

**WatchdogTimer - 看门狗：**
```python
# 如果工具执行超过 60 秒没有响应，强制终止
watchdog.start(task_id)
# 如果超时...
logger.warning(f"Watchdog timeout: {task_id}")
task.cancel()
```

**InterruptManager - 中断管理：**
```python
# 紧急任务可以插入当前执行流程
await interrupt_manager.raise_interrupt(priority=1, handler=urgent_handler)
# 优先级高的任务先执行
```

**类比：**
| CPU | Agent |
|-----|-------|
| Watchdog Timer | 工具超时保护 |
| Interrupt Controller | 紧急任务优先处理 |
| Exception Handler | 工具执行失败的 Fallback |

---

### 5. 📦 批量处理 (Batch Processing)

**CPU 启示：** SIMD/向量化指令单次操作多个数据，显著提升吞吐量。

**BatchProcessor - 批量处理器：**
```python
# 将多个相似请求打包处理
self.batch_processor = BatchProcessor(max_batch_size=8)

# 等待最多 50ms 收集批量项，然后一次性处理
results = await batch_processor.submit(item_id, data)
```

**类比：**
| CPU | Agent |
|-----|-------|
| SIMD | 批量工具调用 |
| Vectorization | 批量推理请求 |
| DMA | 工具直接写共享内存 |

---

### 6. 🏗️ 调度与并行 (Scheduling & Parallelism)

**CPU 启示：** 双发射允许一个时钟周期发出两条指令，流水线让多条指令并行经过不同阶段。

**DualQueue - 双队列：**
```python
class DualQueue:
    pending: asyncio.Queue()    # 待执行队列
    in_flight: OrderedDict()   # 执行中队列 (in-flight instructions)
    done: asyncio.Queue()      # 完成队列
    max_in_flight = 3          # 最多 3 个任务同时执行
```

**PipelineScheduler - 流水线调度：**
```python
# 任务分阶段：
# 1. Decode - 理解任务
# 2. Execute - 执行工具
# 3. Retire - 提交结果
```

**类比：**
| CPU | Agent |
|-----|-------|
| Dual-issue | 双队列并行执行 |
| Pipeline | 任务分阶段流水处理 |
| Out-of-Order | 独立任务乱序执行 |
| Reservation Station | 任务等待资源就绪 |

---

## 数据流示例

```
用户输入: "读取 config.py，然后在末尾添加一行"
    │
    ▼
┌─────────────────┐
│ BranchPredictor │  ← 预测: Read → Edit/Write
│   (分支预测)     │
└────────┬────────┘
         │ 预测需要读取 config.py
         ▼
┌─────────────────┐
│   Prefetcher    │  ← 提前加载 config.py 到 L2 缓存
│    (预取器)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  DualQueue      │  ← task 进入 pending 队列
│   (双队列)       │  ← dispatch 到 in_flight
└────────┬────────┘
         │
    并行执行
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌───────┐
│ L1    │ │ L1    │  ← 工具结果缓存
│ Cache │ │ Cache │
└───┬───┘ └───┬───┘
    │         │
    └────┬────┘
         ▼
┌─────────────────┐
│  Semaphore      │  ← 控制并发数
│  (信号量)        │
└─────────────────┘
```

---

## 快速开始

```bash
# 安装依赖
uv sync

# 启动
uv run python -m src.web_app

# 访问
http://localhost:5000
```

---

## API

### POST /api/chat
```json
{
  "message": "读取 config.py",
  "session_id": "default"
}
```

### GET /api/status
查看引擎实时状态和性能指标：

```json
{
  "metrics": {
    "total_requests": 42,
    "avg_latency_ms": 1234.5,
    "min_latency_ms": 234.1,
    "max_latency_ms": 5678.9,
    "cache_hit_rate_%": 35.2,
    "cache_hits": 15,
    "cache_misses": 27,
    "prediction_accuracy_%": 68.5,
    "correct_predictions": 37,
    "total_predictions": 54,
    "prefetch_hit_rate_%": 42.0,
    "prefetches_used": 8,
    "total_prefetches": 19,
    "peak_in_flight": 3
  }
}
```

### 如何衡量效率提升？

1. **延迟** — `avg_latency_ms` 越低越好
2. **缓存命中率** — `cache_hit_rate_%` 越高越好（减少重复计算）
3. **预测准确率** — `prediction_accuracy_%` 越高（减少等待）
4. **预取命中率** — `prefetch_hit_rate_%` 越高（减少 I/O 等待）
5. **并发峰值** — `peak_in_flight` 反映并行利用程度

### POST /api/clear
清除会话

---

## 架构优势

1. **高吞吐** - 双队列 + 流水线并行处理，批量请求合并 API 调用
2. **低延迟** - 多级缓存 + TLB 减少重复计算，预取减少 I/O 等待
3. **可控** - 看门狗防死循环，信号量限制并发防止 API 超出限额
4. **可预测** - 分支预测提前准备资源，减少 LL 推理等待
5. **容错** - 中断机制处理异常，不让单个失败影响整体

---

## 未来方向

- [ ] 实现真正的工具调用批量处理（SIMD 风格的批量 LLM 调用）
- [ ] 添加缓存持久化（断电不丢失记忆）
- [ ] 多 Agent 协调（流水线上的多个 Worker Agent）
- [ ] 学习式预测（用简单模型替代规则预测）

---

*受 CPU 架构启发，为 LLM Agent 系统提供更高效、更可控的执行框架。*

---

## 🐛 Bug Log

| 日期 | 问题 | 修复 | 状态 |
|-----|------|------|------|
| 2026-04-03 | `Semaphore` 对象不支持 async context manager 协议，导致 `'Semaphore' object does not support the asynchronous context manager protocol` | 直接使用 `asyncio.Semaphore` 替代自定义包装类 | ✅ 已修复 |
| 2026-04-03 | Metrics 显示全是 0%：缓存定义了但没实际使用、预测准确率和预取命中率没有记录 | 添加 `record_cache_hit/miss`，修复 Prefetcher 返回值，添加 test_metrics.py 验证 | ✅ 已修复 |
| 2026-04-03 | demo_realtime.py 运行时报 UnicodeEncodeError (GBK 无法编码 emoji) | 移除 emoji，使用中文符号替代 | ✅ 已修复 |
| 2026-04-03 | MiniMax API 返回 520 错误时没有重试，直接把错误 JSON 当结果返回 | 添加 520 自动重试（最多3次），检查 base_resp.status_code，错误响应不缓存 | ✅ 已修复 |
| 2026-04-03 | "API Error 0:" — status_code=0 被当作最终错误而非可重试状态 | 将 status_code=0 加入可重试错误列表（与520同等处理） | ✅ 已修复 |
| 2026-04-03 | 缓存 key 用 `prompt[:100]` 截断，导致"两数之和 vs 三数之和"等相似问题误命中 | 改用 `blake2b` 完整 hash（Claude Code 策略） | ✅ 已修复 |

---

## 📈 Benchmark 结果 (2026-04-03)

### 测试结果分析

**注意：** 上述 98.4% 提升**主要来自缓存生效**，而非纯架构优化。

| 测试场景 | 结果 | 说明 |
|---------|------|------|
| 重复 prompt | 259ms vs 15,905ms | 缓存命中，真正的 LLM 调用只需一次 |
| 全新 prompt | ~12s (首次) | 缓存未命中，需要真实 API 调用 |

**真正的架构优化效果：**
- 信号量和并发控制让请求调度更稳定
- 错误处理和重试机制避免 API 错误导致失败
- 缓存对重复问题的加速效果显著（95%+ 提升）

### 测试脚本

- `benchmark.py` - 完整基准测试
- `demo_realtime.py` - 实时对比演示
- `test_metrics.py` - Metrics 功能专项测试
- `test_fair.py` - 公平测试（含调试）

## h2A 队列性能测试 (Claude Code 标准)

| 指标 | 目标 | 实际结果 | 状态 |
|------|------|----------|------|
| 吞吐量 | > 10,000 msgs/sec | 131,565 msgs/sec | 通过 |
| 延迟 | < 1ms | 0.01 ms (9.52us) | 通过 |
| 内存 | < 100MB (1M消息) | ~312MB (推算) | 超出 |
| 零丢失 | 0% | 0% | 通过 |
| 错误恢复 | 90%+ | 100% | 通过 |
