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

MAX_NEW_ARTICLES_PER_RUN = 10000
API_DELAY_SECONDS = 2 # API 안정성을 위해 1초 -> 2초로 늘림
# 재시도 횟수 설정 (총 3번 시도)
max_retries = 5

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
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()

def get_gemini_summary(article_data, model_id):
    
    """
    Gemini API를 사용하여 기사 콘텐츠를 번역하고 요약합니다.
    유튜브 영상의 경우 URL을 통해 직접 영상 콘텐츠를 분석합니다.
    
    Args:
        article_data (dict): title_en, description_en, url, source를 포함한 기사 메타데이터
        
    Returns:
        tuple: (translated_title_kr, summary_kr)
    """
    
    title_en = article_data['title_en']
    description_en = article_data['description_en']
    url = article_data['url']
    source = article_data.get('source', '')
    
    api_key = os.environ.get('GEMINI_API_KEY')
    
    if not api_key:
        print("  [AI] ❌ GEMINI_API_KEY를 찾을 수 없습니다. 번역을 건너뜁니다.")
        return title_en, f"[요약 실패] API 키 없음. (원본: {description_en[:100]}...)"
    
    client = genai.Client(api_key=api_key)
    
    for attempt in range(max_retries):
        try:        
            # 현재 시도 중인 모델 출력
            print(f"  [AI] 🤖 모델 연결 시도: {model_id} ...")
            time.sleep(5)
            # 유튜브 영상: URL을 통해 직접 영상 콘텐츠 분석
            if 'YouTube' in source:
                print(f"  [AI] 🎥 유튜브 영상 분석 중: '{title_en[:40]}...'")
                
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
                    model = model_id,
                    contents=[
                        prompt,
                        types.Part.from_uri(
                            file_uri=url,
                            mime_type="video/youtube"
                        )
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                
            # 텍스트 기사: 설명을 바탕으로 번역 및 요약
            else:
                print(f"  [AI] 📝 기사 번역 중: '{title_en[:40]}...'")
                
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
                    model = model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
    
    
            # [수정된 부분] 텍스트 정제 (마크다운 제거)
            text = response.text
            if text.startswith("```"):
                text = re.sub(r"^```json\s*", "", text) # 시작 부분 ```json 제거
                text = re.sub(r"^```\s*", "", text)     # 시작 부분 ``` 제거
                text = re.sub(r"\s*```$", "", text)     # 끝 부분 ``` 제거
            
            text = text.strip() # 앞뒤 공백 제거
    
            # JSON 파싱
            data = json.loads(text, strict=False)
            
            title_kr = data.get('title_kr', title_en)
            summary_kr = data.get('summary_kr', "요약 내용 없음")
    
            log(f"  [AI] ✅ 완료: {title_kr[:20]}...")
            return title_kr, summary_kr
    
        # 🚨 에러 처리 핸들러 (다음 모델로 넘길지 결정)
        except Exception as e:
            error_msg = str(e)
            
            # 1. 할당량 초과 (429) 또는 모델 없음 (404) -> 다음 모델로 Pass
            if "429" in error_msg or "404" in error_msg or "ResourceExhausted" in error_msg or "Not Found" in error_msg:
                print(f"  [AI] ⚠️ {model_id} 사용 불가 (한도초과/미지원). (시도 {attempt+1}): {e}")
                return title_en, f"[요약 실패] {str(e)}"
        
        except json.JSONDecodeError as e:
            print(f"  [AI] ❌ JSON 파싱 에러: {e}")
            print(f"  [디버그] 문제의 텍스트: {response.text[:100]}...") # 디버깅용 출력
            return title_en, "[요약 실패] AI 응답 오류 (JSON 파싱 실패)"
        
        except Exception as e:
            # [수정] 대기 시간 점진적 증가 (2초 -> 4초 -> 8초 -> 16초...)
            wait_time = 2 * (2 ** attempt) 
            print(f"  [AI] ⚠️ 에러 발생 (시도 {attempt+1}): {e}")
            
            if attempt < max_retries - 1:
                print(f"  ⏳ {wait_time}초 대기 후 재시도합니다...")
                time.sleep(wait_time)
                continue
            else:
                print(f"  [AI] ❌ 최종 실패: {title_en[:20]}...")
                return title_en, f"[요약 실패] {str(e)}"
                
# ============================================================================
# 스크래퍼
# ============================================================================

def scrape_feed(feed_url, source_name, category_name):
    articles = []
    log(f"크롤링 시작: {source_name}", "INFO")

    try:
        response = requests.get(feed_url, headers=HEADERS, timeout=10)
        feed = feedparser.parse(response.content)
        
        # [핵심] 이 시간이 곧 기사의 날짜가 됩니다.
        palo_alto_now = datetime.now(PALO_ALTO_TZ)
        date_str = palo_alto_now.strftime('%Y-%m-%d')

        for entry in feed.entries:
            link = entry.get('link')
            title = entry.get('title')
            
            if not link or not title:
                continue

            # [삭제됨] 기존의 published_parsed 로직 제거
            # 무조건 위에서 정의한 date_str(오늘)을 사용합니다.
            
            # 이미지 추출
            image_url = None
            if entry.get('media_thumbnail'):
                image_url = entry.media_thumbnail[0]['url']
            elif entry.get('links'):
                for lk in entry.links:
                    if lk.get('type', '').startswith('image/'):
                        image_url = lk.get('href')
                        break
            
            # 내용 추출
            desc = entry.get('summary', '')
            clean_desc = BeautifulSoup(desc, 'html.parser').get_text(strip=True)

            articles.append({
                'title_en': title,
                'description_en': clean_desc,
                'url': link,
                'source': source_name,
                'category': category_name,
                'date': date_str, # 무조건 오늘 날짜
                'image_url': image_url
            })
            
        log(f"[{source_name}] 완료: {len(articles)}개 기사 수집됨", "INFO")

    except requests.exceptions.Timeout:
        log(f"{source_name}: 연결 시간 초과 (Timeout)", "ERROR")
    except Exception as e:
        log(f"{source_name} 크롤링 중 오류: {e}", "ERROR")

    return articles
# ============================================================================
# 유튜브 채널 스크래퍼
# ============================================================================

def scrape_youtube_videos(channel_id, source_name, category_name):
    articles = []
    log(f"🔍 [{source_name}] 유튜브 크롤링 중... (채널: {channel_id})")
    feed_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'

    try:
        response = requests.get(feed_url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        # [핵심] 유튜브도 무조건 오늘(Palo Alto) 날짜로 고정
        palo_alto_now = datetime.now(PALO_ALTO_TZ)
        date_str = palo_alto_now.strftime('%Y-%m-%d')

        print(f"  [i] {len(feed.entries)}개의 최신 영상 발견")

        for entry in feed.entries:
            try:
                if not entry.get('title') or not entry.get('link'):
                    continue

                title_en = entry.title
                link = entry.link
                video_id = link.split('v=')[-1]

                # [삭제됨] 기존의 published_parsed 로직 제거
                
                # 고화질 썸네일
                image_url = None
                if entry.get('media_thumbnail') and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0]['url'].replace('default.jpg', 'hqdefault.jpg')

                description_en = entry.get('media_description', entry.get('summary', title_en))
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)
                
                log(f"    [i] 영상 {video_id} 로드됨.")

                articles.append({
                    'title_en': title_en,
                    'description_en': description_text,
                    'url': link,
                    'source': source_name,
                    'category': category_name,
                    'date': date_str, # 무조건 오늘 날짜
                    'image_url': image_url
                })

            except Exception as item_err:
                log(f"  ✗ 영상 파싱 실패: {item_err}")

    except Exception as e:
        log(f"❌ [{source_name}] 오류: {e}")

    return articles

