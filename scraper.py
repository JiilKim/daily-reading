#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
지정된 HTML 및 RSS 피드에서 뉴스/논문/영상을 크롤링하고
Gemini API를 이용해 번역/요약한 후
articles.json을 업데이트합니다.
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import feedparser
import time
import os
import google.generativeai as genai
import google.generativeai.types as genai_types
# YouTube 스크립트 API 임포트
from youtube_transcript_api import YouTubeTranscriptApi
# URL 파싱을 위한 라이브러리
from urllib.parse import urljoin

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
        # [수정] 'BlockedPromptError'가 아닌 'BlockedPromptException'으로 수정
        if isinstance(e, genai_types.generation_types.BlockedPromptException):
             print(f"  [AI] ❌ Gemini API - 콘텐츠 차단 오류: {e}")
             return title_en, "[요약 실패] API가 콘텐츠를 차단했습니다."
        
        # 그 외 다른 API 오류
        print(f"  [AI] ❌ Gemini API 오류: {e}")
        # API 할당량 초과(ResourceExhausted) 등의 오류를 여기서 잡음
        return title_en, f"[요약 실패] API 호출 중 오류 발생. (원본: {description_en[:100]}...)"
    
    except json.JSONDecodeError as e:
        print(f"  [AI] ❌ JSON 파싱 오류: {e}. 응답 텍스트: {response.text[:100]}...")
        return title_en, f"[요약 실패] API 응답 형식 오류. (원본: {description_en[:100]}...)"


# --- 웹사이트별 스크래퍼 ---

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# 1. HTML 페이지 스크래핑 함수 (Nature News)
def scrape_nature_news_html():
    """<기사> https://www.nature.com/nature/articles?type=news"""
    articles = []
    base_url = 'https://www.nature.com'
    url = f'{base_url}/nature/articles?type=news'
    print(f"🔍 [Nature News] (HTML) 크롤링 중...: {url}")
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        article_items = soup.find_all('li', class_='app-article-list__item')
        print(f"  [i] {len(article_items)}개 잠재적 기사 항목 찾음 (li.app-article-list__item)")

        if not article_items:
             print("  [i] 'li.app-article-list__item' 없음. 'article[data-track-component=results-article]'로 재시도...")
             article_items = soup.select('article[data-track-component="results-article"]')

        
        for item in article_items:
            try:
                article_tag = item.find('article')
                if not article_tag:
                    article_tag = item

                title_elem = article_tag.find('h3', {'data-test': 'article-title'}) or article_tag.find('h3')
                link_elem = article_tag.find('a', {'data-track-action': 'view article'}) or article_tag.find('a', href=True)
                
                if title_elem and link_elem:
                    title_en = title_elem.get_text(strip=True)
                    link = urljoin(base_url, link_elem.get('href', ''))
                    
                    desc_elem = article_tag.find('div', {'data-test': 'article-description'}) or article_tag.find('div', class_='c-card__summary')
                    description_en = desc_elem.get_text(strip=True) if desc_elem else ''
                    
                    image_url = None
                    img_elem = article_tag.find('img')
                    if img_elem:
                        image_url = img_elem.get('data-src') or img_elem.get('src')
                        if image_url:
                            image_url = urljoin(base_url, image_url)
                    
                    articles.append({
                        'title_en': title_en,
                        'description_en': description_en,
                        'url': link,
                        'source': 'Nature',
                        'category': 'News',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'image_url': image_url
                    })
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            
    except Exception as e:
        print(f"❌ [Nature News] 크롤링 오류: {e}")
    
    return articles

# 2. HTML 페이지 스크래핑 함수 (Science News)
def scrape_science_news_html():
    """<기사> https://www.science.org/news/all-news"""
    articles = []
    base_url = 'https://www.science.org'
    url = f'{base_url}/news/all-news'
    print(f"🔍 [Science News] (HTML) 크롤링 중...: {url}")
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        list_container = soup.find('div', {'data-type': 'search-result-list'})
        if list_container:
            article_items = list_container.find_all('article', class_='card')
            print(f"  [i] {len(article_items)}개 잠재적 기사 항목 찾음 (div[data-type=search-result-list] article.card)")
        else:
            print("  [i] 'search-result-list' 컨테이너 없음. 'article.card'로 재시도...")
            article_items = soup.select('article.card')
            
        if not article_items:
             print("  [i] 'article.card' 없음. 'article[class*=\"card\"]'로 재시도...")
             article_items = soup.select('article[class*="card"]')

        
        for item in article_items:
            try:
                title_elem = item.find('h3', class_='card-title') or item.find(['h2', 'h3'])
                link_elem = item.find('a', href=True)
                
                title_en = ""
                if title_elem:
                    title_en = title_elem.get_text(strip=True)
                    link_elem_inner = title_elem.find('a', href=True)
                    if link_elem_inner:
                        link_elem = link_elem_inner
                
                if not link_elem or 'href' not in link_elem.attrs:
                    link_elem = item.find('a', href=True)

                if not title_en or not link_elem:
                    continue

                link = urljoin(base_url, link_elem.get('href', ''))
                
                desc_elem = item.find('div', class_='card-text') or item.find('p')
                description_en = desc_elem.get_text(strip=True) if desc_elem else title_en
                
                image_url = None
                img_elem = item.find('img')
                if img_elem:
                    image_url = img_elem.get('data-src') or img_elem.get('src')
                    if image_url:
                        image_url = urljoin(base_url, image_url)

                articles.append({
                    'title_en': title_en,
                    'description_en': description_en,
                    'url': link,
                    'source': 'Science',
                    'category': 'News',
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'image_url': image_url
                })
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            
    except Exception as e:
        print(f"❌ [Science News] 크롤링 오류: {e}")
    
    return articles

