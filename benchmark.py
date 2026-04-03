# benchmark.py - 性能基准测试
# 对比旧版 (port 5000) vs 新版 CPU架构启发版 (port 5002)

import asyncio
import httpx
import time
import statistics
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BenchmarkResult:
    project_name: str
    port: int
    requests: int
    latencies_ms: list = field(default_factory=list)
    errors: int = 0
    avg_latency_ms: float = 0
    min_latency_ms: float = 0
    max_latency_ms: float = 0
    p50_latency_ms: float = 0
    p95_latency_ms: float = 0
    p99_latency_ms: float = 0
    throughput_rps: float = 0

    def calculate(self):
        if self.latencies_ms:
            self.avg_latency_ms = statistics.mean(self.latencies_ms)
            self.min_latency_ms = min(self.latencies_ms)
            self.max_latency_ms = max(self.latencies_ms)
            self.p50_latency_ms = statistics.median(self.latencies_ms)
            sorted_latencies = sorted(self.latencies_ms)
            self.p95_latency_ms = sorted_latencies[int(len(sorted_latencies) * 0.95)]
            self.p99_latency_ms = sorted_latencies[int(len(sorted_latencies) * 0.99)]
        total_time = sum(self.latencies_ms) / 1000 if self.latencies_ms else 1
        self.throughput_rps = self.requests / total_time if total_time > 0 else 0


async def send_request(client: httpx.AsyncClient, port: int, message: str, session_id: str) -> tuple[bool, float]:
    """发送请求并返回 (是否成功, 延迟ms)"""
    start = time.perf_counter()
    try:
        response = await client.post(
            f"http://localhost:{port}/api/chat",
            json={"message": message, "session_id": session_id},
            timeout=120.0
        )
        latency = (time.perf_counter() - start) * 1000
        return response.status_code == 200, latency
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        print(f"      请求失败: {e}")
        return False, latency


async def send_status_request(client: httpx.AsyncClient, port: int) -> Optional[dict]:
    """获取 /api/status"""
    try:
        response = await client.get(f"http://localhost:{port}/api/status", timeout=10.0)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None


async def clear_session(client: httpx.AsyncClient, port: int, session_id: str):
    """清除会话"""
    try:
        await client.post(f"http://localhost:{port}/api/clear", json={"session_id": session_id}, timeout=10.0)
    except:
        pass


async def benchmark_project(name: str, port: int, prompts: list[str], concurrent: int = 1) -> BenchmarkResult:
    """对一个项目进行基准测试"""
    print(f"\n{'='*60}")
    print(f"  开始测试: {name} (端口 {port})")
    print(f"{'='*60}")

    result = BenchmarkResult(project_name=name, port=port, requests=len(prompts))
    
    async with httpx.AsyncClient() as client:
        # 清除之前的会话
        await clear_session(client, port, "benchmark")
        await asyncio.sleep(0.5)

        # 串行测试（每次请求等上一次完成）
        print(f"\n  [1/2] 串行测试 ({len(prompts)} 个请求)...")
        for i, prompt in enumerate(prompts):
            success, latency = await send_request(client, port, prompt, "benchmark")
            result.latencies_ms.append(latency)
            if not success:
                result.errors += 1
            print(f"      请求 {i+1}/{len(prompts)}: {latency:.1f}ms {'✓' if success else '✗'}")

        # 并发测试
        print(f"\n  [2/2] 并发测试 ({concurrent} 并发)...")
        start_time = time.perf_counter()
        
        tasks = []
        for i in range(concurrent):
            prompt = prompts[i % len(prompts)]
            tasks.append(send_request(client, port, prompt, f"benchmark_concurrent_{i}"))
        
        results = await asyncio.gather(*tasks)
        for success, latency in results:
            if success:
                result.latencies_ms.append(latency)
            else:
                result.errors += 1
        
        concurrent_time = time.perf_counter() - start_time
        print(f"      {concurrent} 个并发请求耗时: {concurrent_time*1000:.1f}ms")

        # 获取状态（仅新版有完整 metrics）
        print(f"\n  [状态] /api/status")
        status = await send_status_request(client, port)
        if status:
            if "metrics" in status:
                m = status["metrics"]
                print(f"      总请求数: {m.get('total_requests', 'N/A')}")
                print(f"      平均延迟: {m.get('avg_latency_ms', 'N/A')}ms")
                print(f"      缓存命中率: {m.get('cache_hit_rate_%', 'N/A')}%")
                print(f"      预测准确率: {m.get('prediction_accuracy_%', 'N/A')}%")
                print(f"      预取命中率: {m.get('prefetch_hit_rate_%', 'N/A')}%")
                print(f"      峰值并发: {m.get('peak_in_flight', 'N/A')}")
            else:
                print(f"      (旧版项目，无 metrics)")

    result.calculate()
    return result


