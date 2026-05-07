# ============================================================
# audit_logger.py
# GitHub Actions Job: 감사 로그 생성 + Notion 동기화 허브 업데이트
# ============================================================

from __future__ import annotations
import os, json, glob, logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

STATUS_EMOJI = {'success': '✅', 'failure': '❌', 'skipped': '⏭️', 'cancelled': '🚫'}


def aggregate_reports() -> dict:
    """reports/*.json 집계"""
    files = glob.glob('reports/sync_*.json')
    if not files:
        return {'total_pages': 0, 'sections_updated': 0, 'sections_failed': 0}
    aggregated = {'total_pages': len(files), 'sections_updated': 0,
                  'sections_failed': 0, 'pages': []}
    for f in files:
        with open(f) as fp:
            data = json.load(fp)
        aggregated['sections_updated'] += data.get('sections_updated', 0)
        aggregated['sections_failed']  += data.get('sections_failed', 0)
        aggregated['pages'].append({
            'label': data.get('page_label', '?'),
            'ok': data.get('sections_updated', 0),
            'fail': data.get('sections_failed', 0),
        })
    return aggregated


def build_audit_entry(run_id: str, commit_sha: str,
                      sync_status: str, agg: dict) -> dict:
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    emoji = STATUS_EMOJI.get(sync_status, '❓')
    return {
        'run_id': run_id,
        'commit_sha': commit_sha[:8],
        'timestamp': now,
        'sync_status': f'{emoji} {sync_status}',
        'total_pages': agg['total_pages'],
        'sections_updated': agg['sections_updated'],
        'sections_failed': agg['sections_failed'],
    }


def save_audit_log(entry: dict) -> str:
    os.makedirs('audit_logs', exist_ok=True)
    date_str = datetime.utcnow().strftime('%Y%m%d')
    path = f'audit_logs/audit_{date_str}.jsonl'
    with open(path, 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    logger.info('감사 로그 추가: %s', path)
    return path


def main() -> None:
    run_id      = os.environ.get('WORKFLOW_RUN_ID', 'local')
    commit_sha  = os.environ.get('COMMIT_SHA', '')
    sync_status = os.environ.get('SYNC_STATUS', 'unknown')

    agg   = aggregate_reports()
    entry = build_audit_entry(run_id, commit_sha, sync_status, agg)
    path  = save_audit_log(entry)

    logger.info('Audit 완료: pages=%d ok=%d fail=%d',
                agg['total_pages'], agg['sections_updated'], agg['sections_failed'])
    print(json.dumps(entry, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
