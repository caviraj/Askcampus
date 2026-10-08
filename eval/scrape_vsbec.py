import sys
import time
import re
from urllib.parse import urlparse
from scrapling import Fetcher

TARGET_URLS = [
    ("Homepage & Overview", "https://vsbec.edu.in/"),
    ("About VSB Engineering College", "https://vsbec.edu.in/about-us-vsb-engineering-college/"),
    ("Admissions", "https://vsbec.edu.in/admissions/"),
    ("Academics", "https://vsbec.edu.in/academics/"),
    ("Placement Overview", "https://vsbec.edu.in/about-placement/"),
    ("Placement Highlights", "https://vsbec.edu.in/highlights-placements/"),
    ("Contact Us", "https://vsbec.edu.in/contact-us/"),
    ("Infrastructure & Facilities", "https://vsbec.edu.in/infrastructure/"),
    ("Hostel Facilities", "https://vsbec.edu.in/hostel/"),
    ("Cafeteria & Dining", "https://vsbec.edu.in/cafeteria/"),
    ("Anti Ragging Policy", "https://vsbec.edu.in/anti-ragging/"),
    ("Achievements", "https://vsbec.edu.in/achievements/"),
    ("Computer Science & Engineering (CSE)", "https://vsbec.edu.in/computer-science-and-engineering/"),
    ("Artificial Intelligence & Data Science (AI-DS)", "https://vsbec.edu.in/ai-ds/"),
    ("Artificial Intelligence & Machine Learning (AI-ML)", "https://vsbec.edu.in/ai-ml/"),
    ("Computer Science & Business Systems (CSBS)", "https://vsbec.edu.in/computer-science-and-business-system/"),
    ("Electronics & Communication Engineering (ECE)", "https://vsbec.edu.in/ece/"),
    ("Electrical & Electronics Engineering (EEE)", "https://vsbec.edu.in/eee/"),
    ("Civil Engineering", "https://vsbec.edu.in/civil-engineering/"),
]

def clean_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    clean_lines = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                clean_lines.append("")
                prev_blank = True
        else:
            clean_lines.append(line)
            prev_blank = False
    return "\n".join(clean_lines).strip()

def extract_page_data(title: str, url: str) -> str:
    print(f"Scraping: {title} ({url}) ...", flush=True)
    try:
        response = Fetcher.get(url, timeout=30)
        if response.status != 200:
            print(f"  Failed with status {response.status}", flush=True)
            return f"## {title}\nURL: {url}\nStatus: {response.status} (Failed)\n\n"
        
        # Remove navigation, footer, scripts, styles if possible or extract main content
        main_text_parts = []
        
        # Try finding primary headings and paragraphs
        h1s = response.css("h1::text").getall()
        h2s = response.css("h2::text").getall()
        h3s = response.css("h3::text").getall()
        
        # Extract content containers (article, main, .entry-content, or body text)
        content_nodes = response.css("article, main, .entry-content, .content, #content, .elementor-widget-container")
        
        raw_text = ""
        if content_nodes:
            # Join text from content containers
            for node in content_nodes:
                text = node.text if hasattr(node, 'text') else ""
                if text:
                    raw_text += "\n" + text
        else:
            raw_text = response.text if hasattr(response, 'text') else ""
            
        cleaned = clean_text(raw_text)
        # If raw text is too short, get all paragraphs and list items
        if len(cleaned) < 100:
            p_items = response.css("p::text, li::text, span::text").getall()
            cleaned = "\n".join([p.strip() for p in p_items if len(p.strip()) > 20])
            
        output = [
            f"# {title}",
            f"Source URL: {url}",
            f"Extraction Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            cleaned,
            "\n" + ("=" * 60) + "\n"
        ]
        return "\n".join(output)
    except Exception as e:
        print(f"  Error scraping {url}: {e}", flush=True)
        return f"# {title}\nSource URL: {url}\nError: {e}\n\n"

def main():
    all_content = [
        "# V.S.B. ENGINEERING COLLEGE (VSBEC) - COMPREHENSIVE INSTITUTIONAL KNOWLEDGE BASE",
        "Extracted using Scrapling Web Scraper & Crawler",
        f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 80,
        ""
    ]
    
    for title, url in TARGET_URLS:
        content = extract_page_data(title, url)
        all_content.append(content)
        time.sleep(0.5)
        
    full_text = "\n".join(all_content)
    output_path = r"c:\Users\Caviraj\Desktop\hogwarts-legacy\eval\corpus\vsbec-knowledge-base.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_text)
        
    print(f"\nDone! Knowledge base saved to {output_path} ({len(full_text)} characters)", flush=True)

if __name__ == "__main__":
    main()
