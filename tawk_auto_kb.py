"""
Tawk.to Knowledge Base Auto-Filler using PyAutoGUI.

HOW TO USE:
1. Open Edge browser
2. Go to Tawk.to dashboard -> Knowledge Base
3. Run this script
4. It will tell you what to do step by step
5. It types everything automatically using clipboard + keyboard

The script copies each article to clipboard and pastes it.
You just need to click "New Article" each time.
"""
import time
import re
import os
import sys
import pyautogui
import pyperclip

# Safety: move mouse to corner to abort
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

# ============================================================
# 1. Parse knowledge base
# ============================================================
KB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tawk_ai_knowledge.md')

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
    if 'PERSONALITY' in title.upper() or 'INSTRUCTION' in title.upper():
        custom_instructions = body
        continue
    clean = title
    if ':' in title:
        clean = title.split(':', 1)[-1].strip()
    clean = re.sub(r'^Article \d+\s*', '', clean).strip()
    if clean.startswith(': '):
        clean = clean[2:]
    articles.append({'title': clean, 'body': body})

print(f"\n{'='*60}")
print(f"  Tawk.to Knowledge Base Auto-Filler")
print(f"  {len(articles)} articles + 1 custom instruction")
print(f"{'='*60}\n")

# ============================================================
# 2. Custom Instructions first
# ============================================================
if custom_instructions:
    print("STEP 1: CUSTOM INSTRUCTIONS")
    print("-" * 40)
    print("In Tawk.to, go to: AI Assist -> Custom Instructions")
    print("Click inside the text box, then press ENTER here.")
    print("I'll paste the instructions automatically.\n")
    input(">>> Press ENTER when cursor is in Custom Instructions box...")

    pyperclip.copy(custom_instructions)
    time.sleep(0.3)
    pyautogui.hotkey('ctrl', 'a')  # Select all existing text
    time.sleep(0.2)
    pyautogui.hotkey('ctrl', 'v')  # Paste
    time.sleep(0.5)
    print("  PASTED! Now click Save in Tawk.to.\n")
    input(">>> Press ENTER when saved and ready for articles...")

# ============================================================
# 3. Articles one by one
# ============================================================
print(f"\nSTEP 2: KNOWLEDGE BASE ARTICLES ({len(articles)} total)")
print("-" * 40)
print("Go to: Knowledge Base in Tawk.to dashboard\n")

for i, art in enumerate(articles):
    print(f"\n[{i+1}/{len(articles)}] {art['title'][:55]}")
    print(f"  Click 'New Article' (or 'Add Article') in Tawk.to")
    print(f"  Then click inside the TITLE field")
    input(f"  >>> Press ENTER when cursor is in the title field...")

    # Type title
    pyperclip.copy(art['title'])
    time.sleep(0.2)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.1)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.3)

    print(f"  Title pasted! Now click inside the BODY/CONTENT area.")
    input(f"  >>> Press ENTER when cursor is in the body field...")

    # Paste body
    pyperclip.copy(art['body'])
    time.sleep(0.2)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.1)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.5)

    print(f"  Body pasted! Click Save/Publish in Tawk.to.")
    if i < len(articles) - 1:
        input(f"  >>> Press ENTER when saved (next: {articles[i+1]['title'][:40]}...)")
    else:
        print(f"\n  LAST ARTICLE DONE!")

print(f"\n{'='*60}")
print(f"  ALL {len(articles)} ARTICLES UPLOADED!")
print(f"  Don't forget to enable AI Assist in Tawk.to settings.")
print(f"{'='*60}")
