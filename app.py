# app.py - Pak Buy Pro Scraping Server
# Performance Mode B: Accurate scraping with Puppeteer + AI matching

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

app = Flask(__name__)
CORS(app)

# AI Server URL
AI_SERVER_URL = os.environ.get('AI_SERVER_URL', 'http://localhost:5000')

# User agents for anti-detection
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
]

def get_headers():
    """Generate realistic headers"""
    import random
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Referer': 'https://www.google.com/'
    }

def clean_price(price_text):
    """Extract numeric price"""
    if not price_text:
        return 0
    price = re.sub(r'[^\d.]', '', price_text)
    try:
        return int(float(price))
    except:
        return 0

def get_clean_title(original_title):
    """Get clean title from AI server with fallback"""
    try:
        response = requests.post(
            f'{AI_SERVER_URL}/clean-title',
            json={'title': original_title, 'timeout': 3},
            timeout=5
        )
        if response.ok:
            data = response.json()
            if data.get('success'):
                return data.get('cleaned', original_title)
    except:
        pass
    return clean_title_local(original_title)

def clean_title_local(title):
    """Local regex fallback"""
    garbage = ['PTA Approved', 'Official Warranty', 'Fast Shipping', 
               'Cash on Delivery', 'Free Delivery', 'Original', 'New', 'Sealed']
    cleaned = title
    for word in garbage:
        cleaned = re.sub(word, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()

def is_similar_product(title1, title2, threshold=0.70):
    """
    Advanced product matching using similarity ratio
    Threshold: 0.70 (70% match required)
    """
    # Normalize both titles
    t1 = title1.lower().strip()
    t2 = title2.lower().strip()
    
    # Calculate similarity
    similarity = SequenceMatcher(None, t1, t2).ratio()
    
    # Also check for key spec matches (RAM, storage)
    ram_pattern = r'(\d+)\s*GB\s*(?:RAM)?'
    storage_pattern = r'(\d+)\s*(?:GB|TB)\s*(?:Storage|SSD|HDD)?'
    
    t1_ram = re.search(ram_pattern, t1, re.IGNORECASE)
    t2_ram = re.search(ram_pattern, t2, re.IGNORECASE)
    
    t1_storage = re.search(storage_pattern, t1, re.IGNORECASE)
    t2_storage = re.search(storage_pattern, t2, re.IGNORECASE)
    
    # Boost similarity if RAM/storage match
    if t1_ram and t2_ram and t1_ram.group(1) == t2_ram.group(1):
        similarity += 0.05
    if t1_storage and t2_storage and t1_storage.group(1) == t2_storage.group(1):
        similarity += 0.05
    
    match = similarity >= threshold
    
    if match:
        print(f"✅ Match ({similarity:.2f}): '{t1[:40]}' ≈ '{t2[:40]}'")
    
    return match

# ============================================
# SITE SCRAPERS (Performance Mode B - Accurate)
# ============================================

def scrape_with_retry(scraper_func, *args, max_retries=2):
    """Retry scraping on failure"""
    for attempt in range(max_retries):
        try:
            result = scraper_func(*args)
            if result:
                return result
            time.sleep(1)  # Brief delay before retry
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Failed after {max_retries} attempts: {e}")
                return []
            time.sleep(2)
    return []

def scrape_priceoye(query):
    """Scrape PriceOye.pk with retry"""
    return scrape_with_retry(_scrape_priceoye, query)

def _scrape_priceoye(query):
    try:
        url = f'https://priceoye.pk/search?q={requests.utils.quote(query)}'
        print(f'🔍 Scraping PriceOye: {query}')
        
        response = requests.get(url, headers=get_headers(), timeout=15)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        
        # Multiple selector fallbacks
        items = (soup.find_all('div', class_='product-card') or 
                soup.find_all('div', class_='product-item') or
                soup.find_all('div', {'data-product': True}))[:5]
        
        for item in items:
            try:
                title_el = (item.find('h3') or 
                           item.find('a', class_='product-title') or
                           item.find(class_='title'))
                
                price_el = (item.find('span', class_='price-box') or 
                           item.find('div', class_='price') or
                           item.find(class_='product-price'))
                
                link_el = item.find('a')
                img_el = item.find('img')
                
                if title_el and price_el:
                    title = title_el.get_text(strip=True)
                    price = clean_price(price_el.get_text(strip=True))
                    link = link_el.get('href', '') if link_el else ''
                    img = img_el.get('src', '') if img_el else ''
                    
                    if not link.startswith('http'):
                        link = f'https://priceoye.pk{link}'
                    
                    if price > 0:
                        products.append({
                            'title': title,
                            'price': price,
                            'url': link,
                            'image': img,
                            'site': 'PriceOye'
                        })
            except Exception as e:
                continue
        
        print(f'✅ PriceOye: Found {len(products)} products')
        return products
        
    except Exception as e:
        print(f'❌ PriceOye error: {e}')
        return []

def scrape_mega(query):
    """Scrape Mega.pk with retry"""
    return scrape_with_retry(_scrape_mega, query)

def _scrape_mega(query):
    try:
        url = f'https://www.mega.pk/search/{requests.utils.quote(query)}'
        print(f'🔍 Scraping Mega.pk: {query}')
        
        response = requests.get(url, headers=get_headers(), timeout=15)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        
        items = (soup.find_all('div', class_='product-item') or
                soup.find_all('div', class_='product-box') or
                soup.find_all('article', class_='product'))[:5]
        
        for item in items:
            try:
                title_el = (item.find('h4') or 
                           item.find('h3') or
                           item.find('a', class_='product-name'))
                
                price_el = (item.find('span', class_='price') or
                           item.find('div', class_='price'))
                
                link_el = item.find('a')
                img_el = item.find('img')
                
                if title_el and price_el:
                    title = title_el.get_text(strip=True)
                    price = clean_price(price_el.get_text(strip=True))
                    link = link_el.get('href', '') if link_el else ''
                    img = img_el.get('src', '') if img_el else ''
                    
                    if not link.startswith('http'):
                        link = f'https://www.mega.pk{link}'
                    
                    if price > 0:
                        products.append({
                            'title': title,
                            'price': price,
                            'url': link,
                            'image': img,
                            'site': 'Mega'
                        })
            except:
                continue
        
        print(f'✅ Mega.pk: Found {len(products)} products')
        return products
        
    except Exception as e:
        print(f'❌ Mega.pk error: {e}')
        return []

def scrape_daraz(query):
    """Scrape Daraz.pk with retry"""
    return scrape_with_retry(_scrape_daraz, query)

def _scrape_daraz(query):
    try:
        url = f'https://www.daraz.pk/catalog/?q={requests.utils.quote(query)}'
        print(f'🔍 Scraping Daraz.pk: {query}')
        
        response = requests.get(url, headers=get_headers(), timeout=15)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        
        items = (soup.find_all('div', {'data-qa-locator': 'product-item'}) or
                soup.find_all('div', class_='product-item'))[:5]
        
        for item in items:
            try:
                title_el = (item.find('div', class_='title') or
                           item.find('a', class_='title'))
                
                price_el = (item.find('span', class_='price') or
                           item.find('div', class_='price'))
                
                link_el = item.find('a')
                img_el = item.find('img')
                
                if title_el and price_el:
                    title = title_el.get_text(strip=True)
                    price = clean_price(price_el.get_text(strip=True))
                    link = link_el.get('href', '') if link_el else ''
                    img = img_el.get('src', '') if img_el else ''
                    
                    if link and not link.startswith('http'):
                        link = f'https:{link}' if link.startswith('//') else f'https://www.daraz.pk{link}'
                    
                    if price > 0:
                        products.append({
                            'title': title,
                            'price': price,
                            'url': link,
                            'image': img,
                            'site': 'Daraz'
                        })
            except:
                continue
        
        print(f'✅ Daraz: Found {len(products)} products')
        return products
        
    except Exception as e:
        print(f'❌ Daraz error: {e}')
        return []

# ============================================
# MAIN COMPARISON ENDPOINT
# ============================================

@app.route('/compare', methods=['POST'])
def compare_prices():
    """
    Main price comparison endpoint
    Performance Mode B: High accuracy with AI matching
    """
    try:
        data = request.json
        original_title = data.get('title', '')
        current_price = data.get('current_price', 0)
        current_site = data.get('current_site', 'daraz').lower()
        
        if not original_title:
            return jsonify({'error': 'Title required'}), 400
        
        print(f'\n📥 Compare request: {original_title[:60]}...')
        print(f'💰 Current: Rs. {current_price:,} on {current_site}')
        
        start_time = time.time()
        
        # STEP 1: Clean title with AI
        cleaned_title = get_clean_title(original_title)
        clean_time = time.time() - start_time
        print(f'🧹 Cleaned: "{cleaned_title}" ({clean_time:.2f}s)')
        
        # STEP 2: Scrape sites in parallel (only PriceOye, Mega, Daraz)
        sites_to_scrape = {
            'priceoye': scrape_priceoye,
            'mega': scrape_mega,
            'daraz': scrape_daraz
        }
        
        # Remove current site
        if current_site in sites_to_scrape:
            del sites_to_scrape[current_site]
        
        all_results = []
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_site = {
                executor.submit(scraper, cleaned_title): site 
                for site, scraper in sites_to_scrape.items()
            }
            
            for future in as_completed(future_to_site):
                site = future_to_site[future]
                try:
                    results = future.result()
                    all_results.extend(results)
                except Exception as e:
                    print(f'❌ {site} failed: {e}')
        
        # STEP 3: Smart product matching (70% similarity threshold)
        matched_products = []
        for product in all_results:
            if is_similar_product(cleaned_title, product['title']):
                matched_products.append(product)
        
        print(f'🎯 Matched {len(matched_products)} of {len(all_results)} scraped products')
        
        # STEP 4: Find cheaper options
        cheaper_options = [
            p for p in matched_products 
            if p['price'] > 0 and p['price'] < current_price
        ]
        
        # Sort by price
        cheaper_options.sort(key=lambda x: x['price'])
        
        best_deal = cheaper_options[0] if cheaper_options else None
        total_time = time.time() - start_time
        
        response = {
            'success': True,
            'original_title': original_title,
            'cleaned_title': cleaned_title,
            'current_price': current_price,
            'current_site': current_site,
            'found_cheaper': len(cheaper_options) > 0,
            'cheaper_options': cheaper_options[:5],
            'best_deal': best_deal,
            'savings': current_price - best_deal['price'] if best_deal else 0,
            'total_results': len(all_results),
            'matched_results': len(matched_products),
            'search_time_ms': int(total_time * 1000)
        }
        
        if best_deal:
            print(f'💰 Best: {best_deal["site"]} - Rs. {best_deal["price"]:,} (Save Rs. {response["savings"]:,})')
        else:
            print(f'✅ {current_site.title()} has the best price!')
        
        print(f'⏱️  Total: {total_time:.2f}s\n')
        
        return jsonify(response)
        
    except Exception as e:
        print(f'❌ Error: {e}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({
        'status': 'ok',
        'service': 'Pak Buy Pro Scraping Server',
        'ai_server': AI_SERVER_URL,
        'sites': ['PriceOye', 'Mega', 'Daraz'],
        'mode': 'Performance B (Accurate)',
        'features': {
            'retry_logic': True,
            'similarity_matching': True,
            'ai_title_cleaning': True,
            'parallel_scraping': True
        }
    })

@app.route('/', methods=['GET'])
def index():
    """Welcome page"""
    return jsonify({
        'service': 'Pak Buy Pro Scraping Server',
        'version': '1.0.0',
        'mode': 'Performance B - High Accuracy',
        'endpoints': {
            '/health': 'Health check',
            '/compare': 'Compare prices (POST)'
        }
    })

# ============================================
# START SERVER
# ============================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    
    print("\n" + "="*50)
    print("🚀 Pak Buy Pro Scraping Server")
    print("="*50)
    print("🌐 Supported sites:")
    print("   • PriceOye.pk")
    print("   • Mega.pk")
    print("   • Daraz.pk")
    print(f"\n🤖 AI Server: {AI_SERVER_URL}")
    print("⚡ Performance Mode: B (High Accuracy)")
    print("🎯 Similarity Threshold: 70%")
    print("🔄 Retry Logic: Enabled")
    print(f"📍 Port: {port}")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=False)
