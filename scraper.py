#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
웹사이트에서 뉴스/논문/영상을 크롤링하고
Gemini API를 이용해 번역/요약한 후
articles.json을 업데이트합니다.
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime  # <-- 누락되었던 datetime 임포트
import feedparser
import time
import os
import google.generativeai as genai
import google.generativeai.types as genai_types
# YouTube 스크립트 API 임포트
from youtube_transcript_api import YouTubeTranscriptApi

# --- AI 요약 기능 (JSON 포맷) ---

def get_gemini_summary(title_en, description_en):
    """
    Gemini API를 호출하여 제목과 설명을 한글로 번역 및 요약합니다.
    결과를 JSON 형식으로 받습니다.
    """
    print(f"  [AI] '{title_en[:30]}...' 번역/요약 요청 중...")
    
    try:
        api_key = os.environ.get('GEMINI_API_KEY')
        
        if not api_key:
            print("  [AI] ❌ GEMINI_API_KEY가 설정되지 않았습니다. 요약을 건너뜁니다.")
            return title_en, f"[요약 실패] API 키가 없습니다. (원본: {description_en[:100]}...)"

        genai.configure(api_key=api_key)
        
        generation_config = genai.GenerationConfig(response_mime_type="application/json")
        model = genai.GenerativeModel(
            'gemini-2.5-flash-preview-09-2025',
            generation_config=generation_config
        )
        
        prompt = f"""
        당신은 전문 과학 뉴스 편집자입니다.
        아래의 영어 기사 제목과 설명을 바탕으로, 한국어 제목과 한국어 요약본을 작성해 주세요.
        결과는 반드시 지정된 JSON 형식으로 제공해야 합니다.

        [입력]
        - title_en: "{title_en}"
        - description_en: "{description_en}"

        [JSON 출력 형식]
        {{
          "title_kr": "여기에 한국어 번역 제목을 작성",
          "summary_kr": "여기에 5-6 문장으로 구성된 상세한 한국어 요약본을 작성"
        }}

        [규칙]
        1. "title_kr" 키에는 "title_en"을 자연스럽고 전문적인 한국어 제목으로 번역합니다.
        2. "summary_kr" 키에는 "description_en"의 핵심 내용을 상세하게 5-6 문장의 한국어로 요약합니다.
        3. 친절한 말투가 아닌, 전문적이고 간결한 뉴스체로 작성합니다.
        """
        
        # API 호출 시 타임아웃 설정
        response = model.generate_content(prompt, request_options={'timeout': 120})
        
        data = json.loads(response.text)
        
        title_kr = data.get('title_kr', title_en)
        summary_kr = data.get('summary_kr', f"[요약 실패] API 응답 오류. (원본: {description_en[:100]}...)")
        
        print(f"  [AI] ✓ 요약 완료: {title_kr[:30]}...")
        return title_kr, summary_kr
    
    except Exception as e:
        # 오류 발생 시 genai_types.generation_types.BlockedPromptError 같은 특정 오류를 확인
        if isinstance(e, genai_types.generation_types.BlockedPromptError):
             print(f"  [AI] ❌ Gemini API - 콘텐츠 차단 오류: {e}")
             return title_en, "[요약 실패] API가 콘텐츠를 차단했습니다."
        print(f"  [AI] ❌ Gemini API 오류: {e}")
        return title_en, f"[요약 실패] API 호출 중 오류 발생. (원본: {description_en[:100]}...)"
    except json.JSONDecodeError as e:
        print(f"  [AI] ❌ JSON 파싱 오류: {e}. 응답 텍스트: {response.text[:100]}...")
        return title_en, f"[요약 실패] API 응답 형식 오류. (원본: {description_en[:100]}...)"


