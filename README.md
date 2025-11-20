# URL예시

예시 1. https://smartstore.naver.com/maca-mall/products/12491774443

예시 2. https://smartstore.naver.com/ggumggumy/products/12144129760

# 파이썬 설명
1.py는 예시 1이 되는 것\
2.py는 예시 2도 되는 것 : 기능에 스크롤 버전 추가해서 됨. 예시 1,2 둘 다 아이프레임이 없는 구버전 방식으로 됨.\

각 .py에서\
기본 설정에서는 최대 10페이지까지만 추출\
최대 100페이지 수집하고 싶으면\
extract_reviews_to_csv(url, limit_pages=100)\
