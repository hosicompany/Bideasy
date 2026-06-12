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
