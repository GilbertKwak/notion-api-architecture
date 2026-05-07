#!/usr/bin/env python3
# ============================================================
# t09_sync.py
# T-09 Mother Page 동기화 스크립트  (PHASE 2 전환)
# 최우선 스크립트 — 일 2-3회 실행
#
# 변경 이력:
#   PHASE 2  update_content 3개 → replace_content 전환
#            8섹션 MetadataManager 초기화
#            post-update verification 추가
# ============================================================

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation.metadata_manager import (
    initialize_section_metadata,
    update_section_by_metadata,
    validate_metadata_integrity,
    error_predictor,
    parallel_section_update,
)

# ── 로거 설정 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("t09_sync")

# ── 유틸 ───────────────────────────────────────────────────

def normalize_notion_id(raw: str) -> str:
    """
    32자 hex → Notion UUID 형식(8-4-4-4-12) 변환.
    이미 대시 포함 시 그대로 반환.

    Examples
    --------
    >>> normalize_notion_id("34955ed436f081149dd6de25dba027d7")
    '34955ed4-36f0-8114-9dd6-de25dba027d7'
    >>> normalize_notion_id("34955ed4-36f0-8114-9dd6-de25dba027d7")
    '34955ed4-36f0-8114-9dd6-de25dba027d7'
    """
    s = raw.replace("-", "").lower()
    if len(s) != 32:
        raise ValueError(f"유효하지 않은 Notion ID (길이={len(s)}): {raw!r}")
    return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"


# ── 상단 고정 상수 ──────────────────────────────────────────
PAGE_ID = normalize_notion_id("34955ed436f081149dd6de25dba027d7")
# → "34955ed4-36f0-8114-9dd6-de25dba027d7"  ✅ Notion API 수용 확인
PAGE_LABEL = "T-09 Mother Page"
SESSION_LOG_DIR = Path("session_logs")

# ── 섹션별 콘텐츠 생성 함수 ────────────────────────────────
# replace_content 전환 섹션: banner / kg_table / ew_table / session / actions
# update_content  유지 섹션: sop / links  (plain_text_only 태그 준수)

_NOW_KST = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M KST")


def _build_banner() -> str:
    """갱신 배너 — replace_content (PHASE 2 전환)"""
    return (
        f"---\n"
        f"# 📌 갱신 배너\n"
        f"**최종 갱신**: {_NOW_KST}  \n"
        f"**스크립트**: t09_sync.py (PHASE 2)  \n"
        f"**상태**: 🟢 정상  \n"
        f"---\n"
    )


def _build_kg_table(payload: dict | None = None) -> str:
    """KG 현황 테이블 — replace_content (PHASE 2 전환)"""
    rows = (payload or {}).get("kg_rows", [])
    header = (
        "## 📊 Knowledge Graph 현황\n\n"
        "| 도메인 | 노드 수 | 엣지 수 | 최종 갱신 |\n"
        "|--------|---------|---------|----------|\n"
    )
    if not rows:
        rows = [
            {"domain": "PE-SEMI", "nodes": "-", "edges": "-", "updated": _NOW_KST},
            {"domain": "PE-MIN",  "nodes": "-", "edges": "-", "updated": _NOW_KST},
            {"domain": "PE-EQP",  "nodes": "-", "edges": "-", "updated": _NOW_KST},
        ]
    body = "".join(
        f"| {r['domain']} | {r['nodes']} | {r['edges']} | {r['updated']} |\n"
        for r in rows
    )
    return header + body + "\n---\n"


def _build_ew_table(payload: dict | None = None) -> str:
    """EW 트리거 테이블 — replace_content (PHASE 2 전환)"""
    triggers = (payload or {}).get("ew_triggers", [])
    header = (
        "## ⚡ EW 트리거\n\n"
        "| 트리거 ID | 조건 | 상태 | 갱신 시각 |\n"
        "|-----------|------|------|----------|\n"
    )
    if not triggers:
        triggers = []
    body = "".join(
        f"| {t['id']} | {t['condition']} | {t['status']} | {t['updated']} |\n"
        for t in triggers
    ) or "| — | — | — | — |\n"
    return header + body + "\n---\n"


def _build_session(payload: dict | None = None) -> str:
    """세션 히스토리 — replace_content (PHASE 2 전환)"""
    sessions = (payload or {}).get("sessions", [])
    header = (
        "## 📝 세션 히스토리\n\n"
        "| 세션 ID | 시각 | 주요 작업 | 결과 |\n"
        "|---------|------|-----------|------|\n"
    )
    if not sessions:
        sessions = [{"id": "latest", "time": _NOW_KST,
                     "task": "t09_sync.py PHASE 2 전환", "result": "✅"}]
    body = "".join(
        f"| {s['id']} | {s['time']} | {s['task']} | {s['result']} |\n"
        for s in sessions
    )
    return header + body + "\n---\n"


def _build_actions(payload: dict | None = None) -> str:
    """후속 액션 — replace_content (PHASE 2 전환)"""
    actions = (payload or {}).get("actions", [])
    header = (
        "## 🔴 후속 액션\n\n"
        "| 우선순위 | 액션 | 담당 | 기한 |\n"
        "|----------|------|------|------|\n"
    )
    body = "".join(
        f"| {a['priority']} | {a['action']} | {a['owner']} | {a['due']} |\n"
        for a in actions
    ) or "| — | — | — | — |\n"
    return header + body + "\n---\n"


# ── proposed_updates 빌드 ──────────────────────────────────

