# URL예시

예시 1. https://smartstore.naver.com/maca-mall/products/12491774443

예시 2. https://smartstore.naver.com/ggumggumy/products/12144129760

예시 3. https://smartstore.naver.com/contentking/products/10639139232

# 파이썬 설명
1.py는 예시 1이 되는 것\
2.py는 예시 2도 되는 것 : 기능에 스크롤 버전 추가해서 됨. 예시 1,2 둘 다 아이프레임이 없는 구버전 방식으로 됨. 한달사용 및 재구매 키워드가 하나 만 있는 경우는 잘 작동
review_dedup_inspector1.py : 리뷰중에 중복이 어느 페이지 몇에 있는지 검사.
3.py는 예시 3도 되는 것 : 기능에 스크롤 버전도 물론 있거 예시 1,2,3 다 아이프레임이 없는 구버전 방식으로 됨. 한달사용 및 재구매 키워드가 둘 중 하나라도 둘 다 있는 경우도 없는 경우도 잘됨. 근데 리뷰가 1개가 뭔가 누락된 느낌.

각 .py에서\
기본 설정에서는 최대 10페이지까지만 추출\
최대 100페이지 수집하고 싶으면\
extract_reviews_to_csv(url, limit_pages=100)
