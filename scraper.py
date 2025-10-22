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

# --- AI 요약 기능 (JSON 포맷으로 수정) ---

def get_gemini_summary(title_en, description_en):
    """
    Gemini API를 호출하여 제목과 설명을 한글로 번역 및 요약합니다.
    결과를 JSON 형식으로 받습니다.
    """
    print(f"  [AI] '{title_en[:30]}...' 번역/요약 요청 중...")
    
    try:
        # API 키는 GitHub Actions Secrets에서 환경 변수로 가져옵니다.
        api_key = os.environ.get('GEMINI_API_KEY')
        
        if not api_key:
            print("  [AI] ❌ GEMINI_API_KEY가 설정되지 않았습니다. 요약을 건너뜁니다.")
            return title_en, f"[요약 실패] API 키가 없습니다. (원본: {description_en[:100]}...)"

        genai.configure(api_key=api_key)
        
        # JSON 응답을 위한 설정
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
        
        response = model.generate_content(prompt)
        
        # JSON 파싱
        data = json.loads(response.text)
        
        title_kr = data.get('title_kr', title_en)
        summary_kr = data.get('summary_kr', f"[요약 실패] API 응답 오류. (원본: {description_en[:100]}...)")
        
        print(f"  [AI] ✓ 요약 완료: {title_kr[:30]}...")
        return title_kr, summary_kr
    
    except Exception as e:
        print(f"  [AI] ❌ Gemini API 오류: {e}")
        # 오류 발생 시 영어 원본 반환
        return title_en, f"[요약 실패] API 호출 중 오류 발생. (원본: {description_en[:100]}...)"
    except json.JSONDecodeError as e:
        print(f"  [AI] ❌ JSON 파싱 오류: {e}. 응답 텍스트: {response.text[:100]}...")
        return title_en, f"[요약 실패] API 응답 형식 오류. (원본: {description_en[:100]}...)"


