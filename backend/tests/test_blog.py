"""블로그 SSR (/blog, /blog/{slug}) + sitemap 포함 테스트."""


def test_blog_list_renders(client):
    r = client.get("/blog")
    assert r.status_code == 200
    assert "BidEasy 블로그" in r.text
    assert "a-value-guide" in r.text  # 샘플 글 링크 노출


def test_blog_detail_renders(client):
    r = client.get("/blog/a-value-guide")
    assert r.status_code == 200
    assert "A값" in r.text
    assert 'rel="canonical"' in r.text
    assert "application/ld+json" in r.text  # Article 구조화데이터
    assert 'property="og:type" content="article"' in r.text


def test_blog_detail_404_for_missing(client):
    r = client.get("/blog/this-does-not-exist")
    assert r.status_code == 404
    assert "noindex" in r.text


def test_sitemap_includes_blog(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "/blog/a-value-guide" in r.text


def test_sitemap_has_lastmod(client):
    r = client.get("/sitemap.xml")
    assert "<lastmod>" in r.text


def test_blog_detail_byline_and_reading_time(client):
    import re
    r = client.get("/blog/a-value-guide")
    assert r.status_code == 200
    assert "BidEasy" in r.text  # 글쓴이 = 브랜드(가짜 인물 없음)
    assert re.search(r"읽는 시간 \d+분", r.text)


def test_blog_detail_hero_and_og_image(client):
    r = client.get("/blog/a-value-guide")
    assert 'property="og:image"' in r.text
    assert 'name="twitter:image"' in r.text
    assert "https://bideasy.kr/assets/blog/a-value-guide/hero.png" in r.text
    assert 'class="hero"' in r.text


def test_blog_detail_jsonld_image_and_datemodified(client):
    r = client.get("/blog/a-value-guide")
    assert '"image"' in r.text
    assert '"dateModified"' in r.text
    assert '"@type": "Organization"' in r.text  # author/publisher


def test_blog_detail_inline_image_renders_figure(client):
    r = client.get("/blog/a-value-guide")
    assert "<figure>" in r.text          # 본문 단독 이미지 → figure 변환
    assert 'loading="lazy"' in r.text


def test_blog_list_jsonld_and_thumb(client):
    r = client.get("/blog")
    assert '"@type": "Blog"' in r.text
    assert 'class="thumb"' in r.text     # cover 있는 글의 썸네일


def test_blog_public_no_auth(client):
    # 로그인 없이도 공개 — 인증 헤더 없이 200
    assert client.get("/blog").status_code == 200
    assert client.get("/blog/a-value-guide").status_code == 200
    assert client.get("/sitemap.xml").status_code == 200


def test_reading_time_korean_charcount():
    from app.services import blog as blog_svc
    assert blog_svc._reading_time("가" * 1000) >= 2
    assert blog_svc._reading_time("짧은 글") == 1
