<p align="center">
  <img src="web-vue/public/logo.svg?v=0.1.0" width="96" alt="JoveMage logo">
</p>

<h1 align="center">JoveMage</h1>

<p align="center">
  把 ChatGPT 网页版能力封装为 OpenAI / Anthropic 兼容 API 的自托管控制台
</p>

<p align="center">
  <a href="https://github.com/jiujiu532/JoveMage/stargazers"><img src="https://img.shields.io/github/stars/jiujiu532/JoveMage?style=flat-square&logo=github" alt="GitHub stars"></a>
  <a href="VERSION"><img src="https://img.shields.io/badge/version-v0.1.0-2563eb?style=flat-square" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-f97316?style=flat-square" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-≥3.13-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.136-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://vuejs.org/"><img src="https://img.shields.io/badge/Vue-3.5-42b883?style=flat-square&logo=vuedotjs&logoColor=white" alt="Vue"></a>
  <a href="https://github.com/jiujiu532/JoveMage/pkgs/container/jovemage"><img src="https://img.shields.io/badge/GHCR-jiujiu532%2Fjovemage-black?style=flat-square&logo=docker&logoColor=white" alt="GHCR"></a>
</p>

<p align="center">
  <a href="README.md">中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="https://github.com/jiujiu532/JoveMage/releases">Releases</a> ·
  <a href="docs/deployment.md">部署文档</a>
</p>

---

JoveMage 将 ChatGPT 官网的文本对话、图片生成/编辑等能力封装为 **OpenAI / Anthropic 兼容 API**，并附带 Vue 管理控制台：多账号池调度、自动注册机、代理防封、图片链路与运维面板。同一 FastAPI 进程托管 API 与控制台，无需额外 Nginx。

> **镜像**：`ghcr.io/jiujiu532/jovemage`  
> **当前版本**：`v0.1.0`  
> **环境变量兼容**：`CHATGPT2API_*` 仍可继续使用

## 核心功能

- **协议兼容**：`/v1/chat/completions`、`/v1/messages`、`/v1/images/*`、`/v1/models` 等 OpenAI / Anthropic 风格接口
- **账号池调度**：新鲜度口径、轮询取号、token 失效换号、图片远端配额校验
- **自动注册机**：Passwordless 注册、十余种邮箱 Provider、代理池绑定
- **图片链路**：生成 / 编辑、任务轮询、结果存储、失败结构化核验
- **代理防封**：WARP 1–6 实例、`proxy_pool`、FlareSolverr 可选
- **Vue 控制台**：仪表盘、账号、日志、图库、监控、注册机、设置、Studio 对话画图
- **可插拔存储**：`json` / `sqlite` / `postgres` / `git`（账号与密钥）

## 快速开始

### 方式一：管理脚本（推荐）

```bash
bash <(curl -sL https://raw.githubusercontent.com/jiujiu532/JoveMage/main/install.sh)
```

或 clone 后执行：

```bash
git clone https://github.com/jiujiu532/JoveMage.git
cd JoveMage
bash install.sh
```

脚本提供安装、状态、改配置、更新镜像、清理图片、卸载、重启换 IP 等生命周期管理。

### 方式二：Docker Compose

```bash
mkdir -p /opt/jovemage/data && cd /opt/jovemage

cat > config.json << 'EOF'
{
  "auth-key": "请替换为强随机密钥",
  "proxy": "",
  "proxy_pool": [],
  "max_relogin_retries": 3,
  "refresh_account_interval_minute": 15,
  "image_retention_days": 15,
  "image_max_retries": 3,
  "auto_remove_invalid_accounts": true
}
EOF

cat > docker-compose.yml << 'EOF'
services:
  app:
    image: ghcr.io/jiujiu532/jovemage:latest
    container_name: jovemage
    restart: unless-stopped
    ports:
      - "127.0.0.1:9000:80"
    volumes:
      - ./data:/app/data
      - ./config.json:/app/config.json
    environment:
      - TZ=Asia/Shanghai
    networks:
      - jovemage_net

networks:
  jovemage_net:
    name: jovemage_net
EOF

docker compose up -d
```

> 若 GHCR 包为 Private，需先：  
> `echo <PAT> | docker login ghcr.io -u <用户名> --password-stdin`

### 方式三：源码开发

```bash
# 后端
export CHATGPT2API_AUTH_KEY=local-dev-key   # Windows: set CHATGPT2API_AUTH_KEY=local-dev-key
uv sync
uv run python main.py
# 默认 http://127.0.0.1:8000

# 前端
cd web-vue
npm install
npm run dev
# Vite 默认代理到 localhost:8000
```

## 访问地址

| 项目 | 地址 |
|------|------|
| Web 控制台 | `http://127.0.0.1:9000`（compose 默认端口可改） |
| API | `http://127.0.0.1:9000/v1` |
| 数据目录 | `/opt/jovemage/data/` |

登录密码 = `config.json` 里的 `auth-key`（或环境变量 `CHATGPT2API_AUTH_KEY`）。

## 常用配置

| 字段 | 说明 | 默认 |
|------|------|------|
| `auth-key` | 控制台与 API 鉴权密钥 | **必填**，缺失则拒绝启动 |
| `proxy` | 默认出站代理 | 空（直连） |
| `proxy_pool` | 注册代理池（绑定最少策略） | `[]` |
| `max_relogin_retries` | relogin 最大重试 `0–10` | `3` |
| `refresh_account_interval_minute` | 账号新鲜度窗口（分钟） | `15` |
| `image_retention_days` | 图片保留天数 | `15` |
| `image_max_retries` | 生图失败换号重试 | `3` |
| `auto_remove_invalid_accounts` | 自动移除鉴权异常账号 | `true` |

完整示例见 `config.example.yaml`。

## 升级

```bash
bash install.sh
# 选择「更新镜像」

# 或手动
cd /opt/jovemage
docker compose pull
docker compose up -d
```

## CI / 镜像

- 推送 `main` 或 `v*` tag 时，GitHub Actions 自动构建并推送  
  `ghcr.io/jiujiu532/jovemage`（`linux/amd64` + `linux/arm64`）
- 标签：`latest`（main）、`v0.1.0`、`0.1`、`sha-...`
- 工作流：`.github/workflows/docker-publish.yml`

## 免责声明

本项目涉及对 ChatGPT 官网接口的逆向研究，**仅供个人学习、技术研究与非商业性技术交流**。

- 严禁商业用途、规模化滥用、套利倒卖或违反 OpenAI 服务条款与当地法律的行为
- 严禁生成/传播违法、暴力、色情、未成年人相关内容
- 使用者自行承担账号封禁与法律责任风险

---

<p align="center">MIT · Made for self-hosters</p>
