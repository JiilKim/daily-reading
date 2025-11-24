#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
일일 과학 뉴스 크롤러 (최종 수정판)
- ZoneInfo를 통한 정확한 Palo Alto 시간 적용
- AI 응답(List/Dict) 유연한 처리 (에러 방지)
- API 및 네트워크 에러에 대한 강한 내성 및 로깅
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import feedparser
import time
import os
from google import genai
from google.genai import types
import sys
import re
# 타임존 처리를 위한 라이브러리 (Python 3.9+)
try:
    from zoneinfo import ZoneInfo
except ImportError:
    # 구버전 파이썬 대비 (GitHub Actions는 보통 최신임)
    from datetime import timezone, timedelta
    class ZoneInfo:
        def __init__(self, key): pass
        def utcoffset(self, dt): return timedelta(hours=-8)
        def tzname(self, dt): return "PST"
        def dst(self, dt): return timedelta(0)

# ============================================================================
# 설정
# ============================================================================

MAX_NEW_ARTICLES_PER_RUN = 8000
ARCHIVE_DAYS = 7
API_DELAY_SECONDS = 2 # API 안정성을 위해 1초 -> 2초로 늘림

# 팔로알토 시간대 (썸머타임 자동 적용)
try:
    PALO_ALTO_TZ = ZoneInfo("America/Los_Angeles")
