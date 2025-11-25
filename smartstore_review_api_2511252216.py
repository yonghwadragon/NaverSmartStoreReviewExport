# smartstore_review_api.py
"""
SmartStore Review Scraper API (with Naver Cookie Injection)
- 네이버 로그인 쿠키(JSON) 업로드 기반 로그인 유지
- 사람다운 UA + 로케일 + Viewport
- iframe 자동 탐지 & 리뷰 수집
리뷰탭을 누르고 다음은 수동으로 내가 스크롤내림 이부분을 개선해야해. 
"""

import os
import time
import json
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser, Page
from starlette.concurrency import run_in_threadpool

app = FastAPI()


# ============================================================
# 1) 전역 유저 에이전트 (사람 브라우저처럼 보이도록)
# ============================================================
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ============================================================
# 2) 브라우저 런처
# ============================================================
def launch_browser(p) -> Browser:
    headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower()
    headless = headless_env in ("1", "true", "yes")

    return p.chromium.launch(
        headless=headless,
        slow_mo=120,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-web-security",
            "--no-sandbox",
        ],
    )


# ============================================================
# 3) 쿠키 정규화 함수 (가장 중요함)
# ============================================================
def normalize_cookie(c: dict) -> dict:
    """
    Chrome Extension → Playwright 호환 쿠키 변환
    """

    # sameSite 변환
    raw_same = str(c.get("sameSite")).lower()

    if raw_same in ("none", "no_restriction", "unspecified", "null"):
        same_site = "None"
    elif raw_same in ("lax",):
        same_site = "Lax"
    elif raw_same in ("strict",):
        same_site = "Strict"
    else:
        same_site = "None"

    # expires 변환 (None → 0)
    exp = c.get("expires")
    if isinstance(exp, (int, float)):
        expires = exp
    else:
        expires = 0  # 세션 쿠키 처리

    return {
        "name": c["name"],
        "value": c["value"],
        "domain": c["domain"],
        "path": c.get("path", "/"),
        "expires": expires,
        "httpOnly": c.get("httpOnly", False),
        "secure": c.get("secure", False),
        "sameSite": same_site,
    }


# ============================================================
# 4) 페이지 + 쿠키 삽입
# ============================================================
def create_page(browser: Browser, cookie_data: dict) -> Page:
    context = browser.new_context(
        locale="ko-KR",
        user_agent=UA,
        viewport={"width": 1280, "height": 720},
    )

    # 쿠키 적용
    raw_cookies = cookie_data.get("cookies", [])

    fixed_cookies = [normalize_cookie(c) for c in raw_cookies]

    context.add_cookies(fixed_cookies)

    return context.new_page()


# ============================================================
# 5) 리뷰 파싱 함수
# ============================================================
def parse_review_card(card):
    nickname_el = card.select_one(".Db9Dtnf7gY strong")
    nickname = nickname_el.get_text(strip=True) if nickname_el else ""

    date_el = card.select_one(".Db9Dtnf7gY span:nth-of-type(1)")
    date = date_el.get_text(strip=True) if date_el else ""

    rating_el = card.select_one("em.n6zq2yy0KA")
    rating = rating_el.get_text(strip=True) if rating_el else ""

    option_box = card.select_one(".b_caIle8kC")
    option = list(option_box.stripped_strings)[0] if option_box else ""

    buyer_el = card.select_one(".eWRrdDdSzW")
    buyer_info = buyer_el.get_text(" ", strip=True) if buyer_el else ""

    tag_el = card.select_one(".h8uqAeqIe7")
    tag_info = tag_el.get_text(" ", strip=True) if tag_el else ""

    auto_label = " | ".join([x for x in [buyer_info, tag_info] if x.strip()])

    content_box = card.select_one(".KqJ8Qqw082")
    content = ""
    if content_box:
        spans = content_box.select("span")
        if len(spans) >= 2:
            tags = [s.get_text(strip=True) for s in spans[:-1]]
            body = spans[-1].get_text(" ", strip=True)
            content = " ".join(tags + [body])
        elif spans:
            content = spans[0].get_text(" ", strip=True)

    img_box = card.select_one(".s30AvhHfb0")
    image_count = 0
    if img_box:
        count_span = img_box.select_one(".lOzR1kO8jf")
        if count_span:
            digits = "".join(c for c in count_span.get_text(strip=True) if c.isdigit())
            image_count = int(digits or "0")
        elif img_box.select("img"):
            image_count = 1

    return {
        "nickname": nickname,
        "date": date,
        "rating": rating,
        "option": option,
        "auto_label": auto_label,
        "content": content,
        "image_count": image_count,
    }


# ============================================================
# 6) 리뷰탭 & iframe 자동 탐지
# ============================================================
def load_review_frame(page: Page):
    # 리뷰탭 클릭
    for _ in range(50):
        btn = page.locator('[data-name="REVIEW"]').first
        if btn.is_visible():
            btn.scroll_into_view_if_needed()
            btn.click()
            break
        page.mouse.wheel(0, 800)
        time.sleep(0.2)

    # iframe 찾기
    for _ in range(80):
        for f in page.frames:
            url = f.url.lower()
            if "review" in url or "pstatic" in url:
                return f
        time.sleep(0.25)

    return None


# ============================================================
# 7) 네이버 시스템 에러 감지
# ============================================================
def check_service_error(page: Page):
    if "현재 서비스 접속이 불가합니다" in page.content():
        raise HTTPException(503, "네이버가 차단했습니다. 잠시 후 다시 시도하세요.")


# ============================================================
# 8) 메인 스크래핑 함수
# ============================================================
def scrape_reviews(url: str, limit_pages: int, cookie_data: dict):

    with sync_playwright() as p:
        browser = launch_browser(p)
        page = create_page(browser, cookie_data)

        page.goto(url, timeout=60000)
        time.sleep(2)

        check_service_error(page)

        iframe = load_review_frame(page) or page

        results = []
        seen = set()

        for n in range(1, limit_pages + 1):
            soup = BeautifulSoup(iframe.content(), "lxml")
            cards = soup.select(".IwcuBUIAKf")

            for card in cards:
                info = parse_review_card(card)
                key = f"{info['nickname']}|{info['date']}|{info['content'][:20]}"
                if key not in seen:
                    seen.add(key)
                    results.append(info)

            # 다음 페이지 버튼
            next_btn = iframe.locator(f'.LiT9lKOVbw a:has-text("{n+1}")').first
            if next_btn.count():
                next_btn.click()
                time.sleep(2)
            else:
                break

        browser.close()
        return results


# ============================================================
# 9) API 엔드포인트
# ============================================================
@app.post("/scrape")
async def scrape_endpoint(
    url: str = Form(...),
    limit_pages: int = Form(3),
    cookie_file: UploadFile = File(...)
):
    try:
        cookie_json = (await cookie_file.read()).decode("utf-8")
        cookie_data = json.loads(cookie_json)
    except Exception as e:
        raise HTTPException(400, f"쿠키 파일 오류: {e}")

    try:
        data = await run_in_threadpool(scrape_reviews, url, limit_pages, cookie_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"스크래핑 오류: {repr(e)}")

    return {"count": len(data), "reviews": data}


@app.get("/")
def root():
    return {"status": "ok", "message": "SmartStore Scraper Ready"}
