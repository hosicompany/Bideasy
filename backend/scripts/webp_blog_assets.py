"""블로그 이미지 PNG → WebP 병행 생성 (§5.1 이미지 워크플로의 마지막 단계).

PNG 는 **지우지 않는다.** nginx 가 `Accept: image/webp` 를 보고 골라 주기 때문에,
WebP 는 브라우저용이고 PNG 는 공유 미리보기 크롤러(카카오톡·네이버 등)용 폴백이다.
자세한 이유는 infra/nginx/conf.d/default.conf 의 해당 location 주석 참고.

멱등: PNG 보다 새로운 .webp 가 이미 있으면 건너뛴다. 새 이미지를 배치한 뒤
그냥 다시 돌리면 된다.

    python backend/scripts/webp_blog_assets.py          # 변환
    python backend/scripts/webp_blog_assets.py --check  # 변환 없이 누락만 보고 (CI용)

품질: 히어로는 사진형이라 q82 로 충분하고, 도식(fig*)은 **한글 라벨이 뭉개지면
안 되므로** q92 를 쓴다. 값을 낮추기 전에 반드시 눈으로 확인할 것.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

# 히어로는 프롬프트가 `no text` 라 글자가 없다 → 낮은 품질로도 안전.
# 도식은 한글 라벨이 있어 손실 압축에 취약하다.
QUALITY_HERO = 82
QUALITY_FIGURE = 92


def repo_root() -> Path:
    for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (p / ".git").exists():
            return p
    raise SystemExit("레포 루트를 찾지 못했습니다 (.git 없음)")


def quality_for(png: Path) -> int:
    return QUALITY_FIGURE if png.stem.startswith("fig") else QUALITY_HERO


def is_stale(png: Path, webp: Path) -> bool:
    """webp 가 없거나 png 보다 오래됐으면 재생성 대상."""
    return not webp.exists() or webp.stat().st_mtime < png.stat().st_mtime


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="변환하지 않고 누락만 보고")
    args = ap.parse_args()

    base = repo_root() / "infra/nginx/html/assets/blog"
    if not base.is_dir():
        print(f"자산 폴더가 없습니다: {base}", file=sys.stderr)
        return 1

    pngs = sorted(base.glob("*/*.png"))
    if not pngs:
        print("PNG 가 없습니다 — 할 일 없음")
        return 0

    stale = [p for p in pngs if is_stale(p, p.with_suffix(".webp"))]

    if args.check:
        for p in stale:
            print(f"  누락/구버전: {p.relative_to(base)}")
        print(f"\nPNG {len(pngs)}장 중 {len(stale)}장이 WebP 미생성/구버전입니다.")
        return 1 if stale else 0

    if not stale:
        print(f"PNG {len(pngs)}장 전부 최신 WebP 보유 — 할 일 없음")
        return 0

    total_png = total_webp = 0
    for png in stale:
        webp = png.with_suffix(".webp")
        q = quality_for(png)
        # 팔레트(P) 모드 PNG 가 섞여 있어 RGB 로 통일한다.
        Image.open(png).convert("RGB").save(webp, "WEBP", quality=q, method=6)
        a, b = png.stat().st_size, webp.stat().st_size
        total_png += a
        total_webp += b
        print(f"  {str(png.relative_to(base)):30} q{q}  {a // 1024:>5}KB → {b // 1024:>4}KB")

    saved = 100 - (total_webp * 100 // total_png) if total_png else 0
    print(f"\n{len(stale)}장 변환 · {total_png // 1024}KB → {total_webp // 1024}KB ({saved}% 절감)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
