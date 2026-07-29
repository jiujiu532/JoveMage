#!/bin/bash
# ============================================================
#  JoveMage 管理工具
#
#  动态菜单:
#    - 未安装: 安装
#    - 已安装: 状态 / 配置 / 更新 / 清理图片 / 卸载 / 重启换 IP
#              (检测到代理问题时显示「规整代理」)
#
#  架构: 应用 → SOCKS5 → WARP → ChatGPT (无 Privoxy)
#
#  用法: bash install.sh
# ============================================================

set -uo pipefail

# ============================================================
#  全局变量
# ============================================================
# 不写死版本：优先脚本旁 VERSION，其次 GitHub Release latest，再次安装目录戳记
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
INSTALL_DIR="/opt/jovemage"
# 代理套件始终放在安装目录内，不碰系统其他路径
PROXY_DIR="$INSTALL_DIR/proxy"
IMAGE="ghcr.io/jiujiu532/jovemage:latest"

CONFIG_FILE="$INSTALL_DIR/config.json"
COMPOSE_FILE="$INSTALL_DIR/docker-compose.yml"
REGISTER_FILE="$INSTALL_DIR/data/register.json"
PROXY_COMPOSE_FILE="$PROXY_DIR/docker-compose.yml"
APP_NETWORK="jovemage_net"
APP_CONTAINER="jovemage"
APP_COMPOSE_PROJECT="jovemage"
PROXY_COMPOSE_PROJECT="jovemage-proxy"
WARP_NAME_PREFIX="jovemage-warp"
FLARE_CONTAINER="jovemage-flaresolverr"

COMPOSE_CMD=""

# ============================================================
#  基础工具
# ============================================================
log()  { echo "$@"; }
ok()   { echo "  [OK]  $*"; }
info() { echo "  [-->] $*"; }
warn() { echo "  [!]   $*"; }
err()  { echo "  [ERR] $*" >&2; }

ask() {
    local prompt="$1" default="${2:-}" var
    if [ -n "$default" ]; then
        read -rp "  $prompt [默认 $default]: " var
        echo "${var:-$default}"
    else
        read -rp "  $prompt: " var
        echo "$var"
    fi
}

confirm() {
    local prompt="$1" default="${2:-Y}" hint var
    if [ "$default" = "Y" ]; then hint="Y/n"; else hint="y/N"; fi
    read -rp "  $prompt [$hint]: " var
    var="${var:-$default}"
    case "$var" in
        Y|y|YES|yes|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

press_enter() {
    echo ""
    read -rp "  按 Enter 继续..." _
}

# ============================================================
#  依赖检测
# ============================================================
detect_pkg_mgr() {
    if command -v apt-get &> /dev/null; then echo "apt"; return; fi
    if command -v dnf &> /dev/null; then echo "dnf"; return; fi
    if command -v yum &> /dev/null; then echo "yum"; return; fi
    if command -v apk &> /dev/null; then echo "apk"; return; fi
    echo ""
}

install_package() {
    local pkg="$1" mgr
    mgr=$(detect_pkg_mgr)
    case "$mgr" in
        apt) apt-get update -qq && apt-get install -y -qq "$pkg" ;;
        dnf) dnf install -y -q "$pkg" ;;
        yum) yum install -y -q "$pkg" ;;
        apk) apk add --no-cache "$pkg" ;;
        *) err "无法识别包管理器，请手动安装 $pkg"; return 1 ;;
    esac
}

ensure_command() {
    local cmd="$1" pkg="${2:-$cmd}"
    if command -v "$cmd" &> /dev/null; then return 0; fi
    warn "缺少 $cmd，尝试自动安装..."
    if install_package "$pkg"; then
        ok "$cmd 已安装"
        return 0
    fi
    err "$cmd 安装失败，请手动安装后重试"
    return 1
}

ensure_docker() {
    if ! command -v docker &> /dev/null; then
        err "Docker 未安装，请先安装 Docker"
        return 1
    fi
    if docker compose version &> /dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
        return 0
    fi
    if command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
        return 0
    fi
    err "docker compose 未安装"
    return 1
}

# ============================================================
#  状态查询
# ============================================================
is_installed() { [ -f "$COMPOSE_FILE" ]; }

get_app_status() {
    if ! is_installed; then echo "未安装"; return; fi
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$APP_CONTAINER"; then
        echo "运行中"
    else
        echo "已停止"
    fi
}