# 3. RSS 피드를 파싱하는 공통 함수
def scrape_rss_feed(feed_url, source_name, category_name):
    """
    지정된 RSS 피드 URL을 파싱하여 기사 목록을 반환합니다.
    (Transmitter 및 모든 논문 사이트에서 사용)
    """
    articles = []
    print(f"🔍 [{source_name}] (RSS) 크롤링 중... (URL: {feed_url})")
    
    try:
        feed = feedparser.parse(feed_url, agent=HEADERS['User-Agent'])
        
        if feed.bozo:
            print(f"  ❌ RSS 피드 파싱 오류: {feed.bozo_exception}")
            return []
            
        print(f"  [i] {len(feed.entries)}개 항목 찾음")

        for entry in feed.entries:
            try:
                title_en = entry.title
                link = entry.link
                description_en = entry.summary if hasattr(entry, 'summary') else (entry.description if hasattr(entry, 'description') else title_en)
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)
                pub_date = entry.published_parsed if hasattr(entry, 'published_parsed') else datetime.now().timetuple()
                date_str = datetime.fromtimestamp(time.mktime(pub_date)).strftime('%Y-%m-%d')
                
                image_url = None
                if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0]['url']
                elif hasattr(entry, 'media_content') and entry.media_content:
                    image_url = entry.media_content[0]['url']
                
                if not image_url:
                    desc_soup = BeautifulSoup(description_en, 'html.parser')
                    img_tag = desc_soup.find('img')
                    if img_tag:
                        image_url = img_tag.get('src')

                articles.append({
                    'title_en': title_en,
                    'description_en': description_text,
                    'url': link,
                    'source': source_name,
                    'category': category_name,
                    'date': date_str,
                    'image_url': image_url
                })
                
            except Exception as e:
                print(f"  ✗ RSS 항목 파싱 실패: {e}")
            
    except Exception as e:
        print(f"❌ [{source_name}] RSS 크롤링 전체 오류: {e}")
    
    return articles

