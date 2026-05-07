# ============================================================
# preflight.py
# GitHub Actions Job: Pre-flight Validation
# 환경변수 → targets JSON → GitHub Actions output 출력
# ============================================================

from __future__ import annotations
import os, json, sys, logging
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = Path('config/sync_config.yml')
    if not config_path.exists():
        return {}
    import yaml
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def resolve_targets(config: dict, manual_page_id: str | None,
                    event_name: str) -> list[dict]:
    """동기화 대상 페이지 목록 결정"""
    pages = config.get('pages', [])

    # 수동 트리거: 단일 페이지 우선
    if manual_page_id:
        return [{'id': manual_page_id, 'label': 'manual'}]

    # push 트리거: session_logs 변경 → session 관련 페이지만
    if event_name == 'push':
        return [p for p in pages if 'session' in p.get('tags', [])]

    # 스케줄: 활성화된 전체 페이지
    return [p for p in pages if p.get('enabled', True)]


def write_output(key: str, value: str) -> None:
    """GitHub Actions output 쓰기"""
    output_file = os.environ.get('GITHUB_OUTPUT', '')
    if output_file:
        with open(output_file, 'a') as f:
            f.write(f'{key}={value}\n')
    else:
        print(f'::set-output name={key}::{value}')


def main() -> None:
    token       = os.environ.get('NOTION_TOKEN', '')
    manual_page = os.environ.get('INPUT_TARGET_PAGE', '')
    sync_mode   = os.environ.get('INPUT_SYNC_MODE', 'incremental')
    event_name  = os.environ.get('GITHUB_EVENT_NAME', 'workflow_dispatch')

    if not token:
        logger.error('NOTION_TOKEN 미설정 — 동기화 중단')
        write_output('safe_to_sync', 'false')
        write_output('target_pages', '[]')
        sys.exit(1)

    config  = load_config()
    targets = resolve_targets(config, manual_page or None, event_name)

    if not targets:
        logger.warning('동기화 대상 페이지 없음')
        write_output('safe_to_sync', 'false')
        write_output('target_pages', '[]')
        return

    logger.info('Pre-flight OK — 대상 %d페이지, 모드: %s', len(targets), sync_mode)
    write_output('safe_to_sync', 'true')
    write_output('target_pages', json.dumps(targets))
    write_output('sync_mode', sync_mode)


if __name__ == '__main__':
    main()
