# Systemd Service 文件示例

## 报表生成 Worker

文件路径: `/etc/systemd/system/fakabot-report-worker.service`

```ini
[Unit]
Description=FakaBot Report Worker
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=fakabot
WorkingDirectory=/www/wwwroot/fakabot
Environment="PYTHONPATH=/www/wwwroot/fakabot"
Environment="PYTHONDONTWRITEBYTECODE=1"
EnvironmentFile=/www/wwwroot/fakabot/.env
ExecStart=/www/wwwroot/fakabot/.venv/bin/python -m workers.report_worker
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

## 订阅生命周期 Worker

文件路径: `/etc/systemd/system/fakabot-subscription-worker.service`

```ini
[Unit]
Description=FakaBot Subscription Worker
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=fakabot
WorkingDirectory=/www/wwwroot/fakabot
Environment="PYTHONPATH=/www/wwwroot/fakabot"
Environment="PYTHONDONTWRITEBYTECODE=1"
EnvironmentFile=/www/wwwroot/fakabot/.env
ExecStart=/www/wwwroot/fakabot/.venv/bin/python -m workers.subscription_worker
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

## 支付回调重试 Worker

文件路径: `/etc/systemd/system/fakabot-payment-retry-worker.service`

```ini
[Unit]
Description=FakaBot Payment Retry Worker
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=fakabot
WorkingDirectory=/www/wwwroot/fakabot
Environment="PYTHONPATH=/www/wwwroot/fakabot"
Environment="PYTHONDONTWRITEBYTECODE=1"
EnvironmentFile=/www/wwwroot/fakabot/.env
ExecStart=/www/wwwroot/fakabot/.venv/bin/python -m workers.payment_retry_worker
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

## 启用和管理服务

```bash
# 重载 systemd 配置
sudo systemctl daemon-reload

# 启用服务（开机自启）
sudo systemctl enable fakabot-report-worker
sudo systemctl enable fakabot-subscription-worker
sudo systemctl enable fakabot-payment-retry-worker

# 启动服务
sudo systemctl start fakabot-report-worker
sudo systemctl start fakabot-subscription-worker
sudo systemctl start fakabot-payment-retry-worker

# 查看状态
sudo systemctl status fakabot-report-worker
sudo systemctl status fakabot-subscription-worker
sudo systemctl status fakabot-payment-retry-worker

# 查看日志
sudo journalctl -u fakabot-report-worker -f
sudo journalctl -u fakabot-subscription-worker -f
sudo journalctl -u fakabot-payment-retry-worker -f

# 停止服务
sudo systemctl stop fakabot-report-worker
sudo systemctl stop fakabot-subscription-worker
sudo systemctl stop fakabot-payment-retry-worker

# 重启服务
sudo systemctl restart fakabot-report-worker
sudo systemctl restart fakabot-subscription-worker
sudo systemctl restart fakabot-payment-retry-worker
```

## 批量管理脚本

```bash
# scripts/workers-start.sh
#!/bin/bash
sudo systemctl start fakabot-report-worker
sudo systemctl start fakabot-subscription-worker
sudo systemctl start fakabot-payment-retry-worker
echo "All workers started"

# scripts/workers-stop.sh
#!/bin/bash
sudo systemctl stop fakabot-report-worker
sudo systemctl stop fakabot-subscription-worker
sudo systemctl stop fakabot-payment-retry-worker
echo "All workers stopped"

# scripts/workers-status.sh
#!/bin/bash
sudo systemctl status fakabot-report-worker --no-pager
sudo systemctl status fakabot-subscription-worker --no-pager
sudo systemctl status fakabot-payment-retry-worker --no-pager
```
