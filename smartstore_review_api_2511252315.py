# smartstore_review_api.py
"""
Async SmartStore Review Scraper API
- Async Playwright 기반 (FastAPI와 100% 호환)
- 네이버 로그인 쿠키 업로드 방식
- iframe 자동 감지 + 리뷰탭 진입
- Human-like Scroll
- 안정성 개선: 로깅, 타임아웃 증가, 예외 처리 강화
"""

import os
import json
import time
import logging
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.concurrency import run_in_threadpool
from playwright.async_api import async_playwright, Browser, Page
from bs4 import BeautifulSoup

app = FastAPI()

# ============================================================
# 0) 로깅 설정
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("scraper")

# ============================================================
# 1) 전역 유저 에이전트
# ============================================================
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# ============================================================
# 2) 브라우저 런처
# ============================================================
async def launch_browser(p) -> Browser:
    headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower()
    headless = headless_env in ("1", "true", "yes")

    logger.info(f"Launching browser (headless={headless})")

    return await p.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-web-security",
            "--no-sandbox"
        ]
    )

# ============================================================
# 3) 쿠키 정규화
# ============================================================
def normalize_cookie(c: dict) -> dict:
    raw_same = str(c.get("sameSite")).lower()
    if raw_same in ("none", "no_restriction", "unspecified"):
        same_site = "None"
    elif raw_same == "lax":
        same_site = "Lax"
    elif raw_same == "strict":
        same_site = "Strict"
    else:
        same_site = "None"

    expires = c.get("expires")
    expires = expires if isinstance(expires, (int, float)) else 0

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
async def create_page(browser: Browser, cookie_data: dict) -> Page:
    context = await browser.new_context(
        locale="ko-KR",
        user_agent=UA,
        viewport={"width": 1280, "height": 720},
    )

    raw = cookie_data.get("cookies", [])
    fixed = [normalize_cookie(c) for c in raw]

    if fixed:
        await context.add_cookies(fixed)

    return await context.new_page()

# ============================================================
# 5) 리뷰 카드 파서
# ============================================================
def parse_review_card(card):
    try:
        nickname = card.select_one(".Db9Dtnf7gY strong")
        nickname = nickname.get_text(strip=True) if nickname else ""

        date_el = card.select_one(".Db9Dtnf7gY span:nth-of-type(1)")
        date = date_el.get_text(strip=True) if date_el else ""

        rating = card.select_one("em.n6zq2yy0KA")
        rating = rating.get_text(strip=True) if rating else ""

        option_box = card.select_one(".b_caIle8kC")
        option = list(option_box.stripped_strings)[0] if option_box else ""

        buyer_el = card.select_one(".eWRrdDdSzW")
        buyer_info = buyer_el.get_text(" ", strip=True) if buyer_el else ""

        tag_el = card.select_one(".h8uqAeqIe7")
        tag_info = tag_el.get_text(" ", strip=True) if tag_el else ""

        auto_label = " | ".join([x for x in [buyer_info, tag_info] if x.strip()])

        content_box = card.select_one(".KqJ8Qqw082")
        content = content_box.get_text(" ", strip=True) if content_box else ""

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
    except Exception as e:
        logger.error(f"Parse error: {e}")
        return None

# ============================================================
# 6) 리뷰탭 + iframe 탐지
# ============================================================
async def load_review_frame(page: Page):
    logger.info("Seeking REVIEW tab...")

    for _ in range(50):
        btn = page.locator('[data-name="REVIEW"]').first
        if await btn.is_visible():
            await btn.scroll_into_view_if_needed()
            await btn.click()
            break
        await page.mouse.wheel(0, 800)
        await page.wait_for_timeout(200)

    # iframe 찾기
    for _ in range(80):
        for frame in page.frames:
            if "review" in frame.url.lower() or "pstatic" in frame.url.lower():
                logger.info(f"Review iframe found: {frame.url}")
                return frame
        await page.wait_for_timeout(250)

    logger.warning("No iframe found, fallback to main page")
    return page

# ============================================================
# 7) 에러 감지
# ============================================================
async def check_service_error(page: Page):
    html = await page.content()
    if "현재 서비스 접속이 불가합니다" in html:
        raise HTTPException(503, "네이버가 차단했습니다.")

# ============================================================
# 8) Human-like Scroll
# ============================================================
async def smooth_scroll(target, steps=10, delay=300):
    try:
        for _ in range(steps):
            await target.evaluate("window.scrollBy(0, 800)")
            await target.wait_for_timeout(delay)
    except Exception:
        pass

# ============================================================
# 9) 메인 스크래핑
# ============================================================
async def scrape_reviews(url: str, limit_pages: int, cookie_data: dict):

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await create_page(browser, cookie_data)

        await page.goto(url, timeout=120000)
        await page.wait_for_timeout(2000)

        await check_service_error(page)

        iframe = await load_review_frame(page)

        results = []
        seen = set()

        for n in range(1, limit_pages + 1):
            await smooth_scroll(iframe, steps=12, delay=250)

            soup = BeautifulSoup(await iframe.content(), "lxml")
            cards = soup.select(".IwcuBUIAKf")

            for card in cards:
                info = parse_review_card(card)
                if not info:
                    continue

                key = f"{info['nickname']}|{info['date']}|{info['content'][:20]}"
                if key not in seen:
                    seen.add(key)
                    results.append(info)

            # 다음 페이지
            next_btn = iframe.locator(f'.LiT9lKOVbw a:has-text("{n+1}")').first
            if await next_btn.count():
                await next_btn.click()
                await page.wait_for_timeout(2000)
            else:
                break

        await browser.close()
        return results

# ============================================================
# 10) 엔드포인트
# ============================================================
@app.post("/scrape")
async def scrape_endpoint(
    url: str = Form(...),
    limit_pages: int = Form(3),
    cookie_file: UploadFile = File(...)
):
    cookie_json = (await cookie_file.read()).decode("utf-8")
    cookie_data = json.loads(cookie_json)

    try:
        data = await scrape_reviews(url, limit_pages, cookie_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Scraping error: {e}")
        raise HTTPException(500, f"스크래핑 오류: {repr(e)}")

    return {"count": len(data), "reviews": data}


@app.get("/")
async def root():
    return {"status": "ok", "message": "SmartStore Scraper Ready (async)"}
