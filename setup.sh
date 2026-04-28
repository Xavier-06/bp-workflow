#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
# 🐲 IR/BP Workflow — 一键安装脚本
# 用法: bash setup.sh [--workbuddy|--openclaw] [--skip-pip] [--skip-searxng]
# ═══════════════════════════════════════════════════════════
set -euo pipefail

PLATFORM="${1:---workbuddy}"
SKIP_PIP=false
SKIP_SEARXNG=false

for arg in "$@"; do
  case "$arg" in
    --skip-pip)     SKIP_PIP=true ;;
    --skip-searxng) SKIP_SEARXNG=true ;;
    --workbuddy)    PLATFORM="--workbuddy" ;;
    --openclaw)     PLATFORM="--openclaw" ;;
  esac
done

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; }

# ── 1. 确定目标路径 ──
if [ "$PLATFORM" == "--openclaw" ]; then
  BASE_DIR="$HOME/.openclaw/workspace"
  SKILLS_DIR="$HOME/.openclaw/skills"
else
  BASE_DIR="$HOME/.workbuddy"
  SKILLS_DIR="$HOME/.workbuddy/skills"
fi

TARGET_DIR="$BASE_DIR/ir_runtime"

info "Platform: $PLATFORM"
info "Target: $TARGET_DIR"

# ── 2. 克隆或更新 ──
REPO_URL="https://github.com/Xavier-06/ir-bp-workflow.git"

if [ -d "$TARGET_DIR/.git" ]; then
  info "ir_runtime 已存在，拉取最新..."
  cd "$TARGET_DIR"
  git pull origin main || warn "git pull 失败，继续使用本地版本"
else
  info "克隆仓库到 $TARGET_DIR ..."
  mkdir -p "$BASE_DIR"
  git clone "$REPO_URL" "$TARGET_DIR"
  cd "$TARGET_DIR"
fi

# ── 3. 安装 Python 依赖 ──
if [ "$SKIP_PIP" = false ]; then
  info "安装 Python 依赖..."
  pip install -r requirements.txt 2>/dev/null || pip3 install -r requirements.txt
fi

# ── 4. 配置环境变量 ──
if [ ! -f "$TARGET_DIR/.env" ]; then
  cp "$TARGET_DIR/.env.example" "$TARGET_DIR/.env"
  warn ".env 已从模板创建，请编辑 $TARGET_DIR/.env 填写你的 API 配置"
else
  info ".env 已存在，跳过"
fi

# ── 5. 安装 Skills ──
info "安装 AI Skills 到 $SKILLS_DIR ..."
mkdir -p "$SKILLS_DIR"

for skill in ir-coordinator ir-researcher ir-reporter ir-verifier; do
  if [ -d "$SKILLS_DIR/$skill" ]; then
    info "Skill $skill 已存在，更新..."
  else
    info "安装 Skill: $skill"
  fi
  mkdir -p "$SKILLS_DIR/$skill"
  cp "$TARGET_DIR/skills/$skill/SKILL.md" "$SKILLS_DIR/$skill/SKILL.md"
done

# ── 6. 配置平台 ──
if [ "$PLATFORM" == "--openclaw" ]; then
  AGENTS_FILE="$BASE_DIR/AGENTS.md"
  if [ -f "$AGENTS_FILE" ]; then
    if ! grep -q "ir-coordinator" "$AGENTS_FILE" 2>/dev/null; then
      warn "建议在 $AGENTS_FILE 中添加 ir-coordinator 触发规则"
      warn "参考: $TARGET_DIR/docs/openclaw-setup.md"
    fi
  fi
else
  # WorkBuddy: skill 安装到 ~/.workbuddy/skills/ 后自动生效
  info "WorkBuddy Skills 已安装，重启 WorkBuddy 后自动加载"
fi

# ── 7. 创建必要目录 ──
mkdir -p "$TARGET_DIR/jobs"
mkdir -p "$TARGET_DIR/logs"
mkdir -p "$TARGET_DIR/data"
mkdir -p "$TARGET_DIR/sessions"
mkdir -p "$TARGET_DIR/outputs"

# ── 8. 验证安装 ──
info "验证安装..."
cd "$TARGET_DIR"

if python3 -m runtime.orchestrator.pipeline_orchestrator --help &>/dev/null; then
  info "✅ 管线编排器正常"
else
  warn "管线编排器验证失败，请检查 Python 依赖"
fi

echo ""
info "═══════════════════════════════════════════"
info "🐲 IR/BP Workflow 安装完成!"
info ""
info "下一步："
info "  1. 编辑 $TARGET_DIR/.env 配置 API 密钥"
info "  2. 重启 WorkBuddy / OpenClaw"
info "  3. 对话中说'分析XX股票'或'看看这个BP'即可触发"
info ""
info "文档: $TARGET_DIR/docs/"
info "═══════════════════════════════════════════"
