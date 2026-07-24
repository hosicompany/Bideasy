from pathlib import Path


DEPLOY_SCRIPT = (
    Path(__file__).resolve().parents[2] / "infra" / "deploy.sh"
)


def deploy_block(script: str) -> str:
    return script.split("  deploy)", 1)[1].split("  logs)", 1)[0]


def test_deploy_rebuilds_and_recreates_celery_beat_after_migrations():
    block = deploy_block(DEPLOY_SCRIPT.read_text())

    assert "dc build app celery_worker celery_beat" in block
    assert "dc up -d --no-deps --force-recreate celery_beat" in block
    assert 'dc ps --status running --services | grep -qx "celery_beat"' in block
    assert "ERROR: celery_beat did not remain running after deployment." in block

    migration_index = block.index("exec app alembic upgrade head")
    worker_index = block.index("dc up -d --no-deps --force-recreate celery_worker")
    beat_index = block.index("dc up -d --no-deps --force-recreate celery_beat")
    nginx_index = block.index("Reloading nginx config...")
    assert migration_index < worker_index < nginx_index < beat_index


def test_deploy_reexecutes_when_git_pull_updates_the_script():
    block = deploy_block(DEPLOY_SCRIPT.read_text())

    assert "DEPLOY_SCRIPT_PATH=" in block
    assert 'git diff --quiet "$previous_head" HEAD -- infra/deploy.sh' in block
    assert 'exec "$DEPLOY_SCRIPT_PATH" deploy' in block


def test_rollback_rebuilds_celery_beat():
    script = DEPLOY_SCRIPT.read_text()

    assert "dc up -d --build app celery_worker celery_beat" in script
