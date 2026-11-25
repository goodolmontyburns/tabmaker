import os
import sys
import time
import socket
import tempfile
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


def pick_free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_e2e_browser_test():
    print("==================================================", flush=True)
    print("STARTING TABMAKER PLAYWRIGHT E2E BROWSER TEST", flush=True)
    print("==================================================", flush=True)

    backend_port = int(os.environ.get("E2E_BACKEND_PORT") or pick_free_port(8011))
    frontend_port = int(os.environ.get("E2E_FRONTEND_PORT") or pick_free_port(5179))
    backend_url = f"http://127.0.0.1:{backend_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}"

    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(backend_port)],
        cwd=os.path.abspath("."),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=sys.stderr,
    )

    vite_log = tempfile.NamedTemporaryFile(mode="w+", suffix=".log", delete=False)
    fe_env = os.environ.copy()
    fe_env["VITE_API_TARGET"] = backend_url
    frontend_proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(frontend_port)],
        cwd=os.path.abspath("frontend"),
        env=fe_env,
        stdout=vite_log,
        stderr=subprocess.STDOUT,
    )

    b_ok = wait_for_url(f"{backend_url}/health", timeout=20.0)
    f_ok = wait_for_url(frontend_url, timeout=20.0)
    print(f"Backend ready ({backend_port}): {b_ok} | Frontend ready ({frontend_port}): {f_ok}", flush=True)
    assert b_ok and f_ok, "Servers failed to start"

    page_errors = []
    console_errors = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 960})
            page = context.new_page()

            page.on("dialog", lambda dialog: dialog.accept())
            page.on("pageerror", lambda err: page_errors.append(str(err)))
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

            page.goto(frontend_url, wait_until="domcontentloaded", timeout=15000)
            page.evaluate("() => localStorage.clear()")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".ingest-panel", timeout=10000)
            page.wait_for_timeout(400)

            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "01_ingest_view.png"), full_page=True)

            # Verify session 087173c1 (if present) renders with zero AlphaTex parse errors
            clapton_sid = "087173c1-5c73-4157-8161-deb8423e4cda"
            if os.path.exists(os.path.abspath(f"temp_uploads/{clapton_sid}/session.json")):
                page.evaluate(f"() => localStorage.setItem('last_tabmaker_session', '{clapton_sid}')")
                page.reload(wait_until="domcontentloaded")
                page.wait_for_selector(".workspace-card", timeout=15000)
                page.wait_for_timeout(2000)
                assert page.locator("text=Score render issue").count() == 0, "AlphaTex error on session 087173c1!"
                print(f"Verified cached multi-effect session {clapton_sid} rendered cleanly with zero AlphaTex errors.", flush=True)
                page.evaluate("() => localStorage.clear()")
                page.reload(wait_until="domcontentloaded")
                page.wait_for_selector(".ingest-panel", timeout=10000)

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

            # Verify Play Tab Synth initializes, plays, and advances .at-cursor-beat
            synth_btn = page.locator("button:has-text('Play Tab Synth'), button:has-text('Loading Synth'), button:has-text('Pause Tab Synth')")
            synth_btn.first.wait_for(state="visible", timeout=15000)
            # Wait for Play Tab Synth to become ready if SoundFont is still loading
            page.locator("button:has-text('Play Tab Synth')").wait_for(state="visible", timeout=20000)
            page.locator("button:has-text('Play Tab Synth')").click()
            page.locator("button:has-text('Pause Tab Synth')").wait_for(state="visible", timeout=10000)

            def _cursor_rect():
                return page.evaluate("""() => {
                    const el = document.querySelector('.at-cursor-beat');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return { x: r.x, y: r.y, style: el.getAttribute('style') || '' };
                }""")

            c1 = _cursor_rect()
            page.wait_for_timeout(1200)
            c2 = _cursor_rect()
            print(f"Tab Synth cursor c1={c1} -> c2={c2}", flush=True)
            assert c1 is not None and c2 is not None, "AlphaTab beat cursor (.at-cursor-beat) missing"
            assert (c1["x"] != c2["x"]) or (c1["y"] != c2["y"]) or (c1["style"] != c2["style"]), (
                f"AlphaTab beat cursor did not advance during Play Tab Synth ({c1} vs {c2})"
            )
            page.locator("button:has-text('Pause Tab Synth')").click()
            page.locator("button:has-text('Play Tab Synth')").wait_for(state="visible", timeout=5000)

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
            worker_console_errs = [c for c in console_errors if "alphaTab.worker" in c or "alphaTab.worklet" in c]
            assert not worker_console_errs, f"Console worker errors: {worker_console_errs}"
            print("ALL PLAYWRIGHT E2E CHECKS PASSED!", flush=True)
            browser.close()
    finally:
        for proc in (backend_proc, frontend_proc):
            try:
                proc.terminate()
                proc.kill()
            except Exception:
                pass
        vite_log.seek(0)
        vite_output = vite_log.read()
        vite_log.close()
        os.unlink(vite_log.name)
        assert "alphaTab.worker.mjs" not in vite_output, f"Vite emitted alphaTab.worker.mjs error:\n{vite_output}"
        assert "alphaTab.worklet.mjs" not in vite_output, f"Vite emitted alphaTab.worklet.mjs error:\n{vite_output}"
        print("Verified zero alphaTab worker/worklet errors in Vite dev server logs.", flush=True)


if __name__ == "__main__":
    run_e2e_browser_test()
