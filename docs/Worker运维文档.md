# Worker 运维文档

## 概述

FakaBot 平台包含 3 个后台 Worker 进程，负责异步处理任务：

1. **报表生成 Worker** - 处理订单、商品、库存等报表导出
2. **订阅生命周期 Worker** - 自动管理订阅状态转换
3. **支付回调重试 Worker** - 重试失败的支付回调

---

## 1. 报表生成 Worker

### 功能
- 定期扫描 `pending` 状态的报表任务
- 生成 CSV 文件并保存到文件存储
- 更新任务状态为 `completed` 或 `failed`
- 自动清理过期的报表文件

### 支持的报表类型
- `orders` - 订单报表
- `payments` - 支付记录报表
- `inventory` - 库存统计报表
- `ledger` - 账本流水报表
- `products` - 商品信息报表（新增）

### 运行参数
- **运行间隔**: 30秒
- **每次处理数量**: 最多5个任务
- **超时时间**: 无限制（由数据库查询超时控制）

### 监控指标
- 处理任务数量
- 处理成功/失败比例
- 平均处理时长
- 生成文件大小

### 常见问题

#### 报表任务一直 pending
**原因**: Worker 未启动或处理失败
**排查**:
```bash
# 检查 Worker 状态
sudo systemctl status fakabot-report-worker

# 查看日志
sudo journalctl -u fakabot-report-worker -n 100
```

#### 报表生成失败
**原因**: 数据库查询超时、文件权限问题、磁盘空间不足
**排查**:
```bash
# 检查磁盘空间
df -h

# 检查文件存储目录权限
ls -la /www/wwwroot/fakabot/storage/exports/

# 查看错误日志
sudo journalctl -u fakabot-report-worker | grep ERROR
```

---

## 2. 订阅生命周期 Worker

### 功能
自动处理订阅状态转换：

- **试用期结束** → 检查付款 → 转 active/grace
- **当前周期结束** → 检查续费 → 转 active/grace
- **宽限期结束** → 暂停服务 → suspended
- **保留期结束** → 标记待清理（不删除数据）

### 状态机
```
trial → active (有付款) / grace (无付款)
      ↓
active → active (已续费) / grace (未续费)
       ↓
grace → active (补付款) / suspended (宽限到期)
      ↓
suspended → (数据保留期 30天)
          ↓
      标记待清理
```

### 运行参数
- **运行间隔**: 1小时
- **每次处理数量**: 每个状态最多100个
- **通知发送**: TODO（当前只记录日志）

### 监控指标
- 试用期结束数量
- 周期结束数量
- 宽限期结束数量
- 保留期结束数量

### 常见问题

#### 订阅状态未自动更新
**原因**: Worker 未运行或时间检查逻辑问题
**排查**:
```bash
# 检查 Worker 状态
sudo systemctl status fakabot-subscription-worker

# 查看最近处理记录
sudo journalctl -u fakabot-subscription-worker | grep "Processed subscription"

# 手动检查订阅状态
psql -d fakabot -c "SELECT id, tenant_id, status, trial_ends_at, current_period_ends_at, grace_ends_at FROM tenant_subscriptions WHERE status IN ('trial', 'active', 'grace');"
```

#### 服务被意外暂停
**原因**: 宽限期设置过短、续费失败
**解决**: 平台管理员可通过 Admin Web 手动调整订阅周期或状态

---

## 3. 支付回调重试 Worker

### 功能
- 定期扫描失败的支付回调
- 指数退避重试（1min、5min、30min）
- 最多重试3次
- 超过24小时不再重试

### 重试策略
| 重试次数 | 退避时间 |
|---------|---------|
| 第1次 | 1分钟后 |
| 第2次 | 5分钟后 |
| 第3次 | 30分钟后 |

### 运行参数
- **运行间隔**: 5分钟
- **每次处理数量**: 最多20个回调
- **最大重试年龄**: 24小时

### 监控指标
- 重试回调数量
- 重试成功率
- 超过最大重试次数的回调数量

### 常见问题