# %%
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
            
            # [핵심] 날짜 제한 없이 모든 과거 기록을 로드 (중복 방지용)
            for art in data.get('articles', []):
                # URL이 있는 유효한 기사만 로드
                if art.get('url'):
                    old_articles.append(art)
                    seen_urls.add(art['url'])
            
            # 이전 실패 목록 로드
            failed_queue = data.get('failed_queue', [])
            
    except FileNotFoundError:
        log("기존 데이터 파일 없음. 새로 시작.", "WARNING")
    except json.JSONDecodeError:
        log("JSON 파일 깨짐. 백업 후 새로 시작.", "ERROR")
    except Exception as e:
        log(f"데이터 로드 중 알 수 없는 오류: {e}", "ERROR")

    # 2. 수집 소스 정의
    sources = [
        # General
        ('https://www.technologyreview.com/feed/', 'MIT Tech Rev', 'News'),
        ('https://www.nature.com/nature/rss/articles?type=news', 'Nature', 'News'),
        ('https://www.the-scientist.com/atom/latest', 'The Scientist', 'News'),
        ('https://www.science.org/rss/news_current.xml', 'Science', 'News'),
        ('https://www.nature.com/nature/rss/newsandcomment', 'Nature (News & Comment)', 'News'),

        # Bio industry news
        ('https://www.statnews.com/feed/', 'STAT News', 'News'),
        ('https://arstechnica.com/science/feed/', 'Ars Technica', 'News'),
        ('https://www.wired.com/feed/category/science/latest/rss', 'Wired', 'News'),
        ('https://www.fiercebiotech.com/rss/xml', 'Fierce Biotech', 'News'),
        ('https://endpts.com/feed/', 'Endpoints News', 'News'),
        ('https://www.biopharmadive.com/feeds/news/', 'BioPharmaDive', 'News'),
        ('https://www.clinicaltrialsarena.com/feed/', 'Clinical Trials Arena', 'News'),

        # Neuroscience
        ('https://www.thetransmitter.org/feed/', 'The Transmitter', 'Neuroscience'),


        # Research papers
        ('https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science', 'Science (Paper)', 'Paper'),
        ('https://www.cell.com/cell/current.rss', 'Cell', 'Paper'),
        ('https://www.nature.com/neuro/current_issue/rss', 'Nature Neuroscience', 'Paper'),
        ('https://www.nature.com/nm/current_issue/rss', 'Nature Medicine', 'Paper'),
        ('https://www.nature.com/nrd/current_issue/rss', 'Nature Drug Discovery', 'Paper'),
        ('https://www.nature.com/nbt/current_issue/rss', 'Nature Biotechnology', 'Paper'),
        ('https://www.nature.com/nature/research-articles.rss', 'Nature (Paper)', 'Paper'),
        ('https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss', 'NEJM', 'Paper')
    ]

    # 3. 크롤링 및 후보 선정
    candidates = []
    
    # 3-1. 실패했던 것 우선 추가
    if failed_queue:
        log(f"지난 실행 실패 항목 {len(failed_queue)}개 재시도 대기", "INFO")
        for item in failed_queue:
            if item['url'] not in seen_urls:
                candidates.append(item)

    # 유튜브 채널
    candidates.extend(
        scrape_youtube_videos('UCWgXoKQ4rl7SY9UHuAwxvzQ', 'B_ZCF YouTube', 'Video'))
    candidates.extend(
        scrape_youtube_videos('UCXql5C57vS4ogUt6CPEWWHA', '김지윤의 지식Play YouTube', 'Video'))    
    
    candidates = [item for item in candidates if item['url'] not in seen_urls]
        
    
    # 3-2. 신규 크롤링
    for url, source, cat in sources:
        items = scrape_feed(url, source, cat)
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
        
        model_id = 'gemini-2.5-flash-lite'
        title_kr, summary_kr = get_gemini_summary(art, model_id)
        
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

    # 6. logs.json 별도 저장 (날짜별 누적)
    log_file_path = 'logs.json'
    all_logs = {}
    
    # 오늘 날짜 키 생성 (Palo Alto 시간 기준)
    current_date_key = start_time.strftime('%Y-%m-%d')

    if os.path.exists(log_file_path):
        try:
            with open('logs.json', 'r', encoding='utf-8') as f:
                all_logs = json.load(f)
                # 만약 파일 내용이 dict가 아니면 초기화
                if not isinstance(all_logs, dict):
                    all_logs = {}
        except Exception as e:
            print(f"로그 파일 로드 중 오류(무시됨): {e}")
            all_logs = {}
            
    # 오늘 날짜 키에 현재까지 쌓인 로그(execution_logs) 저장
    all_logs[current_date_key] = execution_logs

    try:
        with open('logs.json', 'w', encoding='utf-8') as f:
            json.dump(all_logs, f, ensure_ascii=False, indent=2)
        print(f"로그 저장 완료: {log_file_path} (Key: {current_date_key})")
    except Exception as e:
        print(f"로그 저장 실패: {e}")
    
    print("=== 스크립트 종료 ===")

if __name__ == '__main__':
    main()
