# review_dedup_inspector1.py (중복 리뷰 추적 버전)

import time
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


def parse_review_card(card):
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

    # ★ content 개선 반영
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

    img_box = card.select_one(".s30AvhHfb0")
    image_count = 0
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


def extract_reviews_debug(url, limit_pages=12):
    seen = {}
    duplicates = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        time.sleep(3)
        page.click('[data-name="REVIEW"]')
        time.sleep(2)

        for n in range(1, limit_pages + 1):
            print(f"\n--- PAGE {n} ---")

            soup = BeautifulSoup(page.content(), "lxml")
            review_cards = soup.select(".IwcuBUIAKf")

            for idx, card in enumerate(review_cards, start=1):
                info = parse_review_card(card)

                key = f"{info['nickname']}|{info['date']}|{info['content'][:20]}"

                if key in seen:
                    print("⚠ 중복 감지됨!")
                    print(f" - 페이지 {n}, 리뷰 #{idx}")
                    print(f" - 기존: {seen[key]}")
                    print(f" - 현재: nickname={info['nickname']}, date={info['date']}, content={info['content'][:50]}")
                    duplicates.append((seen[key], (n, idx), key))
                else:
                    seen[key] = (n, idx)

            # next page
            pagination = page.locator(".LiT9lKOVbw")
            next_btn = pagination.locator(f'a:has-text("{n+1}")').first
            if next_btn.count() > 0:
                next_btn.click()
                time.sleep(2)
            else:
                break

        browser.close()

    print("\n=========================")
    print("중복 결과")
    print("=========================")
    if duplicates:
        for prev, curr, key in duplicates:
            print(f"- Key: {key}")
            print(f"  이전 리뷰 위치: 페이지 {prev[0]}, #{prev[1]}")
            print(f"  중복 리뷰 위치: 페이지 {curr[0]}, #{curr[1]}")
    else:
        print("중복 없음!")


if __name__ == "__main__":
    url = "https://smartstore.naver.com/contentking/products/10639139232"
    extract_reviews_debug(url)
