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

# --- AI 요약 기능 ---

def get_gemini_summary(title, description_en):
    """
    Gemini API를 호출하여 제목과 설명을 한글로 번역 및 요약합니다.
    """
    print(f"  [AI] '{title[:30]}...' 요약 요청 중...")
    
    try:
        # API 키는 GitHub Actions Secrets에서 환경 변수로 가져옵니다.
        api_key = os.environ.get('GEMINI_API_KEY')
        
        if not api_key:
            print("  [AI] ❌ GEMINI_API_KEY가 설정되지 않았습니다. 요약을 건너뜁니다.")
            return f"[요약 실패] API 키가 없습니다. (원본: {description_en[:100]}...)"

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')
        
        prompt = f"""
        당신은 전문 과학 뉴스 편집자입니다.
        아래의 영어 기사 제목과 설명을 바탕으로, 한국어로 3~4문장의 핵심 요약본을 작성해 주세요.
        
        - 제목: {title}
        - 설명: {description_en}
        
        규칙:
        1. 전체 내용을 한국어로 번역한 후, 자연스러운 3~4문장으로 요약합니다.
        2. 가장 중요한 핵심 내용만 전달합니다.
        3. 친절한 말투가 아닌, 전문적이고 간결한 뉴스체로 작성합니다.
        """
        
        response = model.generate_content(prompt)
        
        summary_kr = response.text.strip()
        print(f"  [AI] ✓ 요약 완료")
        return summary_kr
    
    except Exception as e:
        print(f"  [AI] ❌ Gemini API 오류: {e}")
        return f"[요약 실패] API 호출 중 오류 발생. (원본: {description_en[:100]}...)"

