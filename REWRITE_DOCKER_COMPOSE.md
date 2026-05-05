# 重写 6 个机器人 docker-compose.yml 文档

本文档用于修复 6 个机器人目录里的 `docker-compose.yml` 被同步代码覆盖回默认模板的问题。

## 1. 问题原因

如果同步代码时执行过类似命令：

```bash
rsync -a --delete \
  --exclude config.json \
  --exclude data/ \
  /opt/fakabot-cluster/source/ \
  "/opt/fakabot-cluster/${bot}/fakabot/"
```

但没有排除 `docker-compose.yml`，那么每个机器人目录里已经定制好的 compose 会被 `/opt/fakabot-cluster/source/docker-compose.yml` 覆盖回默认模板。

默认模板通常包含：

```yaml
container_name: fakabot
container_name: fakabot-redis
ports:
  - "127.0.0.1:58001:58001"
  - "127.0.0.1:58002:58002"
```

这会导致多个机器人共用同一组容器名、端口、网络和 volume，启动后互相顶掉服务。

## 2. 正确目标

6 个机器人应该分别使用独立容器名和端口：

| 机器人 | Bot 容器 | Redis 容器 | HTTP 端口 | 备用端口 |
| --- | --- | --- | --- | --- |
| `bot01` | `fakabot-bot01` | `fakabot-bot01-redis` | `58201` | `58301` |
| `bot02` | `fakabot-bot02` | `fakabot-bot02-redis` | `58202` | `58302` |
| `bot03` | `fakabot-bot03` | `fakabot-bot03-redis` | `58203` | `58303` |
| `bot04` | `fakabot-bot04` | `fakabot-bot04-redis` | `58204` | `58304` |
| `bot05` | `fakabot-bot05` | `fakabot-bot05-redis` | `58205` | `58305` |
| `bot06` | `fakabot-bot06` | `fakabot-bot06-redis` | `58206` | `58306` |

所有机器人共用同一个共享扫链目录：

```text
/opt/fakabot-cluster/shared
```

每个机器人使用自己的业务数据目录：

```text
/opt/fakabot-cluster/bot01/data
/opt/fakabot-cluster/bot02/data
...
```

## 3. 先备份现有 compose

在服务器执行：

```bash
for bot in bot01 bot02 bot03 bot04 bot05 bot06; do
  cp "/opt/fakabot-cluster/${bot}/fakabot/docker-compose.yml" \
     "/opt/fakabot-cluster/${bot}/fakabot/docker-compose.yml.bak.$(date +%F-%H%M%S)"
done
```

## 4. 生成重写脚本

执行下面命令，生成 `/opt/fakabot-cluster/rewrite_bot_compose.sh`：

```bash
cat > /opt/fakabot-cluster/rewrite_bot_compose.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

for n in 1 2 3 4 5 6; do
  bot=$(printf "bot%02d" "$n")
  app_port=$((58200 + n))
  extra_port=$((58300 + n))
  dir="/opt/fakabot-cluster/${bot}/fakabot"
  compose="${dir}/docker-compose.yml"

  if [ ! -d "$dir" ]; then
    echo "ERROR: 目录不存在：$dir"
    exit 1
  fi

  echo "重写 ${bot}: ${compose}"

  cat > "$compose" <<YAML
services:
  redis:
    image: redis:7-alpine
    container_name: fakabot-${bot}-redis
    restart: unless-stopped
    command: redis-server --appendonly yes --maxmemory 128mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data_${bot}:/data
    networks:
      - fakabot_${bot}_network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: "5m"
        max-file: "2"

  sp_shop_bot:
    build: .
    container_name: fakabot-${bot}
    restart: unless-stopped
    environment:
      - TZ=Asia/Shanghai
      - REDIS_HOST=redis
      - REDIS_PORT=6379
    user: "0:0"
    ports:
      - "127.0.0.1:${app_port}:58001"
      - "127.0.0.1:${extra_port}:58002"
    volumes:
      - ./config.json:/app/config.json:ro
      - /opt/fakabot-cluster/${bot}/data:/app/data
      - /opt/fakabot-cluster/shared:/shared
    networks:
      - fakabot_${bot}_network
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c 'import urllib.request,sys; sys.exit(0 if urllib.request.urlopen(\"http://127.0.0.1:58001/health\", timeout=3).read().strip()==b\"ok\" else 1)'"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 10s
    stop_grace_period: 20s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

networks:
  fakabot_${bot}_network:
    driver: bridge

volumes:
  redis_data_${bot}:
    driver: local
YAML

  cd "$dir"
  docker compose -p "fakabot-${bot}" config >/tmp/fakabot-${bot}-compose.yml
  echo "${bot} compose ok"
done
EOF

chmod +x /opt/fakabot-cluster/rewrite_bot_compose.sh
```

## 5. 执行重写

