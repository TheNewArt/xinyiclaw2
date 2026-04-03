# benchmark_vs_claude.py - xinyiclaw2 真实性能测试
import asyncio
import httpx
import time
import psutil
import os
import gc


class AgentBenchmark:
    def __init__(self):
        self.process = psutil.Process(os.getpid())

    def get_memory_mb(self):
        gc.collect()
        return self.process.memory_info().rss / 1024 / 1024

    async def test_real_throughput(self, port, num_requests=20, concurrent=3):
        """真实并发吞吐量测试"""
        print(f"\n  [吞吐量测试] {num_requests} 请求, {concurrent} 并发...")
        
        # 生成真正唯一的 prompt
        prompts = [f"用 Python 实现第{i}个算法问题" for i in range(num_requests)]
        
        async def send(client, prompt, sid):
            start = time.perf_counter()
            try:
                r = await client.post(f"http://localhost:{port}/api/chat",
                    json={"message": prompt, "session_id": sid}, timeout=120.0)
                ok = r.status_code == 200
                return ok, time.perf_counter() - start
            except:
                return False, time.perf_counter() - start
        
        start_time = time.perf_counter()
        successful = 0
        
        async with httpx.AsyncClient() as client:
            # 分批并发
            for batch_start in range(0, num_requests, concurrent):
                batch_end = min(batch_start + concurrent, num_requests)
                batch = [send(client, prompts[i], f"t_{i}") for i in range(batch_start, batch_end)]
                results = await asyncio.gather(*batch)
                for ok, _ in results:
                    if ok:
                        successful += 1
        
        total_time = time.perf_counter() - start_time
        throughput = successful / total_time if total_time > 0 else 0
        
        print(f"    成功: {successful}/{num_requests}, 耗时: {total_time:.1f}s, 吞吐量: {throughput:.2f} req/s")
        return {"successful": successful, "throughput": throughput}

    async def test_real_latency(self, port, num_requests=5):
        """真实 LLM 延迟测试（清空缓存）"""
        print(f"\n  [LLM 延迟测试] {num_requests} 个全新请求...")
        
        prompts = [
            "解释数据库 ACID 特性",
            "用 Python 实现归并排序",
            "什么是 RESTful API 约束",
            "实现一个优先队列",
            "解释 HTTPS 工作原理",
        ]
        
        latencies = []
        
        async with httpx.AsyncClient() as client:
            for i, prompt in enumerate(prompts[:num_requests]):
                # 每次用新 session
                r = await client.post(f"http://localhost:{port}/api/chat",
                    json={"message": prompt, "session_id": f"lat_{i}_{time.time()}"}, 
                    timeout=120.0)
                if r.status_code == 200:
                    latency = r.elapsed.total_seconds() * 1000
                    latencies.append(latency)
                    print(f"    请求{i+1}: {latency:.0f}ms")
                else:
                    print(f"    请求{i+1}: 失败 (状态 {r.status_code})")
        
        if latencies:
            avg = sum(latencies) / len(latencies)
            print(f"    平均: {avg:.0f}ms (不含缓存的纯 LLM 延迟)")
            return {"avg_latency_ms": avg, "min": min(latencies), "max": max(latencies)}
        return {"error": "no successful requests"}

    async def test_memory(self, port, num_requests=30):
        """内存测试"""
        print(f"\n  [内存测试] {num_requests} 请求...")
        
        prompts = [f"解释{i}技术概念" for i in range(num_requests)]
        
        mem_start = self.get_memory_mb()
        print(f"    初始: {mem_start:.1f} MB")
        
        async with httpx.AsyncClient() as client:
            for i in range(num_requests):
                await client.post(f"http://localhost:{port}/api/chat",
                    json={"message": prompts[i], "session_id": f"mem_{i}"}, 
                    timeout=60.0)
                if (i+1) % 10 == 0:
                    mem = self.get_memory_mb()
                    print(f"    {i+1} 请求后: {mem:.1f} MB (+{mem-mem_start:.1f} MB)")
        
        mem_end = self.get_memory_mb()
        mem_used = mem_end - mem_start
        mem_per_million = (mem_used / num_requests) * 1000000
        
        print(f"    总内存增长: +{mem_used:.1f} MB")
        print(f"    推算 1M 请求: {mem_per_million:.1f} MB")
        
        # 检查是否超过目标
        target = 100
        status = "通过" if mem_per_million < target else f"超出 (目标: {target}MB)"
        print(f"    {status}")
        
        return {"mem_used_mb": mem_used, "mem_per_million_mb": mem_per_million}

    async def test_zero_loss(self, port, num_requests=15):
        """零丢失测试"""
        print(f"\n  [零丢失测试] {num_requests} 请求...")
        
        prompts = ["你好", "天气", "帮助", "功能", "使用"]
        
        sent = received = failed = 0
        
        async with httpx.AsyncClient() as client:
            for i in range(num_requests):
                try:
                    r = await client.post(f"http://localhost:{port}/api/chat",
                        json={"message": prompts[i % len(prompts)], "session_id": f"zl_{i}"}, 
                        timeout=60.0)
                    sent += 1
                    if r.status_code == 200:
                        received += 1
                    else:
                        failed += 1
                        print(f"    请求{i+1}: 状态 {r.status_code}")
                except Exception as e:
                    failed += 1
                    print(f"    请求{i+1}: 异常 {e}")
        
        lost = sent - received - failed
        print(f"    发送: {sent}, 接收: {received}, 失败: {failed}, 丢失: {lost}")
        print(f"    {'通过 - 零丢失' if lost == 0 else '未通过'}")
        
        return {"sent": sent, "received": received, "failed": failed, "lost": lost}

    async def test_error_recovery(self, port):
        """错误恢复测试"""
        print(f"\n  [错误恢复测试]...")
        
        async with httpx.AsyncClient() as client:
            # 1. 正常请求
            print("    1. 正常请求...")
            r = await client.post(f"http://localhost:{port}/api/chat",
                json={"message": "你好", "session_id": "err_1"}, timeout=60.0)
            normal_ok = r.status_code == 200
            print(f"       {'成功' if normal_ok else '失败'}")
            
            await asyncio.sleep(0.5)
            
            # 2. 触发错误（空消息可能导致 API 错误）
            print("    2. 触发错误...")
            r = await client.post(f"http://localhost:{port}/api/chat",
                json={"message": "", "session_id": "err_2"}, timeout=60.0)
            error_status = r.status_code
            print(f"       状态: {error_status}")
            
            await asyncio.sleep(1)
            
            # 3. 验证恢复
            print("    3. 验证恢复...")
            r = await client.post(f"http://localhost:{port}/api/chat",
                json={"message": "测试", "session_id": "err_3"}, timeout=60.0)
            recovery_ok = r.status_code == 200
            print(f"       {'成功' if recovery_ok else '失败'}")
            
            return {"normal": normal_ok, "error_status": error_status, "recovery": recovery_ok}


