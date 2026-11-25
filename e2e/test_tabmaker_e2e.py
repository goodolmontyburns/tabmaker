import os
import sys
import time
import subprocess
import httpx
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = os.path.abspath("docs/screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


def wait_for_url(url: str, timeout: float = 20.0):
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
    print("STARTING TABMAKER PLAYWRIGHT E2E BROWSER TEST", flush=True)
    print("==================================================", flush=True)

    try:
        subprocess.run(["pkill", "-f", "uvicorn backend.main:app"], check=False)
        time.sleep(0.5)
    except Exception:
        pass

    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=os.path.abspath("."),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=sys.stderr,
    )

    frontend_proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
        cwd=os.path.abspath("frontend"),
        stdout=subprocess.DEVNULL,
        stderr=sys.stderr,
    )

    b_ok = wait_for_url("http://127.0.0.1:8000/health", timeout=20.0)
    f_ok = wait_for_url("http://127.0.0.1:5173", timeout=20.0)
    print(f"Backend ready: {b_ok} | Frontend ready: {f_ok}", flush=True)
    assert b_ok and f_ok, "Servers failed to start"

    page_errors = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 960})
            page = context.new_page()

            page.on("dialog", lambda dialog: dialog.accept())
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            page.goto("http://127.0.0.1:5173", wait_until="domcontentloaded", timeout=15000)
            page.evaluate("() => localStorage.clear()")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".ingest-panel", timeout=10000)
            page.wait_for_timeout(400)

            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "01_ingest_view.png"), full_page=True)

            # Test uploading Freddie King San-Ho-Zay cached WAV (25s)
            audio_file = os.path.abspath("temp_uploads/b7fcbab5-3c64-4ef4-87c3-5d9cc1ba0bf2/cropped.wav")
            if not os.path.exists(audio_file):
                audio_file = os.path.abspath("temp_uploads/benchmark/cropped.wav")
            print(f"Uploading solo audio {audio_file}...", flush=True)
            page.locator("input[type='file']").set_input_files(audio_file)
            page.locator("input[type='number']").nth(0).fill("0")
            page.locator("input[type='number']").nth(1).fill("25")
            page.locator("button:has-text('Transcribe Solo')").click()

            page.wait_for_selector(".workspace-card", timeout=240000)
            page.wait_for_timeout(2500)

            # Verify AlphaTab SVG engraved without error
            assert page.locator("text=Score render issue").count() == 0, "AlphaTab render error detected"
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "02_transcribed_score.png"), full_page=True)

            # Verify audio source toggles work
            for label in ("Lead Guitar", "Backing Track", "Full Mix"):
                btn = page.locator(f".stem-toggle button:has-text('{label}')")
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click()
                    page.wait_for_timeout(200)

            # Switch to Interactive 6-String Editor
            page.locator("button:has-text('Interactive 6-String Editor')").click()
            page.wait_for_timeout(1000)

            note_groups = page.locator("svg g.note-group")
            note_count = note_groups.count()
            print(f"Verified {note_count} SVG note groups rendered in Editor view.", flush=True)
            assert note_count >= 10, f"Expected >= 10 notes, got {note_count}"

            # Open interactive 6-string popover on first note
            page.locator("svg g.note-group text").first.click()
            page.wait_for_timeout(500)
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "04_note_editing_popover.png"), full_page=True)

            # Test MIDI Synth playback and moving red playhead
            page.locator("button:has-text('Play MIDI Solo')").click()
            page.wait_for_timeout(1500)
            playhead_x = page.evaluate("""() => {
                const line = document.querySelector("svg line[stroke='#dc2626']");
                return line ? parseFloat(line.getAttribute('x1') || '0') : 0;
            }""")
            print(f"MIDI Synth playhead x1={playhead_x:.1f}", flush=True)
            assert playhead_x > 45.0, "Red playhead did not advance during MIDI playback"
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "05_synth_playhead.png"), full_page=True)
            page.locator("button:has-text('Stop MIDI Synth')").click()

            # Test PDF Export button & AlphaTex button
            with page.expect_download(timeout=10000) as dl_pdf:
                page.locator("button:has-text('Export PDF')").click()
            print("PDF downloaded:", dl_pdf.value.suggested_filename, flush=True)

            with page.expect_download(timeout=10000) as dl_tex:
                page.locator("button:has-text('Export AlphaTex')").click()
            print("AlphaTex downloaded:", dl_tex.value.suggested_filename, flush=True)

            assert not page_errors, f"Uncaught page errors: {page_errors}"
            print("ALL PLAYWRIGHT E2E CHECKS PASSED!", flush=True)
            browser.close()
    finally:
        for proc in (backend_proc, frontend_proc):
            try:
                proc.terminate()
                proc.kill()
            except Exception:
                pass


if __name__ == "__main__":
    run_e2e_browser_test()
