# smartstore_review_api.py

"""
FastAPI 기반 SmartStore 리뷰 스크래퍼 API 서버
- 사람 행동에 가까운 Playwright 동작 (headless 모드 설정 가능)
- 리뷰 탭 자동 클릭 + iframe 자동 탐지
- 페이지네이션 돌면서 리뷰 수집
어차피 서버에서 하면 안되니 다음에는 크롬 확장프로그램을 이용해서 하는 방법을 할거임
"""

import os
import time
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
from playwright.sync_api import (
    sync_playwright,
    Browser,
    Page,
)

app = FastAPI()


# ================================
# 요청 모델
# ================================
class ReviewRequest(BaseModel):
    url: str
    limit_pages: int = 13


# ================================
# 브라우저 런처 (사람 행동에 가까운 설정)
# ================================
def launch_browser(p) -> Browser:
    """
    Playwright 브라우저 실행.
    - 기본값: headless=False (로컬 디버깅 / 눈으로 확인용)
    - 서버에서 headless를 쓰고 싶으면 환경변수 PLAYWRIGHT_HEADLESS=true 로 설정
    """

    headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower()
    headless = headless_env in ("1", "true", "yes")

    browser = p.chromium.launch(
        headless=headless,
        slow_mo=150,  # 동작 하나하나를 약간 천천히 수행 (사람 행동에 가까운 속도)
    )
    return browser


def create_page(browser: Browser) -> Page:
    """
    사람 실제 브라우저와 비슷한 환경 세팅
    - 한국어 locale
    - 일반적인 데스크톱 UA
    - 적당한 viewport
    """
    context = browser.new_context(
        locale="ko-KR",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 720},
    )
    page = context.new_page()
    return page


# ================================
# 리뷰 카드 파싱
# ================================
def parse_review_card(card) -> Dict[str, Any]:
    nickname_el = card.select_one(".Db9Dtnf7gY strong")
    nickname = nickname_el.get_text(strip=True) if nickname_el else ""

    date_el = card.select_one(".Db9Dtnf7gY span:nth-of-type(1)")
    date = date_el.get_text(strip=True) if date_el else ""

    rating_el = card.select_one("em.n6zq2yy0KA")
    rating = rating_el.get_text(strip=True) if rating_el else ""

    option = ""
    option_box = card.select_one(".b_caIle8kC")
    if option_box:
        all_texts = list(option_box.stripped_strings)
        option = all_texts[0] if all_texts else ""

    buyer_el = card.select_one(".eWRrdDdSzW")
    buyer_info = buyer_el.get_text(" ", strip=True) if buyer_el else ""

    label_el = card.select_one(".h8uqAeqIe7")
    label_info = label_el.get_text(" ", strip=True) if label_el else ""

    auto_label = " | ".join(x for x in [buyer_info, label_info] if x)

    content = ""
    content_box = card.select_one(".KqJ8Qqw082")
    if content_box:
        spans = content_box.select("span")
        if len(spans) >= 2:
            tags = [s.get_text(strip=True) for s in spans[:-1]]
            body = spans[-1].get_text(" ", strip=True)
            content = " ".join(tags + [body])
        elif len(spans) == 1:
            content = spans[0].get_text(" ", strip=True)

    image_count = 0
    img_box = card.select_one(".s30AvhHfb0")
    if img_box:
        count_span = img_box.select_one(".lOzR1kO8jf")
        if count_span:
            number = "".join(
                c for c in count_span.get_text(strip=True) if c.isdigit()
            )
            if number:
                image_count = int(number)
        else:
            imgs = img_box.select("img")
            if len(imgs) >= 1:
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