# --- 웹사이트별 스크래퍼 ---

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def scrape_nature_news():
    """Nature 최신 뉴스 크롤링"""
    articles = []
    print("🔍 [Nature News] 크롤링 중...")
    
    try:
        url = 'https://www.nature.com/nature/articles?type=news'
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        article_items = soup.find_all('article', class_='u-full-height')[:5]
        
        for item in article_items:
            try:
                title_elem = item.find('h3')
                link_elem = item.find('a', {'data-track-action': 'view article'})
                
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    link = link_elem.get('href', '')
                    if link and not link.startswith('http'):
                        link = 'https://www.nature.com' + link
                    
                    desc_elem = item.find('div', class_='c-card__summary')
                    description = desc_elem.get_text(strip=True) if desc_elem else ''
                    
                    summary_kr = get_gemini_summary(title, description)
                    
                    articles.append({
                        'title': title,
                        'url': link,
                        'source': 'Nature',
                        'category': 'Science News',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': summary_kr
                    })
                    print(f"  ✓ {title[:50]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            time.sleep(1) # API 호출 딜레이
            
    except Exception as e:
        print(f"❌ [Nature News] 크롤링 오류: {e}")
    
    return articles

def scrape_science_news():
    """Science.org 최신 뉴스 크롤링"""
    articles = []
    print("🔍 [Science News] 크롤링 중...")
    
    try:
        url = 'https://www.science.org/news'
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 기사 목록 찾기 (구조가 복잡함)
        article_items = soup.select('div.card-data')[:5]
        
        for item in article_items:
            try:
                title_elem = item.find('h2', class_='card-title')
                link_elem = item.find('a')
                
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    link = link_elem.get('href', '')
                    if link and not link.startswith('http'):
                        link = 'https://www.science.org' + link
                    
                    desc_elem = item.find('p', class_='card-summary')
                    description = desc_elem.get_text(strip=True) if desc_elem else title
                    
                    summary_kr = get_gemini_summary(title, description)

                    articles.append({
                        'title': title,
                        'url': link,
                        'source': 'Science',
                        'category': 'Science News',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': summary_kr
                    })
                    print(f"  ✓ {title[:50]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            time.sleep(1)
            
    except Exception as e:
        print(f"❌ [Science News] 크롤링 오류: {e}")
    
    return articles

def scrape_cell_news():
    """Cell.com 최신 뉴스 (RSS 피드 사용)"""
    articles = []
    print("🔍 [Cell News] (RSS) 크롤링 중...")
    
    try:
        # Cell.com은 RSS 피드를 제공합니다. 이게 더 안정적입니다.
        rss_url = 'https://www.cell.com/rss/cell-news.xml'
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries[:5]:
            try:
                title = entry.title
                link = entry.link
                # 'summary'에 설명이 들어있음
                description = entry.summary
                
                # HTML 태그 제거
                description_text = BeautifulSoup(description, 'html.parser').get_text(strip=True)
                
                summary_kr = get_gemini_summary(title, description_text)
                
                pub_date = entry.published_parsed if hasattr(entry, 'published_parsed') else datetime.now().timetuple()
                date_str = datetime.fromtimestamp(time.mktime(pub_date)).strftime('%Y-%m-%d')

                articles.append({
                    'title': title,
                    'url': link,
                    'source': 'Cell',
                    'category': 'Science News',
                    'date': date_str,
                    'summary_kr': summary_kr
                })
                print(f"  ✓ {title[:50]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            time.sleep(1)
            
    except Exception as e:
        print(f"❌ [Cell News] 크롤링 오류: {e}")
    
    return articles

def scrape_thetransmitter():
    """The Transmitter (신경과학 전문 뉴스) 크롤링"""
    articles = []
    print("🔍 [The Transmitter] 크롤링 중...")
    
    try:
        url = 'https://www.thetransmitter.org/news/'
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        article_items = soup.find_all('article')[:5]
        
        for item in article_items:
            try:
                title_elem = item.find('h3') or item.find('h2')
                link_elem = item.find('a')
                
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    link = link_elem.get('href', '')
                    
                    if link and not link.startswith('http'):
                        link = 'https://www.thetransmitter.org' + link
                    
                    desc_elem = item.find('p')
                    description = desc_elem.get_text(strip=True) if desc_elem else title
                    
                    summary_kr = get_gemini_summary(title, description)
                    
                    articles.append({
                        'title': title,
                        'url': link,
                        'source': 'The Transmitter',
                        'category': 'Neuroscience',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': summary_kr
                    })
                    print(f"  ✓ {title[:50]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
            time.sleep(1)
            
    except Exception as e:
        print(f"❌ [The Transmitter] 크롤링 오류: {e}")
    
    return articles

def scrape_nature_journal(journal_name, journal_code, category):
    """Nature 자매지 크롤링 (nrd, nm, neuro)"""
    articles = []
    print(f"🔍 [Nature {journal_name}] 크롤링 중...")
    
    try:
        # Nature 자매지는 'news-and-comment' 또는 'research-articles' 섹션이 있음
        url = f'https://www.nature.com/{journal_code}/news-and-comment'
        response = requests.get(url, headers=HEADERS, timeout=15)
        
        # 404가 나면 research-articles 시도
        if response.status_code == 404:
            print(f"  [i] 'news-and-comment' 없음, 'research'로 재시도...")
            url = f'https://www.nature.com/{journal_code}/research-articles'
            response = requests.get(url, headers=HEADERS, timeout=15)
            
        soup = BeautifulSoup(response.content, 'html.parser')
        article_items = soup.find_all('article')[:3] # 자매지는 3개만
        
        if not article_items:
            # 다른 레이아웃 시도
             article_items = soup.find_all('li', class_='app-article-list-row__item')[:3]

        for item in article_items:
            try:
                title_elem = item.find('h3')
                link_elem = item.find('a')
                
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    link = link_elem.get('href', '')
                    
                    if link and not link.startswith('http'):
                        link = 'https://www.nature.com' + link
                    
                    desc_elem = item.find(['p', 'div'], class_=['c-card__summary', 'app-article-list-row__summary'])
                    description = desc_elem.get_text(strip=True) if desc_elem else title
                    
                    summary_kr = get_gemini_summary(title, description)
                    
                    articles.append({
                        'title': title,
                        'url': link,
                        'source': f'Nature {journal_name}',
                        'category': category,
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': summary_kr
                    })
                    print(f"  ✓ {title[:50]}...")
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
    for article in all_articles:
        if article['url'] not in seen_urls:
            seen_urls.add(article['url'])
            unique_articles.append(article)
    
    # 날짜순 정렬 (최신순)
    unique_articles.sort(key=lambda x: x['date'], reverse=True)
    
    # JSON 파일로 저장
    output = {
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'articles': unique_articles
    }
    
    with open('articles.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print("\n" + "="*60)
    print(f"✅ 완료! 총 {len(unique_articles)}개 항목 수집 및 요약")
    print(f"📁 articles.json 파일 업데이트됨")
    print("="*60 + "\n")
    
    # 소스별 통계
    sources = {}
    for article in unique_articles:
        source = article['source']
        sources[source] = sources.get(source, 0) + 1
    
    print("📊 소스별 수집 현황:")
    for source, count in sources.items():
        print(f"  • {source}: {count}개")


if __name__ == '__main__':
    main()
