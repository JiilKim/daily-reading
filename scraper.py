#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[영구 버전 - GitHub Actions용]
지정된 RSS 피드에서 뉴스/논문을 크롤링하고
Gemini API를 이용해 번역/요약한 후
articles.json을 업데이트합니다. (하루 50개 제한)
YouTube는 update_youtube_locally.py로 별도 실행합니다.
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
from urllib.parse import urljoin
import sys

# --- 설정 ---
# 하루에 요약할 새 기사/논문의 최대 개수 (API 할당량 보호)
MAX_NEW_ARTICLES_PER_RUN = 50

# --- AI 요약 기능 ---

def get_gemini_summary(title_en, description_en):
    """
    Gemini API를 호출하여 제목과 설명을 한글로 번역 및 요약합니다.
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
        # 'BlockedPromptError'가 아닌 'BlockedPromptException'으로 수정
        if isinstance(e, genai_types.generation_types.BlockedPromptException):
             print(f"  [AI] ❌ Gemini API - 콘텐츠 차단 오류: {e}")
             return title_en, "[요약 실패] API가 콘텐츠를 차단했습니다."
        
        print(f"  [AI] ❌ Gemini API 오류: {e}")
        # API 할당량 초과(ResourceExhausted) 등의 오류 포함
        return title_en, f"[요약 실패] API 호출 중 오류 발생. (원본: {description_en[:100]}...)"
    
    except json.JSONDecodeError as e:
        print(f"  [AI] ❌ JSON 파싱 오류: {e}. 응답 텍스트: {response.text[:100]}...")
        return title_en, f"[요약 실패] API 응답 형식 오류. (원본: {description_en[:100]}...)"


# --- 웹사이트별 스크래퍼 ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/xml,application/rss+xml,text/xml;q=0.9,text/html;q=0.8,*/*;q=0.5',
    'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
}

# [신규] 봇 차단 및 오류에 강한 RSS 피드 파싱 함수
def scrape_robust_rss_feed(feed_url, source_name, category_name):
    """
    requests로 먼저 콘텐츠를 가져온 후 feedparser로 파싱하여 안정성을 높인 함수.
    """
    articles = []
    print(f"🔍 [{source_name}] (RSS) 크롤링 중... (URL: {feed_url})")
    
    try:
        # requests로 먼저 접속 시도
        response = requests.get(feed_url, headers=HEADERS, timeout=20)
        
        # HTTP 오류 확인 (예: 404, 500)
        response.raise_for_status() 
        
        # Content-Type 확인 (XML/RSS가 맞는지)
        content_type = response.headers.get('Content-Type', '').lower()
        if 'xml' not in content_type and 'rss' not in content_type:
            print(f"  ❌ RSS 피드가 XML/RSS가 아닌 응답을 반환했습니다. (Content-Type: {content_type})")
            print(f"     응답 내용 (첫 200자): {response.text[:200]}...")
            return [] # 빈 리스트 반환

        # requests로 가져온 콘텐츠를 feedparser로 파싱
        feed = feedparser.parse(response.content)
        
        # feedparser 파싱 오류 확인 (bozo 플래그)
        if feed.bozo:
            print(f"  ⚠️ RSS 피드 파싱 중 오류 발생 (bozo): {feed.bozo_exception}")
            # 오류가 있어도 최대한 파싱된 항목은 처리 시도
        
        print(f"  [i] {len(feed.entries)}개 항목 찾음")

        for entry in feed.entries:
            try:
                title_en = entry.title
                link = entry.link
                
                # 설명: summary > description > title 순서로 찾기
                description_en = entry.summary if hasattr(entry, 'summary') else (entry.description if hasattr(entry, 'description') else title_en)
                
                # HTML 태그 제거
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)
                
                # 날짜 파싱 (오류 발생 시 오늘 날짜로 대체)
                date_str = datetime.now().strftime('%Y-%m-%d')
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        # struct_time을 datetime 객체로 변환 후 포맷팅
                        dt_obj = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        date_str = dt_obj.strftime('%Y-%m-%d')
                    except (TypeError, ValueError) as date_err:
                        print(f"    ⚠️ 날짜 파싱 오류: {date_err}, 오늘 날짜 사용.")
                
                # 이미지 추출 (media_thumbnail, enclosure, description 내 img 태그 순)
                image_url = None
                if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0].get('url')
                elif hasattr(entry, 'links'):
                    for e_link in entry.links:
                        if e_link.get('rel') == 'enclosure' and e_link.get('type', '').startswith('image/'):
                            image_url = e_link.get('href')
                            break
                if not image_url and description_en: # 설명 필드에 HTML이 있을 경우
                    desc_soup = BeautifulSoup(description_en, 'html.parser')
                    img_tag = desc_soup.find('img')
                    if img_tag:
                        # 상대 URL일 수 있으므로 절대 URL로 변환 시도
                        img_src = img_tag.get('src')
                        if img_src:
                            image_url = urljoin(link, img_src) # 기사 링크 기준으로 절대 URL 생성
                            
                # 제목에서 HTML 태그 제거 (<Emphasis> 등)
                title_en = BeautifulSoup(title_en, 'html.parser').get_text(strip=True)

                articles.append({
                    'title_en': title_en,
                    'description_en': description_text,
                    'url': link,
                    'source': source_name,
                    'category': category_name,
                    'date': date_str,
                    'image_url': image_url
                })
                
            except Exception as item_err:
                # 개별 항목 파싱 오류는 로그만 남기고 계속 진행
                print(f"  ✗ RSS 개별 항목 파싱 실패: {item_err}")
            
    except requests.exceptions.RequestException as req_err:
        # requests 관련 오류 (연결 실패, 타임아웃, HTTP 오류 등)
        print(f"❌ [{source_name}] RSS 요청 실패: {req_err}")
    except Exception as e:
        # 그 외 예기치 못한 전체 오류
        print(f"❌ [{source_name}] RSS 크롤링 중 예기치 못한 오류: {e}")
    
    return articles


def main():
    """메인 실행 함수"""
    print("\n" + "="*60)
    print("📰 일일 읽을거리 자동 수집 및 요약 시작")
    print(f"🕐 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")
    
    all_articles_to_check = []
    
    # --- [수정] 님이 주신 RSS 피드 목록 전체 (scrape_robust_rss_feed 사용) ---
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.nature.com/nature/rss/articles?type=news', 'Nature', 'News'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.science.org/rss/news_current.xml', 'Science', 'News'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.thetransmitter.org/feed/', 'The Transmitter', 'Neuroscience'))
    
    
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science', 'Science (Paper)', 'Paper'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.cell.com/cell/current.rss', 'Cell', 'Paper'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.nature.com/neuro/current_issue/rss', 'Nature Neuroscience', 'Paper'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.nature.com/nm/current_issue/rss', 'Nature Medicine', 'Paper'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.nature.com/nrd/current_issue/rss', 'Nature Drug Discovery', 'Paper'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.nature.com/nbt/current_issue/rss', 'Nature Biotechnology', 'Paper'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.nature.com/nature/rss/newsandcomment', 'Nature (News & Comment)', 'News'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.nature.com/nature/research-articles.rss', 'Nature (Paper)', 'Paper'))
    
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.statnews.com/feed/', 'STAT News', 'News'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.the-scientist.com/rss', 'The Scientist', 'News'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://arstechnica.com/science/feed/', 'Ars Technica', 'News'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.wired.com/feed/category/science/latest/rss', 'Wired', 'News'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://neurosciencenews.com/feed/', 'Neuroscience News', 'News'))
    
    # [수정] FDA 주소 변경
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drugs/rss.xml', 'FDA', 'News')) # Drugs 피드는 이 페이지 내에서 찾아야 할 수 있음
    
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.fiercebiotech.com/rss/xml', 'Fierce Biotech', 'News'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://endpts.com/feed/', 'Endpoints News', 'News'))
    all_articles_to_check.extend(scrape_robust_rss_feed('https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss', 'NEJM', 'Paper'))
    
    # [수정] JAMA 주소 변경 (사이트 피드 페이지 참고)
    all_articles_to_check.extend(scrape_robust_rss_feed('https://jamanetwork.com/rss/latest.xml', 'JAMA', 'Paper')) # '최신 전체' 피드
    
    
    seen_urls = set()
    final_article_list = [] # 최종 저장될 리스트 (기존 + 신규)
    
    try:
        with open('articles.json', 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            # 최근 7일간의 기사만 URL 체크 및 최종 리스트에 추가
            for old_article in old_data.get('articles', []):
                try:
                    article_date = datetime.strptime(old_article.get('date', '1970-01-01'), '%Y-%m-%d')
                    if (datetime.now() - article_date).days <= 7:
                        if old_article.get('url'):
                            seen_urls.add(old_article['url'])
                            final_article_list.append(old_article)
                except ValueError:
                    continue # 날짜 형식이 다르면 무시
        print(f"\n[i] 기존 {len(seen_urls)}개의 URL (최근 7일)을 로드했습니다. 새로운 기사만 추가/요약합니다.")
    except FileNotFoundError:
        print("\n[i] 'articles.json' 파일이 없습니다. 새로 생성합니다.")
    except json.JSONDecodeError:
        print("\n[i] ❌ 'articles.json' 파일이 손상되었습니다. 새로 생성합니다.")
        final_article_list = []
        seen_urls = set()
    
    
    new_articles = [] # 새로 요약된 기사만 임시 보관
    existing_articles_count = 0
    new_article_count = 0
    api_errors = 0 # API 오류 횟수
    
    print(f"\n[i] 총 {len(all_articles_to_check)}개의 (RSS) 항목을 확인합니다 (최대 {MAX_NEW_ARTICLES_PER_RUN}개까지 요약).")

    for article_data in all_articles_to_check:
        
        # URL 누락 또는 빈 URL 체크
        if not article_data.get('url'):
            print(f"  ⚠️ URL이 없는 항목 발견 (Source: {article_data.get('source', 'N/A')}). 건너뜁니다.")
            continue
            
        if article_data['url'] not in seen_urls:
            
            if new_article_count >= MAX_NEW_ARTICLES_PER_RUN:
                print(f"  [i] API 할당량 보호를 위해 {MAX_NEW_ARTICLES_PER_RUN}개 도달. 나머지는 다음 실행으로...")
                break # 하루 최대치에 도달하면 루프 중단
            
            new_article_count += 1
            print(f"  [i] ✨ 새로운 기사 발견 ({new_article_count}/{MAX_NEW_ARTICLES_PER_RUN}): {article_data['title_en'][:50]}...")
            
            # API 호출로 번역 및 요약
            title_kr, summary_kr = get_gemini_summary(article_data['title_en'], article_data['description_en'])
            
            # API 요약 실패 시 오류 카운트 증가
            if "[요약 실패]" in summary_kr:
                api_errors += 1
                
            article_data['title'] = title_kr
            article_data['summary_kr'] = summary_kr
            
            # 원본 영어 제목/설명도 저장
            article_data['title_en'] = article_data['title_en']
            article_data['summary_en'] = article_data['description_en']
            del article_data['description_en'] # 중복 필드 제거
            
            new_articles.append(article_data)
            seen_urls.add(article_data['url'])
            
            time.sleep(1) # API 딜레이
            
        elif article_data.get('url'):
            existing_articles_count += 1
    
    print(f"\n[i] {new_article_count}개의 새로운 (RSS) 기사를 요약 시도했습니다.")
    print(f"    (성공: {new_article_count - api_errors}개, API 오류: {api_errors}개)")
    print(f"    (중복/기존 기사 {existing_articles_count}개 제외)")
    
    
    # 3. 기존 데이터와 새로운 데이터를 합침
    final_article_list.extend(new_articles)
    
    # 4. 합친 목록에서 다시 중복 제거 (혹시 모를 경우 대비)
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
    
    json_file_path = 'articles.json'
    try:
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 완료! 총 {len(deduplicated_list)}개 항목 저장 (최근 7일 + 신규)")
        print(f"📁 '{json_file_path}' 파일 업데이트됨")
    except Exception as write_err:
        print(f"\n❌ JSON 파일 저장 실패: {write_err}")
        sys.exit(1) # 오류 코드와 함께 종료

    print("\n" + "="*60 + "\n")
    
    sources = {}
    for article in deduplicated_list:
        source = article.get('source', 'Unknown')
        sources[source] = sources.get(source, 0) + 1
    
    print("📊 소스별 수집 현황 (최근 7일 + 신규):")
    for source, count in sorted(sources.items()):
        print(f"  • {source}: {count}개")


if __name__ == '__main__':
    main()
