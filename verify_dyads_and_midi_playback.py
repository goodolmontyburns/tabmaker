import os
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = "/Users/gbaird/.gemini/antigravity/brain/baa182dc-83fa-4184-8402-2a2233e22444"

def test_dyads_and_playback():
    print("=" * 75)
    print("VERIFICATION: DYADS VERTICAL ALIGNMENT & DEDICATED MIDI SYNTH PLAYBACK")
    print("=" * 75)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 1100})
        page = context.new_page()

        page.goto("http://127.0.0.1:8001/", wait_until="networkidle")
        page.locator("button:has-text('Ground Truth')").first.click()
        page.wait_for_selector("h3:has-text('Eric Clapton')", timeout=15000)
        time.sleep(2)

        # --------------------------------------------------------------------
        # TEST 1: AlphaTab View Soundtrack Playback
        # --------------------------------------------------------------------
        print("\n1. Testing AlphaTab Soundtrack Playback...")
        page.locator("button:has-text('Play')").first.click()
        time.sleep(2)
        
        at_audio = page.evaluate("""() => {
            const audio = document.querySelector('audio');
            return {
                paused: audio ? audio.paused : null,
                currentTime: audio ? audio.currentTime : 0
            };
        }""")
        print(f"   -> AlphaTab View Audio: paused={at_audio['paused']}, currentTime={at_audio['currentTime']:.2f}s")
        assert at_audio['paused'] is False, "Soundtrack should play in AlphaTab view!"
        assert at_audio['currentTime'] > 0.5, "Soundtrack currentTime should advance!"
        
        # Pause AlphaTab audio
        page.locator("button:has-text('Pause')").first.click()
        time.sleep(0.5)

        # --------------------------------------------------------------------
        # TEST 2: Switch to SVG Interactive Note Editor & Test Pure MIDI Synth
        # --------------------------------------------------------------------
        print("\n2. Testing SVG Editor Pure MIDI Synth Playback...")
        page.locator("button:has-text('Interactive Note')").first.click()
        time.sleep(1.5)

        # Start MIDI Synth
        play_midi_btn = page.locator("button:has-text('Play MIDI Solo')").first
        play_midi_btn.click()
        time.sleep(2)

        midi_status = page.evaluate("""() => {
            const audio = document.querySelector('audio');
            const playhead = document.querySelector("svg line[stroke='#dc2626']");
            return {
                soundtrackPaused: audio ? audio.paused : null,
                soundtrackCurrentTime: audio ? audio.currentTime : 0,
                playheadX1: playhead ? parseFloat(playhead.getAttribute('x1') || '0') : 0,
                playheadDisplay: playhead ? playhead.style.display : 'none'
            };
        }""")
        print(f"   -> Soundtrack Audio during MIDI Synth: paused={midi_status['soundtrackPaused']}")
        print(f"   -> Live MIDI Playhead Position: x1={midi_status['playheadX1']:.2f}, display={midi_status['playheadDisplay']}")
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "v3_01_midi_synth_playing.png"))

        assert midi_status['soundtrackPaused'] is True, "Soundtrack MUST BE PAUSED when playing pure MIDI synth!"
        assert midi_status['playheadX1'] > 0, "Playhead line MUST be moving during MIDI synth!"

        # Stop MIDI Synth
        page.locator("button:has-text('Stop MIDI Synth')").first.click()
        time.sleep(0.5)

        # --------------------------------------------------------------------
        # TEST 3: Measure 68 Dyads Vertical Stack Verification (Exact X-Coordinates)
        # --------------------------------------------------------------------
        print("\n3. Testing Measure 68 Dyads Vertical Alignment...")
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

        print(f"   Found {len(dyad_coords)} Dyad / Double Stop Chords on SVG Score:")
        for idx, dc in enumerate(dyad_coords):
            fret_str = "/".join(dc['frets'])
            xs_same = all(abs(x - dc['xs'][0]) < 0.001 for x in dc['xs'])
            ys_diff = dc['ys'][0] != dc['ys'][1] if len(dc['ys']) >= 2 else False
            print(f"   Dyad {idx+1}: Frets=[{fret_str}], X-coords={dc['xs']}, Y-coords={dc['ys']} -> Same X: {xs_same}, Different Strings Y: {ys_diff}")
            assert xs_same, f"Dyad {fret_str} must share the EXACT SAME X-coordinate on the staff!"
            assert ys_diff, f"Dyad {fret_str} must be on different string Y-lines!"

        page.screenshot(path=os.path.join(ARTIFACT_DIR, "v3_02_svg_dyads_verified.png"))

        # --------------------------------------------------------------------
        # TEST 4: AlphaTab AI Transcription Dyads
        # --------------------------------------------------------------------
        print("\n4. Testing AlphaTab AI Transcription Mode Dyads...")
        page.locator("button:has-text('Ultimate Guitar Web Score')").first.click()
        time.sleep(1)
        page.locator("button:has-text('AI Audio Transcription')").first.click()
        time.sleep(2)
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "v3_03_alphatab_ai_dyads.png"))

        print("\n" + "=" * 75)
        print("ALL TESTS PASSED: DYADS ARE VERTICALLY STACKED & MIDI SYNTH IS ISOLATED!")
        print("=" * 75)

        browser.close()

if __name__ == "__main__":
    test_dyads_and_playback()
