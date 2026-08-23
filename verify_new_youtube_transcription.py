import os
import time
import requests
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = "/Users/gbaird/.gemini/antigravity/brain/baa182dc-83fa-4184-8402-2a2233e22444"

def test_new_youtube_workflow():
    print("=" * 80)
    print("VERIFICATION: GENUINE END-TO-END NEW YOUTUBE TRANSCRIPTION (SAN-HO-ZAY)")
    print("=" * 80)

    url = "https://www.youtube.com/watch?v=aUYcv0RTtKc"
    api_endpoint = "http://127.0.0.1:8001/process"

    print(f"\n1. Submitting New YouTube Video to POST /process...")
    print(f"   URL: {url} (Start: 0s, End: 25s)")
    data = {
        "youtube_url": url,
        "start_time": 0.0,
        "end_time": 25.0,
        "target_fret": 8
    }
    
    t0 = time.time()
    resp = requests.post(api_endpoint, data=data, timeout=120)
    elapsed = time.time() - t0
    
    assert resp.status_code == 200, f"Expected 200 OK, got {resp.status_code}: {resp.text}"
    res_data = resp.json()
    
    title = res_data.get("title", "")
    key = res_data.get("key", "")
    duration = res_data.get("duration", 0)
    notes = res_data.get("notes", [])
    is_gt = res_data.get("is_ground_truth", True)
    session_id = res_data.get("session_id", "")

    print(f"   ✓ Process completed in {elapsed:.1f}s")
    print(f"   -> Detected Title: '{title}'")
    print(f"   -> Detected Key: '{key}'")
    print(f"   -> Duration: {duration:.1f}s")
    print(f"   -> Extracted Notes: {len(notes)}")
    print(f"   -> is_ground_truth: {is_gt}")

    assert "San-Ho-Zay" in title or "Freddie" in title or "King" in title, f"Expected San-Ho-Zay title, got: {title}"
    assert is_gt is False, "Expected is_ground_truth to be False for real YouTube ingest!"
    assert duration == 25.0, f"Expected duration 25.0s, got {duration}"
    assert len(notes) > 10, f"Expected at least 10 notes, got {len(notes)}"

    # --------------------------------------------------------------------
    # Check Dyad Quantization in Extracted Notes
    # --------------------------------------------------------------------
    print("\n2. Checking Dyad Timestamp Quantization in Transcribed Notes...")
    dyad_pairs = []
    for i in range(len(notes) - 1):
        n1 = notes[i]
        n2 = notes[i+1]
        if abs(n1["t"] - n2["t"]) <= 0.085 and n1["s"] != n2["s"]:
            dyad_pairs.append((n1, n2))

    print(f"   Found {len(dyad_pairs)} simultaneous dyad note pairs in San-Ho-Zay:")
    for n1, n2 in dyad_pairs:
        print(f"     Dyad: t1={n1['t']:.3f} (s={n1['s']}, f={n1['f']}) | t2={n2['t']:.3f} (s={n2['s']}, f={n2['f']}) | exact_same_t={n1['t'] == n2['t']}")
        assert n1["t"] == n2["t"], f"Dyad notes must share the EXACT same onset timestamp: {n1['t']} vs {n2['t']}"

    # --------------------------------------------------------------------
    # Browser UI Verification with Playwright
    # --------------------------------------------------------------------
    print("\n3. Testing Browser UI Rendering of the New Video in Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1100})
        page.goto("http://127.0.0.1:8001/")

        # Wait for resumed session (last session is automatically loaded)
        page.wait_for_selector(f"h3:has-text('{title}')", timeout=15000)
        time.sleep(2)

        # Verify AlphaTab Score shows San-Ho-Zay
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "v4_01_san_ho_zay_alphatab.png"))
        print("   ✓ Screenshot saved: v4_01_san_ho_zay_alphatab.png")

        # Verify Interactive Note Editor View
        page.locator("button:has-text('Interactive Note')").first.click()
        time.sleep(1.5)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "v4_02_san_ho_zay_editor.png"))
        print("   ✓ Screenshot saved: v4_02_san_ho_zay_editor.png")

        # Test Pure MIDI Synth Playback
        page.locator("button:has-text('Play MIDI Solo')").first.click()
        time.sleep(2)
        midi_status = page.evaluate("""() => {
            const audio = document.querySelector('audio');
            const playhead = document.querySelector("svg line[stroke='#dc2626']");
            return {
                soundtrackPaused: audio ? audio.paused : null,
                playheadX1: playhead ? parseFloat(playhead.getAttribute('x1') || '0') : 0
            };
        }""")
        print(f"   -> MIDI Synth Playing: soundtrackPaused={midi_status['soundtrackPaused']}, playheadX1={midi_status['playheadX1']:.1f}")
        assert midi_status['soundtrackPaused'] is True, "Soundtrack must be paused during MIDI synth!"
        assert midi_status['playheadX1'] > 0, "Playhead line must be moving during MIDI synth!"

        browser.close()

    print("\n" + "=" * 80)
    print("ALL VERIFICATIONS COMPLETE: REAL YOUTUBE PIPELINE WORKING 100% END-TO-END!")
    print("=" * 80)

if __name__ == "__main__":
    test_new_youtube_workflow()
