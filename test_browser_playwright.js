import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const ARTIFACT_DIR = '/Users/gbaird/.gemini/antigravity/brain/baa182dc-83fa-4184-8402-2a2233e22444';

async function runTests() {
  console.log('Starting Playwright automated browser verification...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 1000 } });
  const page = await context.newPage();

  const consoleLogs = [];
  const pageErrors = [];
  page.on('console', msg => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => pageErrors.push(err.toString()));

  try {
    // 1. Ingest Screen
    console.log('1. Navigating to http://127.0.0.1:8001/...');
    await page.goto('http://127.0.0.1:8001/', { waitUntil: 'networkidle' });
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '01_browser_ingest_screen.png') });
    console.log('   Captured 01_browser_ingest_screen.png');

    // 2. Click Benchmark button
    console.log('2. Clicking benchmark button to load 132-note solo...');
    const benchmarkBtn = page.locator('button:has-text("Clapton Ground Truth"), button:has-text("Clapton Benchmark")');
    await benchmarkBtn.first().click();

    // Wait for the tab score container to render
    await page.waitForSelector('.tabmaker-app, h3:has-text("Eric Clapton")', { timeout: 10000 });
    await page.waitForTimeout(3000); // Give AlphaTab time to render SVG

    // 3. Verify AlphaTab rendering
    console.log('3. Inspecting AlphaTab rendered elements...');
    const svgElements = await page.locator('svg').count();
    console.log(`   Found ${svgElements} SVG element(s) on the page.`);
    
    // Check if AlphaTab canvas/container has rendered children
    const alphaTabContainer = page.locator('.alphatab-container, div[style*="min-height: 600px"]');
    const containerHtml = await alphaTabContainer.first().innerHTML();
    console.log(`   AlphaTab container inner HTML length: ${containerHtml.length} bytes`);
    const hasSvgChildren = containerHtml.includes('<svg') || containerHtml.includes('at-') || containerHtml.includes('canvas');
    console.log(`   AlphaTab rendered content present: ${hasSvgChildren}`);

    await page.screenshot({ path: path.join(ARTIFACT_DIR, '02_browser_alphatab_score.png') });
    console.log('   Captured 02_browser_alphatab_score.png');

    // 4. Test Playback Controls in AlphaTab
    console.log('4. Testing AlphaTab Playback controls...');
    const playBtn = page.locator('button:has-text("Play")');
    if (await playBtn.count() > 0) {
      await playBtn.first().click();
      await page.waitForTimeout(1000);
      const isPause = await page.locator('button:has-text("Pause")').count() > 0;
      console.log(`   Playback toggle active: ${isPause}`);
      await page.locator('button:has-text("Pause"), button:has-text("Play")').first().click();
    }

    // 5. Test Switching to Interactive Tab Editor
    console.log('5. Testing switch to Interactive Note & Fingering Editor...');
    const editorTabBtn = page.locator('button:has-text("Interactive Note"), button:has-text("Editor")');
    await editorTabBtn.first().click();
    await page.waitForTimeout(2000);

    await page.screenshot({ path: path.join(ARTIFACT_DIR, '03_browser_interactive_editor.png') });
    console.log('   Captured 03_browser_interactive_editor.png');

    // Check notes on the editor canvas
    const renderedNotes = await page.locator('.note-circle, .tab-note, circle').count();
    console.log(`   Interactive tab editor rendered visual note nodes: ${renderedNotes}`);

    // Click first note to test popover
    const noteEl = page.locator('circle, .tab-note').first();
    if (await noteEl.count() > 0) {
      await noteEl.click();
      await page.waitForTimeout(1000);
      await page.screenshot({ path: path.join(ARTIFACT_DIR, '04_browser_note_popover.png') });
      console.log('   Captured 04_browser_note_popover.png');
    }

    // 6. Test Switch back to AlphaTab Ultimate Guitar view
    console.log('6. Testing switch back to Ultimate Guitar AlphaTab view...');
    const alphaTabTabBtn = page.locator('button:has-text("Ultimate Guitar"), button:has-text("AlphaTab")');
    await alphaTabTabBtn.first().click();
    await page.waitForTimeout(2000);

    // Test Toggle between "Official UG Score" and "AI Audio Transcription"
    const aiTransTab = page.locator('button:has-text("AI Audio Transcription")');
    if (await aiTransTab.count() > 0) {
      console.log('   Testing toggle to AI Audio Transcription mode...');
      await aiTransTab.click();
      await page.waitForTimeout(2000);
      await page.screenshot({ path: path.join(ARTIFACT_DIR, '05_browser_ai_audio_score.png') });
      console.log('   Captured 05_browser_ai_audio_score.png');
    }

    console.log('\n--- BROWSER VERIFICATION COMPLETE ---');
    console.log(`Total Page Errors: ${pageErrors.length}`);
    if (pageErrors.length > 0) {
      console.log('Page Errors:', pageErrors);
    }
    console.log(`Console Logs Sample: ${consoleLogs.slice(-10).join('\n')}`);

  } catch (err) {
    console.error('Playwright Test Failed:', err);
  } finally {
    await browser.close();
  }
}

runTests();
