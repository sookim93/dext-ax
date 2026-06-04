#!/usr/bin/env bash
#
# claude-audit.sh — Claude Code 환경 정리 감사
#
# 점검 항목:
#   1) CLAUDE.md 단어 수 (한계 초과 시 경고)
#   2) 활성 플러그인 & 스킬 5개 초과 여부
#   3) 상시 MCP 서버 3개 초과 여부
#   4) 최근 7일 호출 안 된 스킬 / MCP 서버
#   5) hooks.UserPromptSubmit 훅 목록
#
# 출력: audit-report.md (스크립트와 같은 디렉토리, 또는 인자로 지정)
#
# Usage:  bash claude-audit.sh           # 현재 디렉토리에 저장
#         bash claude-audit.sh /path/dir # 지정 디렉토리에 저장

set -uo pipefail

CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SETTINGS_JSON="$CLAUDE_DIR/settings.json"
CLAUDE_JSON="$HOME/.claude.json"
SESSIONS_DIR="$CLAUDE_DIR/projects"
SKILLS_DIR="$CLAUDE_DIR/skills"
PLUGINS_DIR="$CLAUDE_DIR/plugins"

WORD_LIMIT=1200
PLUGIN_SKILL_LIMIT=5
MCP_LIMIT=3
INACTIVE_DAYS=7

OUT_DIR="${1:-$(pwd)}"
REPORT="$OUT_DIR/audit-report.md"

mkdir -p "$OUT_DIR"

require() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "[ERROR] '$1' 명령이 필요합니다. 설치 후 다시 실행하세요." >&2
        exit 2
    fi
}
require jq
require find
require grep
require sort
require wc

now_iso=$(date '+%Y-%m-%d %H:%M:%S')

# ---------- 1) CLAUDE.md 단어 수 ----------
section_claude_md() {
    echo "## 1. CLAUDE.md 단어 수 점검"
    echo
    echo "| 파일 | 단어 | 한계 | 상태 |"
    echo "|------|------|------|------|"
    local files=("$CLAUDE_DIR/CLAUDE.md" "$(pwd)/CLAUDE.md")
    local any_over=0
    for f in "${files[@]}"; do
        if [[ -f "$f" ]]; then
            local w
            w=$(wc -w <"$f" | tr -d ' ')
            local status="✅ OK"
            if (( w > WORD_LIMIT )); then
                status="⚠️ 초과"
                any_over=1
            fi
            echo "| \`$f\` | $w | $WORD_LIMIT | $status |"
        fi
    done
    echo
    if (( any_over == 1 )); then
        echo "**다이어트 제안:**"
        echo "- 중복 섹션 통합 / 외부 참조(스킬·문서) 링크로 대체"
        echo "- 실제로 안 지켜지는 규칙 삭제"
        echo "- 키워드 트리거·카탈로그성 항목은 별도 reference 파일로 분리"
    else
        echo "_단어 수 한계 미만 — 조치 불필요._"
    fi
    echo
}

