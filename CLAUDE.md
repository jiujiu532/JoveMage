# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

**JoveMage**：把 ChatGPT 网页版（chatgpt.com）逆向封装为 **OpenAI / Anthropic 兼容 API** 的自托管服务。协议转换只是表层，项目复杂度集中在"让白嫖账号活得久、用得满"：多账号池调度、自动注册机、代理防封、图片生成链路。附带一个 Vue 管理控制台，由同一个 FastAPI 进程托管（无需 Nginx）。

Python ≥ 3.13，依赖用 **uv** 管理（`uv.lock`，默认走阿里云 PyPI 镜像）。环境变量前缀 `CHATGPT2API_*` 仍兼容。

## 常用命令

```bash
# 依赖
uv sync

# 本地运行（默认 127.0.0.1:8000；容器内是 uvicorn main:app --host 0.0.0.0 --port 80）
# Windows: set CHATGPT2API_AUTH_KEY=local-dev-key
export CHATGPT2API_AUTH_KEY=local-dev-key
uv run python main.py

# 跑测试：必须带 auth-key，否则 services/config.py 在导入期就 raise
CHATGPT2API_AUTH_KEY=test-auth uv run python -m unittest discover -s test -t . -v

# 跑单个测试文件 / 单个用例（模块名要带 test. 前缀，否则 ModuleNotFoundError）
CHATGPT2API_AUTH_KEY=test-auth uv run python -m unittest test.test_register_pool_metrics -v
CHATGPT2API_AUTH_KEY=test-auth uv run python -m unittest test.test_config.ConfigLoadingTests.test_xxx

# 前端（web-vue/ 下执行）
npm install
npm run dev      # Vite :5173，/api /v1 /auth 等代理到 VITE_DEV_API_TARGET（默认 localhost:8000）
npm run build    # clean:dist && tsc && vite build → web-vue/dist
```

无 lint / formatter 配置，也没有 pytest；测试一律用标准库 `unittest`。CI 只有 `.github/workflows/docker-publish.yml`（构建并推 `ghcr.io/jiujiu532/jovemage`），不跑测试。

**测试分两类，注意区分**：

- 离线单测：绝大多数文件，用 `unittest.mock` 打桩，可直接跑。若测试依赖 auth-key，用 `os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")` 在导入 services 之前设置。
- 需要活服务的集成脚本：`test/utils.py` 里写死 `BASE_URL = http://127.0.0.1:8000` 并从 `config.json` 读 `auth-key`；`test_image.py`、`test_generations*.py`、`test_v1_*.py` 属于这类，要先起服务再跑，会真实打上游、消耗账号额度。**不起服务时它们报 `WinError 10061` 连接被拒是预期行为，不是缺陷**，判断测试健康度时要把这批排除。

**禁止在本地做 Docker 构建或运行**（见全局 AGENTS.md）。涉及容器的改动只做静态检查，说明未做本地验证。

## 代码地图

| 路径 | 职责 |
|---|---|
| `main.py` / `api/app.py` | 入口；`create_app()` 挂路由、CORS、lifespan 后台线程 |
| `api/` | 路由层：`ai`（/v1）、`accounts`、`register`、`image_tasks`、`prompts`、`system`（设置/监控/代理/登录） |
| `services/` | 业务：账号池、注册机、上游调用、日志、图片任务、代理、存储 |
| `services/protocol/` | 协议转换：每个兼容接口一个模块 + 共享 `conversation.py` / `error_response.py` |
| `services/register/` | Passwordless 注册 + 邮箱 Provider |
| `services/storage/` | accounts / auth_keys 可插拔后端 |
| `utils/` | 日志、脱敏、PoW、Turnstile、sentinel 等底层工具 |
| `web-vue/` | Vue 3 管理控制台源码；产物进 `web_dist/` |
| `install.sh` | 生产部署主推脚本（生命周期管理） |
| `docs/` | 部署、FlareSolverr、上游 SSE 等说明 |

## 架构大图

### 请求主链路（`/v1/chat/completions` 为例）

1. **鉴权** `api/support.py` — 从 `Authorization: Bearer` 取 token，先比对全局 `config.auth_key`，否则走 `auth_service` 的 SHA-256 密钥表，返回 `admin`/`user` 角色。**鉴权是每个路由函数里手写 Header 参数解析，不是中间件也不是 `Depends`**，新增路由必须自己带上 `require_identity` / `require_admin`。
2. **预处理** `api/ai.py` — Pydantic 校验 → 判断是否"聊天生图" → 构造 `LoggedCall` 追踪对象 → 线程池里跑 `content_filter`。
3. **`LoggedCall.run()`** `services/log_service.py` — 底层 curl_cffi 是**同步**的，所有 handler 都必须丢进 `run_in_threadpool`；这一层统一做异常 → OpenAI/Anthropic 错误体转换、SSE 包装、各阶段耗时上报。写新接口时把业务逻辑交给它，不要自己拼 `StreamingResponse`。线程池大小由 `CHATGPT2API_THREAD_TOKENS`（默认 80）控制。
4. **选账号** `services/account_service.py` — 文本走 round-robin 取 access_token；图片要额外做远端配额校验，并区分"额度耗尽(429)"与"暂时不可用(503)"两种终结判据。token 失效时 force refresh 或标记失效后换号重试。
5. **打上游** `services/openai_backend_api.py` — curl_cffi 伪造浏览器 TLS 指纹，先过 `sentinel/chat-requirements`（PoW + Turnstile），再 POST `/backend-api/f/conversation` 拿内部 SSE。
6. **协议转换** `services/protocol/conversation.py` — ChatGPT 内部事件流 → 标准 `chat.completion.chunk` 或 Anthropic events。对外兼容面拆在同目录：`openai_v1_chat_complete`、`anthropic_v1_messages`、`openai_v1_image_*`、`openai_v1_response` 等。

