"""공통 js·css 캐시 — 배포 뒤에도 옛 app.js(옛 메뉴)가 남던 문제(2026-10-24) 재발 방지."""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PAGES = list((_ROOT / "infra" / "nginx" / "html").glob("*.html")) + list((_ROOT / "backend" / "templates").glob("*.html"))
_REF = re.compile(r'(?:src|href)="(/assets/[a-z0-9._-]+\.(?:js|css))(\?v=\d+)?"')


def test_every_shared_asset_reference_is_versioned():
    """주소에 ?v= 가 없으면 이미 캐시한 브라우저가 새 파일을 안 받는다 — 파일을 고칠 땐 v 도 올린다."""
    missing = [f"{p.name}:{m.group(1)}" for p in _PAGES for m in _REF.finditer(p.read_text(encoding="utf-8")) if not m.group(2)]
    assert not missing, f"버전 없는 공통 파일 참조: {missing}"


def test_one_version_across_pages():
    versions = {m.group(2) for p in _PAGES for m in _REF.finditer(p.read_text(encoding="utf-8"))}
    assert len(versions) == 1, f"페이지마다 버전이 다름: {versions}"


def test_nginx_revalidates_shared_assets():
    conf = (_ROOT / "infra" / "nginx" / "conf.d" / "default.conf").read_text(encoding="utf-8")
    block = re.search(r"location ~ \^/assets/\[a-z0-9\._-\]\+\\\.\(js\|css\)\$ \{(.*?)\}", conf, re.S)
    assert block and "expires -1;" in block.group(1)
    assert "add_header" not in block.group(1), "add_header 를 쓰면 server 블록 보안 헤더 상속이 끊긴다"
