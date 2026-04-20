"""
Tawk.to Knowledge Base Auto-Uploader via Selenium.

How it works:
1. Opens Chrome with your existing profile (already logged into Tawk.to)
2. Navigates to Knowledge Base
3. Creates each article automatically
4. You just watch it work

Usage:
    python tawk_auto_upload.py

If Chrome profile doesn't work, it will open fresh Chrome -- log in manually,
then press Enter in the terminal to continue.
"""
import time
import re
import os
import sys

from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============================================================
# 1. Parse knowledge base file
# ============================================================
KB_PATH = os.path.join(os.path.dirname(__file__), 'tawk_ai_knowledge.md')

with open(KB_PATH, 'r', encoding='utf-8') as f:
    text = f.read()

sections = re.split(r'^## ', text, flags=re.MULTILINE)
articles = []
custom_instructions = None

for s in sections:
    s = s.strip()
    if not s or len(s) < 50:
        continue
    lines = s.split('\n')
    title = lines[0].strip()
    body = '\n'.join(lines[1:]).strip()
    if not body:
        continue

    if 'PERSONALITY' in title.upper() or 'INSTRUCTIONS' in title.upper():
        custom_instructions = body
        continue

    # Clean title
    clean_title = title
    if ':' in title:
        clean_title = title.split(':', 1)[-1].strip()
    clean_title = re.sub(r'^Article \d+\s*', '', clean_title).strip()
    if clean_title.startswith(': '):
        clean_title = clean_title[2:]

    articles.append({'title': clean_title, 'body': body})

print(f"Parsed {len(articles)} articles + custom instructions")
print(f"Articles:")
for i, a in enumerate(articles):
    print(f"  {i+1}. {a['title'][:60]}")

# ============================================================
# 2. Setup Chrome
# ============================================================
print("\n" + "="*60)
print("  Starting Chrome...")
print("="*60)

opts = Options()
# Use existing Edge profile for auto-login
edge_profile = os.path.expanduser("~") + r"\AppData\Local\Microsoft\Edge\User Data"
if os.path.exists(edge_profile):
    opts.add_argument(f"--user-data-dir={edge_profile}")
    opts.add_argument("--profile-directory=Default")
    print(f"  Using Edge profile: {edge_profile}")
else:
    print("  No Edge profile found, will need manual login")

opts.add_argument("--start-maximized")
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_experimental_option("excludeSwitches", ["enable-automation"])

try:
    driver = webdriver.Edge(options=opts)
except Exception as e:
    print(f"  Edge with profile failed: {e}")
    print("  Trying without profile...")
    opts2 = Options()
    opts2.add_argument("--start-maximized")
    driver = webdriver.Edge(options=opts2)

wait = WebDriverWait(driver, 30)

# ============================================================
# 3. Navigate to Tawk.to Knowledge Base
# ============================================================
PROPERTY_ID = "69e5919ddb71601c34edb7fd"
KB_URL = f"https://dashboard.tawk.to/#/admin/{PROPERTY_ID}/kb"

print(f"\n  Navigating to: {KB_URL}")
driver.get("https://dashboard.tawk.to/")
time.sleep(3)

# Check if logged in
if "login" in driver.current_url.lower() or "signin" in driver.current_url.lower():
    print("\n" + "!"*60)
    print("  NOT LOGGED IN - Please log in manually in the browser")
    print("  Then press ENTER here to continue...")
    print("!"*60)
    input()

driver.get(KB_URL)
time.sleep(5)

print("  On Knowledge Base page")

# ============================================================
# 4. Create articles
# ============================================================
print(f"\n  Creating {len(articles)} articles...")
print("  NOTE: If this is the first time, you may need to create")
print("  a Knowledge Base first in the Tawk.to UI.")
print()

input("  Press ENTER when the Knowledge Base page is loaded and ready...")