# --- 웹사이트별 스크래퍼 ---

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# RSS 피드를 파싱하는 공통 함수
def scrape_rss_feed(feed_url, source_name, category_name):
    """
    지정된 RSS 피드 URL을 파싱하여 기사 목록을 반환합니다.
    """
    articles = []
    print(f"🔍 [{source_name}] (RSS) 크롤링 중... (URL: {feed_url})")
    
    try:
        # feedparser가 User-Agent를 설정하도록 agent 전달
        feed = feedparser.parse(feed_url, agent=HEADERS['User-Agent'])
        
        # 피드 파싱 실패 확인
        if feed.bozo:
            print(f"  ❌ RSS 피드 파싱 오류: {feed.bozo_exception}")
            return []
            
        print(f"  [i] {len(feed.entries)}개 항목 찾음") # 피드 자체가 제공하는 항목 수

        # 피드 자체가 10-15개만 제공할 수 있습니다.
        for entry in feed.entries:
            try:
                title_en = entry.title
                link = entry.link
                
                # 'summary'가 없으면 'description' 사용
                description_en = entry.summary if hasattr(entry, 'summary') else entry.description
                
                # HTML 태그 제거
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)
                
                # 날짜 파싱
                pub_date = entry.published_parsed if hasattr(entry, 'published_parsed') else datetime.now().timetuple()
                date_str = datetime.fromtimestamp(time.mktime(pub_date)).strftime('%Y-%m-%d')

                # RSS 피드는 요약만 하고 바로 반환 (main에서 중복 체크)
                articles.append({
                    'title_en': title_en, # 영어 제목 원본
                    'description_en': description_text, # 영어 설명 원본
                    'url': link,
                    'source': source_name,
                    'category': category_name,
                    'date': date_str,
                })
                
            except Exception as e:
                print(f"  ✗ RSS 항목 파싱 실패: {e}")
            
    except Exception as e:
        print(f"❌ [{source_name}] RSS 크롤링 전체 오류: {e}")
    
    return articles


# Nature News는 HTML 스크래핑이 잘 작동하므로 유지
def scrape_nature_news():
    """Nature 최신 뉴스 크롤링 (제한 없음)"""
    articles = []
    print("🔍 [Nature News] (HTML) 크롤링 중...")
    
    try:
        url = 'https://www.nature.com/nature/articles?type=news'
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        article_items = soup.find_all('article', class_='u-full-height')
        
        for item in article_items:
            try:
                title_elem = item.find('h3')
                link_elem = item.find('a', {'data-track-action': 'view article'})
                
                if title_elem and link_elem:
                    title_en = title_elem.get_text(strip=True)
                    link = link_elem.get('href', '')
                    if link and not link.startswith('http'):
                        link = 'https://www.nature.com' + link
                    
                    desc_elem = item.find('div', class_='c-card__summary')
                    description_en = desc_elem.get_text(strip=True) if desc_elem else ''
                    
                    articles.append({
                        'title_en': title_en,
                        'description_en': description_en,
                        'url': link,
                        'source': 'Nature',
                        'category': 'Science News',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                    })
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            
    except Exception as e:
        print(f"❌ [Nature News] 크롤링 오류: {e}")
    
    return articles

# Nature 자매지도 HTML 스크래핑 유지
def scrape_nature_journal(journal_name, journal_code, category):
    """Nature 자매지 크롤링 (제한 없음)"""
    articles = []
    print(f"🔍 [Nature {journal_name}] (HTML) 크롤링 중...")
    
    try:
        url = f'https://www.nature.com/{journal_code}/news-and-comment'
        response = requests.get(url, headers=HEADERS, timeout=15)
        
        if response.status_code == 404:
            print(f"  [i] 'news-and-comment' 없음, 'research'로 재시도...")
            url = f'https://www.nature.com/{journal_code}/research-articles'
            response = requests.get(url, headers=HEADERS, timeout=15)
            
        soup = BeautifulSoup(response.content, 'html.parser')
        article_items = soup.find_all('article')
        
        if not article_items:
             article_items = soup.find_all('li', class_='app-article-list-row__item')

        for item in article_items:
            try:
                title_elem = item.find('h3')
                link_elem = item.find('a')
                
                if title_elem and link_elem:
                    title_en = title_elem.get_text(strip=True)
                    link = link_elem.get('href', '')
                    
                    if link and not link.startswith('http'):
                        link = 'https://www.nature.com' + link
                    
                    desc_elem = item.find(['p', 'div'], class_=['c-card__summary', 'app-article-list-row__summary'])
                    description_en = desc_elem.get_text(strip=True) if desc_elem else title_en
                    
                    articles.append({
                        'title_en': title_en,
                        'description_en': description_en,
                        'url': link,
                        'source': f'Nature {journal_name}',
                        'category': category,
                        'date': datetime.now().strftime('%Y-%m-%d'),
                    })
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            
    except Exception as e:
        print(f"❌ [Nature {journal_name}] 크롤링 오류: {e}")
    
    return articles

