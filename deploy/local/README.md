# AIRI 本地 Docker 栈

最小可用的 AIRI 本地后端 + 前端，全部跑在 Docker 里。

## 组成

| 服务 | 镜像 | 作用 | 端口 |
|---|---|---|---|
| `backend` | `node:24-trixie-slim` | SQLite 状态库、模型文件、OpenCode `/v1` 代理 | `127.0.0.1:8789` |
| `web` | `nginx:stable-alpine` | AIRI 静态站点 + 反向代理 `/api`、`/v1` | `5173` |

数据存在 Docker volume `airi-data`：

- `/data/airi.db`：SQLite，保存浏览器同步上来的设置和模型元数据
- `/data/models/*.zip`：导入的 Live2D / VRM 模型

`backend` 只监听 `127.0.0.1:8789`。Provider 的 API Key 以明文存在本地 SQLite 里，不要把这个数据库或 `8789` 端口暴露到公网。

`PUT /api/state` 是**合并**写入（只覆盖提交的键，不删除其它键），每次写入前会把上一版存进 `settings_history`。误清空后可以调用 `POST /api/state/restore` 回滚到上一版。

## 使用

首次或改了前端代码后，先在宿主机构建前端（避免在 2GB 的 Docker VM 里跑 pnpm 构建）：

```sh
cd /Users/xu/Projects/airi
./deploy/local/build-web.sh
```

启动：

```sh
docker compose -f deploy/local/docker-compose.yml up -d --build
```

访问：

```text
http://localhost:5173/
```

默认只监听本机。要让手机或局域网其它设备访问，把 `docker-compose.yml` 里的 `127.0.0.1:5173:80` 改成 `5173:80` 再 `up -d`。注意这样同网段的人也能访问 `/api/state`（里面有 Provider API Key）。

## 数据同步方式

`deploy/local/bootstrap.js` 会在应用启动前执行：

1. 从 `GET /api/state` 拉取设置，写入 `localStorage`（只同步 `settings/*`、`airi-cards`、`memory/*` 等白名单键）
2. 从 `GET /api/models` 拉取模型列表，把本地缺失的模型下载进 IndexedDB（`localforage`）
3. 启动应用
4. 每 5 秒把变化的设置推回后端；每 60 秒把本地新导入的模型上传到后端

因此换浏览器 / Profile 后，打开同一个 `http://localhost:5173/` 会自动恢复：

- Provider 配置、API Key、选中的模型
- 角色卡、记忆、UI 设置
- 导入的 Live2D / VRM 模型

不同步的内容：

- 聊天记录（存在 `keyval-store`，仍在各自浏览器里）
- 语音、图片等聊天附件

## 注意

- 前端是 PWA，第一次打开会注册 Service Worker。以后重新 `build-web.sh` 并重建镜像，页面可能提示更新；不行就强制刷新一次（`Cmd+Shift+R`），或在 DevTools → Application → Storage 里清一次站点数据。
- 设置按“最后写入的浏览器”为准做键级合并。两个浏览器同时改同一个设置时，后改的覆盖先改的。

## 资源限制

Colima 虚拟机：

```sh
colima start --cpu 2 --memory 2 --disk 60
```

容器（见 `docker-compose.yml`）：

| 服务 | CPU | 内存 |
|---|---|---|
| `backend` | 0.5 | 256 MB |
| `web` | 0.5 | 128 MB |

## 常用命令

```sh
# 状态
docker compose -f deploy/local/docker-compose.yml ps

# 日志
docker compose -f deploy/local/docker-compose.yml logs -f backend

# 重启
docker compose -f deploy/local/docker-compose.yml restart

# 停止
docker compose -f deploy/local/docker-compose.yml down

# 清空所有同步数据（慎用）
docker compose -f deploy/local/docker-compose.yml down -v
```

## 接口

```text
GET    /health
GET    /api/state
PUT    /api/state                      { "settings": { "key": "value" } }   合并写入
POST   /api/state/restore              回滚到上一版设置
GET    /api/models
PUT    /api/models/:id                 raw zip body
GET    /api/models/:id/file
DELETE /api/models/:id
ANY    /v1/*                           -> https://opencode.ai/inference/go/v1/*
```
