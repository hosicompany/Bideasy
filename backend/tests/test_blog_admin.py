"""DB 블로그(런타임 발행) — admin CRUD + 공개 병합 + 인증 회귀.

마크다운 파일 블로그와 하이브리드: 파일 글은 그대로, DB 글은 배포 없이 발행.
"""


def _create(admin_client, **kw):
    payload = {
        "title": "테스트 글",
        "slug": "test-db-post",
        "summary": "요약",
        "body_md": "# 본문\n\n내용입니다.",
    }
    payload.update(kw)
    return admin_client.post("/api/v1/admin/blog", json=payload)


def test_admin_blog_requires_auth(client):
    """비로그인 → admin 블로그 API 차단."""
    r = client.get("/api/v1/admin/blog")
    assert r.status_code in (401, 403)


def test_create_draft_hidden_from_public(admin_client, client):
    r = _create(admin_client, slug="db-draft-1", status="draft")
    assert r.status_code == 201, r.text
    # 공개 목록엔 없음
    assert "db-draft-1" not in client.get("/blog").text
    # 직접 URL 은 200 (noindex 미리보기)
    assert client.get("/blog/db-draft-1").status_code == 200
    # admin 목록엔 있음
    al = admin_client.get("/api/v1/admin/blog")
    assert any(p["slug"] == "db-draft-1" for p in al.json())


def test_publish_appears_public_and_sitemap(admin_client, client):
    r = _create(admin_client, slug="db-pub-1", title="발행글 제목", status="draft")
    pid = r.json()["id"]
    pr = admin_client.post(f"/api/v1/admin/blog/{pid}/publish")
    assert pr.status_code == 200
    assert pr.json()["status"] == "published"
    assert pr.json()["date"]  # 발행일 자동 세팅
    # 공개 목록 + 상세 + sitemap 에 반영 (배포 없이)
    assert "db-pub-1" in client.get("/blog").text
    detail = client.get("/blog/db-pub-1")
    assert detail.status_code == 200
    assert "발행글 제목" in detail.text
    assert "/blog/db-pub-1" in client.get("/sitemap.xml").text


def test_render_pipeline_applied(admin_client):
    """저장 시 파일과 동일한 렌더 파이프라인(figure 변환·읽는시간)."""
    r = _create(admin_client, slug="db-render-1", body_md="# 제목\n\n![캡션](/x.png)\n")
    assert r.status_code == 201
    body = r.json()
    assert body["reading_time"] >= 1
    assert "<figure>" in body["body_html"]
    assert "<figcaption>캡션</figcaption>" in body["body_html"]


def test_slug_collision_with_markdown(admin_client):
    """기존 마크다운 파일 글 slug 와 충돌 → 409."""
    assert _create(admin_client, slug="a-value-guide").status_code == 409


def test_slug_collision_db(admin_client):
    assert _create(admin_client, slug="dup-1").status_code == 201
    assert _create(admin_client, slug="dup-1").status_code == 409


def test_update_rerenders(admin_client):
    pid = _create(admin_client, slug="db-upd-1", body_md="# old").json()["id"]
    u = admin_client.put(
        f"/api/v1/admin/blog/{pid}",
        json={"body_md": "# 새 본문\n\n더 긴 내용으로 바꿉니다."},
    )
    assert u.status_code == 200
    assert "새 본문" in u.json()["body_html"]


def test_unpublish_hides(admin_client, client):
    pid = _create(admin_client, slug="db-unpub-1", status="published").json()["id"]
    assert "db-unpub-1" in client.get("/blog").text
    admin_client.post(f"/api/v1/admin/blog/{pid}/unpublish")
    assert "db-unpub-1" not in client.get("/blog").text


def test_delete(admin_client):
    pid = _create(admin_client, slug="db-del-1").json()["id"]
    assert admin_client.delete(f"/api/v1/admin/blog/{pid}").status_code == 204
    assert admin_client.get(f"/api/v1/admin/blog/{pid}").status_code == 404


def test_markdown_posts_still_work(client):
    """회귀 — 기존 파일 글(상록수)은 그대로 동작."""
    assert "a-value-guide" in client.get("/blog").text
    assert client.get("/blog/a-value-guide").status_code == 200
