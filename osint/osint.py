import requests
from bs4 import BeautifulSoup
import re
import time
import datetime
import random
from urllib.parse import urljoin, urlparse

# ============================================================
# OSINT WEB SCRAPER
# ============================================================
# What this tool does:
# 1. Fetches a target website
# 2. Extracts emails, links, and metadata
# 3. Checks robots.txt for allowed/disallowed paths
# 4. Identifies technologies used by the site
# 5. Saves a full report to a file
# ============================================================

# Pretend to be a real browser so websites don't block us
# This is called a 'User Agent' — every browser sends one
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

GANDALF_REACTIONS = [
    "🧙 'Even the most guarded secrets leave traces for those who know where to look!'",
    "🧙 'Knowledge is the greatest weapon. And we have gathered much today!'",
    "🧙 'Like reading the threads of fate — the web reveals all to patient eyes!'",
    "🧙 'A wizard sees what others overlook. These findings are most illuminating!'",
]

def fetch_page(url):
    """
    Fetches a web page and returns its HTML content.
    
    requests.get() sends an HTTP GET request — the same thing
    your browser does when you visit a website.
    
    response.status_code tells us if it worked:
    - 200 = OK (success)
    - 404 = Not Found
    - 403 = Forbidden
    - 500 = Server Error
    
    timeout=10 means give up after 10 seconds — prevents
    hanging forever on slow or unresponsive sites.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()  # Raises exception for 4xx/5xx errors
        return response
    except requests.exceptions.ConnectionError:
        print(f"❌ Could not connect to {url}")
        return None
    except requests.exceptions.Timeout:
        print(f"❌ Request timed out for {url}")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None

def check_robots_txt(base_url):
    """
    Checks the robots.txt file of a website.
    
    robots.txt is a standard file that tells web crawlers
    what they are and aren't allowed to access.
    It's publicly available at domain.com/robots.txt
    
    In OSINT, robots.txt is interesting because:
    - Disallowed paths hint at hidden/sensitive areas
    - It reveals the site structure
    - It shows what the site owner wants to hide from crawlers!
    """
    robots_url = urljoin(base_url, "/robots.txt")
    print(f"\n🤖 Checking robots.txt: {robots_url}")

    response = fetch_page(robots_url)
    if not response:
        print("   robots.txt not found")
        return []

    lines = response.text.splitlines()
    disallowed = []
    allowed = []

    for line in lines:
        line = line.strip()
        if line.lower().startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                disallowed.append(path)
                print(f"   🚫 Disallowed: {path}")
        elif line.lower().startswith("allow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                allowed.append(path)

    if not disallowed:
        print("   No disallowed paths found")

    return disallowed

def extract_emails(text):
    """
    Uses REGEX to find email addresses in text.
    
    Remember regex from the password checker? Here we use it
    to find patterns that look like email addresses.
    
    The pattern r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    means:
    - [a-zA-Z0-9._%+-]+ = one or more valid email characters
    - @ = literal @ symbol
    - [a-zA-Z0-9.-]+ = domain name
    - \. = literal dot
    - [a-zA-Z]{2,} = top level domain (com, org, net etc)
    """
    email_pattern = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+[.][a-zA-Z]{2,}'
    emails = re.findall(email_pattern, text)
    # Remove duplicates while preserving order
    return list(dict.fromkeys(emails))

def extract_links(soup, base_url):
    """
    Extracts all links from a page using BeautifulSoup.
    
    BeautifulSoup parses HTML and lets us search it like a database.
    soup.find_all("a") finds every <a> anchor tag on the page.
    tag.get("href") gets the href attribute value — the URL.
    
    urljoin() converts relative URLs to absolute:
    "/about" + "https://example.com" = "https://example.com/about"
    
    We separate internal links (same domain) from external links
    (different domains) — both are useful for different reasons.
    """
    internal_links = set()
    external_links = set()
    base_domain = urlparse(base_url).netloc

    for tag in soup.find_all("a", href=True):
        href = tag.get("href")

        # Skip empty links, javascript, and anchors
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue

        # Convert relative URLs to absolute
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Only keep http/https links
        if parsed.scheme not in ("http", "https"):
            continue

        if parsed.netloc == base_domain:
            internal_links.add(full_url)
        else:
            external_links.add(full_url)

    return sorted(internal_links), sorted(external_links)

def extract_metadata(soup):
    """
    Extracts metadata from HTML head tags.
    
    Every web page has a <head> section with metadata —
    information ABOUT the page rather than visible content.
    This includes title, description, keywords, and more.
    
    soup.find("title") finds the <title> tag.
    soup.find_all("meta") finds all <meta> tags.
    tag.get("content") gets the content attribute.
    
    Metadata is goldmine for OSINT — reveals site purpose,
    technology stack hints, and sometimes contact info.
    """
    metadata = {}

    # Page title
    title = soup.find("title")
    metadata["title"] = title.text.strip() if title else "Not found"

    # Meta tags
    for tag in soup.find_all("meta"):
        name = tag.get("name", "").lower()
        prop = tag.get("property", "").lower()
        content = tag.get("content", "")

        if name in ("description", "keywords", "author", "generator"):
            metadata[name] = content
        elif prop in ("og:title", "og:description", "og:site_name"):
            metadata[prop] = content

    return metadata

def detect_technologies(response, soup):
    """
    Tries to identify what technologies the website uses.
    
    HTTP response headers often reveal the server software:
    - 'Server: Apache/2.4.41' reveals the web server
    - 'X-Powered-By: PHP/7.4' reveals the backend language
    
    We also look for common JavaScript framework signatures
    in the page HTML — script tags with recognizable names.
    
    This is called 'fingerprinting' — a core recon technique!
    """
    technologies = []

    # Check response headers
    headers = response.headers

    server = headers.get("Server", "")
    if server:
        technologies.append(f"Server: {server}")

    powered_by = headers.get("X-Powered-By", "")
    if powered_by:
        technologies.append(f"Powered By: {powered_by}")

    # Check for common frameworks in HTML
    html = str(soup)
    tech_signatures = {
        "WordPress": ["wp-content", "wp-includes"],
        "React": ["react.js", "react.min.js", "_react"],
        "jQuery": ["jquery.js", "jquery.min.js"],
        "Bootstrap": ["bootstrap.css", "bootstrap.min.css"],
        "Angular": ["angular.js", "ng-app"],
        "Vue.js": ["vue.js", "vue.min.js"],
        "Cloudflare": ["cloudflare", "__cf_bm"],
        "Google Analytics": ["google-analytics.com", "gtag"],
    }

    for tech, signatures in tech_signatures.items():
        if any(sig in html for sig in signatures):
            technologies.append(f"Framework/Service: {tech}")

    return technologies

def save_report(target_url, results):
    """
    Saves the full OSINT report to a text file.
    
    We create a timestamped filename so reports don't overwrite
    each other — you can run multiple scans and keep all results.
    
    datetime.now().strftime() formats the date/time as a string.
    '%Y%m%d_%H%M%S' = '20260608_175435' (year month day _ hour min sec)
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    domain = urlparse(target_url).netloc.replace(".", "_")
    filename = f"osint_{domain}_{timestamp}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("🧙 GANDALF'S OSINT REPORT\n")
        f.write("=" * 60 + "\n")
        f.write(f"Target: {target_url}\n")
        f.write(f"Scanned: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")

        for section, data in results.items():
            f.write(f"\n{'='*20} {section.upper()} {'='*20}\n")
            if isinstance(data, list):
                for item in data:
                    f.write(f"  {item}\n")
            elif isinstance(data, dict):
                for key, value in data.items():
                    f.write(f"  {key}: {value}\n")
            else:
                f.write(f"  {data}\n")

    print(f"\n💾 Report saved to: {filename}")
    return filename

