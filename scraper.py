#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
일일 과학 뉴스 크롤러 (개선판)
- 팔로알토 시간 기준
- API 에러 시 재시도 큐 관리
- 8일 이상 된 좀비 기사 원천 차단
- 상세 로그 기록 및 웹 표시 지원
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta, timezone
import feedparser
import time
import os
from google import genai
from google.genai import types
from urllib.parse import urljoin
import sys
from youtube_transcript_api import YouTubeTranscriptApi
import re

# ============================================================================
# 설정
# ============================================================================

MAX_NEW_ARTICLES_PER_RUN = 8000 # API 할당량
ARCHIVE_DAYS = 7
API_DELAY_SECONDS = 1

# 팔로알토 시간대 설정 (UTC-8)
PALO_ALTO_TZ = timezone(timedelta(hours=-8))

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/xml,application/rss+xml,text/xml;q=0.9,*/*;q=0.5',
    'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8',
    'Cache-Control': 'no-cache',
}

# 로그 저장용 리스트
execution_logs = []

def log(message, level="INFO"):
    """로그를 기록하고 출력합니다."""
    timestamp = datetime.now(PALO_ALTO_TZ).strftime('%H:%M:%S')
    log_entry = f"[{timestamp}] [{level}] {message}"
    print(log_entry)
    execution_logs.append({"time": timestamp, "level": level, "message": message})

# ============================================================================
# AI 번역 및 요약
# ============================================================================

def clean_json_text(text):
    """JSON 응답 텍스트에서 마크다운 코드 블록을 제거합니다."""
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    return text.strip()

def get_gemini_summary(article_data):
    title_en = article_data['title_en']
    description_en = article_data['description_en']
    url = article_data['url']
    source = article_data.get('source', '')

    try:
        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            log("GEMINI_API_KEY 없음", "ERROR")
            return title_en, "[요약 실패] API 키 없음"

        client = genai.Client(api_key=api_key)

        if 'YouTube' in source:
            log(f"유튜브 분석 시도: {title_en[:30]}...", "INFO")
            prompt = f"""
다음 유튜브 영상의 제목과 설명을 바탕으로 한국어 제목과 상세한 요약을 JSON으로 작성해 주세요.
[입력 제목]: {title_en}
[입력 설명]: {description_en}

[JSON 출력 형식]
{{
  "title_kr": "한국어 제목",
  "summary_kr": "한국어 상세 요약 (최소 5문장 이상)"
}}
"""
            contents = [prompt] # 텍스트만 전달 (자막 없으면 설명 의존)
            
        else:
            log(f"기사 번역 시도: {title_en[:30]}...", "INFO")
            prompt = f"""
당신은 전문 과학 기자입니다. 아래 기사를 한국어로 번역하고 요약하세요.
[제목]: {title_en}
[내용]: {description_en}

[JSON 출력 형식]
{{
  "title_kr": "한국어 제목",
  "summary_kr": "한국어 상세 요약 (최소 5-6문장)"
}}
"""
            contents = prompt

        response = client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=contents,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )

        cleaned_text = clean_json_text(response.text)
        data = json.loads(cleaned_text)
        
        return data.get('title_kr', title_en), data.get('summary_kr', "[요약 실패] 내용 없음")

    except Exception as e:
        log(f"AI 처리 중 오류: {str(e)}", "ERROR")
        return title_en, f"[요약 실패] {str(e)}"

# ============================================================================
# 스크래퍼 (RSS & YouTube)
# ============================================================================

def scrape_rss_feed(feed_url, source_name, category_name):
    articles = []
    log(f"RSS 크롤링: {source_name}", "INFO")

    try:
        response = requests.get(feed_url, headers=HEADERS, timeout=20)
        feed = feedparser.parse(response.content)
        
        palo_alto_now = datetime.now(PALO_ALTO_TZ)

        for entry in feed.entries:
            if not entry.get('title') or not entry.get('link'): continue

            # 날짜 파싱 및 8일 이상 된 기사 차단
            published_date = palo_alto_now
            if entry.get('published_parsed'):
                try:
                    dt_utc = datetime.fromtimestamp(time.mktime(entry.published_parsed), timezone.utc)
                    published_date = dt_utc.astimezone(PALO_ALTO_TZ)
                except: pass
            
            days_diff = (palo_alto_now - published_date).days
            if days_diff > 8:
                # log(f"오래된 기사 패스 ({days_diff}일 전): {entry.title[:20]}...", "DEBUG")
                continue

            date_str = published_date.strftime('%Y-%m-%d')
            
            # 이미지 추출
            image_url = None
            if entry.get('media_thumbnail'):
                image_url = entry.media_thumbnail[0].get('url')
            elif entry.get('links'):
                for e_link in entry.links:
                    if e_link.get('type', '').startswith('image/'):
                        image_url = e_link.get('href')
                        break
            
            description_text = BeautifulSoup(entry.get('summary', entry.title), 'html.parser').get_text(strip=True)

            articles.append({
                'title_en': BeautifulSoup(entry.title, 'html.parser').get_text(strip=True),
                'description_en': description_text,
                'url': entry.link,
                'source': source_name,
                'category': category_name,
                'date': date_str,
                'image_url': image_url
            })

    except Exception as e:
        log(f"{source_name} 크롤링 실패: {e}", "ERROR")

    return articles

def scrape_youtube_videos(channel_id, source_name, category_name):
    articles = []
    log(f"유튜브 크롤링: {source_name}", "INFO")
    feed_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'

    try:
        feed = feedparser.parse(feed_url)
        palo_alto_now = datetime.now(PALO_ALTO_TZ)

        for entry in feed.entries:
            published_date = palo_alto_now
            if entry.get('published_parsed'):
                dt_utc = datetime.fromtimestamp(time.mktime(entry.published_parsed), timezone.utc)
                published_date = dt_utc.astimezone(PALO_ALTO_TZ)
            
            if (palo_alto_now - published_date).days > 8: continue

            image_url = entry.media_thumbnail[0]['url'] if entry.get('media_thumbnail') else None
            
            articles.append({
                'title_en': entry.title,
                'description_en': entry.get('media_description', entry.title),
                'url': entry.link,
                'source': source_name,
                'category': category_name,
                'date': published_date.strftime('%Y-%m-%d'),
                'image_url': image_url
            })
    except Exception as e:
        log(f"유튜브 실패: {e}", "ERROR")

    return articles

# ============================================================================
# 메인 실행 로직
# ============================================================================

def main():
    log("=== 크롤러 시작 (Palo Alto Time) ===", "INFO")
    
    # 1. 기존 데이터 로드
    seen_urls = set()
    old_articles_to_keep = []
    failed_urls_queue = [] # 재시도 대상

    try:
        with open('articles.json', 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            
            # 기존 성공한 기사 로드
            for art in old_data.get('articles', []):
                if not art.get('url'): continue
                # 최근 7일 데이터만 유지
                try:
                    art_date = datetime.strptime(art.get('date', '1970-01-01'), '%Y-%m-%d')
                    if (datetime.now() - art_date).days <= ARCHIVE_DAYS:
                        old_articles_to_keep.append(art)
                        seen_urls.add(art['url'])
                except: pass
            
            # 이전 실패 목록 로드 (재시도 위해)
            failed_urls_queue = old_data.get('failed_queue', [])
            
    except (FileNotFoundError, json.JSONDecodeError):
        log("기존 데이터 없음. 새로 시작.", "INFO")

    # 2. 소스 정의 및 수집
    sources = [
        # (URL, Source, Category, Type)
        ('UCWgXoKQ4rl7SY9UHuAwxvzQ', 'B_ZCF YouTube', 'Video', 'youtube'),
        ('https://www.thetransmitter.org/feed/', 'The Transmitter', 'Neuroscience', 'rss'),
        ('https://www.nature.com/nature/rss/articles?type=news', 'Nature', 'News', 'rss'),
        ('https://www.statnews.com/feed/', 'STAT News', 'News', 'rss'),
        ('https://www.the-scientist.com/atom/latest', 'The Scientist', 'News', 'rss'),
        ('https://arstechnica.com/science/feed/', 'Ars Technica', 'News', 'rss'),
        ('https://www.wired.com/feed/category/science/latest/rss', 'Wired', 'News', 'rss'),
        ('https://www.fiercebiotech.com/rss/xml', 'Fierce Biotech', 'News', 'rss'),
        ('https://endpts.com/feed/', 'Endpoints News', 'News', 'rss'),
        ('https://www.science.org/rss/news_current.xml', 'Science', 'News', 'rss'),
        ('https://www.nature.com/nature/rss/newsandcomment', 'Nature (News & Comment)', 'News', 'rss'),
        ('https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science', 'Science (Paper)', 'Paper', 'rss'),
        ('https://www.cell.com/cell/current.rss', 'Cell', 'Paper', 'rss'),
        ('https://www.nature.com/neuro/current_issue/rss', 'Nature Neuroscience', 'Paper', 'rss'),
        ('https://www.nature.com/nm/current_issue/rss', 'Nature Medicine', 'Paper', 'rss'),
        ('https://www.nature.com/nrd/current_issue/rss', 'Nature Drug Discovery', 'Paper', 'rss'),
        ('https://www.nature.com/nbt/current_issue/rss', 'Nature Biotechnology', 'Paper', 'rss'),
        ('https://www.nature.com/nature/research-articles.rss', 'Nature (Paper)', 'Paper', 'rss'),
        ('https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss', 'NEJM', 'Paper', 'rss')
    ]

    collected_candidates = []

    # 2-1. 재시도 대상 먼저 추가
    if failed_urls_queue:
        log(f"재시도 대상 {len(failed_urls_queue)}개 로드됨", "INFO")
        for item in failed_urls_queue:
            # 중복 체크 없이 우선 후보군에 넣음 (아래에서 seen_urls 체크함)
            if item['url'] not in seen_urls:
                collected_candidates.append(item)

    # 2-2. 신규 크롤링
    for s_url, s_name, s_cat, s_type in sources:
        if s_type == 'youtube':
            items = scrape_youtube_videos(s_url, s_name, s_cat)
        else:
            items = scrape_rss_feed(s_url, s_name, s_cat)
        
        for item in items:
            if item['url'] not in seen_urls:
                collected_candidates.append(item)

    # 중복 제거 (URL 기준)
    unique_candidates = {v['url']: v for v in collected_candidates}.values()
    log(f"총 처리 대기 항목: {len(unique_candidates)}개", "INFO")

    # 3. API 처리
    new_articles = []
    new_failed_queue = []
    processed_count = 0

    for article_data in unique_candidates:
        if processed_count >= MAX_NEW_ARTICLES_PER_RUN:
            log("API 일일 할당량 도달. 중단합니다.", "WARNING")
            # 처리 못한 나머지 항목은 다음을 위해 실패 큐에 저장
            new_failed_queue.append(article_data)
            continue

        try:
            processed_count += 1
            title_kr, summary_kr = get_gemini_summary(article_data)

            if "[요약 실패]" in summary_kr:
                log(f"요약 실패, 재시도 큐로 이동: {article_data['title_en'][:20]}...", "WARNING")
                new_failed_queue.append(article_data)
            else:
                article_data['title'] = title_kr
                article_data['summary_kr'] = summary_kr
                article_data['summary_en'] = article_data['description_en'] # 원문 백업
                del article_data['description_en']
                new_articles.append(article_data)
                
            time.sleep(API_DELAY_SECONDS)

        except Exception as e:
            log(f"치명적 에러 ({article_data['url']}): {e}", "ERROR")
            new_failed_queue.append(article_data)

    # 4. 저장
    final_articles = old_articles_to_keep + new_articles
    final_articles.sort(key=lambda x: x.get('date', '1970-01-01'), reverse=True)

    log(f"처리 완료: 성공 {len(new_articles)}건, 실패/대기 {len(new_failed_queue)}건", "INFO")
    
    output = {
        'last_updated': datetime.now(PALO_ALTO_TZ).strftime('%Y-%m-%d %H:%M:%S'),
        'logs': execution_logs, # 로그 저장
        'failed_queue': new_failed_queue, # 실패 목록 저장
        'articles': final_articles
    }

    with open('articles.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log("articles.json 업데이트 완료", "INFO")

if __name__ == '__main__':
    main()
