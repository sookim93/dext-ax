/**
 * Client-side JavaScript for bidding notice dashboard
 *
 * Sync is now async: POST /sync returns immediately and we poll /sync/status
 * every few seconds until the background task finishes, then auto-reload.
 */

const SYNC_POLL_INTERVAL_MS = 3000;
const SYNC_MAX_POLLS = 120;  // ~6 minutes ceiling — safety net

/* ---------- Toast notifications (replaces alert()) ---------- */

function toast(message, variant = "info", durationMs = 3500) {
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        container.className = "toast-container";
        document.body.appendChild(container);
    }
    const el = document.createElement("div");
    el.className = `toast toast-${variant}`;
    el.textContent = message;
    container.appendChild(el);
    requestAnimationFrame(() => el.classList.add("toast-show"));
    setTimeout(() => {
        el.classList.remove("toast-show");
        setTimeout(() => el.remove(), 350);
    }, durationMs);
}

/* ---------- Decision (참여 / 패스) ---------- */

async function makeDecision(noticeId, decision) {
    try {
        const response = await fetch(`/notices/${noticeId}/decide`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ decision }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            toast(`오류: ${error.detail || "결정 저장에 실패했습니다."}`, "error");
            return;
        }

        // Update UI in-place
        const row = document.querySelector(`tr[data-notice-id="${noticeId}"]`);
        if (row) {
            row.classList.add("decided");
            const actionCell = row.querySelector(".decision-actions");
            if (actionCell) {
                actionCell.innerHTML = '<span class="decision-made">결정됨</span>';
            }
        }
        toast(decision === "participate" ? "참여로 저장됨" : "패스로 저장됨", "success");
    } catch (err) {
        console.error("Error making decision:", err);
        toast("결정을 저장하는 중에 오류가 발생했습니다.", "error");
    }
}

/* ---------- Sync (background + polling) ---------- */

let syncButtonRef = null;

function setSyncButton(state) {
    if (!syncButtonRef) return;
    if (state === "running") {
        syncButtonRef.disabled = true;
        syncButtonRef.textContent = "동기화 중...";
    } else {
        syncButtonRef.disabled = false;
        syncButtonRef.textContent = "동기화";
    }
}

async function syncNotices(event) {
    syncButtonRef = (event && event.target) || document.querySelector(".btn-sync");

    try {
        setSyncButton("running");
        const response = await fetch("/sync", { method: "POST" });

        if (!response.ok) {
            toast("동기화 시작 실패", "error");
            setSyncButton("idle");
            return;
        }

        const payload = await response.json();
        if (payload.status === "already_running") {
            toast("이미 다른 동기화가 진행 중입니다. 완료를 기다립니다.", "info");
        } else {
            toast("동기화 시작 — 보통 1~2분 소요됩니다.", "info");
        }
        pollSyncStatus();
    } catch (err) {
        console.error("Sync trigger error:", err);
        toast("동기화 시작 중 오류가 발생했습니다.", "error");
        setSyncButton("idle");
    }
}

function pollSyncStatus() {
    let polls = 0;
    const handle = setInterval(async () => {
        polls += 1;
        if (polls > SYNC_MAX_POLLS) {
            clearInterval(handle);
            toast("동기화가 너무 오래 걸립니다. 서버 로그를 확인하세요.", "error");
            setSyncButton("idle");
            return;
        }
        try {
            const resp = await fetch("/sync/status");
            const s = await resp.json();
            if (!s.running) {
                clearInterval(handle);
                setSyncButton("idle");
                if (s.error) {
                    toast(`동기화 실패: ${s.error}`, "error", 6000);
                    return;
                }
                const r = s.last_result || {};
                toast(
                    `동기화 완료 — 신규 ${r.inserted || 0}건 / 필터통과 ${r.filtered || 0}건 / 조회 ${r.fetched || 0}건`,
                    "success",
                    4500
                );
                setTimeout(() => location.reload(), 1500);
            }
        } catch (err) {
            console.error("Polling error:", err);
        }
    }, SYNC_POLL_INTERVAL_MS);
}

/* ---------- On-load: pick up sync that was already running ---------- */

(async function bootstrap() {
    try {
        const resp = await fetch("/sync/status");
        const s = await resp.json();
        if (s.running) {
            syncButtonRef = document.querySelector(".btn-sync");
            setSyncButton("running");
            toast("이전 동기화가 아직 진행 중입니다. 완료를 기다립니다...", "info");
            pollSyncStatus();
        }
    } catch (_) {
        /* silent */
    }
})();