get_app_version() {
    local v
    v=$(docker inspect "$APP_CONTAINER" --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' 2>/dev/null || true)
    if [ -z "$v" ] || [ "$v" = "<no value>" ]; then
        v=$(docker inspect "$APP_CONTAINER" --format '{{ .Config.Image }}' 2>/dev/null | sed 's/.*://' || true)
    fi
    [ -z "$v" ] && echo "未知" || echo "$v"
}

wait_healthy() {
    local max_secs="${1:-30}" port wait_secs=0
    port=$(get_service_port)
    [ -z "$port" ] && port="9000"
    while [ $wait_secs -lt "$max_secs" ]; do
        if curl -fsS --max-time 2 "http://127.0.0.1:${port}/health" &>/dev/null; then
            return 0
        fi
        sleep 2
        wait_secs=$(( wait_secs + 2 ))
        echo -n "."
    done
    echo ""
    return 1
}

# 从 GitHub Releases latest 拉取最新版本；缓存到 /tmp/jovemage-latest-version，60 秒内复用
get_latest_version() {
    local cache="/tmp/jovemage-latest-version"
    if [ -f "$cache" ]; then
        local age
        age=$(( $(date +%s) - $(stat -c %Y "$cache" 2>/dev/null || stat -f %m "$cache" 2>/dev/null || echo 0) ))
        if [ $age -lt 60 ]; then
            cat "$cache"
            return 0
        fi
    fi
    local raw v
    raw=$(curl -fsS --max-time 5 \
        -H "Accept: application/vnd.github+json" \
        -H "User-Agent: jovemage-install" \
        https://api.github.com/repos/jiujiu532/JoveMage/releases/latest 2>/dev/null || true)
    if [ -z "$raw" ]; then
        return 0
    fi
    if command -v jq >/dev/null 2>&1; then
        v=$(printf '%s' "$raw" | jq -r '.tag_name // empty' 2>/dev/null || true)
    else
        v=$(printf '%s' "$raw" \
            | grep -oE '"tag_name"[[:space:]]*:[[:space:]]*"[^"]+"' \
            | head -1 \
            | sed -E 's/.*"([^"]+)"[[:space:]]*$/\1/')
    fi
    if [ -n "$v" ] && [ "$v" != "null" ]; then
        # 去掉 v 前缀（v0.1.0 → 0.1.0）
        v="${v#v}"
        echo "$v" > "$cache" 2>/dev/null || true
        echo "$v"
    fi
}

# 管理工具自身版本：不硬编码
# 1) 脚本同目录 VERSION（仓库/发布包）
# 2) GitHub Release latest（curl 单文件安装时）
# 3) 安装目录 .install-version / VERSION（离线回退）
get_script_version() {
    local v=""
    if [ -n "${SCRIPT_DIR:-}" ] && [ -f "$SCRIPT_DIR/VERSION" ]; then
        v=$(tr -d '[:space:]' < "$SCRIPT_DIR/VERSION" 2>/dev/null || true)
    fi
    if [ -z "$v" ]; then
        v=$(get_latest_version || true)
    fi
    if [ -z "$v" ] && [ -f "$INSTALL_DIR/.install-version" ]; then
        v=$(tr -d '[:space:]' < "$INSTALL_DIR/.install-version" 2>/dev/null || true)
    fi
    if [ -z "$v" ] && [ -f "$INSTALL_DIR/VERSION" ]; then
        v=$(tr -d '[:space:]' < "$INSTALL_DIR/VERSION" 2>/dev/null || true)
    fi
    if [ -n "$v" ]; then
        echo "${v#v}"
    else
        echo "unknown"
    fi
}

# 比较两个版本号，返回:
#   0 = current == latest (最新)
#   1 = current < latest (有更新)
#   2 = current > latest (本地更新，不太可能)
#   3 = 无法判断
compare_versions() {
    local current="${1#v}" latest="${2#v}"
    [ -z "$current" ] || [ "$current" = "未知" ] && return 3
    [ -z "$latest" ] && return 3
    [ "$current" = "$latest" ] && return 0
    # 简单的版本比较: 用 sort -V
    local sorted
    sorted=$(printf '%s\n%s' "$current" "$latest" | sort -V | head -1)
    if [ "$sorted" = "$current" ]; then
        return 1   # current < latest
    else
        return 2   # current > latest
    fi
}

get_service_port() {
    [ -f "$COMPOSE_FILE" ] || { echo ""; return; }
    grep -oE '127\.0\.0\.1:[0-9]+:80' "$COMPOSE_FILE" 2>/dev/null | head -1 | awk -F: '{print $2}'
}

# 本部署所属容器名（仅 jovemage 前缀，绝不扫描系统其它 WARP/Flare）
own_warp_name() { echo "${WARP_NAME_PREFIX}-$1"; }

# 本部署正在运行的 WARP 数量
count_own_warp_running() {
    local n=0 i
    for (( i=1; i<=6; i++ )); do
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$(own_warp_name "$i")"; then
            n=$((n + 1))
        fi
    done
    echo "$n"
}

# 本部署 compose 声明的 WARP 数量
count_own_warp_declared() {
    [ -f "$PROXY_COMPOSE_FILE" ] || { echo 0; return; }
    local n
    n=$(grep -cE "container_name:[[:space:]]*${WARP_NAME_PREFIX}-[0-9]+" "$PROXY_COMPOSE_FILE" 2>/dev/null || true)
    # grep -c 无匹配时某些环境输出空或 0 且非 0 退出码；统一成整数
    [[ "$n" =~ ^[0-9]+$ ]] || n=0
    echo "$n"
}

has_own_flare_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$FLARE_CONTAINER"
}

has_own_proxy_suite() {
    [ -f "$PROXY_COMPOSE_FILE" ] && [ "$(count_own_warp_declared)" -gt 0 ]
}

# 专属网络是否存在
has_app_network() {
    docker network ls --format '{{.Name}}' 2>/dev/null | grep -qx "$APP_NETWORK"
}

# 容器是否在专属网络中
container_in_app_network() {
    local name="$1"
    docker inspect "$name" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null | grep -qw "$APP_NETWORK"
}

# 本部署相关容器列表（仅自己的名字）
list_own_containers() {
    local names=("$APP_CONTAINER" "$FLARE_CONTAINER") i
    for (( i=1; i<=6; i++ )); do
        names+=("$(own_warp_name "$i")")
    done
    local name
    for name in "${names[@]}"; do
        if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
            echo "$name"
        fi
    done
}

# 确保专属网络存在；已存在则复用，不改名、不碰其它网络
ensure_app_network() {
    if ! has_app_network; then
        docker network create "$APP_NETWORK" >/dev/null
        ok "已创建专属网络: $APP_NETWORK"
    fi
}

# 重建专属网络（同名）：只断开本部署容器，不碰其它容器/网络
recreate_app_network() {
    local name
    info "重建专属网络 $APP_NETWORK（仅断开本部署容器）..."
    while IFS= read -r name; do
        [ -z "$name" ] && continue
        docker network disconnect -f "$APP_NETWORK" "$name" 2>/dev/null || true
    done < <(list_own_containers)

    if has_app_network; then
        if docker network rm "$APP_NETWORK" >/dev/null 2>&1; then
            ok "已删除旧网络 $APP_NETWORK"
        else
            warn "无法删除 $APP_NETWORK（可能仍有非本部署容器占用），将继续复用"
            return 0
        fi
    fi
    docker network create "$APP_NETWORK" >/dev/null
    ok "已创建网络 $APP_NETWORK"
}

# 把本部署容器加入专属网络（如果还没加入）
connect_to_app_network() {
    local name="$1"
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
        if ! container_in_app_network "$name"; then
            docker network connect "$APP_NETWORK" "$name" 2>/dev/null || true
        fi
    fi
}

connect_own_containers_to_app_network() {
    local name n i
    connect_to_app_network "$APP_CONTAINER"
    connect_to_app_network "$FLARE_CONTAINER"
    n=$(count_own_warp_declared)
    [ "$n" -lt 1 ] && n=$(count_own_warp_running)
    for (( i=1; i<=n; i++ )); do
        connect_to_app_network "$(own_warp_name "$i")"
    done
}

is_port_in_use() {
    local port="$1"
    if command -v ss &> /dev/null; then
        ss -ltn "( sport = :$port )" 2>/dev/null | grep -q LISTEN
    elif command -v netstat &> /dev/null; then
        netstat -ltn 2>/dev/null | grep -qE "[:.]$port[[:space:]]"
    else
        docker ps --format '{{.Ports}}' 2>/dev/null | grep -qE "[:.]$port->"
    fi
}

# 检测本部署是否需要规整代理 (返回 0=需要, 1=不需要)
# 只看 /opt/jovemage 内配置与本部署容器，不扫描系统其它 WARP/Flare/Privoxy
detect_proxy_issues() {
    # 1) 本部署 config 的 proxy_pool 仍含 privoxy（失效架构）
    if [ -f "$CONFIG_FILE" ] && validate_json "$CONFIG_FILE"; then
        if jq -e '.proxy_pool[]? | select(test("privoxy";"i"))' "$CONFIG_FILE" >/dev/null 2>&1; then
            return 0
        fi
        # 2) 本部署 config 仍指向未加前缀的旧主机名 warp-N / flaresolverr
        if jq -e --arg p "$WARP_NAME_PREFIX" \
            '.proxy_pool[]? | select(test("://warp-[0-9]+(:|/|$)") and (contains($p) | not))' \
            "$CONFIG_FILE" >/dev/null 2>&1; then
            return 0
        fi
    fi
    # 3) 声明了本部署代理套件，但容器未跑齐
    if has_own_proxy_suite; then
        local declared running
        declared=$(count_own_warp_declared)
        running=$(count_own_warp_running)
        if [ "$declared" -gt 0 ] && [ "$running" -lt "$declared" ]; then
            return 0
        fi
        if ! has_own_flare_running; then
            return 0
        fi
    fi
    # 4) 本部署 app 不在专属网络（且本部署有 WARP）
    local warp_count
    warp_count=$(count_own_warp_running)
    if [ "$warp_count" -gt 0 ] && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$APP_CONTAINER"; then
        if ! container_in_app_network "$APP_CONTAINER"; then
            return 0
        fi
    fi
    return 1
}

# ============================================================
#  JSON 操作（jq）
# ============================================================
jq_set_string() {
    local file="$1" path="$2" value="$3" tmp
    tmp=$(mktemp)
    if jq --arg v "$value" "$path = \$v" "$file" > "$tmp"; then
        mv "$tmp" "$file"; return 0
    fi
    rm -f "$tmp"; return 1
}

jq_set_number() {
    local file="$1" path="$2" value="$3" tmp
    tmp=$(mktemp)
    if jq --argjson v "$value" "$path = \$v" "$file" > "$tmp"; then
        mv "$tmp" "$file"; return 0
    fi
    rm -f "$tmp"; return 1
}

jq_set_bool() {
    local file="$1" path="$2" value="$3" tmp
    tmp=$(mktemp)
    if jq --argjson v "$value" "$path = \$v" "$file" > "$tmp"; then
        mv "$tmp" "$file"; return 0
    fi
    rm -f "$tmp"; return 1
}

jq_set_array() {
    local file="$1" path="$2" lines="$3" tmp json_array
    tmp=$(mktemp)
    json_array=$(printf '%s' "$lines" | jq -R . | jq -s 'map(select(length > 0))')
    if jq --argjson v "$json_array" "$path = \$v" "$file" > "$tmp"; then
        mv "$tmp" "$file"; return 0
    fi
    rm -f "$tmp"; return 1
}

# 写入应用实际读取的 proxy_runtime.clearance（扁平 flaresolverr_url/clearance_mode 不够）
# multi-WARP 出口仍走 proxy_pool；egress_mode 默认 direct，但 runtime.enabled 必须为 true
# 否则 proxy_service.clearance_enabled 恒为 false
jq_set_proxy_runtime_clearance() {
    local file="$1" flare_url="${2:-}" tmp
    [ -f "$file" ] || return 1
    tmp=$(mktemp)
    if [ -n "$flare_url" ]; then
        if jq --arg url "$flare_url" '
            .proxy_runtime = ((.proxy_runtime // {}) * {
              enabled: true,
              egress_mode: ((.proxy_runtime.egress_mode // "direct")),
              proxy_url: ((.proxy_runtime.proxy_url // "")),
              resource_proxy_url: ((.proxy_runtime.resource_proxy_url // "")),
              skip_ssl_verify: ((.proxy_runtime.skip_ssl_verify // false)),
              reset_session_status_codes: ((.proxy_runtime.reset_session_status_codes // [403])),
              clearance: ((.proxy_runtime.clearance // {}) * {
                enabled: true,
                mode: "flaresolverr",
                flaresolverr_url: $url,
                timeout_sec: ((.proxy_runtime.clearance.timeout_sec // 60)),
                refresh_interval: ((.proxy_runtime.clearance.refresh_interval // 3600)),
                warm_up_on_start: ((.proxy_runtime.clearance.warm_up_on_start // false)),
                browser: ((.proxy_runtime.clearance.browser // "chrome")),
                user_agent: ((.proxy_runtime.clearance.user_agent // "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")),
                cf_cookies: ((.proxy_runtime.clearance.cf_cookies // "")),
                cf_clearance: ((.proxy_runtime.clearance.cf_clearance // ""))
              })
            })
            | .flaresolverr_url = $url
            | .clearance_mode = "flaresolverr"
            | .clearance_refresh_interval = ((.clearance_refresh_interval // 3600))
          ' "$file" > "$tmp"; then
            mv "$tmp" "$file"; return 0
        fi
    else
        if jq '
            .proxy_runtime = ((.proxy_runtime // {}) * {
              enabled: ((.proxy_runtime.enabled // false)),
              egress_mode: ((.proxy_runtime.egress_mode // "direct")),
              clearance: ((.proxy_runtime.clearance // {}) * {
                enabled: false,
                mode: "none",
                flaresolverr_url: ""
              })
            })
            | .clearance_mode = "none"
            | .flaresolverr_url = ""
          ' "$file" > "$tmp"; then
            mv "$tmp" "$file"; return 0
        fi
    fi
    rm -f "$tmp"; return 1
}

jq_get() {
    local file="$1" path="$2" default="${3:-}" v
    v=$(jq -r "$path // empty" "$file" 2>/dev/null)
    if [ -z "$v" ] || [ "$v" = "null" ]; then echo "$default"; else echo "$v"; fi
}

jq_get_array() {
    local file="$1" path="$2"
    jq -r "$path[]? // empty" "$file" 2>/dev/null
}

validate_json() {
    local file="$1"
    [ -f "$file" ] || return 1
    jq empty "$file" 2>/dev/null
}

# ============================================================
#  代理套件 (SOCKS5 直连，无 Privoxy)
# ============================================================
# 生成 N 个 WARP + 1 个 FlareSolverr 的 compose（仅本部署命名）
generate_proxy_compose() {
    local out="$1" n="$2" i warp_name
    {
        echo "services:"
        for (( i=1; i<=n; i++ )); do
            warp_name="$(own_warp_name "$i")"
            cat <<EOF
  warp-$i:
    image: caomingjun/warp:latest
    container_name: $warp_name
    restart: unless-stopped
    environment:
      - WARP_SLEEP=2
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    sysctls:
      - net.ipv6.conf.all.disable_ipv6=0
      - net.ipv4.conf.all.src_valid_mark=1
    networks:
      - app_net

EOF
        done
        cat <<EOF
  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:latest
    container_name: $FLARE_CONTAINER
    restart: unless-stopped
    environment:
      TZ: Asia/Shanghai
      LOG_LEVEL: info
    networks:
      - app_net

networks:
  app_net:
    external: true
    name: $APP_NETWORK
EOF
    } > "$out"
}

# 等待本部署 WARP 就绪（只探测 jovemage-warp-*）
wait_warp_ready() {
    info "等待本部署 WARP 连接初始化..."
    local waited=0 probe i
    while [ $waited -lt 60 ]; do
        probe=""
        for (( i=1; i<=6; i++ )); do
            if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$(own_warp_name "$i")"; then
                probe="$(own_warp_name "$i")"
                break
            fi
        done
        if [ -n "$probe" ] && \
           docker exec "$probe" curl -fsS --max-time 3 https://cloudflare.com/cdn-cgi/trace &>/dev/null; then
            ok "WARP 已连接（$probe，耗时 ${waited}s）"
            return 0
        fi
        sleep 3
        waited=$(( waited + 3 ))
        echo -n "."
    done
    echo ""
    warn "WARP 60 秒内未完成连接，请检查本部署容器: docker ps | grep $WARP_NAME_PREFIX"
    return 1
}

# 生成 N 个 SOCKS5 URL（换行分隔，主机名为本部署容器名）
generate_socks5_pool_text() {
    local n="$1" i out=""
    for (( i=1; i<=n; i++ )); do
        if [ -z "$out" ]; then
            out="socks5h://$(own_warp_name "$i"):1080"
        else
            out="$out
socks5h://$(own_warp_name "$i"):1080"
        fi
    done
    echo "$out"
}

# 本部署固定使用专属网络名
detect_proxy_network() {
    echo "$APP_NETWORK"
}

compose_in() {
    local dir="$1"; shift
    local project="$APP_COMPOSE_PROJECT"
    if [ "$dir" = "$PROXY_DIR" ]; then
        project="$PROXY_COMPOSE_PROJECT"
    fi
    (cd "$dir" && $COMPOSE_CMD -p "$project" "$@")
}

# ============================================================
#  setup_proxy_suite (安装时调用) — 只管理 $INSTALL_DIR/proxy
# ============================================================
setup_proxy_suite() {
    PROXY_POOL_TEXT=""
    FLARE_URL=""
    USE_NETWORK=""

    log ""
    log "[2/5] 部署代理套件..."
    log ""
    log "  范围说明: 仅操作 $INSTALL_DIR 与专属网络 $APP_NETWORK"
    log "  不会检测/改动系统中其它 WARP、FlareSolverr 或 Docker 网络"
    log ""

    # 本部署已有代理套件 → 复用
    if has_own_proxy_suite; then
        local existing_warp
        existing_warp=$(count_own_warp_declared)
        ok "检测到本部署代理套件: $existing_warp 个 WARP（$PROXY_DIR）"
        ensure_app_network
        if [ "$(count_own_warp_running)" -lt "$existing_warp" ] || ! has_own_flare_running; then
            info "本部署代理未完全运行，尝试启动..."
            compose_in "$PROXY_DIR" up -d || { err "本部署代理启动失败"; return 1; }
            wait_warp_ready || true
        fi
        connect_own_containers_to_app_network
        PROXY_POOL_TEXT=$(generate_socks5_pool_text "$existing_warp")
        FLARE_URL="http://${FLARE_CONTAINER}:8191"
        USE_NETWORK="$APP_NETWORK"
        info "将使用本部署已有代理套件"
        return 0
    fi

    # 仅当本部署 config 仍含 privoxy / 旧主机名时提示重建（不扫系统其它栈）
    # 注意：匹配 ://warp-N，不会命中 socks5h://jovemage-warp-N
    if [ -f "$CONFIG_FILE" ] && validate_json "$CONFIG_FILE"; then
        if jq -e --arg p "$WARP_NAME_PREFIX" \
            '.proxy_pool[]? | select(test("privoxy";"i") or (test("://warp-[0-9]+(:|/|$)") and (contains($p) | not)))' \
            "$CONFIG_FILE" >/dev/null 2>&1; then
            warn "本部署 config 中的 proxy_pool 仍是旧格式"
            if confirm "是否按新架构重建本部署代理套件" "Y"; then
                local existing_warp
                cmd_normalize_proxies "install"
                existing_warp=$(count_own_warp_declared)
                [ "$existing_warp" -lt 1 ] && existing_warp=$(count_own_warp_running)
                [ "$existing_warp" -lt 1 ] && existing_warp=2
                PROXY_POOL_TEXT=$(generate_socks5_pool_text "$existing_warp")
                FLARE_URL="http://${FLARE_CONTAINER}:8191"
                USE_NETWORK="$APP_NETWORK"
                return 0
            fi
        fi
    fi

    info "本部署尚未安装代理套件，需要部署 WARP 用于 ChatGPT 访问。"
    log ""
    log "  代理池策略说明:"
    log "    账号会按\"最少绑定\"分散到 N 个 WARP 出口 IP"
    log "    每个 WARP 约占 100MB 内存"
    log "    容器名: ${WARP_NAME_PREFIX}-N / $FLARE_CONTAINER"
    log "    目录: $PROXY_DIR"
    log ""

    local warp_n
    while true; do
        warp_n=$(ask "请输入 WARP 实例数量 (1-6)" "2")
        if [[ "$warp_n" =~ ^[1-6]$ ]]; then break; fi
        warn "请输入 1-6 之间的数字"
    done

    info "正在部署 $warp_n 个 WARP + FlareSolverr 到 $PROXY_DIR ..."
    mkdir -p "$PROXY_DIR"
    # 网络同名新建或复用；不改名、不删其它网络
    ensure_app_network
    generate_proxy_compose "$PROXY_COMPOSE_FILE" "$warp_n"

    if ! compose_in "$PROXY_DIR" pull; then
        err "代理套件镜像拉取失败"
        return 1
    fi
    if ! compose_in "$PROXY_DIR" up -d; then
        err "代理套件启动失败"
        return 1
    fi
    ok "代理套件部署完成"
    log ""
    wait_warp_ready

    PROXY_POOL_TEXT=$(generate_socks5_pool_text "$warp_n")
    FLARE_URL="http://${FLARE_CONTAINER}:8191"
    USE_NETWORK="$APP_NETWORK"

    log ""
    ok "代理池: $warp_n 个 SOCKS5 出口"
    [ -n "$FLARE_URL" ] && ok "FlareSolverr: $FLARE_URL"
    return 0
}

# ============================================================
#  生成 config.json + register.json
# ============================================================
generate_config_files() {
    mkdir -p "$INSTALL_DIR/data"
    local clearance_mode="none"
    local clearance_enabled=false
    local runtime_enabled=false
    [ -n "$FLARE_URL" ] && clearance_mode="flaresolverr" && clearance_enabled=true && runtime_enabled=true

    local pool_json
    if [ -n "$PROXY_POOL_TEXT" ]; then
        pool_json=$(printf '%s' "$PROXY_POOL_TEXT" | jq -R . | jq -s .)
    else
        pool_json="[]"
    fi

    # 应用只读 proxy_runtime.clearance.*；顶层 flaresolverr_url/clearance_mode 仅作兼容镜像
    # multi-WARP 业务出口走 proxy_pool，故 egress_mode=direct；但 enabled 必须为 true 才能开清障
    jq -n \
        --arg auth_key "$AUTH_KEY" \
        --argjson pool "$pool_json" \
        --arg clearance_mode "$clearance_mode" \
        --arg flare_url "$FLARE_URL" \
        --argjson clearance_enabled "$clearance_enabled" \
        --argjson runtime_enabled "$runtime_enabled" \
        --argjson max_retries "$IMAGE_MAX_RETRIES" \
        --argjson auto_remove "$AUTO_REMOVE_INVALID" \
        '{
            "auth-key": $auth_key,
            "proxy_pool": $pool,
            "clearance_mode": $clearance_mode,
            "flaresolverr_url": $flare_url,
            "clearance_refresh_interval": 3600,
            "refresh_account_interval_minute": 15,
            "image_retention_days": 15,
            "image_max_retries": $max_retries,
            "auto_remove_invalid_accounts": $auto_remove,
            "proxy_runtime": {
                "enabled": $runtime_enabled,
                "egress_mode": "direct",
                "proxy_url": "",
                "resource_proxy_url": "",
                "skip_ssl_verify": false,
                "reset_session_status_codes": [403],
                "clearance": {
                    "enabled": $clearance_enabled,
                    "mode": $clearance_mode,
                    "cf_cookies": "",
                    "cf_clearance": "",
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                    "browser": "chrome",
                    "flaresolverr_url": $flare_url,
                    "timeout_sec": 60,
                    "refresh_interval": 3600,
                    "warm_up_on_start": false
                }
            }
        }' > "$CONFIG_FILE"

    jq -n \
        --argjson pool "$pool_json" \
        '{
            "proxy_pool": $pool,
            "total": 10,
            "threads": 3,
            "mode": "total",
            "mail": {
                "request_timeout": 30,
                "wait_timeout": 60,
                "wait_interval": 3,
                "providers": []
            }
        }' > "$REGISTER_FILE"
}

generate_app_compose() {
    if [ -n "$USE_NETWORK" ]; then
        cat > "$COMPOSE_FILE" <<EOF
services:
  app:
    image: $IMAGE
    container_name: $APP_CONTAINER
    restart: unless-stopped
    ports:
      - "127.0.0.1:${SERVICE_PORT}:80"
    volumes:
      - ./data:/app/data
      - ./config.json:/app/config.json
    environment:
      - TZ=Asia/Shanghai
    networks:
      - app_net

networks:
  app_net:
    external: true
    name: $APP_NETWORK
EOF
    else
        cat > "$COMPOSE_FILE" <<EOF
services:
  app:
    image: $IMAGE
    container_name: $APP_CONTAINER
    restart: unless-stopped
    ports:
      - "127.0.0.1:${SERVICE_PORT}:80"
    volumes:
      - ./data:/app/data
      - ./config.json:/app/config.json
    environment:
      - TZ=Asia/Shanghai
EOF
    fi
}

# ============================================================
#  cmd_install
# ============================================================
cmd_install() {
    log ""
    log "========================================="
    log "  安装 jovemage"
    log "========================================="

    if is_installed; then
        warn "检测到已安装在 $INSTALL_DIR"
        if ! confirm "是否覆盖（保留旧数据）" "N"; then
            info "已取消"
            return 0
        fi
    fi

    log ""
    log "[1/5] 前置检查..."
    log ""
    ensure_docker || return 1
    ok "Docker 可用"
    ok "Compose 命令: $COMPOSE_CMD"

    setup_proxy_suite || return 1

    log ""
    log "[3/5] 应用配置..."
    log ""
    AUTH_KEY=""
    while [ -z "$AUTH_KEY" ]; do
        AUTH_KEY=$(ask "请输入 auth-key（管理面板密码）" "")
        if [ -z "$AUTH_KEY" ]; then
            warn "auth-key 不能为空"
        elif [ ${#AUTH_KEY} -lt 8 ]; then
            warn "建议使用至少 8 字符的密码（当前 ${#AUTH_KEY} 字符）"
            if ! confirm "确认使用此密码" "N"; then AUTH_KEY=""; fi
        fi
    done

    while true; do
        SERVICE_PORT=$(ask "请输入服务端口" "9000")
        if [[ ! "$SERVICE_PORT" =~ ^[0-9]+$ ]] || [ "$SERVICE_PORT" -lt 1 ] || [ "$SERVICE_PORT" -gt 65535 ]; then
            warn "端口需要在 1-65535 之间"
            continue
        fi
        if is_port_in_use "$SERVICE_PORT"; then
            warn "端口 $SERVICE_PORT 已被占用"
            if confirm "仍要使用此端口" "N"; then break; fi
        else
            break
        fi
    done

    if confirm "是否开启 自动移除异常账号（401 持续失败自动删除）" "Y"; then
        AUTO_REMOVE_INVALID="true"
    else
        AUTO_REMOVE_INVALID="false"
    fi

    while true; do
        IMAGE_MAX_RETRIES=$(ask "图片生成失败时的换号重试次数（0=不重试）" "3")
        if [[ "$IMAGE_MAX_RETRIES" =~ ^[0-9]+$ ]] && [ "$IMAGE_MAX_RETRIES" -le 10 ]; then break; fi
        warn "请输入 0-10 的数字"
    done

    log ""
    log "[4/5] 生成配置文件..."
    log ""
    mkdir -p "$INSTALL_DIR/data"
    generate_config_files
    generate_app_compose
    {
        get_script_version
    } > "$INSTALL_DIR/.install-version"
    ok "配置已生成: $CONFIG_FILE"
    ok "Compose 已生成: $COMPOSE_FILE"

    log ""
    log "[5/5] 拉取镜像并启动..."
    log ""
    if ! docker pull "$IMAGE"; then
        err "镜像拉取失败"
        return 1
    fi
    if ! compose_in "$INSTALL_DIR" up -d; then
        err "服务启动失败"
        return 1
    fi

    log ""
    info "等待服务启动..."
    local wait_secs=0 healthy=0
    while [ $wait_secs -lt 30 ]; do
        if curl -fsS --max-time 2 "http://127.0.0.1:${SERVICE_PORT}/health" &> /dev/null; then
            healthy=1
            break
        fi
        sleep 2
        wait_secs=$(( wait_secs + 2 ))
        echo -n "."
    done
    echo ""

    log ""
    log "========================================="
    if [ $healthy -eq 1 ]; then
        ok "安装完成"
    else
        warn "服务未在 30 秒内通过健康检查"
        warn "请用 'docker logs jovemage' 查看日志"
    fi
    log "========================================="
    log ""
    log "  访问地址:     http://127.0.0.1:${SERVICE_PORT}"
    log "  管理密钥:     $AUTH_KEY"
    log "  安装目录:     $INSTALL_DIR"
    if [ -n "$PROXY_POOL_TEXT" ]; then
        local pool_count
        pool_count=$(echo "$PROXY_POOL_TEXT" | grep -c .)
        log "  代理池:       $pool_count 个 SOCKS5 出口"
    fi
    [ -n "$FLARE_URL" ] && log "  FlareSolverr: $FLARE_URL"
    log ""
    log "  外网访问请用 nginx 反代到 127.0.0.1:${SERVICE_PORT}"
    log ""
    return 0
}

# ============================================================
#  cmd_update
# ============================================================
cmd_update() {
    log ""
    log "========================================="
    log "  更新 jovemage"
    log "========================================="
    log ""

    if ! is_installed; then
        warn "未安装"
        return 0
    fi
    ensure_docker || return 1

    local old_version
    old_version=$(get_app_version)
    log "  当前版本: $old_version"
    log "  目标镜像: $IMAGE"
    log ""

    if ! confirm "确定升级到最新镜像吗" "Y"; then
        info "已取消"
        return 0
    fi

    info "备份当前 docker-compose.yml (几 KB，不含数据)..."
    cp "$COMPOSE_FILE" "${COMPOSE_FILE}.bak"
    ok "备份: ${COMPOSE_FILE}.bak"

    log ""
    info "拉取最新镜像..."
    if ! docker pull "$IMAGE"; then
        err "镜像拉取失败"
        return 1
    fi

    info "docker compose up -d (滚动更新)..."
    if ! compose_in "$INSTALL_DIR" up -d; then
        err "服务启动失败，尝试回滚..."
        cp "${COMPOSE_FILE}.bak" "$COMPOSE_FILE"
        compose_in "$INSTALL_DIR" up -d
        return 1
    fi

    local port
    port=$(get_service_port)
    [ -z "$port" ] && port="9000"
    info "等待健康检查..."
    local wait_secs=0
    while [ $wait_secs -lt 30 ]; do
        if curl -fsS --max-time 2 "http://127.0.0.1:${port}/health" &> /dev/null; then
            break
        fi
        sleep 2
        wait_secs=$(( wait_secs + 2 ))
        echo -n "."
    done
    echo ""
    ok "服务已就绪"

    local new_version
    new_version=$(get_app_version)
    log ""
    log "========================================="
    log "  升级完成"
    log "========================================="
    log ""
    ok "$old_version → $new_version"
    return 0
}

# ============================================================
#  cmd_restart — 重启本部署服务并换 IP
# ============================================================
cmd_restart() {
    log ""
    log "========================================="
    log "  重启并换 IP"
    log "========================================="
    log ""

    ensure_docker || return 1

    local warp_count
    warp_count=$(count_own_warp_running)

    log "  操作范围: 仅 $INSTALL_DIR 与网络 $APP_NETWORK"
    log "  当前本部署 WARP: $warp_count 个"
    if has_own_flare_running; then
        log "  FlareSolverr:    运行中 ($FLARE_CONTAINER)"
    else
        log "  FlareSolverr:    未运行"
    fi
    log ""

    if ! confirm "确认重启本部署所有服务并更换 IP" "Y"; then
        info "已取消"
        return 0
    fi

    # 1. 重启本部署代理套件
    if [ -f "$PROXY_COMPOSE_FILE" ]; then
        info "重启本部署代理套件..."
        if compose_in "$PROXY_DIR" restart; then
            ok "代理套件已重启"
        else
            warn "代理套件重启失败，尝试 down + up..."
            compose_in "$PROXY_DIR" down 2>/dev/null || true
            ensure_app_network
            compose_in "$PROXY_DIR" up -d || { err "代理启动失败"; return 1; }
            ok "代理套件已重建"
        fi
        log "  等待 WARP 重新连接..."
        sleep 10
        wait_warp_ready || true
        connect_own_containers_to_app_network
    else
        warn "未找到本部署代理 compose（$PROXY_COMPOSE_FILE），跳过代理重启"
    fi

    # 2. 重启主服务
    info "重启 $APP_CONTAINER..."
    if compose_in "$INSTALL_DIR" restart; then
        ok "服务已重启"
    else
        warn "restart 失败，尝试 down + up..."
        compose_in "$INSTALL_DIR" down 2>/dev/null || true
        compose_in "$INSTALL_DIR" up -d || { err "服务启动失败"; return 1; }
        ok "服务已重建"
    fi
    connect_to_app_network "$APP_CONTAINER"

    # 3. 健康检查
    info "等待健康检查..."
    wait_healthy 30
    ok "服务已就绪，IP 已更换"
}

# ============================================================
#  cmd_normalize_proxies — 重建本部署代理
#  参数 $1: 调用上下文 ("migrate" | "install" | "" 表示菜单调用)
#  只操作 $INSTALL_DIR/proxy 与 $APP_NETWORK，不动系统其它容器
# ============================================================
cmd_normalize_proxies() {
    local context="${1:-menu}"

    if [ "$context" = "menu" ]; then
        log ""
        log "========================================="
        log "  规整本部署代理"
        log "========================================="
        log ""
        log "  本功能用于:"
        log "    - 重建 $PROXY_DIR 下的 WARP / FlareSolverr"
        log "    - 重写本部署 proxy_pool 为 socks5h://${WARP_NAME_PREFIX}-N:1080"
        log "    - 确保专属网络 $APP_NETWORK 存在（同名新建或复用）"
        log ""
        log "  不会:"
        log "    - 扫描或删除系统中其它 warp / flaresolverr / privoxy"
        log "    - 修改或删除其它 Docker 网络"
        log ""
    fi

    ensure_docker || return 1

    local current_warp
    current_warp=$(count_own_warp_declared)
    if [ "${current_warp:-0}" -lt 1 ]; then
        current_warp=$(count_own_warp_running)
    fi

    if [ "$context" = "menu" ]; then
        log "  当前本部署状态:"
        log "    目录:              $PROXY_DIR"
        log "    WARP 声明/运行:    $(count_own_warp_declared) / $(count_own_warp_running)"
        if has_own_flare_running; then
            log "    FlareSolverr:      运行中 ($FLARE_CONTAINER)"
        else
            log "    FlareSolverr:      未运行"
        fi
        if ! has_app_network; then
            log "    专属网络:          未创建 (将自动创建 $APP_NETWORK)"
        elif docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$APP_CONTAINER" && ! container_in_app_network "$APP_CONTAINER"; then
            log "    专属网络:          $APP_CONTAINER 未加入 (将自动修复)"
        else
            log "    专属网络:          正常 ($APP_NETWORK)"
        fi
        if [ -f "$CONFIG_FILE" ] && validate_json "$CONFIG_FILE"; then
            if jq -e '.proxy_pool[]? | select(test("privoxy";"i"))' "$CONFIG_FILE" >/dev/null 2>&1; then
                log "    ⚠️  config proxy_pool 含 privoxy (将覆盖)"
            fi
        fi
        log ""
    fi

    local default_n=$(( current_warp > 0 ? current_warp : 2 ))
    if [ "$default_n" -lt 1 ]; then default_n=2; fi
    if [ "$default_n" -gt 6 ]; then default_n=6; fi

    local target_n
    while true; do
        target_n=$(ask "请输入目标 WARP 实例数量 (1-6)" "$default_n")
        if [[ "$target_n" =~ ^[1-6]$ ]]; then break; fi
        warn "请输入 1-6"
    done

    log ""
    log "  最终配置（仅本部署）:"
    local i
    for (( i=1; i<=target_n; i++ )); do
        log "    - $(own_warp_name "$i") (SOCKS5 端口 1080)"
    done
    log "    - $FLARE_CONTAINER"
    log ""
    log "  proxy_pool 将被覆盖为:"
    for (( i=1; i<=target_n; i++ )); do
        log "    socks5h://$(own_warp_name "$i"):1080"
    done
    log ""

    if [ "$context" = "menu" ]; then
        if ! confirm "确认执行（仅影响本部署）" "Y"; then
            info "已取消"
            return 0
        fi
    fi

    # 只 down 本部署 proxy compose / 本部署命名容器
    info "停止本部署代理容器..."
    if [ -f "$PROXY_COMPOSE_FILE" ]; then
        compose_in "$PROXY_DIR" down 2>/dev/null || true
    fi
    docker rm -f "$FLARE_CONTAINER" 2>/dev/null || true
    for (( i=1; i<=6; i++ )); do
        docker rm -f "$(own_warp_name "$i")" 2>/dev/null || true
    done
    ok "本部署旧代理容器已清理"

    info "生成本部署 compose..."
    mkdir -p "$PROXY_DIR"
    generate_proxy_compose "$PROXY_COMPOSE_FILE" "$target_n"
    ok "compose 已生成: $PROXY_COMPOSE_FILE"

    info "启动 $target_n 个 WARP + FlareSolverr..."
    ensure_app_network
    if ! compose_in "$PROXY_DIR" pull; then
        err "镜像拉取失败"
        return 1
    fi
    if ! compose_in "$PROXY_DIR" up -d; then
        err "代理启动失败"
        return 1
    fi
    ok "容器已启动"
    connect_own_containers_to_app_network

    log ""
    wait_warp_ready

    local new_pool
    new_pool=$(generate_socks5_pool_text "$target_n")

    if [ -f "$CONFIG_FILE" ] && validate_json "$CONFIG_FILE"; then
        info "覆盖 config.json proxy_pool / proxy_runtime.clearance..."
        jq_set_array "$CONFIG_FILE" '.proxy_pool' "$new_pool" && ok "config.json proxy_pool: $target_n 个"
        if jq_set_proxy_runtime_clearance "$CONFIG_FILE" "http://${FLARE_CONTAINER}:8191"; then
            ok "proxy_runtime.clearance: flaresolverr @ http://${FLARE_CONTAINER}:8191"
        else
            warn "写入 proxy_runtime 失败，请手动在设置页启用 FlareSolverr 清障"
        fi
        if jq -e 'has("proxy")' "$CONFIG_FILE" >/dev/null 2>&1; then
            local tmp_c
            tmp_c=$(mktemp)
            jq 'del(.proxy)' "$CONFIG_FILE" > "$tmp_c" && mv "$tmp_c" "$CONFIG_FILE"
        fi
    fi

    if [ -f "$REGISTER_FILE" ] && validate_json "$REGISTER_FILE"; then
        info "覆盖 register.json proxy_pool..."
        jq_set_array "$REGISTER_FILE" '.proxy_pool' "$new_pool" && ok "register.json proxy_pool: $target_n 个"
        if jq -e 'has("proxy")' "$REGISTER_FILE" >/dev/null 2>&1; then
            local tmp_r
            tmp_r=$(mktemp)
            jq 'del(.proxy)' "$REGISTER_FILE" > "$tmp_r" && mv "$tmp_r" "$REGISTER_FILE"
        fi
    fi

    if [ "$context" = "menu" ] && is_installed; then
        log ""
        connect_to_app_network "$APP_CONTAINER"
        if [ -f "$COMPOSE_FILE" ]; then
            local cur_port
            cur_port=$(get_service_port)
            SERVICE_PORT="${cur_port:-9000}"
            USE_NETWORK="$APP_NETWORK"
            generate_app_compose
            ok "docker-compose.yml 已更新为专属网络 $APP_NETWORK"
        fi
        if confirm "重启 $APP_CONTAINER 应用新配置" "Y"; then
            compose_in "$INSTALL_DIR" up -d 2>/dev/null || warn "重启失败"
            connect_to_app_network "$APP_CONTAINER"
            ok "已重启"
        fi
    fi

    log ""
    ok "本部署代理规整完成"
    return 0
}

# ============================================================
#  cmd_config 子菜单
# ============================================================
restart_app_if_needed() {
    if confirm "改动需要重启服务才能生效，现在重启吗" "Y"; then
        compose_in "$INSTALL_DIR" restart 2>/dev/null || warn "重启失败"
        ok "已重启"
    else
        warn "未重启，请稍后手动执行: cd $INSTALL_DIR && $COMPOSE_CMD restart"
    fi
}

config_change_auth_key() {
    log ""
    local current
    current=$(jq_get "$CONFIG_FILE" '.["auth-key"]' "")
    if [ ${#current} -gt 6 ]; then
        log "  当前 auth-key: ${current:0:3}***${current: -3}"
    fi
    log ""
    local new
    new=$(ask "请输入新的 auth-key" "")
    if [ -z "$new" ]; then
        warn "未输入，跳过"
        return
    fi
    if [ ${#new} -lt 8 ]; then
        warn "密码强度较弱（${#new} 字符）"
        if ! confirm "确认使用" "N"; then return; fi
    fi
    jq_set_string "$CONFIG_FILE" '.["auth-key"]' "$new" || { err "写入失败"; return; }
    ok "auth-key 已更新"
    restart_app_if_needed
}

config_change_port() {
    log ""
    local current
    current=$(get_service_port)
    log "  当前端口: $current"
    log ""
    local new
    while true; do
        new=$(ask "请输入新端口" "$current")
        if [[ ! "$new" =~ ^[0-9]+$ ]] || [ "$new" -lt 1 ] || [ "$new" -gt 65535 ]; then
            warn "端口需 1-65535"
            continue
        fi
        if [ "$new" != "$current" ] && is_port_in_use "$new"; then
            warn "端口 $new 已被占用"
            if confirm "仍要使用" "N"; then break; fi
            continue
        fi
        break
    done
    if [ "$new" = "$current" ]; then
        info "端口未变化"
        return
    fi
    sed -i.bak "s|127.0.0.1:${current}:80|127.0.0.1:${new}:80|g" "$COMPOSE_FILE"
    ok "端口已改为 $new"
    info "重启容器使端口生效..."
    compose_in "$INSTALL_DIR" up -d || warn "重启失败"
    ok "新端口: $new"
}

# 代理池子菜单（支持同步到另一个文件）
config_proxy_pool_submenu() {
    local file="$1" jq_path="$2" title="$3" sync_file="$4" sync_title="$5"

    while true; do
        log ""
        log "  ===== $title ====="
        log ""
        local items
        items=$(jq_get_array "$file" "$jq_path")
        if [ -z "$items" ]; then
            log "  当前代理池：空"
        else
            log "  当前代理池："
            local i=1
            while IFS= read -r p; do
                [ -z "$p" ] && continue
                printf "    %d) %s\n" "$i" "$p"
                i=$(( i + 1 ))
            done <<< "$items"
        fi
        log ""
        log "    a) 添加一个代理"
        log "    d) 删除某个代理（按编号）"
        log "    c) 清空"
        log "    0) 完成"
        log ""
        local choice
        choice=$(ask "请选择" "0")
        case "$choice" in
            a|A)
                local url
                url=$(ask "请输入代理 URL（如 socks5h://${WARP_NAME_PREFIX}-1:1080）" "")
                if [ -z "$url" ]; then continue; fi
                local new_items
                if [ -z "$items" ]; then
                    new_items="$url"
                else
                    new_items="$items
$url"
                fi
                jq_set_array "$file" "$jq_path" "$new_items" && ok "已添加" || err "写入失败"
                ;;
            d|D)
                if [ -z "$items" ]; then warn "代理池为空"; continue; fi
                local idx
                idx=$(ask "请输入要删除的编号" "")
                if ! [[ "$idx" =~ ^[0-9]+$ ]]; then continue; fi
                local new_items
                new_items=$(echo "$items" | awk -v n="$idx" 'NR != n')
                jq_set_array "$file" "$jq_path" "$new_items" && ok "已删除" || err "写入失败"
                ;;
            c|C)
                if confirm "确认清空代理池" "N"; then
                    jq_set_array "$file" "$jq_path" "" && ok "已清空"
                fi
                ;;
            0) break ;;
            *) warn "无效选项" ;;
        esac
    done

    # 询问是否同步到另一个文件
    if [ -n "$sync_file" ] && [ -f "$sync_file" ]; then
        log ""
        local final_items
        final_items=$(jq_get_array "$file" "$jq_path")
        if confirm "也同步到「$sync_title」吗" "Y"; then
            jq_set_array "$sync_file" "$jq_path" "$final_items" && ok "已同步到 $sync_title"
        fi
    fi

    restart_app_if_needed
}

config_change_image_max_retries() {
    log ""
    local current
    current=$(jq_get "$CONFIG_FILE" '.image_max_retries' "3")
    log "  当前: $current"
    log ""
    local new
    while true; do
        new=$(ask "请输入新值 (0-10)" "$current")
        if [[ "$new" =~ ^[0-9]+$ ]] && [ "$new" -le 10 ]; then break; fi
        warn "请输入 0-10"
    done
    if [ "$new" = "$current" ]; then info "未变化"; return; fi
    jq_set_number "$CONFIG_FILE" '.image_max_retries' "$new" || { err "写入失败"; return; }
    ok "已更新为 $new"
    restart_app_if_needed
}

config_toggle_auto_remove() {
    log ""
    local current
    current=$(jq_get "$CONFIG_FILE" '.auto_remove_invalid_accounts' "false")
    log "  当前: $current"
    log ""
    local new_bool
    if [ "$current" = "true" ]; then
        if confirm "切换为关闭" "Y"; then new_bool="false"; else return; fi
    else
        if confirm "切换为开启" "Y"; then new_bool="true"; else return; fi
    fi
    jq_set_bool "$CONFIG_FILE" '.auto_remove_invalid_accounts' "$new_bool" || { err "写入失败"; return; }
    ok "已切换为 $new_bool"
    restart_app_if_needed
}

config_advanced_edit() {
    local editor="${EDITOR:-vi}"
    if ! command -v "$editor" &> /dev/null; then editor="vi"; fi
    log ""
    info "将使用 $editor 打开 $CONFIG_FILE"
    press_enter
    "$editor" "$CONFIG_FILE"
    if ! validate_json "$CONFIG_FILE"; then
        err "JSON 格式无效！请检查后重新编辑"
        return
    fi
    ok "JSON 格式校验通过"
    restart_app_if_needed
}

cmd_config() {
    if ! is_installed; then
        warn "未安装"
        return 0
    fi
    ensure_docker || return 1
    if ! validate_json "$CONFIG_FILE"; then
        err "config.json 损坏，无法继续"
        return 1
    fi

    while true; do
        log ""
        log "========================================="
        log "  修改配置"
        log "========================================="
        log ""
        log "  请选择要修改的项:"
        log "    1) 修改 auth-key (管理面板密码)"
        log "    2) 修改服务端口"
        log "    3) 调整代理套件 (WARP 数量)"
        log "    4) 修改业务代理池"
        log "    5) 修改注册代理池"
        log "    6) 修改图片重试次数 (image_max_retries)"
        log "    7) 切换 自动移除异常账号 开关"
        log "    8) 高级: vi 编辑 config.json"
        log "    0) 返回主菜单"
        log ""
        local choice
        choice=$(ask "请输入选项" "0")
        case "$choice" in
            1) config_change_auth_key ;;
            2) config_change_port ;;
            3) cmd_normalize_proxies "menu" ;;
            4) config_proxy_pool_submenu "$CONFIG_FILE" '.proxy_pool' "业务代理池" "$REGISTER_FILE" "注册代理池" ;;
            5) config_proxy_pool_submenu "$REGISTER_FILE" '.proxy_pool' "注册代理池" "$CONFIG_FILE" "业务代理池" ;;
            6) config_change_image_max_retries ;;
            7) config_toggle_auto_remove ;;
            8) config_advanced_edit ;;
            0) break ;;
            *) warn "无效选项"; sleep 1 ;;
        esac
    done
}

# ============================================================
#  cmd_uninstall
# ============================================================
backup_app_data() {
    local ts backup
    ts=$(date +%Y%m%d-%H%M%S)
    backup="${HOME}/jovemage-backup-${ts}.tar.gz"
    info "正在备份到 $backup （排除 data/images/）..."
    tar -czf "$backup" \
        --exclude="$(basename "$INSTALL_DIR")/data/images" \
        -C "$(dirname "$INSTALL_DIR")" "$(basename "$INSTALL_DIR")" 2>/dev/null
    if [ -f "$backup" ]; then
        ok "备份完成: $backup"
        return 0
    fi
    err "备份失败"
    return 1
}

uninstall_app_only() {
    [ -d "$INSTALL_DIR" ] || return 0
    info "停止并删除本部署应用容器 ($APP_CONTAINER)..."
    compose_in "$INSTALL_DIR" down 2>/dev/null || true
    docker rm -f "$APP_CONTAINER" 2>/dev/null || true
    ok "服务已停止"
}

uninstall_proxy_suite() {
    # 仅清理本部署 /opt/jovemage/proxy 与本命名容器，不动系统其它代理
    [ -d "$PROXY_DIR" ] || [ -f "$PROXY_COMPOSE_FILE" ] || return 0
    info "停止并删除本部署代理套件 ($PROXY_DIR)..."
    if [ -f "$PROXY_COMPOSE_FILE" ]; then
        compose_in "$PROXY_DIR" down 2>/dev/null || true
    fi
    local i
    for (( i=1; i<=6; i++ )); do
        docker rm -f "$(own_warp_name "$i")" 2>/dev/null || true
    done
    docker rm -f "$FLARE_CONTAINER" 2>/dev/null || true
    ok "本部署代理套件已停止"
}

cmd_uninstall() {
    log ""
    log "========================================="
    log "  卸载 jovemage"
    log "========================================="
    log ""
    log "  ⚠️  这将停止/删除 jovemage 服务"
    log ""
    log "  请选择卸载范围:"
    log "    1) 仅停止服务 (保留所有数据和配置)"
    log "    2) 卸载服务，保留数据"
    log "       - 删除容器和 compose 文件"
    log "       - 保留 config.json + data/ + 镜像"
    log "    3) 完全卸载 (含数据 + 镜像)"
    log "       - 删除 $INSTALL_DIR 全部"
    log "    4) 同时卸载代理套件 ($PROXY_DIR)"
    log "       - 在 1/2/3 基础上加上代理套件清理"
    log "    0) 返回"
    log ""
    local scope
    scope=$(ask "请输入选项" "0")

    case "$scope" in
        0) return 0 ;;
        1)
            if ! is_installed; then warn "未安装"; return 0; fi
            ensure_docker || return 1
            info "停止服务..."
            compose_in "$INSTALL_DIR" stop 2>/dev/null || true
            ok "已停止"
            ;;
        2)
            if ! is_installed; then warn "未安装"; return 0; fi
            ensure_docker || return 1
            uninstall_app_only
            rm -f "$COMPOSE_FILE" "${COMPOSE_FILE}.bak"
            ok "服务已卸载"
            ;;
        3)
            if ! is_installed && [ ! -d "$INSTALL_DIR" ]; then
                warn "无安装目录"; return 0
            fi
            ensure_docker || return 1
            log ""
            warn "⚠️  即将删除 $INSTALL_DIR 下所有数据，包括账号池！"
            warn "此操作不可恢复！"
            log ""
            if confirm "是否在卸载前备份数据" "Y"; then
                backup_app_data || warn "备份失败但继续"
            fi
            log ""
            local cw
            read -rp '  请输入 "DELETE" 确认: ' cw
            if [ "$cw" != "DELETE" ]; then warn "已取消"; return 0; fi
            # 先清本部署代理容器（PROXY_DIR 在 INSTALL_DIR 内，目录删除后容器仍会残留）
            uninstall_proxy_suite
            uninstall_app_only
            docker rmi "$IMAGE" 2>/dev/null || true
            rm -rf "$INSTALL_DIR"
            ok "完全卸载完成"
            ;;
        4)
            ensure_docker || return 1
            log ""
            log "  请先选择应用的卸载范围:"
            log "    1) 仅停止应用"
            log "    2) 卸载应用，保留数据"
            log "    3) 完全卸载应用"
            log "    0) 跳过应用，只清理代理套件"
            log ""
            local sub
            sub=$(ask "请选择" "2")
            case "$sub" in
                1) compose_in "$INSTALL_DIR" stop 2>/dev/null || true ;;
                2) uninstall_app_only; rm -f "$COMPOSE_FILE" "${COMPOSE_FILE}.bak" ;;
                3)
                    if confirm "是否在卸载前备份数据" "Y"; then backup_app_data || true; fi
                    local cw2
                    read -rp '  请输入 "DELETE" 确认: ' cw2
                    if [ "$cw2" != "DELETE" ]; then
                        warn "跳过应用清理"
                    else
                        uninstall_app_only
                        docker rmi "$IMAGE" 2>/dev/null || true
                        rm -rf "$INSTALL_DIR"
                    fi
                    ;;
                0) info "跳过应用" ;;
            esac
            uninstall_proxy_suite
            if confirm "是否删除 $PROXY_DIR 目录" "N"; then
                rm -rf "$PROXY_DIR"
                ok "已删除 $PROXY_DIR"
            fi
            ok "卸载完成"
            ;;
        *) warn "无效选项" ;;
    esac
}

# ============================================================
#  cmd_clean_images
# ============================================================
cmd_clean_images() {
    log ""
    log "========================================="
    log "  清理图片缓存"
    log "========================================="
    log ""

    local img_dir="$INSTALL_DIR/data/images"
    local img_pattern='.*\.\(png\|jpg\|jpeg\|webp\|gif\|bmp\)$'

    if [ ! -d "$img_dir" ]; then
        warn "未发现图片目录: $img_dir"
        return 0
    fi

    local size count
    size=$(du -sh "$img_dir" 2>/dev/null | awk '{print $1}')
    count=$(find "$img_dir" -type f -regex "$img_pattern" 2>/dev/null | wc -l)

    log "  图片目录: $img_dir"
    log "  占用空间: $size"
    log "  图片数量: $count 张"
    log ""
    log "  说明: 仅删除图片文件，保留目录结构；不影响服务运行（无需重启）"
    log ""
    warn "⚠️  此操作不可恢复！"
    log ""
    if ! confirm "确认清理 $count 张图片" "N"; then
        info "已取消"
        return 0
    fi

    local total_bytes
    total_bytes=$(du -sb "$img_dir" 2>/dev/null | awk '{print $1}')
    if [ "${total_bytes:-0}" -gt 10737418240 ]; then
        warn "即将清理超过 10GB 的数据"
        local cw
        read -rp '  请输入 "DELETE" 确认: ' cw
        if [ "$cw" != "DELETE" ]; then
            warn "已取消"
            return 0
        fi
    fi

    info "清理 $img_dir ..."
    find "$img_dir" -type f -regex "$img_pattern" -delete 2>/dev/null
    find "$img_dir" -mindepth 1 -type d -empty -delete 2>/dev/null
    local after_count
    after_count=$(find "$img_dir" -type f -regex "$img_pattern" 2>/dev/null | wc -l)
    local deleted=$(( count - after_count ))

    log ""
    ok "图片清理完成，共删除 $deleted 张图片"
    log "  (服务无需重启，可继续使用)"
}

# ============================================================
#  cmd_status
# ============================================================
cmd_status() {
    log ""
    log "========================================="
    log "  JoveMage 状态"
    log "========================================="
    log ""

    log "  📦 应用"
    if is_installed; then
        local v port status
        v=$(get_app_version)
        port=$(get_service_port)
        status=$(get_app_status)
        log "     状态:        $status"

        # 版本对比（查询最新版）
        local latest version_line
        latest=$(get_latest_version)
        if [ -n "$latest" ]; then
            compare_versions "$v" "$latest"
            case $? in
                0) version_line="$v  ✅ 已是最新" ;;
                1) version_line="$v  ⚠️  有新版可用: $latest（菜单 3 可更新）" ;;
                2) version_line="$v  (本地版本高于远端 $latest)" ;;
                3) version_line="$v  (无法对比远端版本)" ;;
            esac
        else
            version_line="$v  (无法查询远端版本)"
        fi
        log "     版本:        $version_line"

        log "     端口:        127.0.0.1:$port"
        log "     安装目录:    $INSTALL_DIR"
        if [ -d "$INSTALL_DIR/data" ]; then
            local size
            size=$(du -sh "$INSTALL_DIR/data" 2>/dev/null | awk '{print $1}')
            log "     数据大小:    $size"
        fi
    else
        log "     状态:        未安装"
    fi

    log ""
    log "  🌐 本部署代理套件 (仅 $PROXY_DIR)"
    local warp_running warp_declared
    warp_running=$(count_own_warp_running)
    warp_declared=$(count_own_warp_declared)
    if has_own_proxy_suite || [ "$warp_running" -gt 0 ]; then
        log "     目录:          $PROXY_DIR"
        log "     WARP:          运行 $warp_running / 声明 $warp_declared"
        if has_own_flare_running; then
            log "     FlareSolverr:  运行中 ($FLARE_CONTAINER)"
        else
            log "     FlareSolverr:  未运行"
        fi
        if has_app_network; then
            log "     专属网络:      $APP_NETWORK"
        else
            log "     专属网络:      未创建"
        fi
    else
        log "     未部署（脚本不会扫描系统中其它 WARP/Flare）"
    fi

    if is_installed && validate_json "$CONFIG_FILE"; then
        log ""
        log "  🔑 配置"
        local pool_count register_pool_count max_retries auto_remove
        pool_count=$(jq '.proxy_pool | length' "$CONFIG_FILE" 2>/dev/null || echo "0")
        if [ -f "$REGISTER_FILE" ]; then
            register_pool_count=$(jq '.proxy_pool | length' "$REGISTER_FILE" 2>/dev/null || echo "0")
        else
            register_pool_count="0"
        fi
        max_retries=$(jq_get "$CONFIG_FILE" '.image_max_retries' "3")
        auto_remove=$(jq_get "$CONFIG_FILE" '.auto_remove_invalid_accounts' "false")
        log "     业务代理池:    $pool_count 个"
        log "     注册代理池:    $register_pool_count 个"
        log "     图片重试次数:  $max_retries"
        log "     自动移除异常:  $auto_remove"
    fi

    if is_installed && detect_proxy_issues; then
        log ""
        log "  ⚠️  代理名称/配置存在问题，建议: 主菜单选择 [9) 规整代理]"
    fi

    log ""
}

# ============================================================
#  show_menu - 动态菜单
# ============================================================
show_menu() {
    clear 2>/dev/null || true

    local tool_ver
    tool_ver=$(get_script_version)
    cat <<EOF
=========================================
  JoveMage 管理工具 v${tool_ver}
=========================================

EOF

    local choice

    if ! is_installed; then
        log "  当前状态: 未安装"
        log ""
        log "  请选择操作:"
        log "    1) 安装           (Install)"
        log "    0) 退出"
        log ""
        choice=$(ask "请输入选项" "")
        case "$choice" in
            1) cmd_install ;;
            0) log "再见"; exit 0 ;;
            *) warn "无效选项"; sleep 1 ;;
        esac
        press_enter
        return
    fi

    # 已安装
    local v port status
    v=$(get_app_version)
    port=$(get_service_port)
    status=$(get_app_status)
    log "  当前状态: $status"

    # 版本对比
    local latest version_display
    latest=$(get_latest_version)
    if [ -n "$latest" ]; then
        compare_versions "$v" "$latest"
        case $? in
            0) version_display="$v  ✅ 已最新" ;;
            1) version_display="$v  ⚠️  有新版: $latest" ;;
            *) version_display="$v" ;;
        esac
    else
        version_display="$v"
    fi
    log "  版本:     $version_display"

    log "  端口:     127.0.0.1:$port"
    log "  数据目录: $INSTALL_DIR"
    log ""

    local show_normalize=0
    if detect_proxy_issues; then show_normalize=1; fi

    log "  请选择操作:"
    log "    1) 状态                  (Status)"
    log "    2) 修改配置              (Configure)"
    log "    3) 更新镜像              (Update)"
    log "    4) 清理图片              (Clean Images)"
    log "    5) 卸载                  (Uninstall)"
    log "    6) 重启并换 IP           (Restart)"
    if [ $show_normalize -eq 1 ]; then
        log "    9) ⚠️  规整代理            (Normalize Proxies)"
    fi
    log "    0) 退出"
    log ""
    choice=$(ask "请输入选项" "")
    case "$choice" in
        1) cmd_status ;;
        2) cmd_config ;;
        3) cmd_update ;;
        4) cmd_clean_images ;;
        5) cmd_uninstall ;;
        6) cmd_restart ;;
        9) [ $show_normalize -eq 1 ] && cmd_normalize_proxies "menu" || warn "无效选项" ;;
        0) log "再见"; exit 0 ;;
        *) warn "无效选项"; sleep 1 ;;
    esac
    press_enter
}

# ============================================================
#  入口
# ============================================================
main() {
    ensure_command curl curl || true
    ensure_command jq jq || true
    ensure_command awk gawk || true

    while true; do
        show_menu
    done
}

main "$@"