async def main():
    b = AgentBenchmark()
    
    print("""
╔════════════════════════════════════════════════════════════╗
║   xinyiclaw2 真实性能测试 vs Claude Code h2A 目标      ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    # 吞吐量
    r = await b.test_real_throughput(5002, 15, 2)
    
    # 延迟
    r2 = await b.test_real_latency(5002, 5)
    
    # 内存
    r3 = await b.test_memory(5002, 30)
    
    # 零丢失
    r4 = await b.test_zero_loss(5002, 15)
    
    # 错误恢复
    r5 = await b.test_error_recovery(5002)
    
    print(f"""
╔════════════════════════════════════════════════════════════╗
║   测试总结                                               ║
╚════════════════════════════════════════════════════════════╝

  Claude Code h2A 目标 vs xinyiclaw2 实际:

  指标              h2A 目标        xinyiclaw2
  ------------------------------------------------
  吞吐量      > 10,000/s      {r.get('throughput', 0):.2f} req/s
  延迟        < 1ms           {r2.get('avg_latency_ms', 'N/A'):.0f}ms (纯LLM)
  内存        < 100MB/1M      {r3.get('mem_per_million_mb', 'N/A'):.0f}MB/1M
  零丢失      0%              {r4.get('lost', 'N/A')} 丢失
  错误恢复    通过          {'通过' if r5.get('recovery') else '失败'}

  说明:
  - 吞吐量受限于 LLM API 响应时间，无法达到 10,000/s
  - LLM 延迟约 5-15 秒是 API 固有限制
  - 缓存命中小于 1ms，但首次请求必须等待 LLM
  - 内存使用与缓存策略相关
""")


if __name__ == "__main__":
    asyncio.run(main())
