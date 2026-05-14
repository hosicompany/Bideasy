"""
자가보정 Celery 태스크
========================
정기적으로 자가보정 사이클을 실행한다. celery_app.py 의 beat_schedule 이
이 태스크를 매주 호출하고, should_recalibrate() 가드가 새 데이터가 없으면
즉시 스킵하므로 불필요한 비용이 발생하지 않는다.

수동 실행은 scripts/run_autocalibrate.py 사용.
"""

from app.core.celery_app import celery_app
from app.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(name="autocalibrate.recalibrate_strategy")
def recalibrate_strategy() -> str:
    """주기적 자가보정 사이클.

    새 개찰 데이터가 누적됐으면 입찰가 산정 파라미터를 재최적화하고,
    regression 가드 통과 시 채택한다. 채택 시 model_accuracy_report 로
    accuracy_history.jsonl 에 지표를 누적한다.
    """
    # 지연 import — Celery worker 부팅 시 무거운 의존성 회피
    from app.services.autocalibrate.loop import run_calibration_cycle

    report = run_calibration_cycle(trigger="scheduled")
    summary = report.summary()
    logger.info(f"[autocalibrate] {summary}")

    # 채택된 경우 정확도 리포트 누적 (별도 프로세스로)
    if report.adopted:
        try:
            import subprocess
            import sys
            from pathlib import Path

            backend_dir = Path(__file__).resolve().parent.parent.parent
            subprocess.run(
                [sys.executable, str(backend_dir / "scripts" / "model_accuracy_report.py")],
                cwd=str(backend_dir),
                capture_output=True,
                timeout=600,
            )
            logger.info("[autocalibrate] model_accuracy_report 누적 완료")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[autocalibrate] accuracy_report 실행 실패: {e}")

    return summary
