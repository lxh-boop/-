from __future__ import annotations

from news_content_fetcher import article_text_quality, extract_article_text


def test_extract_article_text_from_eastmoney_content_body() -> None:
    body = "公司公告称，产业园区业务签约销售面积增加，租金收入保持稳定。" * 4
    html = f"""
    <html>
      <head><meta name="description" content="short description"></head>
      <body>
        <div class="txtinfos" id="ContentBody">
          <p style="display:none">hidden text</p>
          <p>{body}</p>
        </div>
      </body>
    </html>
    """

    text, method, reason = extract_article_text(html, title="公司公告", min_chars=80)

    assert method == "target_container"
    assert reason == ""
    assert "产业园区业务签约销售面积增加" in text
    assert "hidden text" not in text


def test_article_text_quality_rejects_title_only_and_login_pages() -> None:
    assert article_text_quality("同一个标题", title="同一个标题")[0] is False
    assert article_text_quality("请登录后查看，验证码 verification required" * 5, title="公告")[0] is False
