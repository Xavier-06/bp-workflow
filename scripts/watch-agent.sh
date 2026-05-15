#!/bin/zsh
set -euo pipefail

WORKSPACE="/Users/xavier/WorkBuddy/20260409155327/ir_runtime"
SESSION="${1:-main}"
MODE="${2:-auto}"

activity_cmd=$(cat <<EOF
while true; do
  clear
  date '+%Y-%m-%d %H:%M:%S %Z'
  echo
  echo '=== session ==='
  echo '${SESSION}'
  echo
  echo '=== git status ==='
  git -C '${WORKSPACE}' status --short
  echo
  echo '=== diff stat ==='
  git -C '${WORKSPACE}' diff --stat
  echo
  echo '=== files changed in last 10 min ==='
  find '${WORKSPACE}' -type f -mmin -10 \
    ! -path '*/.git/*' \
    ! -path '*/__pycache__/*' \
    | sort
  sleep 2
done
EOF
)

logs_cmd="openclaw logs --follow --local-time | grep -v 'cron: timer armed'"
tui_cmd="openclaw tui --session ${SESSION}"

print_commands() {
  cat <<EOF
# Window 1: workspace activity
${activity_cmd}

# Window 2: gateway logs (cron noise filtered)
${logs_cmd}

# Window 3: TUI for current session
${tui_cmd}
EOF
}

launch_tmux() {
  local session_name="openclaw-watch"
  tmux has-session -t "${session_name}" 2>/dev/null && tmux kill-session -t "${session_name}"
  tmux new-session -d -s "${session_name}" -c "${WORKSPACE}" "zsh -lc $(printf '%q' "${activity_cmd}")"
  tmux split-window -h -t "${session_name}:0" -c "${WORKSPACE}" "zsh -lc $(printf '%q' "${logs_cmd}")"
  tmux split-window -v -t "${session_name}:0.1" -c "${WORKSPACE}" "zsh -lc $(printf '%q' "${tui_cmd}")"
  tmux select-layout -t "${session_name}:0" tiled >/dev/null
  tmux attach -t "${session_name}"
}

write_temp_watchers() {
  local tmpdir="${TMPDIR:-/tmp}/openclaw-watch-${SESSION}"
  mkdir -p "${tmpdir}"

  cat > "${tmpdir}/activity.sh" <<EOF
#!/bin/zsh
${activity_cmd}
EOF

  cat > "${tmpdir}/logs.sh" <<EOF
#!/bin/zsh
${logs_cmd}
EOF

  cat > "${tmpdir}/tui.sh" <<EOF
#!/bin/zsh
cd '${WORKSPACE}'
${tui_cmd}
EOF

  chmod +x "${tmpdir}/activity.sh" "${tmpdir}/logs.sh" "${tmpdir}/tui.sh"
  printf '%s\n' "${tmpdir}"
}

launch_terminal_tabs() {
  local tmpdir
  tmpdir=$(write_temp_watchers)

  osascript <<EOF
set workspacePath to "${WORKSPACE}"
set activityScript to "${tmpdir}/activity.sh"
set logsScript to "${tmpdir}/logs.sh"
set tuiScript to "${tmpdir}/tui.sh"

tell application "Terminal"
  activate
  do script "cd " & quoted form of workspacePath & "; zsh " & quoted form of activityScript
  delay 0.3
  tell application "System Events" to keystroke "t" using command down
  delay 0.3
  do script "cd " & quoted form of workspacePath & "; zsh " & quoted form of logsScript in selected tab of front window
  delay 0.3
  tell application "System Events" to keystroke "t" using command down
  delay 0.3
  do script "cd " & quoted form of workspacePath & "; zsh " & quoted form of tuiScript in selected tab of front window
end tell
EOF
}

if [[ "${MODE}" == "print" ]]; then
  print_commands
  exit 0
fi

if command -v tmux >/dev/null 2>&1; then
  launch_tmux
  exit 0
fi

if [[ "${MODE}" == "tmux" ]]; then
  echo "tmux not found. Install tmux or run: zsh ${WORKSPACE}/scripts/watch-agent.sh ${SESSION} print" >&2
  exit 1
fi

if command -v osascript >/dev/null 2>&1; then
  launch_terminal_tabs
  exit 0
fi

print_commands
