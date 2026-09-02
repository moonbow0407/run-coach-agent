"""Phase 5 durable workers。

本包实现“本地消息表（outbox）→ arq 队列 → 幂等消费”的后台执行链路。
"""
