from pathlib import Path


DEPLOY_SCRIPT = (
    Path(__file__).resolve().parents[2] / "infra" / "deploy.sh"
)


def deploy_block(script: str) -> str:
    return script.split("  deploy)", 1)[1].split("  logs)", 1)[0]


def test_deploy_rebuilds_and_recreates_celery_beat_after_migrations():
    block = deploy_block(DEPLOY_SCRIPT.read_text(encoding="utf-8"))

    assert "dc build app celery_worker celery_beat" in block
    assert "dc up -d --no-deps --force-recreate celery_beat" in block
    assert 'dc ps --status running --services | grep -qx "celery_beat"' in block
    assert "ERROR: celery_beat did not remain running after deployment." in block

    # 마이그레이션은 app 재시작보다 먼저다. 뒤로 가면 마이그레이션만 실패했을 때
    # "새 코드 + 구 스키마"가 남는다(CLAUDE.md 함정 19 — 2026-08-12 실사고).
    # `run --rm` 이라야 구 app 이 서비스를 계속하는 동안 스키마를 올릴 수 있다.
    assert "exec app alembic upgrade head" not in block

    migration_index = block.index("dc run --rm --no-deps app alembic upgrade head")
    app_index = block.index("dc up -d --no-deps --force-recreate app")
    worker_index = block.index("dc up -d --no-deps --force-recreate celery_worker")
    beat_index = block.index("dc up -d --no-deps --force-recreate celery_beat")
    nginx_index = block.index("Reloading nginx config...")
    assert migration_index < app_index < worker_index < nginx_index < beat_index


def test_deploy_reexecutes_when_git_pull_updates_the_script():
    block = deploy_block(DEPLOY_SCRIPT.read_text(encoding="utf-8"))

    assert "DEPLOY_SCRIPT_PATH=" in block
    assert 'git diff --quiet "$previous_head" HEAD -- infra/deploy.sh' in block
    assert 'exec "$DEPLOY_SCRIPT_PATH" deploy' in block


def test_rollback_rebuilds_celery_beat():
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "dc up -d --build app celery_worker celery_beat" in script
