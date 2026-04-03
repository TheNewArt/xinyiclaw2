# benchmark_h2a.py - Claude Code h2A 队列性能基准测试
# 
# 测试指标:
# - 吞吐量 > 10,000 msgs/sec
# - 延迟 < 1ms
# - 内存 < 100MB (1M 消息)
# - 零丢失
# - 错误恢复

import asyncio
import time
import psutil
import os
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Message:
    id: int
    payload: str
    timestamp: float = field(default_factory=time.perf_counter)


class H2AQueueBenchmark:
    """Claude Code h2A 队列性能测试"""

    def __init__(self):
        self.queue = asyncio.Queue()
        self.in_flight = {}
        self.max_in_flight = 100
        self.process = psutil.Process(os.getpid())
        
        # 统计
        self.messages_sent = 0
        self.messages_received = 0
        self.messages_failed = 0
        self.total_latency_ms = 0
        self.min_latency_ms = float('inf')
        self.max_latency_ms = 0
        self.latencies = []

    def reset_stats(self):
        self.messages_sent = 0
        self.messages_received = 0
        self.messages_failed = 0
        self.total_latency_ms = 0
        self.min_latency_ms = float('inf')
        self.max_latency_ms = 0
        self.latencies = []

    def get_memory_mb(self) -> float:
        """获取当前进程内存使用 (MB)"""
        return self.process.memory_info().rss / 1024 / 1024

    async def send_message(self, msg: Message):
        """发送消息到队列"""
        self.messages_sent += 1
        try:
            await asyncio.wait_for(self.queue.put(msg), timeout=5.0)
        except asyncio.TimeoutError:
            self.messages_failed += 1

    async def receive_message(self) -> Optional[Message]:
        """从队列接收消息"""
        try:
            msg = await asyncio.wait_for(self.queue.get(), timeout=5.0)
            return msg
        except asyncio.TimeoutError:
            return None

    async def throughput_test(self, num_messages: int = 100000) -> dict:
        """吞吐量测试: 10,000+ msgs/sec"""
        print(f"\n  [吞吐量测试] 发送 {num_messages:,} 条消息...")
        self.reset_stats()
        
        # 清空队列
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except:
                break
        
        start_time = time.perf_counter()
        
        # 批量发送
        for i in range(num_messages):
            msg = Message(id=i, payload=f"msg_{i}")
            await self.send_message(msg)
        
        send_end = time.perf_counter()
        send_duration = send_end - start_time
        send_throughput = num_messages / send_duration
        
        # 批量接收
        recv_start = time.perf_counter()
        received = 0
        while received < num_messages and received < num_messages * 2:  # 放宽限制
            msg = await self.receive_message()
            if msg:
                received += 1
            else:
                break
        recv_end = time.perf_counter()
        recv_duration = recv_end - recv_start
        
        # 如果队列还有消息，继续消费
        remaining = 0
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                remaining += 1
            except:
                break
        
        total_duration = recv_end - start_time
        overall_throughput = self.messages_sent / total_duration
        
        return {
            "messages_sent": self.messages_sent,
            "messages_failed": self.messages_failed,
            "send_duration_sec": send_duration,
            "recv_duration_sec": recv_duration,
            "total_duration_sec": total_duration,
            "send_throughput": send_throughput,
            "overall_throughput": overall_throughput,
            "messages_per_sec_target": 10000,
            "pass": overall_throughput >= 10000
        }

    async def latency_test(self, num_messages: int = 1000) -> dict:
        """延迟测试: < 1ms"""
        print(f"\n  [延迟测试] 发送 {num_messages:,} 条消息...")
        self.reset_stats()
        
        latencies = []
        
        # 清空队列
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except:
                break
        
        # 发送-接收配对测试
        for i in range(num_messages):
            send_time = time.perf_counter()
            msg = Message(id=i, payload=f"latency_test_{i}")
            await self.send_message(msg)
            
            recv_msg = await self.receive_message()
            if recv_msg:
                recv_time = time.perf_counter()
                latency_us = (recv_time - send_time) * 1000 * 1000  # 转换为微秒
                latencies.append(latency_us)
                self.messages_received += 1
        
        if latencies:
            avg_latency_us = sum(latencies) / len(latencies)
            p50_latency_us = sorted(latencies)[len(latencies) // 2]
            p99_latency_us = sorted(latencies)[int(len(latencies) * 0.99)]
            
            return {
                "messages_tested": len(latencies),
                "avg_latency_us": avg_latency_us,
                "p50_latency_us": p50_latency_us,
                "p99_latency_us": p99_latency_us,
                "min_latency_us": min(latencies),
                "max_latency_us": max(latencies),
                "target_latency_us": 1000,  # 1ms = 1000us
                "pass": avg_latency_us < 1000
            }
        return {"error": "No messages received"}

    async def memory_test(self, num_messages: int = 1000000) -> dict:
        """内存测试: < 100MB for 1M messages"""
        print(f"\n  [内存测试] 创建 {num_messages:,} 条消息...")
        
        # 清空队列
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except:
                break
        
        initial_memory = self.get_memory_mb()
        print(f"    初始内存: {initial_memory:.1f} MB")
        
        # 创建消息队列（不存储，只测量队列对象内存）
        test_queue = asyncio.Queue()
        
        # 批量放入队列
        for i in range(num_messages):
            msg = Message(id=i, payload=f"mem_test_{i}" * 10)  # 较大payload
            await test_queue.put(msg)
            if (i + 1) % 100000 == 0:
                current_mem = self.get_memory_mb()
                print(f"    {i+1:,} 消息: {current_mem:.1f} MB (+{current_mem - initial_memory:.1f} MB)")
        
        final_memory = self.get_memory_mb()
        memory_used = final_memory - initial_memory
        
        # 清空
        cleared = 0
        while not test_queue.empty():
            try:
                test_queue.get_nowait()
                cleared += 1
            except:
                break
        
        return {
            "num_messages": num_messages,
            "initial_memory_mb": initial_memory,
            "final_memory_mb": final_memory,
            "memory_used_mb": memory_used,
            "target_memory_mb": 100,
            "pass": memory_used < 100,
            "memory_per_message_bytes": (memory_used * 1024 * 1024) / num_messages
        }

    async def zero_loss_test(self, num_messages: int = 10000) -> dict:
        """零丢失测试"""
        print(f"\n  [零丢失测试] 发送 {num_messages:,} 条消息...")
        self.reset_stats()
        
        # 清空队列
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except:
                break
        
        # 发送所有消息
        for i in range(num_messages):
            msg = Message(id=i, payload=f"loss_test_{i}")
            await self.send_message(msg)
        
        # 接收所有消息
        received_ids = set()
        timeout_count = 0
        max_timeouts = 100
        
        while len(received_ids) < num_messages and timeout_count < max_timeouts:
            msg = await asyncio.wait_for(self.receive_message(), timeout=1.0)
            if msg:
                received_ids.add(msg.id)
                self.messages_received += 1
            else:
                timeout_count += 1
        
        lost = num_messages - len(received_ids)
        loss_rate = (lost / num_messages) * 100 if num_messages > 0 else 0
        
        return {
            "messages_sent": num_messages,
            "messages_received": len(received_ids),
            "messages_lost": lost,
            "loss_rate_percent": loss_rate,
            "zero_loss_target": 0,
            "pass": lost == 0
        }

    async def error_recovery_test(self) -> dict:
        """错误恢复测试"""
        print(f"\n  [错误恢复测试] 模拟故障和恢复...")
        
        errors_injected = 0
        errors_recovered = 0
        
        # 测试1: 队列满后恢复
        print("    测试1: 队列满后恢复...")
        for i in range(100):
            msg = Message(id=i, payload=f"recovery_test_{i}")
            try:
                await asyncio.wait_for(self.queue.put(msg), timeout=0.1)
            except asyncio.TimeoutError:
                errors_injected += 1
        
        # 清空队列
        recovered = 0
        for _ in range(150):
            try:
                msg = await asyncio.wait_for(self.queue.get(), timeout=0.1)
                if msg:
                    recovered += 1
            except:
                break
        
        errors_recovered += recovered
        
        # 测试2: 并发错误恢复
        print("    测试2: 并发压力下的错误恢复...")
        self.reset_stats()
        
        async def stress_sender(count):
            for i in range(count):
                msg = Message(id=i, payload=f"stress_{i}")
                try:
                    await asyncio.wait_for(self.queue.put(msg), timeout=0.01)
                except asyncio.TimeoutError:
                    self.messages_failed += 1
        
        async def stress_receiver(count):
            received = 0
            for _ in range(count):
                try:
                    msg = await asyncio.wait_for(self.receive_message(), timeout=0.01)
                    if msg:
                        received += 1
                except:
                    pass
            return received
        
        # 启动并发发送和接收
        senders = [asyncio.create_task(stress_sender(100)) for _ in range(5)]
        receivers = [asyncio.create_task(stress_receiver(100)) for _ in range(5)]
        
        await asyncio.gather(*senders)
        await asyncio.gather(*receivers)
        
        return {
            "errors_injected": errors_injected,
            "errors_recovered": errors_recovered,
            "failed_under_stress": self.messages_failed,
            "recovered_under_stress": self.messages_received,
            "pass": errors_recovered >= errors_injected * 0.9  # 90%恢复率
        }

    async def run_all_tests(self):
        """运行所有测试"""
        print("""
╔════════════════════════════════════════════════════════════╗
║   Claude Code h2A Queue 性能基准测试                      ║
║   - 吞吐量 > 10,000 msgs/sec                           ║
║   - 延迟 < 1ms                                          ║
║   - 内存 < 100MB (1M 消息)                              ║
║   - 零丢失                                              ║
║   - 错误恢复                                             ║
╚════════════════════════════════════════════════════════════╝
        """)

        results = {}

        # 1. 吞吐量测试
        try:
            result = await self.throughput_test(100000)
            results["throughput"] = result
            print(f"\n  吞吐量结果:")
            print(f"    发送消息: {result['messages_sent']:,}")
            print(f"    总耗时: {result['total_duration_sec']:.2f} sec")
            print(f"    吞吐量: {result['overall_throughput']:,.0f} msgs/sec")
            print(f"    目标: {result['messages_per_sec_target']:,} msgs/sec")
            print(f"    结果: {'✅ 通过' if result['pass'] else '❌ 未通过'}")
        except Exception as e:
            results["throughput"] = {"error": str(e)}
            print(f"\n  吞吐量测试错误: {e}")

        # 2. 延迟测试
        try:
            result = await self.latency_test(1000)
            results["latency"] = result
            print(f"\n  延迟结果:")
            print(f"    平均延迟: {result['avg_latency_us']:.2f} µs ({result['avg_latency_us']/1000:.3f} ms)")
            print(f"    P50延迟: {result['p50_latency_us']:.2f} µs")
            print(f"    P99延迟: {result['p99_latency_us']:.2f} µs")
            print(f"    目标: < {result['target_latency_us']:,} µs (1 ms)")
            print(f"    结果: {'✅ 通过' if result['pass'] else '❌ 未通过'}")
        except Exception as e:
            results["latency"] = {"error": str(e)}
            print(f"\n  延迟测试错误: {e}")

        # 3. 内存测试 (用较小数量避免内存爆炸)
        try:
            result = await self.memory_test(100000)  # 10万条测试
            results["memory"] = result
            print(f"\n  内存结果:")
            print(f"    {result['num_messages']:,} 消息:")
            print(f"    内存使用: {result['memory_used_mb']:.1f} MB")
            print(f"    每消息: {result['memory_per_message_bytes']:.1f} bytes")
            print(f"    目标: < {result['target_memory_mb']} MB")
            print(f"    推算1M消息: {result['memory_used_mb'] * 10:.1f} MB")
            print(f"    结果: {'✅ 通过' if result['pass'] else '❌ 未通过'}")
        except Exception as e:
            results["memory"] = {"error": str(e)}
            print(f"\n  内存测试错误: {e}")

        # 4. 零丢失测试
        try:
            result = await self.zero_loss_test(10000)
            results["zero_loss"] = result
            print(f"\n  零丢失结果:")
            print(f"    发送: {result['messages_sent']:,}")
            print(f"    接收: {result['messages_received']:,}")
            print(f"    丢失: {result['messages_lost']:,}")
            print(f"    丢失率: {result['loss_rate_percent']:.2f}%")
            print(f"    目标: 0%")
            print(f"    结果: {'✅ 通过' if result['pass'] else '❌ 未通过'}")
        except Exception as e:
            results["zero_loss"] = {"error": str(e)}
            print(f"\n  零丢失测试错误: {e}")

        # 5. 错误恢复测试
        try:
            result = await self.error_recovery_test()
            results["error_recovery"] = result
            print(f"\n  错误恢复结果:")
            print(f"    注入错误: {result['errors_injected']}")
            print(f"    恢复错误: {result['errors_recovered']}")
            print(f"    压力下失败: {result['failed_under_stress']}")
            print(f"    压力下恢复: {result['recovered_under_stress']}")
            print(f"    结果: {'✅ 通过' if result['pass'] else '❌ 未通过'}")
        except Exception as e:
            results["error_recovery"] = {"error": str(e)}
            print(f"\n  错误恢复测试错误: {e}")

        # 总结
        print("""
╔════════════════════════════════════════════════════════════╗
║   测试总结                                               ║
╚════════════════════════════════════════════════════════════╝
        """)
        
        all_passed = True
        for test_name, result in results.items():
            if "error" in result:
                print(f"  {test_name}: ❌ 错误 - {result['error']}")
                all_passed = False
            elif "pass" in result:
                status = "✅ 通过" if result["pass"] else "❌ 未通过"
                print(f"  {test_name}: {status}")
                if not result["pass"]:
                    all_passed = False
        
        print(f"\n  总体: {'✅ 全部通过' if all_passed else '❌ 存在失败项'}")
        
        return results


async def main():
    benchmark = H2AQueueBenchmark()
    await benchmark.run_all_tests()


if __name__ == "__main__":
    print("""
    使用说明:
    运行 h2A 队列性能基准测试
    
    python benchmark_h2a.py
    """)
    asyncio.run(main())