# ================================
# 리뷰탭 클릭 + iframe 자동 탐지
# ================================
def load_review_frame(page: Page):
    print("🔎 리뷰탭 탐색 중…")

    # 아래로 조금씩 스크롤해가며 REVIEW 탭 찾기
    for _ in range(40):
        btn = page.locator('[data-name="REVIEW"]').first
        if btn.is_visible():
            btn.scroll_into_view_if_needed()
            btn.click()
            print("✔ 리뷰탭 클릭 성공")
            break
        page.mouse.wheel(0, 600)
        time.sleep(0.2)
    else:
        print("❌ 리뷰탭 못 찾음")
        return None

    # iframe 찾기
    print("⌛ 리뷰 iframe 로딩 대기…")
    for _ in range(80):
        for f in page.frames:
            lower = f.url.lower()
            if ("review" in lower) or ("reviews" in lower) or ("pstatic" in lower):
                print(f"✔ iframe 감지됨: {f.url}")
                return f
        time.sleep(0.25)

    print("❌ iframe 감지 실패")
    return None


# ================================
# 서비스 에러 페이지 감지
# ================================
def check_service_error(page: Page):
    """
    네이버 쪽에서 '현재 서비스 접속이 불가합니다.' 같은
    시스템 에러 페이지가 뜨는지 감지.
    """
    html = page.content()
    if "현재 서비스 접속이 불가합니다" in html:
        raise HTTPException(
            status_code=503,
            detail="네이버에서 일시적으로 서비스를 제공하지 않고 있습니다. 잠시 후 다시 시도해주세요.",
        )


# ================================
# 리뷰 수집 함수 (API 내부에서 사용)
# ================================
def scrape_reviews(url: str, limit_pages: int = 13) -> List[Dict[str, Any]]:
    reviews: List[Dict[str, Any]] = []
    seen = set()

    with sync_playwright() as p:
        browser = launch_browser(p)
        try:
            page = create_page(browser)

            print("⏳ 페이지 접속 중…")
            page.goto(url, timeout=60000)
            time.sleep(3)

            # 네이버 시스템 에러 페이지 감지
            check_service_error(page)

            iframe = load_review_frame(page)

            # iframe 없는 구버전 (DOM 직접 렌더링)
            if iframe is None:
                print("👉 iframe 없음 → 구버전 리뷰 방식으로 전환")
                iframe = page

            for n in range(1, limit_pages + 1):
                print(f"\n📌 페이지 {n} 수집…")

                soup = BeautifulSoup(iframe.content(), "lxml")
                review_cards = soup.select(".IwcuBUIAKf")
                print(f"  - 리뷰 감지: {len(review_cards)}")

                for card in review_cards:
                    info = parse_review_card(card)
                    key = (
                        f"{info['nickname']}|{info['date']}|"
                        f"{info['content'][:20]}"
                    )
                    if key not in seen:
                        seen.add(key)
                        reviews.append(info)

                # 다음 페이지 버튼 클릭
                pagination = iframe.locator(".LiT9lKOVbw")
                next_btn = pagination.locator(f'a:has-text("{n+1}")').first

                if next_btn.count() > 0:
                    print(f"➡ 페이지 {n+1} 이동")
                    next_btn.click()
                    time.sleep(2)
                else:
                    print("⛔ 다음 페이지 없음")
                    break

        finally:
            browser.close()

    print("✅ 수집 완료, 총 리뷰 수:", len(reviews))
    return reviews


# ================================
# 헬스 체크용 루트
# ================================
@app.get("/")
def root():
    return {"message": "SmartStore Review API is running"}


# ================================
# API 엔드포인트
# ================================
@app.post("/scrape")
def scrape_endpoint(req: ReviewRequest):
    """
    SmartStore 리뷰를 JSON으로 반환하는 엔드포인트
    - body:
        {
          "url": "https://smartstore.naver.com/...",
          "limit_pages": 3
        }
    """
    try:
        data = scrape_reviews(req.url, req.limit_pages)
    except HTTPException:
        # check_service_error 에서 올린 예외는 FastAPI가 그대로 처리
        raise
    except Exception as e:
        print("❌ 스크래핑 중 오류:", repr(e))
        raise HTTPException(
            status_code=500,
            detail="리뷰를 수집하는 중 오류가 발생했습니다. 콘솔 로그를 확인해주세요.",
        )

    return {
        "count": len(data),
        "reviews": data,
    }
