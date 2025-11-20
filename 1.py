# smartstore_review_scraper.py

import time
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


# ================================
# 리뷰 카드 1개 파싱
# ================================
def parse_review_card(card):

    # ---------------------------
    # 닉네임
    # ---------------------------
    nickname_el = card.select_one(".Db9Dtnf7gY strong")
    nickname = nickname_el.get_text(strip=True) if nickname_el else ""

    # ---------------------------
    # 날짜
    # ---------------------------
    date_el = card.select_one(".Db9Dtnf7gY span:nth-of-type(1)")
    date = date_el.get_text(strip=True) if date_el else ""

    # ---------------------------
    # 평점 (5, 4, 3…)
    # ---------------------------
    rating_el = card.select_one("em.n6zq2yy0KA")
    rating = rating_el.get_text(strip=True) if rating_el else ""

    # ---------------------------
    # 옵션 (첫 텍스트만)
    # ---------------------------
    option = ""
    option_box = card.select_one(".b_caIle8kC")
    if option_box:
        # 모든 텍스트 리스트 가져와서 첫 번째만 사용
        all_texts = list(option_box.stripped_strings)
        option = all_texts[0] if all_texts else ""



    # ---------------------------
    # 구매자 정보
    # ---------------------------
    buyer_el = card.select_one(".eWRrdDdSzW")
    buyer_info = buyer_el.get_text(" ", strip=True) if buyer_el else ""

    # ---------------------------
    # 자동 라벨 (유통기한/포장/편리 등)
    # ---------------------------
    label_el = card.select_one(".h8uqAeqIe7")
    label_info = label_el.get_text(" ", strip=True) if label_el else ""

    # auto_label = buyer_info + label_info 합쳐서 저장
    auto_label = " | ".join(x for x in [buyer_info, label_info] if x)

    # ---------------------------
    # 본문
    # ---------------------------
    content_el = card.select_one(".KqJ8Qqw082 span")
    content = content_el.get_text(" ", strip=True) if content_el else ""

    # ---------------------------
    # 이미지 개수 (정확하게 0/1/2+)
    # ---------------------------
    image_count = 0
    img_box = card.select_one(".s30AvhHfb0")

    if img_box:
        # ① 2개 이상 → 숫자 span 존재
        count_span = img_box.select_one(".lOzR1kO8jf")
        if count_span:
            number = "".join(c for c in count_span.get_text(strip=True) if c.isdigit())
            if number:
                image_count = int(number)
        else:
            # ② 숫자 span 없음 + img 있음 → 1개
            imgs = img_box.select("img")
            if len(imgs) >= 1:
                image_count = 1
    else:
        # ③ img_box 자체 없음 → 0개
        image_count = 0

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
# 리뷰 전체 수집
# ================================
def extract_reviews_to_csv(url, limit_pages=10):
    reviews = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print("⏳ URL 접속 중…")
        page.goto(url, timeout=60000)
        time.sleep(3)

        print("🔎 리뷰탭 클릭…")
        try:
            page.click('[data-name="REVIEW"]')
            print("✔ 리뷰탭 클릭 성공")
            time.sleep(2)
        except:
            print("❌ 리뷰탭 클릭 실패")
            browser.close()
            return

        for n in range(1, limit_pages + 1):
            print(f"\n📌 {n} 페이지 수집 중…")

            soup = BeautifulSoup(page.content(), "lxml")
            review_cards = soup.select(".IwcuBUIAKf")

            print(f"  - 감지된 리뷰 수: {len(review_cards)}")

            for card in review_cards:
                info = parse_review_card(card)

                # 중복 제거
                key = f"{info['nickname']}|{info['date']}|{info['content'][:20]}"
                if key not in seen:
                    seen.add(key)
                    reviews.append(info)

            # 다음 페이지 이동
            pagination = page.locator(".LiT9lKOVbw")
            next_btn = pagination.locator(f'a:has-text("{n+1}")').first

            if next_btn.count() > 0:
                print(f"➡ {n+1} 페이지 이동")
                next_btn.click()
                time.sleep(2)
            else:
                print("⛔ 다음 페이지 없음 → 종료")
                break

        browser.close()

    df = pd.DataFrame(reviews)
    df.to_csv("reviews.csv", index=False, encoding="utf-8-sig")

    print("\n==========================================")
    print(f"✅ 최종 저장된 리뷰 수: {len(reviews)}")
    print("📁 reviews.csv 생성 완료")
    print("==========================================")


if __name__ == "__main__":
    test_url = "https://smartstore.naver.com/maca-mall/products/12491774443"
    extract_reviews_to_csv(test_url)
