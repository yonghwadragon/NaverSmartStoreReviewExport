# smartstore_review_scraper.py

import time
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


# ================================
# 리뷰 카드 파싱
# ================================
def parse_review_card(card):

    # 닉네임
    nickname_el = card.select_one(".Db9Dtnf7gY strong")
    nickname = nickname_el.get_text(strip=True) if nickname_el else ""

    # 날짜
    date_el = card.select_one(".Db9Dtnf7gY span:nth-of-type(1)")
    date = date_el.get_text(strip=True) if date_el else ""

    # 평점
    rating_el = card.select_one("em.n6zq2yy0KA")
    rating = rating_el.get_text(strip=True) if rating_el else ""

    # 옵션 (맨 첫 줄만)
    option = ""
    option_box = card.select_one(".b_caIle8kC")
    if option_box:
        all_texts = list(option_box.stripped_strings)
        option = all_texts[0] if all_texts else ""

    # 구매자 정보
    buyer_el = card.select_one(".eWRrdDdSzW")
    buyer_info = buyer_el.get_text(" ", strip=True) if buyer_el else ""

    # 자동 라벨
    label_el = card.select_one(".h8uqAeqIe7")
    label_info = label_el.get_text(" ", strip=True) if label_el else ""

    auto_label = " | ".join(x for x in [buyer_info, label_info] if x)

    # 본문
    content = ""
    content_box = card.select_one(".KqJ8Qqw082")
    if content_box:
        spans = content_box.select("span")

        # 모든 span 중 마지막을 '본문'으로 처리하고
        # 마지막 이전 span들은 모두 태그(한달사용, 재구매 등)
        if len(spans) >= 2:
            tags = [s.get_text(strip=True) for s in spans[:-1]]     # 한달사용, 재구매 등
            body = spans[-1].get_text(" ", strip=True)               # 실제 본문
            content = " ".join(tags + [body])
        elif len(spans) == 1:
            content = spans[0].get_text(" ", strip=True)


    # 이미지 개수
    image_count = 0
    img_box = card.select_one(".s30AvhHfb0")

    if img_box:
        count_span = img_box.select_one(".lOzR1kO8jf")
        if count_span:
            number = "".join(c for c in count_span.get_text(strip=True) if c.isdigit())
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
def load_review_frame(page):

    print("🔎 리뷰탭 탐색 중…")

    # 리뷰탭 보일 때까지 스크롤
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
# 리뷰 전체 수집
# ================================
def extract_reviews_to_csv(url, limit_pages=10):
    reviews = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        print("⏳ 페이지 접속 중…")
        page.goto(url, timeout=60000)
        time.sleep(3)

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
                key = f"{info['nickname']}|{info['date']}|{info['content'][:20]}"
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

        browser.close()

    # 저장
    df = pd.DataFrame(reviews)
    df.to_csv("reviews.csv", index=False, encoding="utf-8-sig")
    print("\n====================================")
    print(f"✅ 총 리뷰 수집 완료: {len(reviews)}")
    print("📁 reviews.csv 저장됨")
    print("====================================")


if __name__ == "__main__":
    test_url = "https://smartstore.naver.com/contentking/products/10639139232"
    extract_reviews_to_csv(test_url)
