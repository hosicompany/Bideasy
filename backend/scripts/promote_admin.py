"""
운영자 계정에 admin 권한 부여
================================
신규 마이그레이션(c5e3a8d72f41)으로 users.is_admin 컬럼 추가됨. 이 스크립트는
지정한 이메일의 사용자에게 is_admin=True 를 부여 (idempotent — 이미 admin 이면
no-op).

사용법:
    python scripts/promote_admin.py --email hosicompany@gmail.com
    python scripts/promote_admin.py --email hosicompany@gmail.com --revoke  # 회수

운영 배포 직후 1회 실행 권장. Docker 환경:
    docker compose exec app python scripts/promote_admin.py --email hosicompany@gmail.com
"""
import argparse
import sys
from pathlib import Path

# Windows 콘솔 한글 깨짐 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import models
from app.db.session import SessionLocal


def main():
    parser = argparse.ArgumentParser(description="BidEasy 관리자 권한 부여")
    parser.add_argument("--email", required=True, help="대상 사용자 이메일")
    parser.add_argument("--revoke", action="store_true", help="권한 회수 (기본은 부여)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == args.email).first()
        if not user:
            print(f"[ERROR] 사용자 없음: {args.email}", file=sys.stderr)
            sys.exit(1)

        target = not args.revoke
        action = "회수" if args.revoke else "부여"

        if user.is_admin == target:
            print(f"[SKIP] {args.email} 의 is_admin 이 이미 {target} 입니다 — 변경 없음")
            return

        user.is_admin = target
        db.commit()
        print(f"[OK] {args.email} 의 admin 권한을 {action}했습니다 (is_admin={target})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