def print_comparison(old_result: BenchmarkResult, new_result: BenchmarkResult):
    """打印对比结果"""
    print(f"\n{'='*60}")
    print(f"  📊 性能对比结果")
    print(f"{'='*60}")

    def improvement(old_val, new_val, lower_is_better=True):
        if old_val == 0:
            return "N/A"
        pct = ((old_val - new_val) / old_val) * 100
        if pct > 0:
            return f"+{pct:.1f}%" if lower_is_better else f"-{pct:.1f}%"
        else:
            return f"{pct:.1f}%" if lower_is_better else f"+{-pct:.1f}%"

    print(f"\n  {'指标':<20} {'旧版 (5000)':<15} {'新版 (5002)':<15} {'提升':<12}")
    print(f"  {'-'*62}")
    print(f"  {'总请求数':<20} {old_result.requests:<15} {new_result.requests:<15} {'-':<12}")
    print(f"  {'错误数':<20} {old_result.errors:<15} {new_result.errors:<15} {'-':<12}")
    print(f"  {'平均延迟 (ms)':<20} {old_result.avg_latency_ms:<15.1f} {new_result.avg_latency_ms:<15.1f} {improvement(old_result.avg_latency_ms, new_result.avg_latency_ms):<12}")
    print(f"  {'最小延迟 (ms)':<20} {old_result.min_latency_ms:<15.1f} {new_result.min_latency_ms:<15.1f} {improvement(old_result.min_latency_ms, new_result.min_latency_ms):<12}")
    print(f"  {'最大延迟 (ms)':<20} {old_result.max_latency_ms:<15.1f} {new_result.max_latency_ms:<15.1f} {improvement(old_result.max_latency_ms, new_result.max_latency_ms):<12}")
    print(f"  {'P50 延迟 (ms)':<20} {old_result.p50_latency_ms:<15.1f} {new_result.p50_latency_ms:<15.1f} {improvement(old_result.p50_latency_ms, new_result.p50_latency_ms):<12}")
    print(f"  {'P95 延迟 (ms)':<20} {old_result.p95_latency_ms:<15.1f} {new_result.p95_latency_ms:<15.1f} {improvement(old_result.p95_latency_ms, new_result.p95_latency_ms):<12}")
    print(f"  {'P99 延迟 (ms)':<20} {old_result.p99_latency_ms:<15.1f} {new_result.p99_latency_ms:<15.1f} {improvement(old_result.p99_latency_ms, new_result.p99_latency_ms):<12}")
    print(f"  {'吞吐量 (req/s)':<20} {old_result.throughput_rps:<15.1f} {new_result.throughput_rps:<15.1f} {improvement(old_result.throughput_rps, new_result.throughput_rps, lower_is_better=False):<12}")

    print(f"\n  💡 总结:")
    avg_improvement = ((old_result.avg_latency_ms - new_result.avg_latency_ms) / old_result.avg_latency_ms * 100) if old_result.avg_latency_ms > 0 else 0
    if avg_improvement > 0:
        print(f"     新版平均延迟比旧版快了 {avg_improvement:.1f}%")
    elif avg_improvement < 0:
        print(f"     旧版平均延迟比新版快了 {-avg_improvement:.1f}%")
    else:
        print(f"     两版本平均延迟相当")


async def main():
    print("""
╔════════════════════════════════════════════════════════════╗
║         XinyiClaw 性能基准测试                           ║
║   对比: 旧版 (port 5000) vs 新版 CPU架构启发 (port 5002)  ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    # 测试用的 prompts
    prompts = [
        "你好，介绍一下你自己",
        "写一个快速排序算法",
        "什么是 CPU 的流水线？",
        "用 Python 写一个计算器",
        "解释一下什么是 LRU 缓存",
    ]

    # 先测试旧版
    old_result = await benchmark_project("旧版 (xinyiclaw-py-web)", 5000, prompts)
    
    # 等待一下再测新版
    await asyncio.sleep(2)
    
    # 测试新版
    new_result = await benchmark_project("新版 (xinyiclaw2 - CPU架构启发)", 5002, prompts)
    
    # 打印对比
    print_comparison(old_result, new_result)


if __name__ == "__main__":
    print("""
    使用说明:
    1. 确保两个项目都在运行:
       - 旧版: python -m src.web_app  (端口 5000)
       - 新版: python -m src.web_app  (端口 5002)
    
    2. 运行测试:
       python benchmark.py
    """)
    asyncio.run(main())
