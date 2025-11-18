#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
일일 과학 뉴스 크롤러 (Gemini AI 번역 및 요약 기능 포함)
- RSS 피드 및 유튜브 채널 크롤링
- Gemini API를 사용하여 콘텐츠 번역 및 요약
- URL 컨텍스트를 통한 유튜브 영상 분석 지원
- 최근 7일간의 아카이브 유지
- GitHub Actions 호환
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
from urllib.parse import urljoin
import sys

# ============================================================================
# 설정
# ============================================================================

MAX_NEW_ARTICLES_PER_RUN = 8000
ARCHIVE_DAYS = 7
API_DELAY_SECONDS = 1

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/xml,application/rss+xml,text/xml;q=0.9,*/*;q=0.5',
    'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8',
    'Cache-Control': 'no-cache',
}

# ============================================================================
# AI 번역 및 요약
# ============================================================================

def get_gemini_summary(article_data):
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

    try:
        api_key = os.environ.get('GEMINI_API_KEY')
        
        if not api_key:
            print("  [AI] ❌ GEMINI_API_KEY를 찾을 수 없습니다. 번역을 건너뜁니다.")
            return title_en, f"[요약 실패] API 키 없음. (원본: {description_en[:100]}...)"

        client = genai.Client(api_key=api_key)

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
                model='gemini-2.5-flash', # 모델 버전
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
                model='gemini-2.5-flash', # 모델 버전
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

        # JSON 응답 파싱
        data = json.loads(response.text)
        title_kr = data.get('title_kr', title_en)
        summary_kr = data.get('summary_kr', f"[요약 실패] API 오류. (원본: {description_en[:100]}...)")

        print(f"  [AI] ✓ 번역 완료: {title_kr[:40]}...")
        return title_kr, summary_kr

    except json.JSONDecodeError as e:
        print(f"  [AI] ❌ JSON 파싱 오류: {e}")
        return title_en, f"[요약 실패] 잘못된 API 응답. (원본: {description_en[:100]}...)"
    
    except Exception as e:
        print(f"  [AI] ❌ API 오류: {e}")
        return title_en, f"[요약 실패] API 호출 실패. (원본: {description_en[:100]}...)"


# ============================================================================
# RSS 피드 스크래퍼
# ============================================================================

def scrape_rss_feed(feed_url, source_name, category_name):
    """
    강력한 오류 처리를 포함하여 RSS 피드에서 기사를 스크랩합니다.
    
    Args:
        feed_url (str): RSS 피드 URL
        source_name (str): 식별을 위한 소스 이름
        category_name (str): 기사 카테고리 (News/Paper/Video)
        
    Returns:
        list: 기사 딕셔너리 리스트
    """
    articles = []
    print(f"🔍 [{source_name}] RSS 크롤링 중... (URL: {feed_url})")

    try:
        response = requests.get(feed_url, headers=HEADERS, timeout=20)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '').lower()
        if not any(ct in content_type for ct in ['xml', 'rss', 'atom']):
            print(f"  ❌ 잘못된 콘텐츠 유형: {content_type}")
            print(f"     응답 미리보기: {response.text[:200]}...")
            return []

        feed = feedparser.parse(response.content)

        if feed.bozo:
            print(f"  ⚠️ 피드 파싱 경고: {feed.bozo_exception}")

        print(f"  [i] {len(feed.entries)}개 아이템 발견")

        for entry in feed.entries:
            try:
                if not entry.get('title') or not entry.get('link'):
                    print("    ⚠️ 제목 또는 링크 누락. 건너뜁니다.")
                    continue

                title_en = entry.title
                link = entry.link
                description_en = entry.get('summary') or entry.get('description') or title_en
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)

                # 발행일 파싱
                date_str = datetime.now().strftime('%Y-%m-%d')
                if entry.get('published_parsed'):
                    try:
                        dt_obj = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        date_str = dt_obj.strftime('%Y-%m-%d')
                    except (TypeError, ValueError):
                        pass

                # 이미지 URL 추출
                image_url = None
                if entry.get('media_thumbnail'):
                    image_url = entry.media_thumbnail[0].get('url')
                elif entry.get('links'):
                    for e_link in entry.links:
                        if e_link.get('rel') == 'enclosure' and e_link.get('type', '').startswith('image/'):
                            image_url = e_link.get('href')
                            break
                
                if not image_url and description_en:
                    desc_soup = BeautifulSoup(description_en, 'html.parser')
                    img_tag = desc_soup.find('img')
                    if img_tag and img_tag.get('src'):
                        image_url = urljoin(link, img_tag.get('src'))

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
                print(f"  ✗ 아이템 파싱 실패: {item_err}")

    except requests.exceptions.RequestException as req_err:
        print(f"❌ [{source_name}] 요청 실패: {req_err}")
    except Exception as e:
        print(f"❌ [{source_name}] 예상치 못한 오류: {e}")

    return articles


# ============================================================================
# 유튜브 채널 스크래퍼
# ============================================================================

def scrape_youtube_videos(channel_id, source_name, category_name):
    """
    유튜브 채널 RSS 피드에서 최신 동영상을 스크랩합니다.
    영상 콘텐츠는 AI가 URL 컨텍스트를 사용하여 분석합니다.
    
    Args:
        channel_id (str): 유튜브 채널 ID
        source_name (str): 식별을 위한 소스 이름
        category_name (str): 기사 카테고리
        
    Returns:
        list: 영상 딕셔너리 리스트
    """
    articles = []
    print(f"🔍 [{source_name}] 유튜브 크롤링 중... (채널: {channel_id})")
    feed_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'

    try:
        response = requests.get(feed_url, headers=HEADERS, timeout=20)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '').lower()
        if 'xml' not in content_type:
            print(f"  ❌ 잘못된 콘텐츠 유형: {content_type}")
            return []

        feed = feedparser.parse(response.content)

        if feed.bozo:
            print(f"  ⚠️ 피드 파싱 경고: {feed.bozo_exception}")

        print(f"  [i] {len(feed.entries)}개의 최신 영상 발견")

        for entry in feed.entries:
            try:
                if not entry.get('title') or not entry.get('link'):
                    print("    ⚠️ 제목 또는 링크 누락. 건너뜁니다.")
                    continue

                title_en = entry.title
                link = entry.link
                video_id = link.split('v=')[-1]

                # 발행일 파싱
                date_str = datetime.now().strftime('%Y-%m-%d')
                if entry.get('published_parsed'):
                    dt_obj = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                    date_str = dt_obj.strftime('%Y-%m-%d')

                # 고화질 썸네일 가져오기
                image_url = None
                if entry.get('media_thumbnail') and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0]['url'].replace('default.jpg', 'hqdefault.jpg')

                # AI를 위한 보조 정보로 RSS 설명 사용
                description_en = entry.get('media_description', entry.get('summary', title_en))
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)
                
                print(f"    [i] 영상 {video_id} 로드됨. AI가 URL을 직접 분석합니다.")

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
                print(f"  ✗ 영상 파싱 실패: {item_err}")

    except requests.exceptions.RequestException as req_err:
        print(f"❌ [{source_name}] 요청 실패: {req_err}")
    except Exception as e:
        print(f"❌ [{source_name}] 예상치 못한 오류: {e}")

    return articles


# ============================================================================
# 메인 실행
# ============================================================================

def main():
    """GitHub Actions 워크플로우를 위한 메인 실행 함수"""
    
    print("\n" + "="*60)
    print("📰 일일 과학 뉴스 크롤러 - 시작")
    print(f"🕐 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")

    # ========================================================================
    # 1. 모든 소스 크롤링
    # ========================================================================
    
    all_articles_to_check = []
    
    # 유튜브 채널
    all_articles_to_check.extend(
        scrape_youtube_videos('UCWgXoKQ4rl7SY9UHuAwxvzQ', 'B_ZCF YouTube', 'Video')
    )
    
    # 뉴스 소스
    all_articles_to_check.extend(scrape_rss_feed('https://www.thetransmitter.org/feed/', 'The Transmitter', 'Neuroscience'))    
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/nature/rss/articles?type=news', 'Nature', 'News'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.statnews.com/feed/', 'STAT News', 'News'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.the-scientist.com/atom/latest', 'The Scientist', 'News'))
    all_articles_to_check.extend(scrape_rss_feed('https://arstechnica.com/science/feed/', 'Ars Technica', 'News'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.wired.com/feed/category/science/latest/rss', 'Wired', 'News'))
    all_articles_to_check.extend(scrape_rss_feed('https://neurosciencenews.com/feed/', 'Neuroscience News', 'News'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.fiercebiotech.com/rss/xml', 'Fierce Biotech', 'News'))
    all_articles_to_check.extend(scrape_rss_feed('https://endpts.com/feed/', 'Endpoints News', 'News'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.science.org/rss/news_current.xml', 'Science', 'News'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/nature/rss/newsandcomment', 'Nature (News & Comment)', 'News'))
    
    # 과학 논문
    all_articles_to_check.extend(scrape_rss_feed('https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science', 'Science (Paper)', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.cell.com/cell/current.rss', 'Cell', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/neuro/current_issue/rss', 'Nature Neuroscience', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/nm/current_issue/rss', 'Nature Medicine', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/nrd/current_issue/rss', 'Nature Drug Discovery', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/nbt/current_issue/rss', 'Nature Biotechnology', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nature.com/nature/research-articles.rss', 'Nature (Paper)', 'Paper'))
    all_articles_to_check.extend(scrape_rss_feed('https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss', 'NEJM', 'Paper'))

    # ========================================================================
    # 2. 기존 기사 로드 (***수정된 로직***)
    # ========================================================================
    
    seen_urls = set()
    old_articles_to_keep = [] # ARCHIVE_DAYS 내의 기사만 보관할 임시 리스트

    try:
        with open('articles.json', 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            for old_article in old_data.get('articles', []):
                if not old_article.get('url'):
                    continue
                
                # [수정] 1. 날짜와 상관없이 모든 URL을 'seen_urls'에 추가하여 API 중복 호출 방지
                seen_urls.add(old_article['url'])
                
                # [수정] 2. 7일 이내의 기사인지 별도로 확인하여 최종 목록에 유지
                try:
                    article_date = datetime.strptime(old_article.get('date', '1970-01-01'), '%Y-%m-%d')
                    if (datetime.now() - article_date).days <= ARCHIVE_DAYS:
                        old_articles_to_keep.append(old_article)
                except ValueError:
                    continue # 날짜 형식이 잘못된 경우 무시
                    
        print(f"\n[i] 기존 URL {len(seen_urls)}개 로드 (API 중복 호출 방지용)")
        print(f"    (그 중 {len(old_articles_to_keep)}개 기사가 {ARCHIVE_DAYS}일 이내이므로 보관)")
        
    except FileNotFoundError:
        print("\n[i] 'articles.json' 파일을 찾을 수 없습니다. 새 파일을 생성합니다.")
    except json.JSONDecodeError:
        print("\n[i] ❌ 'articles.json' 파일이 손상되었습니다. 새 파일을 생성합니다.")
        old_articles_to_keep = []
        seen_urls = set()

    # ========================================================================
    # 3. 새 기사 AI 번역 처리
    # ========================================================================
    
    new_articles = []
    existing_articles_count = 0
    new_article_count = 0
    api_errors = 0

    print(f"\n[i] {len(all_articles_to_check)}개 아이템 확인 중 (최대 {MAX_NEW_ARTICLES_PER_RUN}개 새 기사)")

    for article_data in all_articles_to_check:
        
        if not article_data.get('url'):
            print(f"  ⚠️ URL 누락 (소스: {article_data.get('source', 'N/A')}). 건너뜁니다.")
            continue

        # [수정] 이제 seen_urls는 모든 과거 기사 URL을 포함하므로 7일이 지난 기사도 API 호출을 건너뜀
        if article_data['url'] not in seen_urls:
            
            if new_article_count >= MAX_NEW_ARTICLES_PER_RUN:
                print(f"  [i] 최대 개수 ({MAX_NEW_ARTICLES_PER_RUN}개)에 도달했습니다. 할당량 보호를 위해 중지합니다.")
                break

            new_article_count += 1
            print(f"  [i] ✨ 새 아이템 발견 ({new_article_count}/{MAX_NEW_ARTICLES_PER_RUN}): {article_data['title_en'][:50]}...")

            # AI로 번역 및 요약
            title_kr, summary_kr = get_gemini_summary(article_data)

            # [사용자 요청] 번역/요약에 실패한 기사는 건너뜀
            if "[Translation Failed]" in summary_kr or "[요약 실패]" in summary_kr:
                api_errors += 1
                print(f"  [i] ❌ AI 실패. 기사를 건너뜁니다: {article_data['title_en'][:50]}...")
            else:
                # 최종 기사 객체 준비
                article_data['title'] = title_kr
                article_data['summary_kr'] = summary_kr
                article_data['summary_en'] = article_data['description_en']
                del article_data['description_en']

                new_articles.append(article_data)
                seen_urls.add(article_data['url']) # 혹시나 중복 수집될 경우를 대비해 여기서도 추가

            time.sleep(API_DELAY_SECONDS)

        else:
            existing_articles_count += 1

    print(f"\n[i] 새 기사 {new_article_count}개 처리 완료")
    print(f"    (성공: {new_article_count - api_errors}, API 오류: {api_errors})")
    print(f"    (기존 기사 {existing_articles_count}개 건너뜀)")

    # ========================================================================
    # 4. 기사 병합 및 중복 제거 (***수정된 로직***)
    # ========================================================================
    
    # [수정] final_article_list 대신 old_articles_to_keep에서 시작
    deduplicated_list = old_articles_to_keep
    deduplicated_list.extend(new_articles)

    # 남은 중복 항목 제거 (혹시 모를 경우 대비)
    final_seen_urls = set()
    final_deduplicated_list = []
    
    for article in deduplicated_list:
        if article.get('url') and article['url'] not in final_seen_urls:
            # [사용자 요청] 번역/요약 실패 항목이 기존 목록에 있더라도 최종 목록에는 추가하지 않음
            if "[Translation Failed]" not in article.get('summary_kr', '') and "[요약 실패]" not in article.get('summary_kr', ''):
                final_seen_urls.add(article['url'])
                final_deduplicated_list.append(article)
            else:
                print(f"  [i] 🗑️ 기존 목록에서 실패한 항목 제거: {article.get('title', 'N/A')[:50]}...")

    # [수정] 최종 리스트를 할당
    deduplicated_list = final_deduplicated_list

    # 날짜순 정렬 (최신순)
    deduplicated_list.sort(key=lambda x: x.get('date', '1970-01-01'), reverse=True)

    # ========================================================================
    # 5. JSON 파일로 저장
    # ========================================================================
    
    output = {
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'articles': deduplicated_list
    }

    json_file_path = 'articles.json'
    try:
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 성공! {len(deduplicated_list)}개 기사 저장 (최근 {ARCHIVE_DAYS}일 + 신규)")
        print(f"📁 '{json_file_path}' 업데이트 완료")
    except Exception as write_err:
        print(f"\n❌ JSON 저장 실패: {write_err}")
        sys.exit(1)

    # ========================================================================
    # 6. 통계 출력
    # ========================================================================
    
    print("\n" + "="*60)
    print(f"📊 수집 통계 (최근 {ARCHIVE_DAYS}일 + 신규):")
    print("="*60)
    
    sources = {}
    for article in deduplicated_list:
        source = article.get('source', 'Unknown')
        sources[source] = sources.get(source, 0) + 1

    for source, count in sorted(sources.items()):
        print(f"  • {source}: {count} articles")
    
    print("\n" + "="*60)
    print(f"🕐 종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")


if __name__ == '__main__':
    main()

