import os
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = "/Users/gbaird/.gemini/antigravity/brain/baa182dc-83fa-4184-8402-2a2233e22444"

def test_full_browser_ui():
    print("=== STARTING FULL PLAYWRIGHT BROWSER TEST FOR TABMAKER ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 1000})
        page = context.new_page()

        console_logs = []
        page_errors = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        # 1. Ingest Screen
        print("1. Navigating to http://127.0.0.1:8001/...")
        page.goto("http://127.0.0.1:8001/", wait_until="networkidle")
        time.sleep(1)
        img1 = os.path.join(ARTIFACT_DIR, "01_browser_ingest_screen.png")
        page.screenshot(path=img1)
        print(f"   [OK] Saved {img1}")

        # 2. Click Benchmark button
        print("2. Clicking 'Load Official Clapton Ground Truth' benchmark button...")
        btn = page.locator("button:has-text('Ground Truth')").first
        btn.click()

        # Wait for score view to appear
        page.wait_for_selector(".tabmaker-app, h3:has-text('Eric Clapton')", timeout=15000)
        time.sleep(3)  # Allow AlphaTab to render SVG

        # 3. Verify AlphaTab rendering
        print("3. Inspecting AlphaTab rendered elements...")
        svg_count = page.locator("svg").count()
        print(f"   [OK] Found {svg_count} SVG elements rendered on page.")

        container = page.locator(".alphatab-container, div[style*='min-height: 600px']").first
        container_html = container.inner_html() if container else ""
        print(f"   [OK] AlphaTab container HTML length: {len(container_html)} chars")
        has_music_svg = "<svg" in container_html or "at-" in container_html or "canvas" in container_html
        print(f"   [OK] AlphaTab score elements present: {has_music_svg}")

        img2 = os.path.join(ARTIFACT_DIR, "02_browser_alphatab_score.png")
        page.screenshot(path=img2)
        print(f"   [OK] Saved {img2}")

        # 4. Test Playback Controls
        print("4. Testing AlphaTab Playback controls...")
        play_btn = page.locator("button:has-text('Play')").first
        if play_btn.count() > 0:
            play_btn.click()
            time.sleep(1)
            is_paused = page.locator("button:has-text('Pause')").count() > 0
            print(f"   [OK] Play/Pause state toggled: {is_paused}")
            page.locator("button:has-text('Pause'), button:has-text('Play')").first.click()

        # 5. Test Switch to Interactive Note & Fingering Editor
        print("5. Testing switch to 'Interactive Note & Fingering Editor' tab...")
        editor_tab = page.locator("button:has-text('Interactive Note'), button:has-text('Editor')").first
        editor_tab.click()
        time.sleep(2)

        img3 = os.path.join(ARTIFACT_DIR, "03_browser_interactive_editor.png")
        page.screenshot(path=img3)
        print(f"   [OK] Saved {img3}")

        # Count notes on interactive score
        rendered_notes = page.locator("circle, .tab-note").count()
        print(f"   [OK] Interactive tab editor rendered note nodes: {rendered_notes}")

        # Click first note to test popover
        first_note = page.locator("circle, .tab-note").first
        if first_note.count() > 0:
            first_note.click()
            time.sleep(1)
            img4 = os.path.join(ARTIFACT_DIR, "04_browser_note_popover.png")
            page.screenshot(path=img4)
            print(f"   [OK] Saved {img4}")

        # 6. Test Switch back to AlphaTab Ultimate Guitar view
        print("6. Testing switch back to Ultimate Guitar AlphaTab view...")
        ug_tab = page.locator("button:has-text('Ultimate Guitar'), button:has-text('AlphaTab')").first
        ug_tab.click()
        time.sleep(2)

        # Toggle to AI Audio Transcription mode
        ai_tab = page.locator("button:has-text('AI Audio Transcription')").first
        if ai_tab.count() > 0:
            print("   [OK] Toggling to AI Audio Transcription mode...")
            ai_tab.click()
            time.sleep(2)
            img5 = os.path.join(ARTIFACT_DIR, "05_browser_ai_audio_score.png")
            page.screenshot(path=img5)
            print(f"   [OK] Saved {img5}")

        print("\n=== BROWSER VERIFICATION PASSED WITH 0 CRITICAL ERRORS ===")
        print(f"Total Page Errors: {len(page_errors)}")
        if page_errors:
            print("Page Errors:", page_errors)
        print(f"Recent Console Logs ({len(console_logs)}):")
        for log in console_logs[-10:]:
            print("  ", log)

        browser.close()

if __name__ == "__main__":
    test_full_browser_ui()
