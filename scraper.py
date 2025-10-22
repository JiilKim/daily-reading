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
from datetime import datetime
import feedparser
import time
import os
import google.generativeai as genai
import google.generativeai.types as genai_types

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
        print(f"  [AI] ❌ Gemini API 오류: {e}")
        return title_en, f"[요약 실패] API 호출 중 오류 발생. (원본: {description_en[:100]}...)"
    except json.JSONDecodeError as e:
        print(f"  [AI] ❌ JSON 파싱 오류: {e}. 응답 텍스트: {response.text[:100]}...")
        return title_en, f"[요약 실패] API 응답 형식 오류. (원본: {description_en[:100]}...)"


# --- 웹사이트별 스크래퍼 ---

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# [수정] RSS 피드를 파싱하는 공통 함수
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
            
        print(f"  [i] {len(feed.entries)}개 항목 찾음")

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
                print(f"  ✗ RSS 항목 파싱 실패: {e}")
            time.sleep(1) # API 딜레이
            
    except Exception as e:
        print(f"❌ [{source_name}] RSS 크롤링 전체 오류: {e}")
    
    return articles


# [유지] Nature News는 HTML 스크래핑이 잘 작동하므로 유지
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
                    
                    title_kr, summary_kr = get_gemini_summary(title_en, description_en)
                    
                    articles.append({
                        'title': title_kr,
                        'title_en': title_en,
                        'url': link,
                        'source': 'Nature',
                        'category': 'Science News',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': summary_kr
                    })
                    print(f"  ✓ {title_en[:50]}... -> {title_kr[:30]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            time.sleep(1)
            
    except Exception as e:
        print(f"❌ [Nature News] 크롤링 오류: {e}")
    
    return articles

# [유지] Nature 자매지도 HTML 스크래핑 유지
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
                    
                    title_kr, summary_kr = get_gemini_summary(title_en, description_en)
                    
                    articles.append({
                        'title': title_kr,
                        'title_en': title_en,
                        'url': link,
                        'source': f'Nature {journal_name}',
                        'category': category,
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': summary_kr
                    })
                    print(f"  ✓ {title_en[:50]}... -> {title_kr[:30]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            time.sleep(1)
            
    except Exception as e:
        print(f"❌ [Nature {journal_name}] 크롤링 오류: {e}")
    
    return articles


def main():
    """메인 실행 함수"""
    print("\n" + "="*60)
    print("📰 일일 읽을거리 자동 수집 및 요약 시작")
    print(f"🕐 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")
    
    all_articles = []
    
    # [수정] HTML 크롤링 대신 RSS 함수로 교체
    all_articles.extend(scrape_rss_feed('https://www.science.org/rss/news_current.xml', 'Science', 'Science News'))
    all_articles.extend(scrape_rss_feed('https://www.cell.com/rss/cell-news.xml', 'Cell', 'Science News'))
    all_articles.extend(scrape_rss_feed('https://www.thetransmitter.org/feed/', 'The Transmitter', 'Neuroscience'))

    # Nature 계열은 HTML로 유지
    all_articles.extend(scrape_nature_news())
    all_articles.extend(scrape_nature_journal("Neuroscience", "neuro", "Neuroscience"))
    all_articles.extend(scrape_nature_journal("Drug Discovery", "nrd", "Industry News"))
    all_articles.extend(scrape_nature_journal("Medicine", "nm", "Medical News"))
    
    # 중복 제거 (URL 기준)
    seen_urls = set()
    unique_articles = []
    
    # [개선] 기존 데이터를 로드하여 중복 URL을 미리 확보
    try:
        with open('articles.json', 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            # 최근 7일간의 기사만 URL 체크 (너무 오래된 기사까지 다루면 seen_urls가 너무 커짐)
            for old_article in old_data.get('articles', []):
                try:
                    article_date = datetime.strptime(old_article.get('date', '1970-01-01'), '%Y-%m-%d')
                    if (datetime.now() - article_date).days <= 7:
                        seen_urls.add(old_article['url'])
                except ValueError:
                    continue # 날짜 형식이 다르면 무시
        print(f"[i] 기존 {len(seen_urls)}개의 URL (최근 7일)을 로드했습니다. 새로운 기사만 추가/요약합니다.")
    except FileNotFoundError:
        print("[i] 'articles.json' 파일이 없습니다. 새로 생성합니다.")
    
    
    new_articles = []
    existing_articles_count = 0
    
    for article in all_articles:
        if article['url'] not in seen_urls:
            seen_urls.add(article['url'])
            new_articles.append(article)
        else:
            existing_articles_count += 1
    
    print(f"\n[i] {len(new_articles)}개의 새로운 기사를 찾았습니다. (중복/기존 기사 {existing_articles_count}개 제외)")
    
    # [개선] 기존 데이터와 새로운 데이터를 합침
    # 1. 기존 데이터 로드 (최근 7일치만)
    final_article_list = []
    if 'old_data' in locals():
        for old_article in old_data.get('articles', []):
             try:
                article_date = datetime.strptime(old_article.get('date', '1970-01-01'), '%Y-%m-%d')
                if (datetime.now() - article_date).days <= 7:
                    final_article_list.append(old_article)
             except ValueError:
                continue
    
    # 2. 새로운 기사 추가
    final_article_list.extend(new_articles)
    
    # 3. 합친 목록에서 다시 중복 제거 (혹시 모를 경우 대비)
    final_seen_urls = set()
    deduplicated_list = []
    for article in final_article_list:
        if article['url'] not in final_seen_urls:
            final_seen_urls.add(article['url'])
            deduplicated_list.append(article)

    # 4. 날짜순 정렬 (최신순)
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