# --- 웹사이트별 스크래퍼 (기사 수 제한 제거) ---

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def scrape_nature_news():
    """Nature 최신 뉴스 크롤링 (제한 없음)"""
    articles = []
    print("🔍 [Nature News] 크롤링 중...")
    
    try:
        url = 'https://www.nature.com/nature/articles?type=news'
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        # [수정] 기사 수 제한 제거
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
                    
                    # [수정] title_kr, summary_kr 반환
                    title_kr, summary_kr = get_gemini_summary(title_en, description_en)
                    
                    articles.append({
                        'title': title_kr,       # 한국어 제목
                        'title_en': title_en,    # (참고용) 영어 원본 제목
                        'url': link,
                        'source': 'Nature',
                        'category': 'Science News',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': summary_kr
                    })
                    print(f"  ✓ {title_en[:50]}... -> {title_kr[:30]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            time.sleep(1) # API 호출 딜레이
            
    except Exception as e:
        print(f"❌ [Nature News] 크롤링 오류: {e}")
    
    return articles

def scrape_science_news():
    """Science.org 최신 뉴스 크롤링 (제한 없음)"""
    articles = []
    print("🔍 [Science News] 크롤링 중...")
    
    try:
        url = 'https://www.science.org/news'
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # [수정] 기사 수 제한 제거
        article_items = soup.select('div.card-data')
        
        for item in article_items:
            try:
                title_elem = item.find('h2', class_='card-title')
                link_elem = item.find('a')
                
                if title_elem and link_elem:
                    title_en = title_elem.get_text(strip=True)
                    link = link_elem.get('href', '')
                    if link and not link.startswith('http'):
                        link = 'https://www.science.org' + link
                    
                    desc_elem = item.find('p', class_='card-summary')
                    description_en = desc_elem.get_text(strip=True) if desc_elem else title_en
                    
                    title_kr, summary_kr = get_gemini_summary(title_en, description_en)

                    articles.append({
                        'title': title_kr,
                        'title_en': title_en,
                        'url': link,
                        'source': 'Science',
                        'category': 'Science News',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': summary_kr
                    })
                    print(f"  ✓ {title_en[:50]}... -> {title_kr[:30]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            time.sleep(1)
            
    except Exception as e:
        print(f"❌ [Science News] 크롤링 오류: {e}")
    
    return articles

def scrape_cell_news():
    """Cell.com 최신 뉴스 (RSS 피드 사용) (제한 없음)"""
    articles = []
    print("🔍 [Cell News] (RSS) 크롤링 중...")
    
    try:
        rss_url = 'https://www.cell.com/rss/cell-news.xml'
        feed = feedparser.parse(rss_url)
        
        # [수정] 기사 수 제한 제거
        for entry in feed.entries:
            try:
                title_en = entry.title
                link = entry.link
                description_en = entry.summary
                
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)
                
                title_kr, summary_kr = get_gemini_summary(title_en, description_text)
                
                pub_date = entry.published_parsed if hasattr(entry, 'published_parsed') else datetime.now().timetuple()
                date_str = datetime.fromtimestamp(time.mktime(pub_date)).strftime('%Y-%m-%d')

                articles.append({
                    'title': title_kr,
                    'title_en': title_en,
                    'url': link,
                    'source': 'Cell',
                    'category': 'Science News',
                    'date': date_str,
                    'summary_kr': summary_kr
                })
                print(f"  ✓ {title_en[:50]}... -> {title_kr[:30]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            time.sleep(1)
            
    except Exception as e:
        print(f"❌ [Cell News] 크롤링 오류: {e}")
    
    return articles

def scrape_thetransmitter():
    """[수정] The Transmitter (신경과학 전문 뉴스) 크롤링 (제한 없음)"""
    articles = []
    print("🔍 [The Transmitter] 크롤링 중...")
    
    try:
        url = 'https://www.thetransmitter.org/news/'
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # [수정] 선택자 변경 및 기사 수 제한 제거
        article_items = soup.select('div.hp-post-card')
        
        if not article_items:
             print("  [i] 'hp-post-card' 선택자 없음. 'article'로 재시도...")
             article_items = soup.find_all('article')
             
        print(f"  [i] {len(article_items)}개 기사 카드 찾음")

        for item in article_items:
            try:
                # [수정] 새로운 선택자
                title_elem_a = item.select_one('h3.hp-post-card__title a')
                
                # 대체 선택자 (기존 방식)
                if not title_elem_a:
                     title_elem_a = item.find('h3').find('a') if item.find('h3') else None

                if title_elem_a:
                    title_en = title_elem_a.get_text(strip=True)
                    link = title_elem_a.get('href', '')
                    
                    if link and not link.startswith('http'):
                        link = 'https://www.thetransmitter.org' + link
                    
                    # [수정] 새로운 선택자
                    desc_elem = item.select_one('p.hp-post-card__excerpt')
                    # 대체 선택자 (기존 방식)
                    if not desc_elem:
                        desc_elem = item.find('p')
                        
                    description_en = desc_elem.get_text(strip=True) if desc_elem else title_en
                    
                    title_kr, summary_kr = get_gemini_summary(title_en, description_en)
                    
                    articles.append({
                        'title': title_kr,
                        'title_en': title_en,
                        'url': link,
                        'source': 'The Transmitter',
                        'category': 'Neuroscience',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': summary_kr
                    })
                    print(f"  ✓ {title_en[:50]}... -> {title_kr[:30]}...")
                else:
                    print("  ✗ 항목에서 제목/링크를 찾을 수 없음")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            time.sleep(1)
            
    except Exception as e:
        print(f"❌ [The Transmitter] 크롤링 오류: {e}")
    
    return articles

def scrape_nature_journal(journal_name, journal_code, category):
    """Nature 자매지 크롤링 (제한 없음)"""
    articles = []
    print(f"🔍 [Nature {journal_name}] 크롤링 중...")
    
    try:
        url = f'https://www.nature.com/{journal_code}/news-and-comment'
        response = requests.get(url, headers=HEADERS, timeout=15)
        
        if response.status_code == 404:
            print(f"  [i] 'news-and-comment' 없음, 'research'로 재시도...")
            url = f'https://www.nature.com/{journal_code}/research-articles'
            response = requests.get(url, headers=HEADERS, timeout=15)
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # [수정] 기사 수 제한 제거
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
    
    # 요청하신 사이트 목록 크롤링
    all_articles.extend(scrape_nature_news())
    all_articles.extend(scrape_science_news())
    all_articles.extend(scrape_cell_news())
    all_articles.extend(scrape_thetransmitter())
    all_articles.extend(scrape_nature_journal("Neuroscience", "neuro", "Neuroscience"))
    all_articles.extend(scrape_nature_journal("Drug Discovery", "nrd", "Industry News"))
    all_articles.extend(scrape_nature_journal("Medicine", "nm", "Medical News"))
    
    # 중복 제거 (URL 기준)
    seen_urls = set()
    unique_articles = []
    
    # 이전에 로드된 데이터를 읽어와서 중복 체크에 활용 (선택 사항)
    try:
        with open('articles.json', 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            for old_article in old_data.get('articles', []):
                seen_urls.add(old_article['url'])
        print(f"[i] 기존 {len(seen_urls)}개의 URL을 로드했습니다. 새로운 기사만 추가합니다.")
    except FileNotFoundError:
        print("[i] 'articles.json' 파일이 없습니다. 새로 생성합니다.")
    
    
    new_article_count = 0
    for article in all_articles:
        if article['url'] not in seen_urls:
            seen_urls.add(article['url'])
            unique_articles.append(article)
            new_article_count += 1
    
    print(f"\n[i] {new_article_count}개의 새로운 기사를 찾았습니다.")
    
    # 기존 데이터와 새로운 데이터를 합침 (선택 사항: 여기서는 새 기사만 저장)
    # 여기서는 매번 새로 덮어쓰는 방식을 유지하되, 중복 제거된 전체 목록을 사용
    # 날짜순 정렬 (최신순)
    unique_articles.sort(key=lambda x: x['date'], reverse=True)
    
    # JSON 파일로 저장
    output = {
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'articles': unique_articles # 모든 기사 (중복 제거됨)
    }
    
    with open('articles.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print("\n" + "="*60)
    print(f"✅ 완료! 총 {len(unique_articles)}개 항목 수집 및 요약")
    print(f"📁 articles.json 파일 업데이트됨")
    print("="*60 + "\n")
    
    sources = {}
    for article in unique_articles:
        source = article['source']
        sources[source] = sources.get(source, 0) + 1
    
    print("📊 소스별 수집 현황:")
    for source, count in sources.items():
        print(f"  • {source}: {count}개")


if __name__ == '__main__':
    main()