for i, article in enumerate(articles):
    print(f"\n  [{i+1}/{len(articles)}] Creating: {article['title'][:50]}...")

    try:
        # Look for "New Article" or "Add Article" button
        try:
            new_btn = driver.find_element(By.XPATH,
                "//button[contains(text(),'New Article') or contains(text(),'Add Article') or contains(text(),'Create')]")
            new_btn.click()
            time.sleep(2)
        except:
            # Try alternative selectors
            try:
                new_btn = driver.find_element(By.CSS_SELECTOR, "[data-test='kb-new-article'], .btn-primary, .add-article-btn")
                new_btn.click()
                time.sleep(2)
            except:
                print(f"    Could not find 'New Article' button. Trying direct URL...")
                driver.get(f"{KB_URL}/article/new")
                time.sleep(3)

        # Find title input
        try:
            title_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,
                "input[placeholder*='title' i], input[name='title'], input[type='text']:first-of-type, .article-title input")))
            title_input.clear()
            title_input.send_keys(article['title'])
            time.sleep(0.5)
        except:
            print(f"    Could not find title input, trying contenteditable...")
            title_input = driver.find_element(By.CSS_SELECTOR, "[contenteditable='true']")
            title_input.clear()
            title_input.send_keys(article['title'])

        # Find body/content area
        time.sleep(1)
        try:
            # Try contenteditable div (rich text editor)
            body_area = driver.find_element(By.CSS_SELECTOR,
                ".ql-editor, .ProseMirror, [contenteditable='true']:not(input), .article-body textarea, textarea")
            body_area.click()
            time.sleep(0.3)
            body_area.clear()

            # Send text in chunks to avoid issues
            chunk_size = 500
            body_text = article['body']
            for j in range(0, len(body_text), chunk_size):
                chunk = body_text[j:j+chunk_size]
                body_area.send_keys(chunk)
                time.sleep(0.1)

            time.sleep(0.5)
        except Exception as e:
            print(f"    Body input error: {e}")
            # Try JavaScript injection
            try:
                editors = driver.find_elements(By.CSS_SELECTOR, "[contenteditable='true']")
                if len(editors) > 1:
                    driver.execute_script("arguments[0].innerText = arguments[1]", editors[-1], article['body'])
                time.sleep(0.5)
            except:
                print(f"    FAILED to enter body text")
                continue

        # Try to save/publish
        time.sleep(1)
        try:
            save_btn = driver.find_element(By.XPATH,
                "//button[contains(text(),'Save') or contains(text(),'Publish') or contains(text(),'Create')]")
            save_btn.click()
            time.sleep(2)
        except:
            try:
                save_btn = driver.find_element(By.CSS_SELECTOR, ".btn-primary, .save-btn, [data-test='save']")
                save_btn.click()
                time.sleep(2)
            except:
                print(f"    Could not find Save button -- please save manually")
                input(f"    Press ENTER after saving article {i+1}...")

        print(f"    Done!")

        # Navigate back to KB list
        time.sleep(1)
        driver.get(KB_URL)
        time.sleep(3)

    except Exception as e:
        print(f"    ERROR: {e}")
        print(f"    Skipping this article. Press ENTER to continue...")
        input()
        driver.get(KB_URL)
        time.sleep(3)

# ============================================================
# 5. Custom Instructions
# ============================================================
if custom_instructions:
    print("\n" + "="*60)
    print("  CUSTOM INSTRUCTIONS")
    print("="*60)
    print("  The AI personality instructions need to be pasted in:")
    print("  Tawk.to -> AI Assist -> Custom Instructions")
    print()
    print("  I'll copy it to your clipboard now...")

    try:
        import subprocess
        process = subprocess.Popen(['clip'], stdin=subprocess.PIPE)
        process.communicate(custom_instructions.encode('utf-8'))
        print("  COPIED to clipboard! Go paste it in AI Assist -> Custom Instructions")
    except:
        print("  Could not copy to clipboard. The text is saved in tawk_ai_knowledge.md")

print("\n" + "="*60)
print(f"  DONE! {len(articles)} articles processed.")
print("  Don't forget to paste Custom Instructions in AI Assist!")
print("="*60)

input("\nPress ENTER to close browser...")
driver.quit()
