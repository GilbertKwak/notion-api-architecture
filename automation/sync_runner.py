# ============================================================
# sync_runner.py
# GitHub Actions Job: 실제 동기화 실행
# session_logs/*.md → Notion 페이지 섹션 업데이트
# ============================================================

from __future__ import annotations
import os, json, time, glob, logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def load_session_logs(since_sha: str | None = None) -> list[dict]:
    """session_logs/*.md 파싱 → 구조화 데이터"""
    logs = []
    for path in sorted(glob.glob('session_logs/*.md'), reverse=True)[:10]:
        stem = Path(path).stem   # SESSION-C33-20260504-AFT
        parts = stem.split('-')  # ['SESSION', 'C33', '20260504', 'AFT']
        with open(path) as f:
            content = f.read()
        logs.append({
            'filename': stem,
            'session_id': parts[1] if len(parts) > 1 else '',
            'date': parts[2] if len(parts) > 2 else '',
            'slot': parts[3] if len(parts) > 3 else '',
            'content': content,
            'path': path,
        })
    return logs


def build_session_table(logs: list[dict]) -> str:
    """세션 히스토리 → Notion 마크다운 테이블"""
    rows = []
    for log in logs:
        date_fmt = f"{log['date'][:4]}-{log['date'][4:6]}-{log['date'][6:]}" \
                   if len(log['date']) == 8 else log['date']
        rows.append(
            f"| {log['session_id']} | {date_fmt} | {log['slot']} | "
            f"[보기](session_logs/{log['filename']}.md) |"
        )
    header = ('| 세션 | 날짜 | 슬롯 | 링크 |\n'
              '|------|------|------|------|')
    return header + '\n' + '\n'.join(rows)


def build_proposed_updates(logs: list[dict], sync_mode: str) -> dict[str, str]:
    """섹션별 업데이트 내용 생성"""
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    updates: dict[str, str] = {}

    # 배너: 항상 갱신
    latest = logs[0] if logs else {}
    updates['banner'] = (
        f'> 🔄 **마지막 동기화**: {now}  \n'
        f'> 📋 **최신 세션**: {latest.get("session_id", "—")} '
        f'({latest.get("date", "—")})'
    )

    # 세션 히스토리 테이블
    updates['session'] = (
        f'## 📝 세션 히스토리\n\n' + build_session_table(logs)
    )

    # full 모드: 전체 섹션 재생성
    if sync_mode == 'full':
        updates['actions'] = (
            f'## 🔴 후속 액션\n\n'
            f'| 우선순위 | 액션 | 상태 |\n'
            f'|----------|------|------|\n'
            f'| — | sync_runner 전체 재동기화 완료 | ✅ |'
        )

    return updates


def main() -> None:
    from automation.metadata_manager import (initialize_section_metadata,
                                             error_predictor,
                                             parallel_section_update)

    page_id    = os.environ.get('PAGE_ID', '')
    page_label = os.environ.get('PAGE_LABEL', page_id[:8])
    token      = os.environ.get('NOTION_TOKEN', '')
    sync_mode  = os.environ.get('SYNC_MODE', 'incremental')
    commit_sha = os.environ.get('COMMIT_SHA', '')

    logger.info('▶ sync_runner 시작 — page=%s mode=%s', page_label, sync_mode)
    start = time.time()

    # dry_run 모드
    if sync_mode == 'dry_run':
        logger.info('[DRY RUN] write 없이 검증만 실행')
        logs    = load_session_logs()
        updates = build_proposed_updates(logs, 'incremental')
        check   = error_predictor(page_id, updates, token)
        report  = {'dry_run': True, 'risk': check['risk_level'],
                   'safe': check['safe_to_proceed'], 'sections': list(updates.keys())}
        _save_report(page_label, report)
        return

    # PHASE 2~4 공통 패턴
    meta    = initialize_section_metadata(page_id, token, page_label)
    logs    = load_session_logs()
    updates = build_proposed_updates(logs, sync_mode)

    # 사전 검증
    check = error_predictor(page_id, updates, token)
    logger.info('ErrorPredictor: risk=%s safe=%s', check['risk_level'],
                check['safe_to_proceed'])

    if not check['safe_to_proceed']:
        logger.error('사전 검증 실패 — write 중단. 권고: %s',
                     check['recommendation'])
        _save_report(page_label, {'error': 'preflight_failed', **check})
        return

    # 병렬 섹션 업데이트
    results = parallel_section_update(page_id, updates, token, max_workers=3)
    elapsed = time.time() - start

    ok_count   = sum(1 for r in results.values() if r.get('ok'))
    fail_count = len(results) - ok_count
    report = {
        'page_id': page_id,
        'page_label': page_label,
        'commit_sha': commit_sha[:8],
        'sync_mode': sync_mode,
        'sections_updated': ok_count,
        'sections_failed': fail_count,
        'elapsed_s': round(elapsed, 2),
        'results': results,
    }
    _save_report(page_label, report)
    logger.info('▶ sync 완료 — ok=%d fail=%d %.2fs', ok_count, fail_count, elapsed)


def _save_report(label: str, data: dict) -> None:
    import os
    os.makedirs('reports', exist_ok=True)
    ts   = int(time.time())
    path = f'reports/sync_{label}_{ts}.json'
    with open(path, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info('리포트 저장: %s', path)


if __name__ == '__main__':
    main()