#### 回调一直重试失败
**原因**: 订单状态异常、支付金额不匹配、签名验证失败
**排查**:
```bash
# 查看失败回调
psql -d fakabot -c "SELECT id, order_id, provider, process_status, failure_reason, retry_count FROM payment_callbacks WHERE process_status = 'failed' ORDER BY created_at DESC LIMIT 10;"

# 查看重试日志
sudo journalctl -u fakabot-payment-retry-worker | grep "Retrying payment callback"
```

#### 回调重试成功但订单未更新
**原因**: 重试逻辑未完全实现（TODO）
**解决**: 当前版本只更新重试计数，完整回调处理逻辑待补充

---

## 健康检查

### 心跳监控
每个 Worker 定期更新心跳到 Redis：

```bash
# 检查心跳（需要 Redis）
redis-cli GET worker:report-worker:heartbeat
redis-cli GET worker:subscription-worker:heartbeat
redis-cli GET worker:payment-retry-worker:heartbeat
```

心跳超时时间为运行间隔的3倍。

### 进程监控
```bash
# 检查进程是否运行
ps aux | grep "workers"

# 检查 systemd 服务状态
sudo systemctl status fakabot-*-worker
```

### 日志监控
```bash
# 实时监控所有 Worker 日志
sudo journalctl -u fakabot-report-worker -u fakabot-subscription-worker -u fakabot-payment-retry-worker -f

# 查看错误日志
sudo journalctl -u fakabot-*-worker | grep -E "ERROR|CRITICAL"

# 统计今天处理的任务数量
sudo journalctl -u fakabot-report-worker --since today | grep "Processed"
```

---

## 性能优化

### 报表生成优化
- 使用流式写入大批量数据
- 分批查询避免内存溢出
- 临时文件写入完成后再移动到正式路径

### 订阅 Worker 优化
- 使用数据库行锁避免并发冲突 (`with_for_update(skip_locked=True)`)
- 批量处理避免频繁数据库往返
- 分别处理不同状态避免单次查询过大

### 支付重试优化
- 限制每次处理数量避免阻塞
- 使用退避时间避免过度重试
- 记录重试历史便于排查问题

---

## 故障排查清单

### Worker 无法启动
1. 检查 Python 虚拟环境是否激活
2. 检查环境变量是否正确加载
3. 检查数据库连接是否正常
4. 检查文件权限和工作目录

### Worker 频繁重启
1. 检查是否有未捕获的异常
2. 检查数据库连接池是否耗尽
3. 检查内存是否不足
4. 查看详细错误日志

### 任务处理缓慢
1. 检查数据库性能（慢查询）
2. 检查磁盘 I/O 性能
3. 检查并发处理数量是否合理
4. 考虑增加 Worker 实例

### 数据不一致
1. 检查事务是否正确提交
2. 检查并发控制是否生效
3. 检查审计日志完整性
4. 手动核对数据库状态

---

## 备份和恢复

### Worker 配置备份
```bash
# 备份 systemd service 文件
sudo cp /etc/systemd/system/fakabot-*-worker.service ~/backup/

# 备份环境变量
cp /www/wwwroot/fakabot/.env ~/backup/
```

### 报表文件备份
```bash
# 备份报表存储目录
tar -czf reports_backup_$(date +%Y%m%d).tar.gz /www/wwwroot/fakabot/storage/exports/
```

---

## 升级和维护

### Worker 代码更新
```bash
# 拉取最新代码
cd /www/wwwroot/fakabot
git pull

# 重启 Worker
sudo systemctl restart fakabot-report-worker
sudo systemctl restart fakabot-subscription-worker
sudo systemctl restart fakabot-payment-retry-worker
```

### 数据库迁移后重启
```bash
# 执行迁移
alembic upgrade head

# 重启所有 Worker
sudo systemctl restart fakabot-*-worker
```

---

## 联系支持

遇到无法解决的问题，请收集以下信息：

1. Worker 状态输出
2. 最近1小时的日志
3. 数据库相关表的状态快照
4. 系统资源使用情况（CPU、内存、磁盘）

联系方式：TODO