```bash
/opt/fakabot-cluster/rewrite_bot_compose.sh
```

如果输出类似下面内容，说明 6 个 compose 文件都合法：

```text
bot01 compose ok
bot02 compose ok
bot03 compose ok
bot04 compose ok
bot05 compose ok
bot06 compose ok
```

## 6. 检查重写结果

```bash
for bot in bot01 bot02 bot03 bot04 bot05 bot06; do
  echo "===== ${bot} ====="
  grep -E 'container_name:|127.0.0.1:|/app/data|/shared|fakabot_.*_network|redis_data_' \
    "/opt/fakabot-cluster/${bot}/fakabot/docker-compose.yml"
done
```

你应该看到：

```text
bot01 -> fakabot-bot01, fakabot-bot01-redis, 58201, 58301
bot02 -> fakabot-bot02, fakabot-bot02-redis, 58202, 58302
...
bot06 -> fakabot-bot06, fakabot-bot06-redis, 58206, 58306
```

## 7. 清理旧冲突容器

如果 `docker ps` 里还有旧容器：

```text
fakabot
fakabot-redis
fakabot-redis-bot2
```

确认不再使用后停止并删除：

```bash
docker stop fakabot fakabot-redis fakabot-redis-bot2 2>/dev/null || true
docker rm fakabot fakabot-redis fakabot-redis-bot2 2>/dev/null || true
```

不要删除：

```text
fakabot-usdt-scanner
fakabot-bot01
fakabot-bot02
...
```

## 8. 一台一台重启机器人

重启 `bot01`：

```bash
cd /opt/fakabot-cluster/bot01/fakabot
docker compose -p fakabot-bot01 up -d --build redis sp_shop_bot
curl -fsS http://127.0.0.1:58201/health && echo "bot01 ok"
docker logs --tail 80 fakabot-bot01
```

重启 `bot02`：

```bash
cd /opt/fakabot-cluster/bot02/fakabot
docker compose -p fakabot-bot02 up -d --build redis sp_shop_bot
curl -fsS http://127.0.0.1:58202/health && echo "bot02 ok"
docker logs --tail 80 fakabot-bot02
```

重启 `bot03`：

```bash
cd /opt/fakabot-cluster/bot03/fakabot
docker compose -p fakabot-bot03 up -d --build redis sp_shop_bot
curl -fsS http://127.0.0.1:58203/health && echo "bot03 ok"
docker logs --tail 80 fakabot-bot03
```

重启 `bot04`：

```bash
cd /opt/fakabot-cluster/bot04/fakabot
docker compose -p fakabot-bot04 up -d --build redis sp_shop_bot
curl -fsS http://127.0.0.1:58204/health && echo "bot04 ok"
docker logs --tail 80 fakabot-bot04
```

重启 `bot05`：

```bash
cd /opt/fakabot-cluster/bot05/fakabot
docker compose -p fakabot-bot05 up -d --build redis sp_shop_bot
curl -fsS http://127.0.0.1:58205/health && echo "bot05 ok"
docker logs --tail 80 fakabot-bot05
```

重启 `bot06`：

```bash
cd /opt/fakabot-cluster/bot06/fakabot
docker compose -p fakabot-bot06 up -d --build redis sp_shop_bot
curl -fsS http://127.0.0.1:58206/health && echo "bot06 ok"
docker logs --tail 80 fakabot-bot06
```

## 9. 检查最终容器状态

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

正确状态应该类似：

```text
fakabot-bot01          127.0.0.1:58201->58001/tcp, 127.0.0.1:58301->58002/tcp
fakabot-bot01-redis    6379/tcp
fakabot-bot02          127.0.0.1:58202->58001/tcp, 127.0.0.1:58302->58002/tcp
fakabot-bot02-redis    6379/tcp
...
fakabot-bot06          127.0.0.1:58206->58001/tcp, 127.0.0.1:58306->58002/tcp
fakabot-bot06-redis    6379/tcp
fakabot-usdt-scanner   58001/tcp
```

不应该再看到：

```text
fakabot
fakabot-redis
```

## 10. 后续同步代码要排除 compose

以后同步代码时必须排除 `docker-compose.yml`：

```bash
rsync -a --delete \
  --exclude config.json \
  --exclude data/ \
  --exclude docker-compose.yml \
  /opt/fakabot-cluster/source/ \
  /opt/fakabot-cluster/scanner/fakabot/

for bot in bot01 bot02 bot03 bot04 bot05 bot06; do
  rsync -a --delete \
    --exclude config.json \
    --exclude data/ \
    --exclude docker-compose.yml \
    /opt/fakabot-cluster/source/ \
    "/opt/fakabot-cluster/${bot}/fakabot/"
done
```

如果不排除 `docker-compose.yml`，下次同步代码后会再次覆盖为默认模板。