# YouTube 채널 스크립트 크롤링 함수
def scrape_youtube_channel(channel_id, source_name, category_name, seen_urls):
    """
    YouTube 채널 RSS를 확인하고, *새로운* 영상의 스크립트를 가져와 요약합니다.
    """
    articles = []
    print(f"🔍 [{source_name}] (YouTube) 크롤링 중...")
    feed_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    
    try:
        feed = feedparser.parse(feed_url, agent=HEADERS['User-Agent'])
        if feed.bozo:
            print(f"  ❌ RSS 피드 파싱 오류: {feed.bozo_exception}")
            return []
        
        print(f"  [i] 최신 {len(feed.entries)}개 영상 확인...")

        # (참고: YouTube RSS 피드 자체도 15개 정도의 제한이 있습니다)
        for entry in feed.entries:
            try:
                title_en = entry.title
                link = entry.link
                
                if link in seen_urls:
                    # 이미 처리된 영상이면 건너뛰기
                    continue
                
                print(f"  [i] ✨ 새로운 영상 발견: {title_en[:50]}...")
                
                # 영상 설명 (스크립트 실패 시 fallback)
                description_en = entry.summary if hasattr(entry, 'summary') else entry.description
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)
                
                pub_date = entry.published_parsed if hasattr(entry, 'published_parsed') else datetime.now().timetuple()
                date_str = datetime.fromtimestamp(time.mktime(pub_date)).strftime('%Y-%m-%d')
                
                # 스크립트 가져오기 시도
                video_id = link.split('v=')[-1]
                summary_kr = ""
                try:
                    # 영어 스크립트 우선, 없으면 자동 생성된 영어 스크립트
                    transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'a.en'])
                    transcript_text = " ".join([item['text'] for item in transcript_list])
                    print(f"  [i] 스크립트 로드 완료 (약 {len(transcript_text)}자)")
                    
                    # Gemini 요약 (스크립트 기반)
                    title_kr, summary_kr = get_gemini_summary(title_en, transcript_text)

                except Exception as e:
                    print(f"  [i] ⚠️ 스크립트를 가져올 수 없음: {e}. 영상 설명을 대신 요약합니다.")
                    # 스크립트 실패 시, 영상 설명이라도 요약
                    title_kr, summary_kr = get_gemini_summary(title_en, description_text)

                articles.append({
                    'title': title_kr,
                    'title_en': title_en,
                    'url': link,
                    'source': source_name,
                    'category': category_name,
                    'date': date_str,
                    'summary_kr': summary_kr
                })
                print(f"  ✓ {title_en[:50]}... -> {title_kr[:30]}...")
                
            except Exception as e:
                print(f"  ✗ YouTube 항목 파싱 실패: {e}")
            time.sleep(1) # API 딜레이
    
    except Exception as e:
        print(f"❌ [{source_name}] YouTube 크롤링 전체 오류: {e}")
    
    return articles


