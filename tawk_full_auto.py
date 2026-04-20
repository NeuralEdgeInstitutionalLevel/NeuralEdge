"""
Full auto KB uploader - controls mouse and keyboard.
Tawk.to Knowledge Base must be open in the browser.
"""
import pyautogui
import pyperclip
import time
import re
import os

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15

# Parse articles
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
    articles.append({'title': clean, 'body': body})

print(f"Parsed {len(articles)} articles")
print("Starting in 3 seconds... DON'T TOUCH THE MOUSE!")
time.sleep(3)


def take_screenshot(name='screen_auto.png'):
    img = pyautogui.screenshot()
    img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), name))
    return img


def click_create_button():
    """Click the green + Create button"""
    # The Create button is at approximately x=311, y=163 based on the screenshot
    pyautogui.click(311, 163)
    time.sleep(2)


def fill_article(title, body):
    """Fill in article title and body after clicking Create"""
    # After clicking Create, a new article editor should open
    # Take screenshot to see the state
    time.sleep(1)

    # The title field should be focused or we need to find it
    # Try clicking where the title input would be (center-top area)
    pyautogui.click(750, 200)
    time.sleep(0.5)

    # Select all and paste title
    pyperclip.copy(title)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.2)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.5)

    # Tab to body or click body area
    pyautogui.press('tab')
    time.sleep(0.5)

    # Paste body
    pyperclip.copy(body)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.2)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.5)


# First, take a screenshot to confirm we're on the right page
take_screenshot('before_start.png')

for i, art in enumerate(articles):
    print(f"\n[{i+1}/{len(articles)}] Creating: {art['title'][:50]}...")

    # Step 1: Click "+ Create"
    click_create_button()

    # Step 2: Take screenshot to see the editor
    take_screenshot(f'step_{i+1}_editor.png')

    # Step 3: Fill in the article
    fill_article(art['title'], art['body'])

    # Step 4: Take screenshot to verify
    take_screenshot(f'step_{i+1}_filled.png')

    # Step 5: We need to find and click Save/Publish
    # This will vary - let's take a screenshot and handle it
    print(f"  Filled! Taking screenshot to find Save button...")

    # Wait a moment for the content to settle
    time.sleep(1)

    # Try to find a Save/Publish button - usually top right area
    # First attempt: look for it with screenshot
    break  # Stop after first article to check if it works

print("\nFirst article attempted. Check the screenshot files to verify.")
print("If it worked, I'll continue with the rest.")
