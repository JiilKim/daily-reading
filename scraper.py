#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
일일 과학 뉴스 크롤러 (기능 확장판)
- 로그 날짜별 분리 저장 및 상세 로깅
- Gemini 기반 일일 추천 콘텐츠 생성
- 차트 데이터 구조 최적화
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
import traceback

# 타임존 처리를 위한 라이브러리
try:
    from zoneinfo import ZoneInfo
except ImportError:
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
ARCHIVE_DAYS = 99999
API_DELAY_SECONDS = 2

try:
    PALO_ALTO_TZ = ZoneInfo("America/Los_Angeles")
except:
    PALO_ALTO_TZ = timezone(timedelta(hours=-8))

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/xml,application/rss+xml,text/xml;q=0.9,*/*;q=0.5'
}

# 날짜별 로그 저장을 위한 전역 변수 (Dictionary)
# 구조: { "2025-11-27": [ {time, level, message}, ... ] }
execution_logs_by_date = {} 
current_date_str = datetime.now(PALO_ALTO_TZ).strftime('%Y-%m-%d')

def log(message, level="INFO"):
    """로그를 기록하고 출력합니다."""
    now = datetime.now(PALO_ALTO_TZ)
    timestamp = now.strftime('%H:%M:%S')
    
    # 콘솔 출력
    print(f"[{timestamp}] [{level}] {message}")
    
    # 날짜별 로그 저장
    if current_date_str not in execution_logs_by_date:
        execution_logs_by_date[current_date_str] = []
        
    execution_logs_by_date[current_date_str].append({
        "time": timestamp,
        "level": level,
        "message": message
    })

# ============================================================================
# AI 기능: 번역/요약 및 일일 추천
# ============================================================================

def get_client():
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        log("GEMINI_API_KEY 없음", "ERROR")
        return None
    return genai.Client(api_key=api_key)

def get_gemini_summary(article_data):
    """기사 번역 및 요약"""
    client = get_client()
    if not client:
        return article_data['title_en'], "API 키 누락으로 요약 불가"

    title_en = article_data['title_en']
    description_en = article_data['description_en']
    url = article_data['url']
    source = article_data.get('source', '')

    try:
        start_time = time.time()
        if 'YouTube' in source:
            print(f"  [AI] 🎥 유튜브 영상 분석 중: '{title_en[:40]}...'")
            log(f"[AI] 영상 분석 요청: {title_en[:30]}...", "DETAIL")
            prompt = f"""
            당신은 영상 요약 전문가입니다. 이 유튜브 영상을 분석하여 한국어 제목과 한국어 요약문을 생성해 주세요.
            출력은 반드시 지정된 JSON 형식을 따라야 합니다.
            
            [입력]
            - title_en: "{title_en}"
            
            [JSON 출력 형식]
            {{
              "title_kr": "여기에 제목의 전문적인 한국어 번역을 작성합니다",
              "summary_kr": "핵심 요점을 추출하여, 영상 콘텐츠에 대한 상세하고 최소 10문장 분량의 한국어 요약문을 작성합니다"
            }}
            
            [규칙]
            1. "title_kr": "title_en"을 자연스럽고 전문적인 한국어로 번역합니다.
            2. "summary_kr": 자연스러운 한국어 문체로 상세한 최소 10문장 요약을 제공합니다.
            3. 대화체가 아닌 일반적인 글쓰기 문체를 사용합니다.
            """
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[prompt, types.Part.from_uri(file_uri=url, mime_type="video/youtube")],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
        else:
            log(f"[AI] 텍스트 요약 요청: {title_en[:30]}...", "DETAIL")
            prompt = f"""
            당신은 과학에 능통한 전문 기자 혹은 커뮤니케이터입니다.
            아래의 영어 기사 제목과 설명을 바탕으로, 한국어 제목과 한국어 요약본을 작성해 주세요.
            결과는 반드시 지정된 JSON 형식으로 제공해야 합니다.
             
            [입력]
            - title_en: "{title_en}"
            - description_en: "{description_en}"
            
            [JSON 출력 형식]
            {{
              "title_kr": "여기에 한국어 번역 제목을 작성",
              "summary_kr": "여기에 최소 5-6 문장으로 구성된 상세한 한국어 요약본을 작성"
            }}
            
            [규칙]
            1. "title_kr" 키에는 "title_en"을 자연스럽고 전문적인 한국어 제목으로 번역합니다.
            2. "summary_kr" 키에는 "description_en"의 핵심 내용을 상세하게 한국어로 요약합니다.
            3. 자연스럽고 읽기 쉬운 문체로 작성합니다.
            """
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
        
        elapsed = time.time() - start_time
        data = json.loads(response.text)
        log(f"[AI] 처리 완료 ({elapsed:.2f}s): {data.get('title_kr', '')[:20]}...", "INFO")
        
        return data.get('title_kr', title_en), data.get('summary_kr', "요약 생성 실패")

    except Exception as e:
        log(f"[AI] 에러 발생: {str(e)}", "ERROR")
        return title_en, f"[시스템 에러] 요약 실패: {str(e)}"

def generate_daily_recommendations(articles_today):
    """오늘의 기사들을 바탕으로 심화/관련 추천 콘텐츠 생성 (약 100개 목표)"""
    client = get_client()
    if not client or not articles_today:
        return []

    titles = [a['title'] for a in articles_today[:50]] # 토큰 제한 고려하여 상위 50개만 참조
    titles_text = "\n".join(titles)

    log(f"[AI] 오늘의 추천 콘텐츠 생성 시작 (참조 기사 {len(titles)}건)", "INFO")

    prompt = f"""
    당신은 과학 전문 큐레이터입니다. 아래는 오늘 수집된 주요 과학 기사의 제목들입니다.
    이 주제들과 관련하여, 독자들이 더 읽어볼 만한 '관련성 높고 인기 있는 웹사이트 혹은 기사'를 **최대한 많이(목표: 50~100개)** 추천해 주세요.
    
    [오늘의 기사 주제]
    {titles_text}

    [요구사항]
    1. 결과는 반드시 JSON 배열 형식이어야 합니다.
    2. 각 추천 항목은 {{ "title": "제목", "url": "URL(실제 존재하는 링크여야 함, 모르면 검색 키워드 기반의 구글 검색 링크 생성)", "description": "한글 설명(1-2문장)", "category": "분야" }} 형태여야 합니다.
    3. URL은 할루시네이션을 피하기 위해, 확실하지 않다면 `https://www.google.com/search?q=키워드` 형태로 작성해도 좋습니다.
    4. 한국어 설명은 친근하고 유익하게 작성하세요.
    """

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        recommendations = json.loads(response.text)
        if isinstance(recommendations, list):
            log(f"[AI] 추천 콘텐츠 {len(recommendations)}개 생성 완료", "INFO")
            return recommendations
        elif isinstance(recommendations, dict) and 'recommendations' in recommendations:
             log(f"[AI] 추천 콘텐츠 {len(recommendations['recommendations'])}개 생성 완료", "INFO")
             return recommendations['recommendations']
        else:
            log("[AI] 추천 콘텐츠 형식이 올바르지 않음", "WARNING")
            return []
    except Exception as e:
        log(f"[AI] 추천 콘텐츠 생성 중 오류: {e}", "ERROR")
        return []

# ============================================================================
# 스크래퍼 로직
# ============================================================================

def scrape_feed(feed_url, source_name, category_name, is_youtube):
    articles = []
    log(f"[크롤링] 소스 접근: {source_name}", "INFO")

    try:
        response = requests.get(feed_url, headers=HEADERS, timeout=15)
        feed = feedparser.parse(response.content)
        
        palo_alto_now = datetime.now(PALO_ALTO_TZ)
        count = 0

        for entry in feed.entries:
            if not entry.get('link') or not entry.get('title'): continue

            published_date = palo_alto_now
            if entry.get('published_parsed'):
                try:
                    dt_utc = datetime.fromtimestamp(time.mktime(entry.published_parsed), timezone.utc)
                    published_date = dt_utc.astimezone(PALO_ALTO_TZ)
                except: pass
            
            days_diff = (palo_alto_now - published_date).days
            if days_diff > 8: continue

            date_str = published_date.strftime('%Y-%m-%d')
            
            image_url = None
            if entry.get('media_thumbnail'):
                image_url = entry.media_thumbnail[0]['url']
            elif entry.get('links'):
                for link in entry.links:
                    if link.get('type', '').startswith('image/'):
                        image_url = link.get('href'); break
            
            desc = entry.get('summary', '')
            if is_youtube: desc = entry.get('media_description', entry.get('summary', ''))
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
            count += 1
        
        log(f"[크롤링] {source_name}: {count}개 항목 수집", "INFO")

    except Exception as e:
        log(f"[크롤링] {source_name} 실패: {str(e)}", "ERROR")

    return articles

def scrape_youtube_videos(channel_id, source_name, category_name):
    articles = []
    log(f"[크롤링] 유튜브 채널 탐색: {source_name} ({channel_id})", "INFO")
    feed_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'

    try:
        response = requests.get(feed_url, headers=HEADERS, timeout=20)
        feed = feedparser.parse(response.content)
        
        count = 0
        for entry in feed.entries:
            if not entry.get('title') or not entry.get('link'): continue
            
            link = entry.link
            date_str = datetime.now(PALO_ALTO_TZ).strftime('%Y-%m-%d') # RSS에는 정확한 시간 없을 수 있음
            if entry.get('published_parsed'):
                dt_obj = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                date_str = dt_obj.strftime('%Y-%m-%d')

            image_url = None
            if entry.get('media_thumbnail'):
                image_url = entry.media_thumbnail[0]['url'].replace('default.jpg', 'hqdefault.jpg')

            description_text = BeautifulSoup(entry.get('media_description', ''), 'html.parser').get_text(strip=True)

            articles.append({
                'title_en': entry.title,
                'description_en': description_text,
                'url': link,
                'source': source_name,
                'category': category_name,
                'date': date_str,
                'image_url': image_url
            })
            count += 1
        
        log(f"[크롤링] {source_name}: {count}개 영상 발견", "INFO")

    except Exception as e:
        log(f"[크롤링] 유튜브 오류: {e}", "ERROR")

    return articles

# ============================================================================
# 메인 실행
# ============================================================================

def main():
    global execution_logs_by_date
    start_time = datetime.now(PALO_ALTO_TZ)
    today_str = start_time.strftime('%Y-%m-%d')
    
    log(f"=== 스크립트 실행 시작 ===", "INFO")
    log(f"실행 환경: Palo Alto Time {start_time}", "DETAIL")

    # 1. 기존 데이터 로드
    seen_urls = set()
    old_articles = []
    failed_queue = []
    daily_recommendations = {} # 날짜별 추천 저장소 { "2025-11-27": [...] }

    if os.path.exists('articles.json'):
        try:
            with open('articles.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # 기사 로드
                for art in data.get('articles', []):
                    # 날짜 비교 로직 (단순화)
                    if art.get('date'):
                        old_articles.append(art)
                        seen_urls.add(art['url'])
                
                # 실패 큐 로드
                failed_queue = data.get('failed_queue', [])
                
                # 기존 로그 로드 (날짜별 구조로 되어있다고 가정, 아니면 마이그레이션)
                loaded_logs = data.get('logs', {})
                if isinstance(loaded_logs, list): # 구버전(리스트) 호환
                    log("구버전 로그 형식을 감지하여 날짜별 형식으로 변환합니다.", "WARNING")
                    # 구버전 로그는 보존하지 않거나 오늘 날짜로 편입 (여기선 단순화 위해 생략하거나 별도 처리 가능)
                else:
                    execution_logs_by_date.update(loaded_logs)
                
                # 기존 추천 목록 로드
                daily_recommendations = data.get('recommendations', {})

        except Exception as e:
            log(f"데이터 파일 로드 중 오류: {e}", "ERROR")

    # 2. 소스 정의
    sources = [
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

    # 3. 크롤링
    candidates = []
    
    # 재시도 큐
    if failed_queue:
        log(f"재시도 큐에서 {len(failed_queue)}개 항목 로드", "INFO")
        for item in failed_queue:
            if item['url'] not in seen_urls: candidates.append(item)

    # 유튜브
    candidates.extend(scrape_youtube_videos('UCWgXoKQ4rl7SY9UHuAwxvzQ', 'B_ZCF YouTube', 'Video'))

    # RSS 소스
    for url, source, cat, is_yt in sources:
        items = scrape_feed(url, source, cat, is_yt)
        for item in items:
            if item['url'] not in seen_urls: candidates.append(item)

    # 중복 제거
    unique_candidates = {v['url']: v for v in candidates}.values()
    log(f"처리 대상: 총 {len(unique_candidates)}건", "INFO")

    # 4. AI 처리 (번역/요약)
    new_articles = []
    new_failed_queue = []
    processed_cnt = 0

    for art in unique_candidates:
        if processed_cnt >= MAX_NEW_ARTICLES_PER_RUN:
            new_failed_queue.append(art); continue

        processed_cnt += 1
        title_kr, summary_kr = get_gemini_summary(art)

        if "[요약 실패]" in summary_kr or "[시스템 에러]" in summary_kr:
            new_failed_queue.append(art)
            log(f"처리 실패: {art['title_en'][:20]}...", "WARNING")
        else:
            art['title'] = title_kr
            art['summary_kr'] = summary_kr
            if 'description_en' in art: del art['description_en']
            new_articles.append(art)
        
        time.sleep(API_DELAY_SECONDS)

    # 5. 일일 추천 콘텐츠 생성 (오늘 새로 추가된 기사가 있을 경우)
    if new_articles:
        log(f"오늘의 신규 기사 {len(new_articles)}건에 대한 추천 콘텐츠 생성 중...", "INFO")
        todays_recs = generate_daily_recommendations(new_articles)
        if todays_recs:
            daily_recommendations[today_str] = todays_recs
    else:
        log("신규 기사가 없어 추천 콘텐츠 생성을 건너뜁니다.", "INFO")

    # 6. 저장
    log(f"작업 완료: 성공 {len(new_articles)}건, 보류 {len(new_failed_queue)}건", "INFO")

    final_list = old_articles + new_articles
    final_list.sort(key=lambda x: x.get('date', ''), reverse=True)

    # 현재 메모리에 있는 로그를 저장 구조에 반영
    # execution_logs_by_date는 이미 전역변수로서 log() 함수에 의해 업데이트됨

    output_data = {
        'last_updated': datetime.now(PALO_ALTO_TZ).strftime('%Y-%m-%d %H:%M:%S'),
        'logs': execution_logs_by_date, # 날짜별 로그 객체
        'failed_queue': new_failed_queue,
        'articles': final_list,
        'recommendations': daily_recommendations # 추천 데이터 추가
    }

    try:
        with open('articles.json', 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        log("articles.json 저장 완료", "INFO")
    except Exception as e:
        log(f"파일 저장 실패: {e}", "ERROR")
        sys.exit(1)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f"치명적 스크립트 오류: {traceback.format_exc()}", "ERROR")
        sys.exit(1)