def main():
    """메인 실행 함수"""
    print("\n" + "="*60)
    print("📰 일일 읽을거리 자동 수집 및 요약 시작")
    # 여기가 에러났던 부분
    print(f"🕐 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")
    
    # 크롤링한 기사(요약 전)를 담을 리스트
    all_articles_to_check = []
    
    # HTML 크롤링 대신 RSS 함수로 교체
    all_articles_to_check.extend(scrape_rss_feed('https://www.science.org/rss/news_current.xml', 'Science', 'Science News'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.cell.com/rss/cell-news.xml', 'Cell', 'Science News'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.thetransmitter.org/feed/', 'The Transmitter', 'Neuroscience'))

    # Nature 계열은 HTML로 유지
    all_articles_to_check.extend(scrape_nature_news())
    all_articles_to_check.extend(scrape_nature_journal("Neuroscience", "neuro", "Neuroscience"))
    all_articles_to_check.extend(scrape_nature_journal("Drug Discovery", "nrd", "Industry News"))
    all_articles_to_check.extend(scrape_nature_journal("Medicine", "nm", "Medical News"))
    
    # 로직 변경: seen_urls와 기존 기사 목록을 먼저 로드
    seen_urls = set()
    final_article_list = [] # 최종 저장될 목록 (기존 7일치 + 신규)
    
    try:
        with open('articles.json', 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            # 최근 7일간의 기사만 URL 체크 및 최종 목록에 미리 추가
            for old_article in old_data.get('articles', []):
                try:
                    article_date = datetime.strptime(old_article.get('date', '1970-01-01'), '%Y-%m-%d')
                    if (datetime.now() - article_date).days <= 7:
                        seen_urls.add(old_article['url'])
                        final_article_list.append(old_article) # 기존 7일치 기사
                except ValueError:
                    continue # 날짜 형식이 다르면 무시
        print(f"[i] 기존 {len(seen_urls)}개의 URL (최근 7일)을 로드했습니다. 새로운 기사만 추가/요약합니다.")
    except FileNotFoundError:
        print("[i] 'articles.json' 파일이 없습니다. 새로 생성합니다.")
    
    
    new_articles = [] # 새로 요약한 기사만 담을 리스트
    existing_articles_count = 0
    
    # 1. RSS/HTML로 수집된 기사들 처리
    for article_data in all_articles_to_check:
        if article_data['url'] not in seen_urls:
            # 새로운 기사 -> Gemini 요약
            print(f"  [i] ✨ 새로운 기사 발견: {article_data['title_en'][:50]}...")
            seen_urls.add(article_data['url'])
            
            title_kr, summary_kr = get_gemini_summary(article_data['title_en'], article_data['description_en'])
            
            # 요약된 정보로 article 객체 완성
            article_data['title'] = title_kr
            article_data['summary_kr'] = summary_kr
            
            # 원본 영어 정보 추가 (디버깅 또는 향후 사용)
            article_data['title_en'] = article_data['title_en']
            
            # 원본 영어 설명은 용량이 크므로 삭제
            del article_data['description_en']
            
            new_articles.append(article_data)
            time.sleep(1) # API 딜레이
        else:
            existing_articles_count += 1
    
    print(f"\n[i] {len(new_articles)}개의 새로운 (RSS/HTML) 기사를 요약했습니다. (중복/기존 기사 {existing_articles_count}개 제외)")
    
    # 2. YouTube 채널 확인 (seen_urls 전달)
    # 채널 ID: UC-SgS0O2-j9p1Oa3mXgXFrw
    new_youtube_videos = scrape_youtube_channel(
        'UC-SgS0O2-j9p1Oa3mXgXFrw', 
        'B_ZCF YouTube', 
        'Video', 
        seen_urls # seen_urls를 전달하여 중복 확인
    )
    new_articles.extend(new_youtube_videos)
    
    # 3. 기존 데이터와 새로운 데이터를 합침
    # 1. 기존 7일치 데이터 (final_article_list에 이미 있음)
    # 2. 새로운 기사 추가
    final_article_list.extend(new_articles)
    
    # 4. 합친 목록에서 다시 중복 제거 (혹시 모를 경우 대비)
    final_seen_urls = set()
    deduplicated_list = []
    for article in final_article_list:
        if article.get('url') not in final_seen_urls:
            if article.get('url'): # URL이 없는 비정상 데이터 방지
                final_seen_urls.add(article['url'])
                deduplicated_list.append(article)

    # 5. 날짜순 정렬 (최신순)
    deduplicated_list.sort(key=lambda x: x.get('date', '1970-01-01'), reverse=True)
    
    # JSON 파일로 저장
    output = {
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'articles': deduplicated_list
    }
    
    with open('articles.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print("\n" + "="*60)
    print(f"✅ 완료! 총 {len(deduplicated_list)}개 항목 저장 (최근 7일 + 신규)")
    print(f"📁 articles.json 파일 업데이트됨")
    print("="*60 + "\n")
    
    sources = {}
    for article in deduplicated_list:
        source = article['source']
        sources[source] = sources.get(source, 0) + 1
    
    print("📊 소스별 수집 현황 (최근 7일 + 신규):")
    for source, count in sorted(sources.items()):
        print(f"  • {source}: {count}개")


if __name__ == '__main__':
    main()

