#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Science News Crawler with Gemini AI Translation & Summarization
- Crawls RSS feeds and YouTube channels
- Translates and summarizes content using Gemini API
- Supports YouTube video analysis via URL Context
- Maintains a rolling 7-day archive
- GitHub Actions compatible
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
# Configuration
# ============================================================================

MAX_NEW_ARTICLES_PER_RUN = 300
ARCHIVE_DAYS = 7
API_DELAY_SECONDS = 1

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/xml,application/rss+xml,text/xml;q=0.9,*/*;q=0.5',
    'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8',
    'Cache-Control': 'no-cache',
}

# ============================================================================
# AI Translation & Summarization
# ============================================================================

def get_gemini_summary(article_data):
    """
    Translates and summarizes article content using Gemini API.
    For YouTube videos, analyzes video content directly via URL.
    
    Args:
        article_data (dict): Article metadata including title_en, description_en, url, source
        
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
            print("  [AI] ❌ GEMINI_API_KEY not found. Skipping translation.")
            return title_en, f"[Translation Failed] No API key. (Original: {description_en[:100]}...)"

        client = genai.Client(api_key=api_key)

        # YouTube videos: Analyze video content directly
        if 'YouTube' in source:
            print(f"  [AI] 🎥 Analyzing YouTube video: '{title_en[:40]}...'")
            
            prompt = f"""
You are a video summarizer. Analyze the YouTube video and create a Korean title and Korean summary.
Output MUST be in the specified JSON format.

[Input]
- title_en: "{title_en}"

[JSON Output Format]
{{
  "title_kr": "Write professional Korean translation of the title",
  "summary_kr": "Extract the key points, and write detailed 10 sentences Korean summary of video content"
}}

[Rules]
1. "title_kr": Translate "title_en" into natural, professional Korean
2. "summary_kr": Provide detailed 10 sentence summary in natural Korean style
3. Use general writing style, not conversational tone
"""

            response = client.models.generate_content(
                model='gemini-2.0-flash-exp',
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
            
        # Text articles: Translate and summarize from description
        else:
            print(f"  [AI] 📝 Translating article: '{title_en[:40]}...'")
            
            prompt = f"""
You are a professional science news editor. Translate and summarize the article in Korean.
Output MUST be in the specified JSON format.

[Input]
- title_en: "{title_en}"
- description_en: "{description_en}"

[JSON Output Format]
{{
  "title_kr": "Write professional Korean translation of the title",
  "summary_kr": "Write detailed 5-6 sentence Korean summary"
}}

[Rules]
1. "title_kr": Translate "title_en" into natural, professional Korean
2. "summary_kr": Summarize key points from "description_en" in 5-6 sentences
3. Use professional news writing style, not conversational tone
"""
            
            response = client.models.generate_content(
                model='gemini-2.0-flash-exp',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

        # Parse JSON response
        data = json.loads(response.text)
        title_kr = data.get('title_kr', title_en)
        summary_kr = data.get('summary_kr', f"[Translation Failed] API error. (Original: {description_en[:100]}...)")

        print(f"  [AI] ✓ Translation complete: {title_kr[:40]}...")
        return title_kr, summary_kr

    except json.JSONDecodeError as e:
        print(f"  [AI] ❌ JSON parsing error: {e}")
        return title_en, f"[Translation Failed] Invalid API response. (Original: {description_en[:100]}...)"
    
    except Exception as e:
        print(f"  [AI] ❌ API error: {e}")
        return title_en, f"[Translation Failed] API call failed. (Original: {description_en[:100]}...)"


# ============================================================================
# RSS Feed Scraper
# ============================================================================

def scrape_rss_feed(feed_url, source_name, category_name):
    """
    Scrapes articles from RSS feed with robust error handling.
    
    Args:
        feed_url (str): RSS feed URL
        source_name (str): Source name for identification
        category_name (str): Article category (News/Paper/Video)
        
    Returns:
        list: List of article dictionaries
    """
    articles = []
    print(f"🔍 [{source_name}] Crawling RSS... (URL: {feed_url})")

    try:
        response = requests.get(feed_url, headers=HEADERS, timeout=20)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '').lower()
        if not any(ct in content_type for ct in ['xml', 'rss', 'atom']):
            print(f"  ❌ Invalid content type: {content_type}")
            print(f"     Response preview: {response.text[:200]}...")
            return []

        feed = feedparser.parse(response.content)

        if feed.bozo:
            print(f"  ⚠️ Feed parsing warning: {feed.bozo_exception}")

        print(f"  [i] Found {len(feed.entries)} items")

        for entry in feed.entries:
            try:
                if not entry.get('title') or not entry.get('link'):
                    print("    ⚠️ Missing title or link. Skipping.")
                    continue

                title_en = entry.title
                link = entry.link
                description_en = entry.get('summary') or entry.get('description') or title_en
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)

                # Parse publication date
                date_str = datetime.now().strftime('%Y-%m-%d')
                if entry.get('published_parsed'):
                    try:
                        dt_obj = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        date_str = dt_obj.strftime('%Y-%m-%d')
                    except (TypeError, ValueError):
                        pass

                # Extract image URL
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
                print(f"  ✗ Failed to parse item: {item_err}")

    except requests.exceptions.RequestException as req_err:
        print(f"❌ [{source_name}] Request failed: {req_err}")
    except Exception as e:
        print(f"❌ [{source_name}] Unexpected error: {e}")

    return articles


# ============================================================================
# YouTube Channel Scraper
# ============================================================================

def scrape_youtube_videos(channel_id, source_name, category_name):
    """
    Scrapes latest videos from YouTube channel RSS feed.
    Video content will be analyzed by AI using URL Context.
    
    Args:
        channel_id (str): YouTube channel ID
        source_name (str): Source name for identification
        category_name (str): Article category
        
    Returns:
        list: List of video dictionaries
    """
    articles = []
    print(f"🔍 [{source_name}] Crawling YouTube... (Channel: {channel_id})")
    feed_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'

    try:
        response = requests.get(feed_url, headers=HEADERS, timeout=20)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '').lower()
        if 'xml' not in content_type:
            print(f"  ❌ Invalid content type: {content_type}")
            return []

        feed = feedparser.parse(response.content)

        if feed.bozo:
            print(f"  ⚠️ Feed parsing warning: {feed.bozo_exception}")

        print(f"  [i] Found {len(feed.entries)} latest videos")

        for entry in feed.entries:
            try:
                if not entry.get('title') or not entry.get('link'):
                    print("    ⚠️ Missing title or link. Skipping.")
                    continue

                title_en = entry.title
                link = entry.link
                video_id = link.split('v=')[-1]

                # Parse publication date
                date_str = datetime.now().strftime('%Y-%m-%d')
                if entry.get('published_parsed'):
                    dt_obj = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                    date_str = dt_obj.strftime('%Y-%m-%d')

                # Get high-quality thumbnail
                image_url = None
                if entry.get('media_thumbnail') and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0]['url'].replace('default.jpg', 'hqdefault.jpg')

                # Use RSS description as supplementary info for AI
                description_en = entry.get('media_description', entry.get('summary', title_en))
                description_text = BeautifulSoup(description_en, 'html.parser').get_text(strip=True)
                
                print(f"    [i] Video {video_id} loaded. AI will analyze URL directly.")

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
                print(f"  ✗ Failed to parse video: {item_err}")

    except requests.exceptions.RequestException as req_err:
        print(f"❌ [{source_name}] Request failed: {req_err}")
    except Exception as e:
        print(f"❌ [{source_name}] Unexpected error: {e}")

    return articles


# ============================================================================
# Main Execution
# ============================================================================

def main():
    """Main execution function for GitHub Actions workflow"""
    
    print("\n" + "="*60)
    print("📰 Daily Science News Crawler - Starting")
    print(f"🕐 Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")

    # ========================================================================
    # 1. Crawl all sources
    # ========================================================================
    
    all_articles_to_check = []
    
    # YouTube Channels
    all_articles_to_check.extend(
        scrape_youtube_videos('UCWgXoKQ4rl7SY9UHuAwxvzQ', 'B_ZCF YouTube', 'Video')
    )
    
    # News Sources
    all_articles_to_check.extend(scrape_rss_feed('https://www.thetransmitter.org/feed/', 'The Transmitter', 'Neuroscience'))
    
    # ========================================================================
    # 2. Load existing articles (last 7 days only)
    # ========================================================================
    
    seen_urls = set()
    final_article_list = []

    try:
        with open('articles.json', 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            for old_article in old_data.get('articles', []):
                try:
                    article_date = datetime.strptime(old_article.get('date', '1970-01-01'), '%Y-%m-%d')
                    if (datetime.now() - article_date).days <= ARCHIVE_DAYS:
                        if old_article.get('url'):
                            seen_urls.add(old_article['url'])
                            final_article_list.append(old_article)
                except ValueError:
                    continue
                    
        print(f"\n[i] Loaded {len(seen_urls)} existing URLs (last {ARCHIVE_DAYS} days)")
        
    except FileNotFoundError:
        print("\n[i] 'articles.json' not found. Creating new file.")
    except json.JSONDecodeError:
        print("\n[i] ❌ 'articles.json' is corrupted. Creating new file.")
        final_article_list = []
        seen_urls = set()

    # ========================================================================
    # 3. Process new articles with AI translation
    # ========================================================================
    
    new_articles = []
    existing_articles_count = 0
    new_article_count = 0
    api_errors = 0

    print(f"\n[i] Checking {len(all_articles_to_check)} items (max {MAX_NEW_ARTICLES_PER_RUN} new articles)")

    for article_data in all_articles_to_check:
        
        if not article_data.get('url'):
            print(f"  ⚠️ Missing URL (Source: {article_data.get('source', 'N/A')}). Skipping.")
            continue

        if article_data['url'] not in seen_urls:
            
            if new_article_count >= MAX_NEW_ARTICLES_PER_RUN:
                print(f"  [i] Reached limit ({MAX_NEW_ARTICLES_PER_RUN} articles). Stopping for quota protection.")
                break

            new_article_count += 1
            print(f"  [i] ✨ New item found ({new_article_count}/{MAX_NEW_ARTICLES_PER_RUN}): {article_data['title_en'][:50]}...")

            # Translate and summarize with AI
            title_kr, summary_kr = get_gemini_summary(article_data)

            if "[Translation Failed]" in summary_kr or "[요약 실패]" in summary_kr:
                api_errors += 1

            # Prepare final article object
            article_data['title'] = title_kr
            article_data['summary_kr'] = summary_kr
            article_data['summary_en'] = article_data['description_en']
            del article_data['description_en']

            new_articles.append(article_data)
            seen_urls.add(article_data['url'])

            time.sleep(API_DELAY_SECONDS)

        else:
            existing_articles_count += 1

    print(f"\n[i] Processed {new_article_count} new articles")
    print(f"    (Success: {new_article_count - api_errors}, API Errors: {api_errors})")
    print(f"    (Skipped {existing_articles_count} existing articles)")

    # ========================================================================
    # 4. Merge and deduplicate articles
    # ========================================================================
    
    final_article_list.extend(new_articles)

    # Remove any remaining duplicates
    final_seen_urls = set()
    deduplicated_list = []
    for article in final_article_list:
        if article.get('url') and article['url'] not in final_seen_urls:
            final_seen_urls.add(article['url'])
            deduplicated_list.append(article)

    # Sort by date (newest first)
    deduplicated_list.sort(key=lambda x: x.get('date', '1970-01-01'), reverse=True)

    # ========================================================================
    # 5. Save to JSON file
    # ========================================================================
    
    output = {
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'articles': deduplicated_list
    }

    json_file_path = 'articles.json'
    try:
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Success! Saved {len(deduplicated_list)} articles (last {ARCHIVE_DAYS} days + new)")
        print(f"📁 '{json_file_path}' updated")
    except Exception as write_err:
        print(f"\n❌ Failed to save JSON: {write_err}")
        sys.exit(1)

    # ========================================================================
    # 6. Print statistics
    # ========================================================================
    
    print("\n" + "="*60)
    print("📊 Collection Statistics (last 7 days + new):")
    print("="*60)
    
    sources = {}
    for article in deduplicated_list:
        source = article.get('source', 'Unknown')
        sources[source] = sources.get(source, 0) + 1

    for source, count in sorted(sources.items()):
        print(f"  • {source}: {count} articles")
    
    print("\n" + "="*60)
    print(f"🕐 End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")


if __name__ == '__main__':
    main()
