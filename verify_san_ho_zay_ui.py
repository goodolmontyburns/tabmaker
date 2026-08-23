import os
import json
import shutil
import time
from backend.transcription.pitch_tracker import extract_notes_and_bends
from backend.copilot.tab_polish import infer_key_from_notes, deterministic_tab_polish
from backend.benchmark.export_ground_truth_session import save_notes_to_midi
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = "/Users/gbaird/.gemini/antigravity/brain/baa182dc-83fa-4184-8402-2a2233e22444"

def export_and_verify_san_ho_zay():
    session_id = "san_ho_zay_demo"
    session_dir = f"temp_uploads/{session_id}"
    os.makedirs(session_dir, exist_ok=True)

    # 1. Copy audio
    shutil.copyfile("/tmp/test_solo.audio.wav", f"{session_dir}/cropped.wav")
    
    # 2. Extract & polish
    print("Extracting San-Ho-Zay notes from audio...")
    raw_notes = extract_notes_and_bends(f"{session_dir}/cropped.wav", target_fret=8)
    notes_dict = [n.to_dict() for n in raw_notes]
    key = infer_key_from_notes(notes_dict)
    polished = deterministic_tab_polish(notes_dict, target_fret=8)

    save_notes_to_midi(polished, f"{session_dir}/solo.mid")

    session_data = {
        "session_id": session_id,
        "title": "Freddie King — San-Ho-Zay (AI Transcription)",
        "notes": polished,
        "duration": 154.48,
        "stems": {},
        "ai_applied": True,
        "key": key,
        "is_ground_truth": False,
        "video_analysis": {
            "is_live_guitar": False,
            "mode": "theory_audio",
            "reason": "Direct Acoustic Feature Extraction + Biomechanical Lead Polishing"
        },
        "original": f"/output/{session_id}/cropped.wav",
        "guitar_stem": f"/output/{session_id}/cropped.wav",
        "midi": f"/output/{session_id}/solo.mid"
    }

    with open(f"{session_dir}/session.json", "w") as f:
        json.dump(session_data, f)

    print(f"Saved session with {len(polished)} notes, Key: {key}")

    # 3. Test UI in Playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1100})
        page.goto(f"http://127.0.0.1:8001/")

        # Load session via localStorage or direct resume
        page.evaluate(f"""() => {{
            localStorage.setItem('last_tabmaker_session', '{session_id}');
            window.location.reload();
        }}""")
        page.wait_for_selector("h3:has-text('San-Ho-Zay')", timeout=15000)
        time.sleep(3)

        # Screenshot AlphaTab
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "v4_01_san_ho_zay_alphatab.png"))
        print("✓ Captured AlphaTab score for San-Ho-Zay")

        # Screenshot Interactive Note Editor
        page.locator("button:has-text('Interactive Note')").first.click()
        time.sleep(2)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "v4_02_san_ho_zay_editor.png"))
        print("✓ Captured Interactive Note Editor score for San-Ho-Zay")

        # Test dyad coordinates on SVG canvas
        dyad_coords = page.evaluate("""() => {
            const groups = Array.from(document.querySelectorAll('.note-group'));
            const dyadClusters = [];
            groups.forEach(g => {
                const texts = Array.from(g.querySelectorAll('text[font-size="12"]'));
                if (texts.length >= 2) {
                    const frets = texts.map(t => t.textContent.trim());
                    const xs = texts.map(t => parseFloat(t.getAttribute('x') || '0'));
                    const ys = texts.map(t => parseFloat(t.getAttribute('y') || '0'));
                    dyadClusters.push({ frets, xs, ys });
                }
            });
            return dyadClusters;
        }""")
        print(f"Found {len(dyad_coords)} rendered dyad clusters on SVG canvas for San-Ho-Zay:")
        for dc in dyad_coords[:5]:
            xs_same = all(abs(x - dc['xs'][0]) < 0.001 for x in dc['xs'])
            print(f"  Frets: {dc['frets']}, X: {dc['xs']} (Same X: {xs_same})")
            assert xs_same, "Dyads must share identical X coordinate!"

        browser.close()

if __name__ == "__main__":
    export_and_verify_san_ho_zay()
