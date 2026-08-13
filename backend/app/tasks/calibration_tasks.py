"""
자가보정 Celery 태스크
========================
정기적으로 자가보정 후보를 생성·평가한다. celery_app.py 의 beat_schedule 이
이 태스크를 매주 호출하지만, 운영 active 전략은 변경하지 않는다. 이 루프에는
승격 인자 자체를 전달할 수 없고, 승격은 별도의 검증·승인 경로가 담당한다.

수동 실행은 scripts/run_autocalibrate.py 사용.
"""

from app.core.celery_app import celery_app
from app.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(name="autocalibrate.recalibrate_strategy")
def recalibrate_strategy() -> str:
    """주기적 자가보정 후보 평가 사이클.

    새 개찰 데이터가 누적됐으면 입찰가 산정 파라미터를 재최적화하고,
    regression 가드 결과와 후보를 기록한다. 스케줄 실행은 사람 승인 증적을
    가질 수 없으므로 active 전략을 절대 승격하지 않는다.
    """
    # 지연 import — Celery worker 부팅 시 무거운 의존성 회피
    from app.services.autocalibrate.loop import run_calibration_cycle
    from app.db.session import SessionLocal

    # 누적 opening_results(매일 크롤) 도 학습 데이터에 병합 → 최신 시장 반영
    db = SessionLocal()
    try:
        report = run_calibration_cycle(
            trigger="scheduled",
            db=db,
        )
    finally:
        db.close()
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