# 4. YouTube 채널 스크립트 크롤링 함수
def scrape_youtube_channel(channel_id, source_name, category_name, seen_urls):
    """
    YouTube 채널 RSS를 확인하고, *새로운* 영상의 스크립트를 가져와 요약합니다.
    (requests를 사용하여 차단 우회)
    """
    articles = []
    print(f"🔍 [{source_name}] (YouTube) 크롤링 중...")
    feed_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    
    try:
        response = requests.get(feed_url, headers=HEADERS, timeout=15)
        content_type = response.headers.get('Content-Type', '')
        
        if 'application/xml' not in content_type and 'application/atom+xml' not in content_type:
            print(f"  ❌ YouTube RSS가 XML이 아닌 응답을 반환했습니다. (Content-Type: {content_type})")
            return []
            
        feed = feedparser.parse(response.content)

        if feed.bozo:
            print(f"  ❌ RSS 피드 파싱 오류: {str(feed.bozo_exception)}")
            return []
        
        print(f"  [i] 최신 {len(feed.entries)}개 영상 확인...")

        for entry in feed.entries:
            try:
                title_en = entry.title
                link = entry.link
                
                if link in seen_urls:
                    continue
                
                print(f"  [i] ✨ 새로운 영상 발견: {title_en[:50]}...")
                
                description_en = entry.summary if hasattr(entry, 'summary') else entry.description
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)
                pub_date = entry.published_parsed if hasattr(entry, 'published_parsed') else datetime.now().timetuple()
                date_str = datetime.fromtimestamp(time.mktime(pub_date)).strftime('%Y-%m-%d')
                
                image_url = None
                if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0]['url'].replace('default.jpg', 'hqdefault.jpg')
                
                video_id = link.split('v=')[-1]
                summary_kr = ""
                try:
                    transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'a.en'])
                    transcript_text = " ".join([item['text'] for item in transcript_list])
                    print(f"  [i] 스크립트 로드 완료 (약 {len(transcript_text)}자)")
                    
                    title_kr, summary_kr = get_gemini_summary(title_en, transcript_text)

                except Exception as e:
                    print(f"  [i] ⚠️ 스크립트를 가져올 수 없음: {e}. 영상 설명을 대신 요약합니다.")
                    title_kr, summary_kr = get_gemini_summary(title_en, description_text)

                articles.append({
                    'title': title_kr,
                    'title_en': title_en,
                    'url': link,
                    'source': source_name,
                    'category': category_name,
                    'date': date_str,
                    'summary_kr': summary_kr,
                    'image_url': image_url
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
    print(f"🕐 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")
    
    all_articles_to_check = []
    
    # <기사> (HTML)
    all_articles_to_check.extend(scrape_nature_news_html())
    all_articles_to_check.extend(scrape_science_news_html())
    
    # <기사> (RSS)
    all_articles_to_check.extend(scrape_rss_feed('https://www.thetransmitter.org/feed/', 'The Transmitter', 'Neuroscience'))

    # <논문> (RSS)
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/nature/research-articles.rss', 'Nature (Paper)', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science', 'Science (Paper)', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.cell.com/cell/current.rss', 'Cell', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/neuro/current_issue/rss', 'Nature Neuroscience', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/nm/current_issue/rss', 'Nature Medicine', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/nrd/current_issue/rss', 'Nature Drug Discovery', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/nbt/current_issue/rss', 'Nature Biotechnology', 'Paper'))
    
    seen_urls = set()
    final_article_list = [] 
    
    try:
        with open('articles.json', 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            for old_article in old_data.get('articles', []):
                try:
                    article_date = datetime.strptime(old_article.get('date', '1970-01-01'), '%Y-%m-%d')
                    if (datetime.now() - article_date).days <= 7:
                        if old_article.get('url'):
                            seen_urls.add(old_article['url'])
                            final_article_list.append(old_article)
                except ValueError:
                    continue
        print(f"[i] 기존 {len(seen_urls)}개의 URL (최근 7일)을 로드했습니다. 새로운 기사만 추가/요약합니다.")
    except FileNotFoundError:
        print("[i] 'articles.json' 파일이 없습니다. 새로 생성합니다.")
    
    
    new_articles = [] 
    existing_articles_count = 0
    
    # 1. RSS/HTML로 수집된 기사들 요약 처리
    
    # [수정] API 할당량 초과를 막기 위해 한 번에 처리할 새 기사 수 제한
    new_article_count = 0
    MAX_NEW_ARTICLES_PER_RUN = 50 # 하루 250개 한도보다 훨씬 적게 설정
    
    for article_data in all_articles_to_check:
        
        # [수정] 새 기사 처리 개수 제한
        if new_article_count >= MAX_NEW_ARTICLES_PER_RUN:
            print(f"  [i] API 할당량을 위해 최대 {MAX_NEW_ARTICLES_PER_RUN}개 까지만 요약합니다. 나머지는 다음 실행으로 넘어갑니다.")
            break # 새 기사 처리를 중단
            
        if article_data.get('url') and article_data['url'] not in seen_urls:
            print(f"  [i] ✨ 새로운 기사 발견 ({new_article_count + 1}/{MAX_NEW_ARTICLES_PER_RUN}): {article_data['title_en'][:50]}...")
            seen_urls.add(article_data['url'])
            
            title_kr, summary_kr = get_gemini_summary(article_data['title_en'], article_data['description_en'])
            
            # API 오류가 발생하지 않았을 때만 리스트에 추가 (요약 실패 시에도 추가는 됨)
            article_data['title'] = title_kr
            article_data['summary_kr'] = summary_kr
            
            if 'description_en' in article_data:
                del article_data['description_en']
            
            new_articles.append(article_data)
            new_article_count += 1 # [수정] 처리한 새 기사 카운트 증가
            time.sleep(1) # API 딜레이
            
        elif article_data.get('url'):
            existing_articles_count += 1
    
    print(f"\n[i] {len(new_articles)}개의 새로운 (RSS/HTML) 기사를 요약했습니다. (중복/기존 기사 {existing_articles_count}개 제외)")
    
    # 2. YouTube 채널 확인 (seen_urls 전달)
    # [수정] YouTube는 새 기사 카운트와 별도로 실행 (영상은 보통 하루에 1~2개이므로)
    new_youtube_videos = scrape_youtube_channel(
        'UC-SgS0O2-j9p1Oa3mXgXFrw', 
        'B_ZCF YouTube', 
        'Video', 
        seen_urls
    )
    new_articles.extend(new_youtube_videos)
    
    # 3. 기존 데이터와 새로운 데이터를 합침
    final_article_list.extend(new_articles)
    
    # 4. 합친 목록에서 다시 중복 제거
    final_seen_urls = set()
    deduplicated_list = []
    for article in final_article_list:
        if article.get('url') not in final_seen_urls:
            if article.get('url'):
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
        source = article.get('source', 'Unknown')
        sources[source] = sources.get(source, 0) + 1
    
    print("📊 소스별 수집 현황 (최근 7일 + 신규):")
    for source, count in sorted(sources.items()):
        print(f"  • {source}: {count}개")


if __name__ == '__main__':
    main()