def scan_target(url):
    """
    Main scanning function — runs all OSINT checks on a target.
    """
    # Make sure URL has a scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    print("\n" + "=" * 60)
    print("🧙 GANDALF'S OSINT SCANNER")
    print("=" * 60)
    print(f"🎯 Target: {url}")
    print(f"⏰ Started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {}

    # Step 1 — Fetch the page
    print("\n📡 Fetching target page...")
    response = fetch_page(url)
    if not response:
        print("❌ Could not reach target. Scan aborted.")
        return

    print(f"✅ Connected! Status: {response.status_code}")
    print(f"📦 Page size: {len(response.content):,} bytes")

    # Parse HTML with BeautifulSoup
    # "html.parser" is Python's built in HTML parser — no extra install needed
    soup = BeautifulSoup(response.text, "html.parser")

    # Step 2 — Extract metadata
    print("\n📋 Extracting metadata...")
    metadata = extract_metadata(soup)
    results["Metadata"] = metadata
    for key, value in metadata.items():
        print(f"   {key}: {value}")

    # Step 3 — Detect technologies
    print("\n🔧 Detecting technologies...")
    technologies = detect_technologies(response, soup)
    results["Technologies"] = technologies
    if technologies:
        for tech in technologies:
            print(f"   ✅ {tech}")
    else:
        print("   No technologies detected")

    # Step 4 — Extract emails
    print("\n📧 Searching for email addresses...")
    emails = extract_emails(response.text)
    results["Emails"] = emails
    if emails:
        for email in emails:
            print(f"   📧 {email}")
    else:
        print("   No emails found on this page")

    # Step 5 — Extract links
    print("\n🔗 Extracting links...")
    internal_links, external_links = extract_links(soup, url)
    results["Internal Links"] = list(internal_links)[:20]  # Limit to 20
    results["External Links"] = list(external_links)[:20]
    print(f"   Internal links: {len(internal_links)}")
    print(f"   External links: {len(external_links)}")

    # Show first few internal links
    if internal_links:
        print("\n   First 5 internal links:")
        for link in list(internal_links)[:5]:
            print(f"   → {link}")

    # Step 6 — Check robots.txt
    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    disallowed = check_robots_txt(base_url)
    results["Robots.txt Disallowed"] = disallowed

    # Step 7 — Summary
    print("\n" + "=" * 60)
    print("📊 SCAN SUMMARY")
    print("=" * 60)
    print(f"✅ Page title:       {metadata.get('title', 'N/A')}")
    print(f"✅ Technologies:     {len(technologies)} detected")
    print(f"✅ Emails found:     {len(emails)}")
    print(f"✅ Internal links:   {len(internal_links)}")
    print(f"✅ External links:   {len(external_links)}")
    print(f"✅ Disallowed paths: {len(disallowed)}")
    print("=" * 60)
    print(f"\n{random.choice(GANDALF_REACTIONS)}")

    # Save report
    save_report(url, results)

def main():
    print("🧙 GANDALF'S OSINT SCANNER")
    print("=" * 60)
    print("*peers into the digital realm with all-seeing eyes*")
    print("Every website leaves traces for those who know where to look...\n")

    while True:
        print("\nWhat would you like to do?")
        print("1. Scan a target website")
        print("2. Quit")

        choice = input("\nEnter choice (1-2): ").strip()

        if choice == "1":
            url = input("\nEnter target URL (e.g. example.com): ").strip()
            if url:
                scan_target(url)
            else:
                print("❌ Please enter a URL!")

        elif choice == "2":
            print("\n🧙 'Knowledge gathered, now use it wisely. Farewell!'")
            break

        else:
            print("❌ Invalid choice!")

if __name__ == "__main__":
    main()