except:
    PALO_ALTO_TZ = timezone(timedelta(hours=-8)) # fallback

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/xml,application/rss+xml,text/xml;q=0.9,*/*;q=0.5'
}

# 실행 로그 전역 변수
execution_logs = []

def log(message, level="INFO"):
    """로그를 기록하고 출력합니다."""
    now = datetime.now(PALO_ALTO_TZ)
    timestamp = now.strftime('%H:%M:%S')
    
    # 콘솔 출력 (GitHub Actions 로그용)
    print(f"[{timestamp}] [{level}] {message}")
    
    # 파일 저장용 로그 (웹 표시용)
    execution_logs.append({
        "time": timestamp,
        "level": level,
        "message": message
    })

# ============================================================================
# AI 번역 및 요약
# ============================================================================

def clean_json_text(text):
    """JSON 응답 텍스트 정제"""
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    return text.strip()

def get_gemini_summary(article_data):
    title_en = article_data['title_en']
    description_en = article_data['description_en']
    source = article_data.get('source', '')

    try:
        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            log("GEMINI_API_KEY가 설정되지 않았습니다.", "ERROR")
            return title_en, "[요약 실패] API 키 없음"

        client = genai.Client(api_key=api_key)

        # 프롬프트 구성
        if 'YouTube' in source:
            prompt_text = f"""
다음 유튜브 영상 정보를 바탕으로 한국어 제목과 상세 요약을 JSON으로 작성하세요.
[제목]: {title_en}
[설명]: {description_en}

Output JSON format:
{{
  "title_kr": "한국어 제목",
  "summary_kr": "한국어 상세 요약 (최소 5문장, 평어체)"
}}
"""
        else:
            prompt_text = f"""
다음 기사 정보를 바탕으로 한국어 제목과 상세 요약을 JSON으로 작성하세요.
[제목]: {title_en}
[내용]: {description_en}

Output JSON format:
{{
  "title_kr": "한국어 제목",
  "summary_kr": "한국어 상세 요약 (최소 5-6문장, 평어체)"
}}
"""

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt_text,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )

        cleaned_text = clean_json_text(response.text)
        data = json.loads(cleaned_text)

        # [중요 수정] Gemini가 가끔 리스트로 반환하는 경우 처리 ([{...}])
        if isinstance(data, list):
            if len(data) > 0:
                data = data[0]
            else:
                data = {}

        title_kr = data.get('title_kr', title_en)
        summary_kr = data.get('summary_kr', "[요약 실패] AI 응답 형식이 올바르지 않습니다.")

        return title_kr, summary_kr

    except Exception as e:
        log(f"AI 처리 실패 ({title_en[:15]}...): {str(e)}", "ERROR")
        return title_en, f"[요약 실패] {str(e)}"

# ============================================================================
# 스크래퍼
# ============================================================================

def scrape_feed(feed_url, source_name, category_name, is_youtube=False):
    articles = []
    log(f"크롤링 시작: {source_name}", "INFO")

    try:
        # 타임아웃 10초 설정 (Wired 등 느린 사이트 대기 시간 제한)
        response = requests.get(feed_url, headers=HEADERS, timeout=10)
        feed = feedparser.parse(response.content)
        
        palo_alto_now = datetime.now(PALO_ALTO_TZ)

        for entry in feed.entries:
            # 필수 필드 체크
            if not entry.get('link') or not entry.get('title'):
                continue

            # 날짜 파싱 (Palo Alto 시간 기준)
            published_date = palo_alto_now
            if entry.get('published_parsed'):
                try:
                    dt_utc = datetime.fromtimestamp(time.mktime(entry.published_parsed), timezone.utc)
                    published_date = dt_utc.astimezone(PALO_ALTO_TZ)
                except:
                    pass # 파싱 실패시 현재 시간 유지
            
            # 8일 지난 기사 차단 (좀비 기사 방지)
            days_diff = (palo_alto_now - published_date).days
            if days_diff > 8:
                continue

            date_str = published_date.strftime('%Y-%m-%d')
            
            # 이미지 추출
            image_url = None
            if entry.get('media_thumbnail'):
                image_url = entry.media_thumbnail[0]['url']
            elif entry.get('links'):
                for link in entry.links:
                    if link.get('type', '').startswith('image/'):
                        image_url = link.get('href')
                        break
            
            # 내용 추출
            desc = entry.get('summary', '')
            if is_youtube:
                desc = entry.get('media_description', entry.get('summary', ''))
            
            clean_desc = BeautifulSoup(desc, 'html.parser').get_text(strip=True)

            articles.append({
                'title_en': entry.title,
                'description_en': clean_desc,
                'url': entry.link,
                'source': source_name,
                'category': category_name,
                'date': date_str,
                'image_url': image_url
            })

    except requests.exceptions.Timeout:
        log(f"{source_name}: 연결 시간 초과 (Timeout)", "ERROR")
    except Exception as e:
        log(f"{source_name} 크롤링 중 오류: {e}", "ERROR")

    return articles

# ============================================================================
# 메인 실행
# ============================================================================

def main():
    start_time = datetime.now(PALO_ALTO_TZ)
    log(f"=== 스크립트 시작 (날짜: {start_time.strftime('%Y-%m-%d')}) ===", "INFO")

    # 1. 데이터 로드
    seen_urls = set()
    old_articles = []
    failed_queue = []

    try:
        with open('articles.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 기존 기사 중 7일 이내 것만 유지
            for art in data.get('articles', []):
                try:
                    art_date = datetime.strptime(art.get('date', ''), '%Y-%m-%d')
                    # 날짜 비교 시 시간대 정보가 없는 경우를 위해 날짜만 비교
                    days_diff = (start_time.date() - art_date.date()).days
                    if days_diff <= ARCHIVE_DAYS:
                        old_articles.append(art)
                        seen_urls.add(art['url'])
                except:
                    pass # 날짜 형식 에러시 제외
            
            # 이전 실패 목록 로드
            failed_queue = data.get('failed_queue', [])
            
    except Exception:
        log("기존 데이터 파일 없음 또는 손상됨. 새로 시작.", "WARNING")

    # 2. 수집 소스 정의
    sources = [
        ('UCWgXoKQ4rl7SY9UHuAwxvzQ', 'B_ZCF YouTube', 'Video', True),
        ('https://www.thetransmitter.org/feed/', 'The Transmitter', 'Neuroscience', False),
        ('https://www.nature.com/nature/rss/articles?type=news', 'Nature', 'News', False),
        ('https://www.statnews.com/feed/', 'STAT News', 'News', False),
        ('https://www.the-scientist.com/atom/latest', 'The Scientist', 'News', False),
        ('https://arstechnica.com/science/feed/', 'Ars Technica', 'News', False),
        ('https://www.wired.com/feed/category/science/latest/rss', 'Wired', 'News', False),
        ('https://www.fiercebiotech.com/rss/xml', 'Fierce Biotech', 'News', False),
        ('https://endpts.com/feed/', 'Endpoints News', 'News', False),
        ('https://www.science.org/rss/news_current.xml', 'Science', 'News', False),
        ('https://www.nature.com/nature/rss/newsandcomment', 'Nature (News & Comment)', 'News', False),
        ('https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science', 'Science (Paper)', 'Paper', False),
        ('https://www.cell.com/cell/current.rss', 'Cell', 'Paper', False),
        ('https://www.nature.com/neuro/current_issue/rss', 'Nature Neuroscience', 'Paper', False),
        ('https://www.nature.com/nm/current_issue/rss', 'Nature Medicine', 'Paper', False),
        ('https://www.nature.com/nrd/current_issue/rss', 'Nature Drug Discovery', 'Paper', False),
        ('https://www.nature.com/nbt/current_issue/rss', 'Nature Biotechnology', 'Paper', False),
        ('https://www.nature.com/nature/research-articles.rss', 'Nature (Paper)', 'Paper', False),
        ('https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss', 'NEJM', 'Paper', False)
    ]

    # 3. 크롤링 및 후보 선정
    candidates = []
    
    # 3-1. 실패했던 것 우선 추가
    if failed_queue:
        log(f"지난 실행 실패 항목 {len(failed_queue)}개 재시도 대기", "INFO")
        for item in failed_queue:
            if item['url'] not in seen_urls:
                candidates.append(item)

    # 3-2. 신규 크롤링
    for url, source, cat, is_yt in sources:
        items = scrape_feed(url, source, cat, is_yt)
        for item in items:
            if item['url'] not in seen_urls:
                candidates.append(item)

    # 중복 제거
    unique_candidates = {v['url']: v for v in candidates}.values()
    log(f"총 처리 대상: {len(unique_candidates)}건", "INFO")

    # 4. AI 처리
    new_articles = []
    new_failed_queue = []
    processed_cnt = 0

    for art in unique_candidates:
        if processed_cnt >= MAX_NEW_ARTICLES_PER_RUN:
            log(f"할당량({MAX_NEW_ARTICLES_PER_RUN}) 초과. 남은 {len(unique_candidates) - processed_cnt}건은 다음으로 미룸.", "WARNING")
            new_failed_queue.append(art)
            continue

        processed_cnt += 1
        title_kr, summary_kr = get_gemini_summary(art)

        if "[요약 실패]" in summary_kr:
            # 실패시 큐에 저장 (다음 실행때 최우선 처리)
            new_failed_queue.append(art)
        else:
            art['title'] = title_kr
            art['summary_kr'] = summary_kr
            # 원문은 저장하지 않음 (용량 절약) or 필요시 art['summary_en'] = ...
            if 'description_en' in art: del art['description_en']
            new_articles.append(art)
        
        time.sleep(API_DELAY_SECONDS)

    # 5. 결과 저장 (이 부분이 가장 중요. 에러가 나도 반드시 저장되도록 try-finally나 안전장치 필요)
    log(f"오늘 처리 결과: 성공 {len(new_articles)}건, 실패/보류 {len(new_failed_queue)}건", "INFO")

    final_list = old_articles + new_articles
    # 날짜 내림차순 정렬
    final_list.sort(key=lambda x: x.get('date', ''), reverse=True)

    output_data = {
        'last_updated': datetime.now(PALO_ALTO_TZ).strftime('%Y-%m-%d %H:%M:%S'),
        'logs': execution_logs, # 여기에 실행 로그 포함
        'failed_queue': new_failed_queue,
        'articles': final_list
    }

    try:
        with open('articles.json', 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        log("데이터 저장 완료 (articles.json)", "INFO")
    except Exception as e:
        log(f"치명적 오류: 파일 저장 실패 - {e}", "ERROR")
        # 저장 실패시 로그라도 출력
        print(json.dumps(execution_logs, indent=2))
        sys.exit(1)

if __name__ == '__main__':
    main()