错误格式收敛在 `api/errors.py` + `services/protocol/error_response.py`：`/v1/messages` 走 Anthropic 风格 `{"type":"error",...}`，其余 `/v1/*` 走 OpenAI 风格 `{"error":{...}}`，非 `/v1` 走 `{"detail":...}`。

### 账号池：改动最敏感的地方

- **号池健康度** `account_service.evaluate_account_pool()` 是权威入口。核心概念是**"新鲜度"**：只有 `last_remote_checked_at` 在有效期内（默认 `refresh_account_interval_minute`）的账号才计入 `current_quota/current_available`；本地缓存的乐观值叫 `estimated_*`；状态正常但未新鲜确认的算 `unconfirmed_available`。**不要另写一套"统计 status=='正常' 的账号"的简易口径**——`register_service._pool_metrics()` 已经因此改过一次。
- **Token 续期** `_request_access_token_refresh()` 必须用固定 `client_id=app_2SKx67EdpoN0G6j64rFvigXD`（`account_service._OAUTH_CLIENT_ID` / `platform_oauth_client_id`），改错会导致全量续期失败。除 access_token 按提前量刷新外，refresh_token 每 3 天主动保活防吊销。
- **注册走 Passwordless** `services/register/openai_register.py` — 官网新号默认 OTP、不设密码。`register()` 分两支：全新注册 `_start_passwordless_signup()`，微软邮箱域名走 `_passwordless_login()`。相关账号的 password 字段为空是正常状态，不要当成脏数据清理。
- **邮箱来源** `services/register/mail_provider.py` — 十余种 provider 各一个 `BaseMailProvider` 子类，加权随机选取。

`.gitignore` 用 `!/test/test_xxx.py` 白名单专门放行了 Passwordless、号池指标、Sentinel/Turnstile 三个测试，这三条是团队认定的关键回归路径，改动上述逻辑必须跑它们。

### 日志与异常中的敏感信息

`utils/diagnostics.py` 的 `redact_auth_diagnostic()` 负责屏蔽 access_token / refresh_token / cookie / Bearer。**任何要落库或落日志的上游错误详情都要先过它**，`utils/helper.py` 的 `anonymize_token()` 用于展示层脱敏。

### 存储层可插拔

`services/storage/factory.py` 按环境变量 `STORAGE_BACKEND`（json | sqlite | postgres | git）选后端，只覆盖 `accounts` 和 `auth_keys` 两类数据。其余业务数据（`register.json`、`image_tasks.json`、`logs.jsonl`、`dashboard_metrics.json` 等）一律是 `data/` 下的裸 JSON 文件，**写入必须走 `services/json_file.py` 的 `write_json_file()`**（临时文件 + `os.replace` 原子替换 + 自动 `.bak`，读取失败会从 `.bak` 恢复）。直接 `json.dump` 到目标路径会重新引入重启丢数据的老问题。

### 配置

运行时读仓库根的 `config.json`（不入库），`config.example.yaml` 只是带注释的示例。`auth-key` 缺失或为空时**服务拒绝启动**（`services/config.py`）。环境变量 `CHATGPT2API_AUTH_KEY` 优先级高于 `config.json`。

### 前端

Vue 3.5 + TS + Vite 7 + Tailwind 3 + Pinia + vue-router（**hash 模式**），UI 用私有包 `nanocat-ui`，echarts 走 `public/vendor/` 静态引入而非 npm 依赖。

- 认证把密钥原样存 localStorage：当前 key `jovemage.adminKey`，兼容读取旧 key `chatgpt2api.adminKey`（`src/api/client.ts`）。
- 角色隔离：普通 `user` 只能进 Studio（对话画图），其余视图全部 `meta.adminOnly`。
- 流式对话不走 axios，用原生 `fetch` + `ReadableStream` 手工解析 SSE（`src/api/chatStream.ts`）。
- 构建产物由 Dockerfile 多阶段拷成后端目录下的 `web_dist/`，`api/app.py` 的通配路由兜底返回 `index.html`。改前端后要重新构建才能在后端看到效果。

### 代理与防封：两条互不兼容的 WARP 路线

| 路线 | 架构 | 说明 |
|---|---|---|
| `install.sh`（主推） | 应用 → SOCKS5 → WARP，**无 Privoxy**，1-6 实例 | 生产部署脚本，`proxy_pool` 形如 `socks5h://warp-N:1080` |
| `docker-compose.warp.yml` | 单实例 WARP + Privoxy(HTTP转SOCKS5) + FlareSolverr | 仓库自带备用编排，静态单实例 |

两者不可混用。Cloudflare 挑战由 `services/proxy_service.py` 的 `FlareSolverrClearanceProvider` 取 cf_clearance cookie。

三个 compose 文件：`docker-compose.yml`（拉 GHCR 镜像，生产）、`.local.yml`（本地构建，sqlite，8000:80）、`.warp.yml`（WARP 全栈）。

## 需要留意的现状

- `services/openai_backend_api.py`（~3400 行）、`services/protocol/conversation.py`（~2700 行）、`services/register/mail_provider.py`（~2100 行）、`services/account_service.py`（~2000 行）是后端大文件，改动前先定位再动，不要整体重排。
- `.trellis/spec/backend/` 多数仍是 "To fill" 模板；目前已落地的是 `image-result-accounting.md`。**不要把未填充模板当成项目约定**，但改图片结果记账/失败核验前应读该文档。
- 根目录 `test/` 在 `.gitignore` 中默认忽略，仅上述三个白名单测试会进仓库；本地可能有更多未跟踪测试文件。
