# test_metrics.py - 测试 Metrics 功能
# 验证缓存、预测、预取是否正常工作

import asyncio
import httpx
import time


async def test_cache_hit():
    """测试缓存命中 - 发送相同 prompt 两次"""
    print("\n  [测试1] 缓存命中测试")
    print("  发送相同 prompt 两次，第二次应该命中缓存")
    
    async with httpx.AsyncClient() as client:
        prompt = "你好，测试缓存"
        
        # 第一次
        r1 = await client.post("http://localhost:5002/api/chat",
            json={"message": prompt, "session_id": "cache_test"}, timeout=60.0)
        t1 = r1.json()
        
        # 第二次 (相同 prompt)
        r2 = await client.post("http://localhost:5002/api/chat",
            json={"message": prompt, "session_id": "cache_test"}, timeout=60.0)
        t2 = r2.json()
        
        print(f"    第一次: {r1.elapsed.total_seconds()*1000:.0f}ms")
        print(f"    第二次: {r2.elapsed.total_seconds()*1000:.0f}ms")
        
        # 获取状态
        status = await client.get("http://localhost:5002/api/status", timeout=10.0)
        s = status.json()
        if "metrics" in s:
            m = s["metrics"]
            print(f"    缓存命中: {m.get('cache_hits', 0)} | 缓存未命中: {m.get('cache_misses', 0)}")
            print(f"    缓存命中率: {m.get('cache_hit_rate_%', 0):.1f}%")


async def test_prediction():
    """测试预测准确率 - 发送工具调用序列"""
    print("\n  [测试2] 预测准确率测试")
    print("  发送多轮对话，建立工具调用历史")
    
    prompts = [
        "列出台面 xinyiclaw2 目录下所有 .py 文件",
        "读取其中的 engine.py 文件",
        "在末尾添加一行注释",
    ]
    
    async with httpx.AsyncClient() as client:
        for i, p in enumerate(prompts, 1):
            r = await client.post("http://localhost:5002/api/chat",
                json={"message": p, "session_id": "pred_test"}, timeout=60.0)
            print(f"    请求{i}: {r.elapsed.total_seconds()*1000:.0f}ms")
        
        status = await client.get("http://localhost:5002/api/status", timeout=10.0)
        s = status.json()
        if "metrics" in s:
            m = s["metrics"]
            print(f"    预测准确率: {m.get('prediction_accuracy_%', 0):.1f}%")
            print(f"    预测次数: {m.get('total_predictions', 0)}")


async def test_prefetch():
    """测试预取功能"""
    print("\n  [测试3] 预取功能测试")
    
    prompts = [
        "读取 config.py 文件",
        "读取 .env 文件",
        "查看 workspace 目录",
    ]
    
    async with httpx.AsyncClient() as client:
        for i, p in enumerate(prompts, 1):
            r = await client.post("http://localhost:5002/api/chat",
                json={"message": p, "session_id": "prefetch_test"}, timeout=60.0)
            print(f"    请求{i}: {r.elapsed.total_seconds()*1000:.0f}ms")
        
        status = await client.get("http://localhost:5002/api/status", timeout=10.0)
        s = status.json()
        if "metrics" in s:
            m = s["metrics"]
            print(f"    预取次数: {m.get('total_prefetches', 0)}")
            print(f"    预取命中: {m.get('prefetches_used', 0)}")
            print(f"    预取命中率: {m.get('prefetch_hit_rate_%', 0):.1f}%")


async def show_all_metrics():
    """显示所有 metrics"""
    async with httpx.AsyncClient() as client:
        status = await client.get("http://localhost:5002/api/status", timeout=10.0)
        s = status.json()
        if "metrics" in s:
            m = s["metrics"]
            print("\n" + "=" * 50)
            print("  所有 Metrics:")
            print("=" * 50)
            print(f"  总请求数:        {m.get('total_requests', 0)}")
            print(f"  平均延迟:        {m.get('avg_latency_ms', 0):.1f}ms")
            print(f"  最小延迟:        {m.get('min_latency_ms', 0):.1f}ms")
            print(f"  最大延迟:        {m.get('max_latency_ms', 0):.1f}ms")
            print(f"  ---")
            print(f"  缓存命中:        {m.get('cache_hits', 0)}")
            print(f"  缓存未命中:      {m.get('cache_misses', 0)}")
            print(f"  缓存命中率:      {m.get('cache_hit_rate_%', 0):.1f}%")
            print(f"  ---")
            print(f"  预测次数:        {m.get('total_predictions', 0)}")
            print(f"  预测正确次数:    {m.get('correct_predictions', 0)}")
            print(f"  预测准确率:      {m.get('prediction_accuracy_%', 0):.1f}%")
            print(f"  ---")
            print(f"  预取次数:        {m.get('total_prefetches', 0)}")
            print(f"  预取命中:        {m.get('prefetches_used', 0)}")
            print(f"  预取命中率:      {m.get('prefetch_hit_rate_%', 0):.1f}%")
            print(f"  ---")
            print(f"  峰值并发:        {m.get('peak_in_flight', 0)}")


async def main():
    print("=" * 50)
    print("  Metrics 功能测试")
    print("=" * 50)
    
    await test_cache_hit()
    await test_prediction()
    await test_prefetch()
    await show_all_metrics()


if __name__ == "__main__":
    asyncio.run(main())