def build_proposed_updates(payload: dict | None = None,
                           section_filter: list[str] | None = None) -> dict[str, str]:
    """
    섹션 ID → 새 콘텐츠 매핑 생성.

    PHASE 2 전환 원칙:
      replace_content: banner / kg_table / ew_table / session / actions
      update_content : sop / links  ← 함수에서 생성하지 않음 (외부 제공 시에만 포함)
    """
    all_updates: dict[str, str] = {
        "banner":   _build_banner(),
        "kg_table": _build_kg_table(payload),
        "ew_table": _build_ew_table(payload),
        "session":  _build_session(payload),
        "actions":  _build_actions(payload),
    }
    if payload:
        if "sop_content" in payload:
            all_updates["sop"] = payload["sop_content"]
        if "links_content" in payload:
            all_updates["links"] = payload["links_content"]

    if section_filter:
        all_updates = {k: v for k, v in all_updates.items() if k in section_filter}

    return all_updates


# ── 세션 로그 저장 ─────────────────────────────────────────

def _save_session_log(results: dict, meta_summary: dict, elapsed: float) -> Path:
    SESSION_LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = SESSION_LOG_DIR / f"t09_sync_{ts}.json"
    log_data = {
        "script": "t09_sync.py",
        "page_id": PAGE_ID,
        "page_label": PAGE_LABEL,
        "timestamp_utc": ts,
        "elapsed_sec": round(elapsed, 2),
        "results": results,
        "metadata_summary": meta_summary,
    }
    log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2))
    logger.info("[t09_sync] 세션 로그 저장: %s", log_path)
    return log_path


# ── 메인 실행 로직 ─────────────────────────────────────────

def run(
    token: str,
    payload: dict | None = None,
    section_filter: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """
    T-09 동기화 메인 진입점.

    흐름:
      1. MetadataManager 초기화 (8섹션)
      2. error_predictor 사전 검증
      3. safe_to_proceed → parallel_section_update
      4. validate_metadata_integrity
      5. 세션 로그 저장
    """
    t_start = time.time()
    logger.info("=" * 60)
    logger.info("[t09_sync] 시작  PAGE_ID=%s  dry_run=%s", PAGE_ID, dry_run)

    # STEP 1: 메타데이터 초기화
    meta = initialize_section_metadata(PAGE_ID, token, PAGE_LABEL)
    logger.info("[t09_sync] 메타데이터 초기화 완료 — 8섹션")

    # STEP 2: proposed_updates 생성
    proposed_updates = build_proposed_updates(payload, section_filter)
    logger.info("[t09_sync] 업데이트 대상 섹션: %s", list(proposed_updates.keys()))

    if dry_run:
        logger.info("[t09_sync] --dry-run: write 생략")
        return {
            "dry_run": True,
            "sections": list(proposed_updates.keys()),
            "preview": {k: v[:120] + "…" for k, v in proposed_updates.items()},
        }

    # STEP 3: 사전 검증
    check = error_predictor(PAGE_ID, proposed_updates, token)
    logger.info("[t09_sync] error_predictor → risk_level=%s  safe=%s",
                check.get("risk_level"), check.get("safe_to_proceed"))

    if not check["safe_to_proceed"] and not force:
        logger.error("[t09_sync] 사전 검증 실패 — 실행 중단 (--force 로 강제 가능)")
        return {"ok": False, "reason": "preflight_failed", "detail": check}

    if not check["safe_to_proceed"] and force:
        logger.warning("[t09_sync] --force: 사전 검증 경고 무시")

    # STEP 4: 병렬 섹션 업데이트 (max_workers=3)
    results = parallel_section_update(PAGE_ID, proposed_updates, token, max_workers=3)

    ok_count  = sum(1 for r in results.values() if r.get("ok"))
    skip_count = sum(1 for r in results.values() if r.get("skipped"))
    fail_count = len(results) - ok_count

    logger.info("[t09_sync] 완료: ✅ %d  ⏭ %d(skip)  ❌ %d",
                ok_count, skip_count, fail_count)

    # STEP 5: 메타데이터 무결성 검증
    integrity = validate_metadata_integrity(meta)
    if not integrity["ok"]:
        logger.warning("[t09_sync] 무결성 경고: %s", integrity["issues"])

    # STEP 6: 세션 로그
    elapsed = time.time() - t_start
    log_path = _save_session_log(
        results=results,
        meta_summary=meta.summary(),
        elapsed=elapsed,
    )

    return {
        "ok": fail_count == 0,
        "ok_count": ok_count,
        "skip_count": skip_count,
        "fail_count": fail_count,
        "integrity": integrity,
        "results": results,
        "log_path": str(log_path),
        "elapsed_sec": round(elapsed, 2),
    }


# ── CLI ────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="T-09 Mother Page 동기화 (PHASE 2)"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="write 없이 대상 섹션·프리뷰만 출력",
    )
    p.add_argument(
        "--force", action="store_true",
        help="error_predictor 경고 무시 강제 실행",
    )
    p.add_argument(
        "--section", nargs="+", metavar="SECTION_ID",
        help="특정 섹션만 업데이트 (예: --section banner kg_table)",
    )
    p.add_argument(
        "--payload", metavar="JSON_PATH",
        help="콘텐츠 페이로드 JSON 파일 경로",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        logger.error("NOTION_TOKEN 환경 변수가 설정되지 않았습니다.")
        sys.exit(1)

    payload: dict | None = None
    if args.payload:
        with open(args.payload, encoding="utf-8") as f:
            payload = json.load(f)

    output = run(
        token=token,
        payload=payload,
        section_filter=args.section,
        dry_run=args.dry_run,
        force=args.force,
    )

    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if output.get("ok", True) else 1)
