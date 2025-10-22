#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
실제 웹사이트에서 뉴스/논문/영상을 크롤링하는 스크립트
매일 자동 실행되어 articles.json을 업데이트합니다
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import feedparser
import time

def scrape_nature_news():
    """Nature 최신 뉴스 크롤링"""
    articles = []
    print("🔍 Nature 크롤링 중...")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Nature 뉴스 페이지
        url = 'https://www.nature.com/nature/articles?type=news'
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 기사 찾기
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
                    
                    # 간단한 설명 추출
                    desc_elem = item.find('div', class_='c-card__summary')
                    description = desc_elem.get_text(strip=True) if desc_elem else ''
                    
                    articles.append({
                        'id': abs(hash(link)),
                        'title': title,
                        'url': link,
                        'source': 'Nature',
                        'category': 'Neuroscience',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': description[:200] + '...' if len(description) > 200 else description
                    })
                    print(f"  ✓ {title[:50]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
                continue
        
        time.sleep(1)  # 서버 부담 줄이기
        
    except Exception as e:
        print(f"❌ Nature 크롤링 오류: {e}")
    
    return articles


def scrape_science_news():
    """Science.org 최신 뉴스 크롤링"""
    articles = []
    print("🔍 Science 크롤링 중...")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        url = 'https://www.science.org/news/all-news'
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 기사 찾기
        article_items = soup.find_all('div', class_='card-header')[:5]
        
        for item in article_items:
            try:
                title_elem = item.find('h3')
                link_elem = item.find('a')
                
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    link = link_elem.get('href', '')
                    
                    if link and not link.startswith('http'):
                        link = 'https://www.science.org' + link
                    
                    articles.append({
                        'id': abs(hash(link)),
                        'title': title,
                        'url': link,
                        'source': 'Science',
                        'category': 'Neuroscience',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': f"{title}에 대한 최신 과학 뉴스입니다."
                    })
                    print(f"  ✓ {title[:50]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
                continue
        
        time.sleep(1)
        
    except Exception as e:
        print(f"❌ Science 크롤링 오류: {e}")
    
    return articles


def scrape_thetransmitter():
    """The Transmitter (신경과학 전문 뉴스) 크롤링"""
    articles = []
    print("🔍 The Transmitter 크롤링 중...")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        url = 'https://www.thetransmitter.org/'
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 기사 찾기
        article_items = soup.find_all('article')[:5]
        
        for item in article_items:
            try:
                title_elem = item.find('h2') or item.find('h3')
                link_elem = item.find('a')
                
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    link = link_elem.get('href', '')
                    
                    if link and not link.startswith('http'):
                        link = 'https://www.thetransmitter.org' + link
                    
                    articles.append({
                        'id': abs(hash(link)),
                        'title': title,
                        'url': link,
                        'source': 'The Transmitter',
                        'category': 'Neuroscience',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': f"신경과학 관련 최신 연구 및 뉴스: {title}"
                    })
                    print(f"  ✓ {title[:50]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
                continue
        
        time.sleep(1)
        
    except Exception as e:
        print(f"❌ The Transmitter 크롤링 오류: {e}")
    
    return articles


def scrape_youtube_channel(channel_id, channel_name="YouTube"):
    """유튜브 채널 최신 영상 크롤링 (RSS 피드 사용)"""
    videos = []
    print(f"🔍 YouTube ({channel_name}) 크롤링 중...")
    
    try:
        rss_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries[:3]:  # 최신 3개
            try:
                title = entry.title
                link = entry.link
                published = entry.published if hasattr(entry, 'published') else datetime.now().strftime('%Y-%m-%d')
                
                # 날짜 포맷 변환
                try:
                    pub_date = datetime.strptime(published, '%Y-%m-%dT%H:%M:%S%z')
                    date_str = pub_date.strftime('%Y-%m-%d')
                except:
                    date_str = datetime.now().strftime('%Y-%m-%d')
                
                videos.append({
                    'id': abs(hash(link)),
                    'title': title,
                    'url': link,
                    'source': 'YouTube',
                    'category': 'Video',
                    'date': date_str,
                    'summary_kr': f"{channel_name} 채널의 최신 영상입니다."
                })
                print(f"  ✓ {title[:50]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
                continue
        
        time.sleep(1)
        
    except Exception as e:
        print(f"❌ YouTube 크롤링 오류: {e}")
    
    return videos


def scrape_nature_neuroscience_papers():
    """Nature Neuroscience 최신 논문"""
    articles = []
    print("🔍 Nature Neuroscience 논문 크롤링 중...")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        url = 'https://www.nature.com/neuro/research-articles'
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        article_items = soup.find_all('article')[:3]
        
        for item in article_items:
            try:
                title_elem = item.find('h3')
                link_elem = item.find('a')
                
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    link = link_elem.get('href', '')
                    
                    if link and not link.startswith('http'):
                        link = 'https://www.nature.com' + link
                    
                    articles.append({
                        'id': abs(hash(link)),
                        'title': title,
                        'url': link,
                        'source': 'Nature Neuroscience',
                        'category': 'Neuroscience',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'summary_kr': f"Nature Neuroscience에 게재된 최신 논문: {title[:100]}"
                    })
                    print(f"  ✓ {title[:50]}...")
            except Exception as e:
                print(f"  ✗ 항목 파싱 실패: {e}")
                continue
        
        time.sleep(1)
        
    except Exception as e:
        print(f"❌ Nature Neuroscience 크롤링 오류: {e}")
    
    return articles


def main():
    """메인 실행 함수"""
    print("\n" + "="*60)
    print("📰 일일 읽을거리 자동 수집 시작")
    print("="*60 + "\n")
    
    all_articles = []
    
    # 각 소스에서 크롤링
    all_articles.extend(scrape_nature_news())
    all_articles.extend(scrape_science_news())
    all_articles.extend(scrape_thetransmitter())
    all_articles.extend(scrape_nature_neuroscience_papers())
    
    # 유튜브 채널들
    youtube_channels = [
        ('UCsJ6RuBiTVWRX156FVbeaGg', '신경과학 채널 1'),
        # 여기에 더 추가 가능
    ]
    
    for channel_id, channel_name in youtube_channels:
        all_articles.extend(scrape_youtube_channel(channel_id, channel_name))
    
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
    print(f"✅ 완료! 총 {len(unique_articles)}개 항목 수집")
    print(f"📁 articles.json 파일 업데이트됨")
    print(f"🕐 업데이트 시간: {output['last_updated']}")
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
