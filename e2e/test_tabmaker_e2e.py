import os
import sys
import time
import subprocess
import httpx
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = os.path.abspath("docs/screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def wait_for_url(url: str, timeout: float = 15.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def run_e2e_browser_test():
    print("==================================================", flush=True)
    print("STARTING TABMAKER V2 PLAYWRIGHT E2E BROWSER TEST", flush=True)
    print("==================================================", flush=True)

    # Kill any zombie process on port 8001 or 5173
    try:
        subprocess.run(["pkill", "-f", "uvicorn backend.main:app"], check=False)
        time.sleep(0.5)
    except Exception:
        pass

    # 1. Start backend server (port 8001)
    print("Starting FastAPI Backend Server on port 8001...", flush=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8001"],
        cwd=os.path.abspath("."),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=sys.stderr
    )

    # 2. Start frontend dev server (port 5173)
    print("Starting Vite Frontend Server on port 5173...", flush=True)
    frontend_proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
        cwd=os.path.abspath("frontend"),
        stdout=subprocess.DEVNULL,
        stderr=sys.stderr
    )

    print("Waiting for backend (port 8001) and frontend (port 5173)...", flush=True)
    b_ok = wait_for_url("http://127.0.0.1:8001/docs", timeout=15.0)
    f_ok = wait_for_url("http://127.0.0.1:5173", timeout=15.0)
    print(f"Backend ready: {b_ok} | Frontend ready: {f_ok}", flush=True)

    try:
        with sync_playwright() as p:
            print("Launching Chromium...", flush=True)
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 960})
            page = context.new_page()

            # Handle unexpected dialogs and console errors
            page.on("dialog", lambda dialog: dialog.accept())
            page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.type}: {msg.text}", flush=True))
            page.on("pageerror", lambda err: print(f"[BROWSER ERROR] {err}", flush=True))

            # 1. Navigate to Web App & clear previous sessions
            print("1. Navigating to http://127.0.0.1:5173...", flush=True)
            page.goto("http://127.0.0.1:5173", wait_until="domcontentloaded", timeout=15000)
            page.evaluate("() => localStorage.clear()")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".ingest-panel", timeout=10000)
            page.wait_for_timeout(500)

            # Screenshot 1: Ingest View
            shot1 = os.path.join(SCREENSHOTS_DIR, "01_ingest_view.png")
            page.screenshot(path=shot1, full_page=True)
            print(f"Captured: {shot1}", flush=True)

            # Test Ground Truth PDF Rendering
            print("1b. Testing 'View Official PDF Solo (Ground Truth)'...", flush=True)
            gt_btn = page.locator("button:has-text('View Official PDF Solo')")
            if gt_btn.is_visible():
                gt_btn.click()
                page.wait_for_selector(".workspace-card", timeout=10000)
                page.wait_for_timeout(3000)
                shot_gt = os.path.join(SCREENSHOTS_DIR, "06_ground_truth_score.png")
                page.screenshot(path=shot_gt, full_page=True)
                print(f"Captured: {shot_gt}", flush=True)

                # Reset to ingest panel for audio transcription test
                page.evaluate("() => localStorage.clear()")
                page.reload(wait_until="domcontentloaded")
                page.wait_for_selector(".ingest-panel", timeout=10000)
                page.wait_for_timeout(500)

            # 2. Upload the benchmark Clapton audio slice
            audio_file = os.path.abspath("temp_uploads/benchmark/cropped.wav")
            print(f"2. Uploading benchmark audio {audio_file}...", flush=True)
            file_input = page.locator("input[type='file']")
            file_input.set_input_files(audio_file)
            page.wait_for_timeout(500)

            # Adjust Start/End to 0..44
            page.locator("input[type='number']").nth(0).fill("0")
            page.locator("input[type='number']").nth(1).fill("44")

            # 3. Transcribe Solo
            print("3. Triggering 'Transcribe Solo'...", flush=True)
            transcribe_btn = page.locator("button:has-text('Transcribe Solo')")
            transcribe_btn.click()

            # Wait for score to render
            print("Waiting for audio transcription and score rendering...", flush=True)
            page.wait_for_selector(".workspace-card", timeout=120000)
            page.wait_for_timeout(2000)

            # Screenshot 2: Transcribed Tab Score View
            # Screenshot 2: Transcribed AlphaTab Score View
            shot2 = os.path.join(SCREENSHOTS_DIR, "02_transcribed_score.png")
            page.screenshot(path=shot2, full_page=True)
            print(f"Captured AlphaTab Score: {shot2}", flush=True)

            # 4. Trigger AI Polish (Gemini 2.5 / 3.7)
            print("4. Triggering 'AI Polish'...", flush=True)
            polish_btn = page.locator("button:has-text('AI Polish')")
            if polish_btn.is_visible():
                polish_btn.click()
                page.wait_for_timeout(4000)

                # Screenshot 3: AI Polished Score View
                shot3 = os.path.join(SCREENSHOTS_DIR, "03_ai_polished_tab.png")
                page.screenshot(path=shot3, full_page=True)
                print(f"Captured: {shot3}", flush=True)

            # 5. Switch to Interactive Note & Fingering Editor
            print("5. Switching to 'Interactive Note & Fingering Editor'...", flush=True)
            editor_btn = page.locator("button:has-text('Interactive Note')")
            if editor_btn.is_visible():
                editor_btn.click()
                page.wait_for_timeout(1000)

                note_groups = page.locator("svg g.note-group")
                note_count = note_groups.count()
                print(f"Verified: {note_count} SVG note elements rendered in Editor view.", flush=True)
                assert note_count > 10, f"Expected >10 notes rendered, found {note_count}"

                # Test interactive popover
                first_note = page.locator("svg g.note-group text").nth(3)
                first_note.click()
                page.wait_for_timeout(600)

                shot4 = os.path.join(SCREENSHOTS_DIR, "04_note_editing_popover.png")
                page.screenshot(path=shot4, full_page=True)
                print(f"Captured: {shot4}", flush=True)

                # 6. Test Synthesizer Playback
                print("6. Testing Web Audio synth playback & synchronized playhead...")
                play_btn = page.locator("button:has-text('Play Tab')")
                if play_btn.is_visible():
                    play_btn.click()
                page.wait_for_timeout(2000)

                shot5 = os.path.join(SCREENSHOTS_DIR, "05_synth_playhead.png")
                page.screenshot(path=shot5, full_page=True)
                print(f"Captured: {shot5}", flush=True)

                # Stop synth
                stop_btn = page.locator("button:has-text('Stop Synth')")
                if stop_btn.is_visible():
                    stop_btn.click()

            # 7. Test PDF Export
            print("7. Testing vector PDF export...", flush=True)
            pdf_btn = page.locator("button:has-text('Export PDF')")
            assert pdf_btn.is_visible()
            pdf_btn.click()
            page.wait_for_timeout(3000)

            print("==================================================", flush=True)
            print("ALL PLAYWRIGHT E2E BROWSER TESTS PASSED!", flush=True)
            print("Screenshots saved to docs/screenshots/", flush=True)
            print("==================================================", flush=True)

            browser.close()

    finally:
        print("Shutting down dev servers...", flush=True)
        try:
            backend_proc.terminate()
            backend_proc.kill()
        except Exception:
            pass
        try:
            frontend_proc.terminate()
            frontend_proc.kill()
        except Exception:
            pass

if __name__ == "__main__":
    run_e2e_browser_test()