# ---------- 2) 플러그인 & 스킬 ----------
section_plugins_skills() {
    echo "## 2. 활성 플러그인 & 스킬 카운트"
    echo
    local plugins=()
    if [[ -f "$SETTINGS_JSON" ]]; then
        while IFS= read -r line; do
            [[ -n "$line" ]] && plugins+=("$line")
        done < <(jq -r '.enabledPlugins // {} | to_entries[] | select(.value == true or (.value|type == "array")) | .key' "$SETTINGS_JSON" 2>/dev/null)
    fi

    local skill_count=0
    if [[ -d "$SKILLS_DIR" ]]; then
        while IFS= read -r s; do
            [[ -n "$s" ]] && ((skill_count++))
        done < <(find "$SKILLS_DIR" -maxdepth 1 -mindepth 1 -type d -exec basename {} \; 2>/dev/null | sort)
    fi
    if [[ -d "$PLUGINS_DIR" ]]; then
        while IFS= read -r s; do
            [[ -n "$s" ]] && ((skill_count++))
        done < <(find "$PLUGINS_DIR" -mindepth 3 -maxdepth 3 -type d -path '*/skills/*' -exec basename {} \; 2>/dev/null | sort -u)
    fi

    echo "- 활성 플러그인: **${#plugins[@]}개**"
    if [[ ${#plugins[@]} -gt 0 ]]; then
        for p in "${plugins[@]}"; do echo "  - \`$p\`"; done
    fi
    echo "- 총 스킬: **${skill_count}개** (글로벌 + 플러그인 제공)"
    echo

    local total=$(( ${#plugins[@]} + skill_count ))
    if (( total > PLUGIN_SKILL_LIMIT )); then
        echo "⚠️ **합계 ${total}개 — 한계(${PLUGIN_SKILL_LIMIT}) 초과.**"
        echo
        echo "**비활성화 대상 후보** (최근 ${INACTIVE_DAYS}일 미호출 — 섹션 4 참고):"
        echo "- 아래 \"미호출 스킬\" 목록을 우선 검토"
        echo "- 비활성화 방법: \`~/.claude/settings.json\`의 \`enabledPlugins\`에서 \`false\` 설정,"
        echo "  또는 \`skillOverrides\`에 \`{\"<skill>\": \"off\"}\` 추가"
    else
        echo "_한계 미만 — 조치 불필요._"
    fi
    echo
}

# ---------- 3) MCP 서버 ----------
mcp_servers_from_claude_json() {
    [[ -f "$CLAUDE_JSON" ]] && jq -r '.mcpServers // {} | keys[]' "$CLAUDE_JSON" 2>/dev/null
}

section_mcp() {
    echo "## 3. 상시 MCP 서버 점검"
    echo
    local servers=()
    while IFS= read -r s; do
        [[ -n "$s" ]] && servers+=("$s")
    done < <(mcp_servers_from_claude_json)

    echo "- 등록된 MCP 서버: **${#servers[@]}개**"
    if [[ ${#servers[@]} -gt 0 ]]; then
        for s in "${servers[@]}"; do echo "  - \`$s\`"; done
    fi
    echo

    if (( ${#servers[@]} > MCP_LIMIT )); then
        echo "⚠️ **${#servers[@]}개 — 한계(${MCP_LIMIT}) 초과.**"
        echo
        echo "**비활성화 명령** (필요한 것만 켜두는 것을 권장):"
        for s in "${servers[@]}"; do
            echo "- \`/mcp disable $s\`  또는  \`claude mcp remove $s\`"
        done
    else
        echo "_한계 미만 — 조치 불필요._"
    fi
    echo
}

# ---------- 4) 최근 N일 호출 안 된 스킬 / MCP ----------
collect_recent_jsonl() {
    [[ -d "$SESSIONS_DIR" ]] && find "$SESSIONS_DIR" -name '*.jsonl' -mtime "-$INACTIVE_DAYS" 2>/dev/null
}

section_inactive() {
    echo "## 4. 최근 ${INACTIVE_DAYS}일 미호출 스킬 / MCP 서버"
    echo
    local jsonls
    jsonls=$(collect_recent_jsonl)
    local session_count=0
    [[ -n "$jsonls" ]] && session_count=$(echo "$jsonls" | wc -l | tr -d ' ')
    echo "- 분석 세션 파일: ${session_count}개"
    echo

    if [[ -z "$jsonls" ]]; then
        echo "_분석할 세션 로그가 없습니다._"
        echo
        return
    fi

    local used_skills_file used_mcp_file all_skills_file all_mcp_file
    used_skills_file=$(mktemp)
    used_mcp_file=$(mktemp)
    all_skills_file=$(mktemp)
    all_mcp_file=$(mktemp)

    # 호출된 스킬: Skill 도구 호출 시 args에 "skill":"name"
    echo "$jsonls" | xargs grep -hoE '"skill":"[a-zA-Z0-9:_-]+"' 2>/dev/null \
        | sed -E 's/"skill":"([^"]+)"/\1/' \
        | sort -u >"$used_skills_file" || true

    # 호출된 MCP 서버: mcp__<server>__<tool>
    echo "$jsonls" | xargs grep -hoE 'mcp__[a-zA-Z0-9_-]+__' 2>/dev/null \
        | sed -E 's/^mcp__(.+)__$/\1/' \
        | sort -u >"$used_mcp_file" || true

    # 전체 스킬 목록
    {
        [[ -d "$SKILLS_DIR" ]] && find "$SKILLS_DIR" -maxdepth 1 -mindepth 1 -type d -exec basename {} \;
        [[ -d "$PLUGINS_DIR" ]] && find "$PLUGINS_DIR" -mindepth 3 -maxdepth 3 -type d -path '*/skills/*' -exec basename {} \;
    } 2>/dev/null | sort -u >"$all_skills_file"

    # 전체 MCP 서버
    mcp_servers_from_claude_json | sort -u >"$all_mcp_file"

    echo "### 미호출 스킬"
    local inactive_skills
    inactive_skills=$(comm -23 "$all_skills_file" "$used_skills_file" 2>/dev/null || true)
    if [[ -z "$inactive_skills" ]]; then
        echo "_없음._"
    else
        local cnt
        cnt=$(echo "$inactive_skills" | wc -l | tr -d ' ')
        echo "총 ${cnt}개 (정리 대상 후보):"
        echo
        echo "$inactive_skills" | sed 's/^/- /'
    fi
    echo

    echo "### 미호출 MCP 서버"
    local inactive_mcp
    inactive_mcp=$(comm -23 "$all_mcp_file" "$used_mcp_file" 2>/dev/null || true)
    if [[ -z "$inactive_mcp" ]]; then
        echo "_없음._"
    else
        echo "$inactive_mcp" | sed 's/^/- /'
    fi
    echo

    rm -f "$used_skills_file" "$used_mcp_file" "$all_skills_file" "$all_mcp_file"
}

# ---------- 5) UserPromptSubmit 훅 ----------
section_hooks() {
    echo "## 5. hooks.UserPromptSubmit 훅 점검"
    echo
    if [[ ! -f "$SETTINGS_JSON" ]]; then
        echo "_settings.json 없음._"
        echo
        return
    fi
    local hooks_json
    hooks_json=$(jq -c '.hooks.UserPromptSubmit // []' "$SETTINGS_JSON" 2>/dev/null)
    if [[ "$hooks_json" == "[]" || -z "$hooks_json" ]]; then
        echo "_UserPromptSubmit에 등록된 훅 없음 — 조치 불필요._"
        echo
        return
    fi

    local n
    n=$(echo "$hooks_json" | jq 'length' 2>/dev/null)
    echo "- 등록된 훅 매처: **${n}개**"
    echo
    echo "| matcher | type | command/prompt |"
    echo "|---------|------|----------------|"
    echo "$hooks_json" | jq -r '.[] | .matcher as $m | (.hooks // [])[] | "| \($m // "(none)") | \(.type) | \(.command // .prompt // .url // "—" | gsub("\n"; " ") | .[0:80]) |"' 2>/dev/null
    echo
    echo "**검토 권장:**"
    echo "- 모든 프롬프트마다 실행되는 훅은 지연·토큰을 늘리므로 꼭 필요한지 재검토"
    echo "- 중복 매처, 항상 성공만 출력하는 훅, 비활성화된 도구의 훅은 삭제 후보"
    echo
}

# ---------- 보고서 작성 ----------
{
    echo "# Claude 환경 점검 보고서"
    echo
    echo "_생성: ${now_iso}_  "
    echo "_기준 디렉토리: \`${CLAUDE_DIR}\`_"
    echo
    section_claude_md
    section_plugins_skills
    section_mcp
    section_inactive
    section_hooks
    echo "---"
    echo "_claude-audit.sh — 자동 생성_"
} >"$REPORT"

echo "✅ 보고서 저장됨: $REPORT"
