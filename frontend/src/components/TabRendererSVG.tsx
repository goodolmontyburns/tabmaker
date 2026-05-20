import React, { useEffect, useRef, useState } from 'react';
import { jsPDF } from 'jspdf';

interface Note {
  id: string;
  s: number; 
  f: number; 
  t: number; 
  d: number; 
  p: number; 
}

interface TabRendererSVGProps {
  notes: Note[];
  duration: number;
  audioRef: React.RefObject<HTMLAudioElement | null>;
  playheadOffset: number;
  setPlayheadOffset: (offset: number) => void;
  onUpdateNotes: (newNotes: Note[]) => void;
}

const TabRendererSVG: React.FC<TabRendererSVGProps> = ({ notes, duration, audioRef, playheadOffset, setPlayheadOffset, onUpdateNotes }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const playheadRef = useRef<SVGLineElement>(null);
  
  // Ref tracking to avoid React re-renders during 60FPS playback
  const playbackStartOffsetRef = useRef<number>(0);
  const currentPlaybackTimeRef = useRef<number | null>(null);
  const isDraggingPlayheadRef = useRef<boolean>(false);
  const draggingTimeRef = useRef<number>(0);

  // Layout and seeks state
  const [layoutMode, setLayoutMode] = useState<'wrapped' | 'horizontal'>('wrapped');
  const [activeTime, setActiveTime] = useState<number>(0);

  const [zoom, setZoom] = useState(250);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [isSynthPlaying, setIsSynthPlaying] = useState(false);
  const [targetFret, setTargetFret] = useState(7);
  const [preferOpen, setPreferOpen] = useState(true);
  const [tsNum, setTsNum] = useState(4);
  const [tsDenom, setTsDenom] = useState(4);
  const bpm = 120;
  
  const audioContextRef = useRef<AudioContext | null>(null);
  const requestRef = useRef<number | null>(null);
  const synthStartTimeRef = useRef<number>(0);
  const scheduledNotesRef = useRef<Set<string>>(new Set());
  const lastAudioTimeRef = useRef<number>(0);
  const lastSyncTimeRef = useRef<number>(0);
  const playheadOffsetRef = useRef<number>(playheadOffset);
  const containerWidthRef = useRef<number>(0);
  
  const cancelAnimationLoop = () => {
    if (requestRef.current) {
      cancelAnimationFrame(requestRef.current);
      requestRef.current = null;
    }
  };
  
  useEffect(() => {
    playheadOffsetRef.current = playheadOffset;
  }, [playheadOffset]);

  useEffect(() => {
    const handleResize = () => {
      containerWidthRef.current = 0;
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const [selection, setSelection] = useState<{ tStart: number, tEnd: number } | null>(null);
  const [isSelecting, setIsSelecting] = useState(false);
  const [dragStartPos, setDragStartPos] = useState<number | null>(null);
  const [activeEditingNoteId, setActiveEditingNoteId] = useState<string | null>(null);

  // Snap notes that are strummed close together into perfect visual chords
  const alignedNotes = React.useMemo(() => {
    const sorted = [...notes].sort((a, b) => a.t - b.t);
    if (sorted.length === 0) return [];
    
    const aligned: Note[] = [ { ...sorted[0] } ];
    for (let i = 1; i < sorted.length; i++) {
      const current = { ...sorted[i] };
      const prev = aligned[aligned.length - 1];
      // Snap to previous note's time if within 100ms (strummed chord grouping)
      if (current.t - prev.t < 0.100) {
        current.t = prev.t;
      }
      aligned.push(current);
    }
    return aligned;
  }, [notes]);

  const nextNoteIndexRef = useRef<number>(0);

  const resetNextNoteIndex = (seekTime: number) => {
    scheduledNotesRef.current.clear();
    let idx = 0;
    while (idx < alignedNotes.length && alignedNotes[idx].t < seekTime) {
      idx++;
    }
    nextNoteIndexRef.current = idx;
  };

  const beatDuration = 60 / bpm;
  const secsPerMeasure = beatDuration * tsNum;
  
  const paddingLeft = 80; 
  const tabLineSpacing = 24;
  const tabTop = 50;
  const rowHeight = 200;
  const rowWidth = 1000;
  const height = 320;

  const offsets = [64, 59, 55, 50, 45, 40];

  // Number of measures per line in wrapped view
  const measuresPerLine = 3;
  const measureWidth = (rowWidth - paddingLeft) / measuresPerLine;
  const totalMeasures = Math.ceil(duration / secsPerMeasure);
  const numRows = Math.max(1, Math.ceil(totalMeasures / measuresPerLine));
  const svgWrappedHeight = numRows * rowHeight + 60;
  const svgHorizontalWidth = paddingLeft + (duration * zoom) + 150;

  const optimizePositions = (target: number, useOpen: boolean) => {
    const newNotes = [...notes];
    const affectedIndices = selection 
        ? notes.map((n, i) => (n.t >= selection.tStart && n.t <= selection.tEnd) ? i : -1).filter(i => i !== -1)
        : notes.map((_, i) => i);

    affectedIndices.forEach(idx => {
        const n = notes[idx];
        let bestS = n.s; let bestF = n.f; let maxScore = -999;
        
        for (let sIdx = 0; sIdx < 6; sIdx++) {
            const f = n.p - offsets[sIdx];
            if (f >= 0 && f <= 24) {
                let score = 0;
                if (useOpen && f === 0) score += 100; // Open String Priority
                if (useOpen && n.p <= 50 && (sIdx === 4 || sIdx === 5)) {
                    score += 50; // Bass string thumping preference for low pitches
                }
                score -= Math.abs(f - target); // Position proximity
                
                if (score > maxScore) { 
                    maxScore = score; bestS = sIdx + 1; bestF = f; 
                }
            }
        }
        newNotes[idx] = { ...n, s: bestS, f: bestF };
    });
    onUpdateNotes(newNotes);
  };

  // Synchronous Direct DOM Playhead Update
  const updatePlayheadDOM = (t: number) => {
    if (!playheadRef.current) return;
    
    if (layoutMode === 'wrapped') {
      const m = Math.floor(t / secsPerMeasure);
      const rowIndex = Math.floor(m / measuresPerLine);
      const localM = m % measuresPerLine;
      const tLocal = t % secsPerMeasure;
      
      const x = paddingLeft + (localM * measureWidth) + (tLocal / secsPerMeasure) * measureWidth;
      const yStart = rowIndex * rowHeight + tabTop - 10;
      const yEnd = yStart + 5 * tabLineSpacing + 20;
      
      playheadRef.current.setAttribute('x1', x.toString());
      playheadRef.current.setAttribute('x2', x.toString());
      playheadRef.current.setAttribute('y1', yStart.toString());
      playheadRef.current.setAttribute('y2', yEnd.toString());
      playheadRef.current.style.display = 'block';
    } else {
      const x = paddingLeft + (t * zoom);
      playheadRef.current.setAttribute('x1', x.toString());
      playheadRef.current.setAttribute('x2', x.toString());
      playheadRef.current.setAttribute('y1', '0');
      playheadRef.current.setAttribute('y2', height.toString());
      playheadRef.current.style.display = 'block';
      
      if (containerRef.current && !isDraggingPlayheadRef.current) {
        if (containerWidthRef.current === 0) {
          containerWidthRef.current = containerRef.current.clientWidth;
        }
        containerRef.current.scrollLeft = x - (containerWidthRef.current * 0.4);
      }
    }
  };

  const scheduleLookaheadNotes = (currentVirtualTime: number) => {
    const ctx = audioContextRef.current;
    if (!ctx) return;
    
    const synthStart = synthStartTimeRef.current;
    const virtualStart = playbackStartOffsetRef.current;
    
    // Look ahead 250ms of virtual playback time
    const lookaheadVirtualWindow = 0.250 * playbackSpeed;
    const windowEnd = currentVirtualTime + lookaheadVirtualWindow;
    
    // 1. Advance pointer to skip notes that are in the past relative to current playhead
    while (
      nextNoteIndexRef.current < alignedNotes.length &&
      alignedNotes[nextNoteIndexRef.current].t < currentVirtualTime
    ) {
      nextNoteIndexRef.current++;
    }
    
    // 2. Scan and schedule only notes falling in the active look-ahead window
    let idx = nextNoteIndexRef.current;
    while (idx < alignedNotes.length) {
      const n = alignedNotes[idx];
      if (n.t >= windowEnd) break; // Reached beyond lookahead window, stop scanning
      
      if (!scheduledNotesRef.current.has(n.id)) {
        scheduledNotesRef.current.add(n.id);
        
        const relativeStart = (n.t - virtualStart) / playbackSpeed;
        const relativeDuration = n.d / playbackSpeed;
        const targetStartTime = synthStart + relativeStart;
        
        // Guard against scheduling in the past
        const playTime = Math.max(ctx.currentTime + 0.005, targetStartTime);
        const playDuration = relativeDuration;
        
        const freq = 440 * Math.pow(2, (n.p - 69) / 12);
        const osc = ctx.createOscillator(); 
        const gain = ctx.createGain(); 
        const filter = ctx.createBiquadFilter();
        
        // Resonant pluck timbre
        osc.type = 'sawtooth'; 
        osc.frequency.setValueAtTime(freq, playTime);
        
        filter.type = 'lowpass'; 
        filter.frequency.setValueAtTime(3500, playTime);
        filter.frequency.exponentialRampToValueAtTime(800, playTime + 0.1);
        
        gain.gain.setValueAtTime(0, playTime);
        gain.gain.linearRampToValueAtTime(0.2, playTime + 0.005);
        gain.gain.exponentialRampToValueAtTime(0.001, playTime + playDuration);
        
        osc.connect(filter); 
        filter.connect(gain); 
        gain.connect(ctx.destination);
        
        osc.start(playTime); 
        osc.stop(playTime + playDuration);
      }
      idx++;
    }
  };

  const animate = () => {
    let current = 0;
    const audio = document.getElementById('reference-audio') as HTMLAudioElement || audioRef.current;
    if (isSynthPlaying && audioContextRef.current) {
        const elapsed = Math.max(0, audioContextRef.current.currentTime - synthStartTimeRef.current) * playbackSpeed;
        current = playbackStartOffsetRef.current + elapsed;
        scheduleLookaheadNotes(current);
    } else if (audio && !audio.paused) {
        const now = performance.now();
        if (audio.currentTime !== lastAudioTimeRef.current) {
            lastAudioTimeRef.current = audio.currentTime;
            lastSyncTimeRef.current = now;
        }
        const elapsedSinceSync = (now - lastSyncTimeRef.current) / 1000;
        // Clamp the interpolation to a max of 0.5s beyond the last known audio.currentTime to prevent runaway drift
        const interpolated = lastAudioTimeRef.current + Math.min(0.5, elapsedSinceSync * audio.playbackRate);
        current = Math.max(0, Math.min(duration, interpolated - playheadOffsetRef.current));
    } else {
        return; // Stopped or paused
    }
    
    if (current <= duration) {
        updatePlayheadDOM(current);
        currentPlaybackTimeRef.current = current;
        cancelAnimationLoop();
        requestRef.current = requestAnimationFrame(animate);
    } else { 
        stopPlayback(); 
    }
  };

  useEffect(() => {
    const audio = document.getElementById('reference-audio') as HTMLAudioElement || audioRef.current;
    if (isSynthPlaying || (audio && !audio.paused)) {
        cancelAnimationLoop();
        requestRef.current = requestAnimationFrame(animate);
    }
    return () => cancelAnimationLoop();
  }, [isSynthPlaying, zoom, playbackSpeed, layoutMode]);

  // Sync static playhead whenever activeTime, layoutMode or zoom shifts
  useEffect(() => {
    updatePlayheadDOM(activeTime);
    resetNextNoteIndex(activeTime);
  }, [activeTime, layoutMode, zoom]);

  // Sync activeTime with playheadOffset changes while paused
  useEffect(() => {
    const audio = document.getElementById('reference-audio') as HTMLAudioElement || audioRef.current;
    if (audio && audio.paused) {
      const visualTime = Math.max(0, Math.min(duration, audio.currentTime - playheadOffset));
      setActiveTime(visualTime);
    }
  }, [playheadOffset, duration, audioRef.current]);

  // Sync HTML5 reference audio controls with the SVG playhead
  useEffect(() => {
    const audio = document.getElementById('reference-audio') as HTMLAudioElement || audioRef.current;
    if (!audio) return;

    const handlePlay = () => {
      if (isSynthPlaying) stopPlayback();
      lastAudioTimeRef.current = audio.currentTime;
      lastSyncTimeRef.current = performance.now();
      cancelAnimationLoop();
      requestRef.current = requestAnimationFrame(animate);
    };

    const handlePause = () => {
      cancelAnimationLoop();
      const visualTime = Math.max(0, Math.min(duration, audio.currentTime - playheadOffsetRef.current));
      setActiveTime(visualTime);
    };

    const handleSeeked = () => {
      const visualTime = Math.max(0, Math.min(duration, audio.currentTime - playheadOffsetRef.current));
      setActiveTime(visualTime);
      updatePlayheadDOM(visualTime);
      resetNextNoteIndex(visualTime);
    };

    audio.addEventListener('play', handlePlay);
    audio.addEventListener('pause', handlePause);
    audio.addEventListener('seeked', handleSeeked);

    // Initial sync of the static playhead
    const visualTime = Math.max(0, Math.min(duration, audio.currentTime - playheadOffsetRef.current));
    updatePlayheadDOM(visualTime);

    return () => {
      audio.removeEventListener('play', handlePlay);
      audio.removeEventListener('pause', handlePause);
      audio.removeEventListener('seeked', handleSeeked);
    };
  }, [audioRef.current, isSynthPlaying, zoom, playbackSpeed, layoutMode]);

  const stopPlayback = () => {
    if (audioContextRef.current) { audioContextRef.current.close(); audioContextRef.current = null; }
    setIsSynthPlaying(false);
    const audio = document.getElementById('reference-audio') as HTMLAudioElement || audioRef.current;
    if (audio) audio.pause();
    cancelAnimationLoop();
    
    // Commit elapsed playback position to React state
    if (currentPlaybackTimeRef.current !== null) {
      setActiveTime(Math.max(0, Math.min(duration, currentPlaybackTimeRef.current)));
      currentPlaybackTimeRef.current = null;
    }
  };

  const startSynth = async () => {
    if (isSynthPlaying) { stopPlayback(); return; }
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    audioContextRef.current = ctx;
    
    if (ctx.state === 'suspended') {
      await ctx.resume();
    }
    
    const startTime = ctx.currentTime + 0.15;
    synthStartTimeRef.current = startTime;
    playbackStartOffsetRef.current = Math.max(0, Math.min(duration, activeTime)); // start synth from visual playhead score time!

    scheduledNotesRef.current.clear();
    resetNextNoteIndex(playbackStartOffsetRef.current);
    setIsSynthPlaying(true);
  };

  // Pointer Seeking, Scrubbing, and Lasso Calculation
  const handlePointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    const rect = svgRef.current!.getBoundingClientRect();
    const X = e.clientX - rect.left;
    const Y = e.clientY - rect.top;

    const rowIndex = Math.floor(Y / rowHeight);
    const yLocal = Y % rowHeight;

    // Check if pointer is directly in the staff lines range
    const isStaffClick = layoutMode === 'wrapped'
      ? (yLocal >= tabTop - 10 && yLocal <= tabTop + (5 * tabLineSpacing) + 10)
      : (Y >= tabTop - 10 && Y <= tabTop + (5 * tabLineSpacing) + 10);

    if (isStaffClick) {
      stopPlayback();
      // Seek / Playhead Scrubbing Action
      isDraggingPlayheadRef.current = true;
      svgRef.current!.setPointerCapture(e.pointerId);

      let t = 0;
      if (layoutMode === 'wrapped') {
        const xLocal = Math.max(0, Math.min(rowWidth - paddingLeft, X - paddingLeft));
        const rowDuration = measuresPerLine * secsPerMeasure;
        const tLocal = (xLocal / (rowWidth - paddingLeft)) * rowDuration;
        t = rowIndex * rowDuration + tLocal;
      } else {
        const xLocal = Math.max(0, X - paddingLeft);
        t = xLocal / zoom;
      }
      
      const clampedT = Math.max(0, Math.min(duration, t));
      setActiveTime(clampedT);
      draggingTimeRef.current = clampedT;
      
      const audio = document.getElementById('reference-audio') as HTMLAudioElement || audioRef.current;
      if (audio) {
        audio.currentTime = Math.max(0, Math.min(duration, clampedT + playheadOffsetRef.current));
      }
      updatePlayheadDOM(clampedT);
    } else {
      // Area Range Lasso Selection Action (drag in empty margins above/below strings)
      setDragStartPos(X);
      setIsSelecting(true);
      setSelection(null);
    }
  };

  const handlePointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const rect = svgRef.current!.getBoundingClientRect();
    const X = e.clientX - rect.left;
    const Y = e.clientY - rect.top;

    if (isDraggingPlayheadRef.current) {
      let t = 0;
      if (layoutMode === 'wrapped') {
        const rowIndex = Math.max(0, Math.min(numRows - 1, Math.floor(Y / rowHeight)));
        const xLocal = Math.max(0, Math.min(rowWidth - paddingLeft, X - paddingLeft));
        const rowDuration = measuresPerLine * secsPerMeasure;
        const tLocal = (xLocal / (rowWidth - paddingLeft)) * rowDuration;
        t = rowIndex * rowDuration + tLocal;
      } else {
        const xLocal = Math.max(0, X - paddingLeft);
        t = xLocal / zoom;
      }
      const clampedT = Math.max(0, Math.min(duration, t));
      draggingTimeRef.current = clampedT;
      updatePlayheadDOM(clampedT); // Instant 0-lag playhead response
    } else if (isSelecting && dragStartPos !== null) {
      // Horizontal range calculation for selection
      if (layoutMode === 'wrapped') {
        // Multi-line selection mapping based on drag start to end
        const x1 = Math.max(0, Math.min(rowWidth - paddingLeft, dragStartPos - paddingLeft));
        const x2 = Math.max(0, Math.min(rowWidth - paddingLeft, X - paddingLeft));
        
        const rowY = Math.floor(Y / rowHeight);
        const rowDuration = measuresPerLine * secsPerMeasure;
        const t1 = rowY * rowDuration + (x1 / (rowWidth - paddingLeft)) * rowDuration;
        const t2 = rowY * rowDuration + (x2 / (rowWidth - paddingLeft)) * rowDuration;
        
        setSelection({
          tStart: Math.max(0, Math.min(t1, t2)),
          tEnd: Math.min(duration, Math.max(t1, t2))
        });
      } else {
        setSelection({
          tStart: Math.max(0, (Math.min(dragStartPos, X) - paddingLeft) / zoom),
          tEnd: Math.min(duration, (Math.max(dragStartPos, X) - paddingLeft) / zoom)
        });
      }
    }
  };

  const handlePointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    if (isDraggingPlayheadRef.current) {
      isDraggingPlayheadRef.current = false;
      svgRef.current!.releasePointerCapture(e.pointerId);
      const visualTime = draggingTimeRef.current;
      setActiveTime(visualTime);
      const audio = document.getElementById('reference-audio') as HTMLAudioElement || audioRef.current;
      if (audio) {
        audio.currentTime = Math.max(0, Math.min(duration, visualTime + playheadOffsetRef.current));
      }
      resetNextNoteIndex(visualTime);
    }
  };

  const exportPDF = () => {
    const doc = new jsPDF({ orientation: 'p', unit: 'pt', format: 'a4' });
    const pageWidth = doc.internal.pageSize.getWidth();
    const pageHeight = doc.internal.pageSize.getHeight();
    const margins = 50;
    const printableWidth = pageWidth - margins * 2;
    
    doc.setFillColor(255, 255, 255); // White background
    doc.rect(0, 0, pageWidth, pageHeight, 'F');

    doc.setFont("Helvetica", "bold");
    doc.setFontSize(22); 
    doc.setTextColor(15, 23, 42); // Velvet black header text
    doc.text("Transcribed Guitar Solo", margins, 60);

    doc.setFont("Helvetica", "normal");
    doc.setFontSize(10); 
    doc.setTextColor(71, 85, 105); // Slate gray description
    doc.text(`Tuning: E A D G B E (Standard) | Time Signature: ${tsNum}/${tsDenom} | Tempo: ${bpm} BPM`, margins, 80);

    const rowPDFHeight = 140;
    const lineSpacing = 15;
    const pdfMeasuresPerLine = 2;
    const measurePDFWidth = printableWidth / pdfMeasuresPerLine;
    const pdfZoom = measurePDFWidth / secsPerMeasure;
    let currentY = 120;

    for (let m = 0; m < duration / secsPerMeasure; m++) {
        const startTime = m * secsPerMeasure;
        const endTime = (m + 1) * secsPerMeasure;
        
        if (m % pdfMeasuresPerLine === 0) {
            if (currentY + rowPDFHeight > pageHeight - margins) { 
                doc.addPage(); 
                doc.setFillColor(255, 255, 255); 
                doc.rect(0, 0, pageWidth, pageHeight, 'F');
                currentY = margins + 20; 
            }
            doc.setFontSize(10); 
            doc.setTextColor(0, 0, 0); // Black TAB text
            doc.text("TAB", margins - 25, currentY + 42);
        }
        
        const mX = margins + (m % pdfMeasuresPerLine) * measurePDFWidth;
        doc.setDrawColor(148, 163, 184); // Slate 300 gray for strings
        doc.setLineWidth(0.8);
        for (let s = 0; s < 6; s++) {
          doc.line(mX, currentY + s * lineSpacing, mX + measurePDFWidth, currentY + s * lineSpacing);
        }
        
        doc.setDrawColor(0, 0, 0); // Black measure lines
        doc.setLineWidth(1.5);
        doc.line(mX, currentY, mX, currentY + 5 * lineSpacing); // start measure bar

        // Render notes
        alignedNotes.filter(n => n.t >= startTime && n.t < endTime).forEach(n => {
            const nX = mX + (n.t - startTime) * pdfZoom;
            const nY = currentY + (n.s - 1) * lineSpacing;
            
            // Draw clean circle mask for frets (white-filled circle with a thin black border)
            doc.setFillColor(255, 255, 255);
            doc.setDrawColor(0, 0, 0);
            doc.setLineWidth(0.8);
            doc.circle(nX, nY, 7.5, 'FD'); // FD fills and draws border
            
            doc.setTextColor(0, 0, 0); // Black fret text
            doc.setFontSize(10);
            doc.text(n.f.toString(), nX, nY + 3, { align: 'center' });

            // Draw clean timing stems downward (black)
            const pdfStemY = currentY + 5 * lineSpacing + 5;
            doc.setDrawColor(0, 0, 0);
            doc.setLineWidth(0.8);
            doc.line(nX, pdfStemY, nX, pdfStemY + 14);
            
            const beats = n.d / beatDuration;
            if (beats < 0.35) { // sixteenth double flag (black)
                doc.line(nX, pdfStemY + 14, nX + 4, pdfStemY + 10);
                doc.line(nX, pdfStemY + 10, nX + 4, pdfStemY + 6);
            } else if (beats < 0.75) { // eighth single flag (black)
                doc.line(nX, pdfStemY + 14, nX + 4, pdfStemY + 10);
            }
        });
        
        if (m % pdfMeasuresPerLine === pdfMeasuresPerLine - 1 || m >= (duration / secsPerMeasure) - 1) {
            currentY += rowPDFHeight;
        }
    }
    doc.save("TabMaker_Pro_Transcription.pdf");
  };

  // Group notes by time `t` to generate unified rhythmic stems
  const getRhythmStems = () => {
    const beatGroups: Record<string, Note[]> = {};
    alignedNotes.forEach(n => {
      const key = n.t.toFixed(3);
      if (!beatGroups[key]) beatGroups[key] = [];
      beatGroups[key].push(n);
    });

    return Object.entries(beatGroups).map(([tStr, group]) => {
      const t = parseFloat(tStr);
      const maxD = Math.max(...group.map(note => note.d));
      
      let x = 0;
      let rowIndex = 0;
      
      if (layoutMode === 'wrapped') {
        const m = Math.floor(t / secsPerMeasure);
        rowIndex = Math.floor(m / measuresPerLine);
        const localM = m % measuresPerLine;
        const tLocal = t % secsPerMeasure;
        x = paddingLeft + (localM * measureWidth) + (tLocal / secsPerMeasure) * measureWidth;
      } else {
        x = paddingLeft + t * zoom;
      }

      const rowY = layoutMode === 'wrapped' ? rowIndex * rowHeight : 0;
      const yBottomStaff = rowY + tabTop + 5 * tabLineSpacing;
      const durationBeats = maxD / beatDuration;

      return {
        key: tStr,
        x,
        yBottomStaff,
        durationBeats
      };
    });
  };

  const rhythmStems = getRhythmStems();

  return (
    <div className="pro-tab-card" style={{ textAlign: 'left', marginTop: '40px' }}>
      <div className="pro-control-row">
        <div>
          <h3 style={{ margin: 0 }}>Interactive Fretboard Score</h3>
          <p style={{ margin: '4px 0 0 0', fontSize: '0.85rem', color: '#94a3b8' }}>
            Click anywhere on the staff strings to seek the playhead. Drag margins to select sections.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <div className="pro-glass-switch">
            <button 
              className={`pro-switch-btn ${layoutMode === 'wrapped' ? 'active' : ''}`}
              onClick={() => { stopPlayback(); setLayoutMode('wrapped'); }}
            >
              Wrapped System
            </button>
            <button 
              className={`pro-switch-btn ${layoutMode === 'horizontal' ? 'active' : ''}`}
              onClick={() => { stopPlayback(); setLayoutMode('horizontal'); }}
            >
              Continuous Track
            </button>
          </div>
          <button className="pro-btn-outline" onClick={exportPDF}>📄 Save PDF</button>
          <button 
            onClick={startSynth} 
            className={isSynthPlaying ? 'pro-btn-red' : 'pro-btn-gold'}
            style={{ fontWeight: '800' }}
          >
            {isSynthPlaying ? 'Stop' : '🎸 Play Synth'}
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '30px', alignItems: 'center', background: 'rgba(30, 41, 59, 0.4)', padding: '20px', borderRadius: '14px', border: '1px solid rgba(255, 255, 255, 0.05)', flexWrap: 'wrap', marginBottom: '20px' }}>
          <div style={{ flex: '1 1 300px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <label style={{ fontWeight: 'bold', fontSize: '0.9rem', color: '#fbbf24' }}>
                    Fret Position Shift ({selection ? "Selected Lasso" : "All notes"}): Fret {targetFret}
                  </label>
                  <label style={{ cursor: 'pointer', background: 'rgba(15, 23, 42, 0.6)', padding: '5px 12px', borderRadius: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '8px', border: '1px solid rgba(255, 255, 255, 0.05)', color: '#f8fafc' }}>
                      <input 
                        type="checkbox" 
                        className="pro-slider-gold"
                        checked={preferOpen} 
                        onChange={(e) => {
                            const val = e.target.checked;
                            setPreferOpen(val);
                            optimizePositions(targetFret, val);
                        }} 
                      />
                      Prefer Open Bass Strings (Blues Thumb)
                  </label>
              </div>
              <input 
                type="range" 
                min="0" 
                max="17" 
                className="pro-slider-gold"
                value={targetFret} 
                onChange={(e) => { setTargetFret(Number(e.target.value)); optimizePositions(Number(e.target.value), preferOpen); }} 
                style={{ width: '100%', marginTop: '10px' }} 
              />
          </div>
          <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 'bold', color: '#94a3b8' }}>Time Signature</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <input type="number" value={tsNum} onChange={(e) => setTsNum(Math.max(1, Number(e.target.value)))} className="pro-input-dark" style={{ width: '45px' }} />
                      <span style={{ color: '#64748b', fontWeight: 'bold' }}>/</span>
                      <input type="number" value={tsDenom} onChange={(e) => setTsDenom(Math.max(1, Number(e.target.value)))} className="pro-input-dark" style={{ width: '45px' }} />
                  </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '0.75rem', fontWeight: 'bold', color: '#94a3b8' }}>Playback Speed</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <input type="range" min="0.5" max="1.5" step="0.1" className="pro-slider-gold" value={playbackSpeed} onChange={(e) => setPlaybackSpeed(Number(e.target.value))} style={{ width: '90px' }} />
                  <span style={{ fontSize: '0.8rem', fontWeight: 'bold', color: '#fbbf24', minWidth: '35px' }}>{playbackSpeed.toFixed(1)}x</span>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '0.75rem', fontWeight: 'bold', color: '#94a3b8' }}>Playhead Sync</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <input 
                    type="range" 
                    min="-1.5" 
                    max="1.5" 
                    step="0.05" 
                    className="pro-slider-gold" 
                    value={playheadOffset} 
                    onChange={(e) => {
                      const val = Number(e.target.value);
                      setPlayheadOffset(val);
                      localStorage.setItem('tabmaker_playhead_offset', val.toString());
                    }} 
                    style={{ width: '90px' }} 
                  />
                  <span style={{ fontSize: '0.8rem', fontWeight: 'bold', color: '#fbbf24', minWidth: '55px', textAlign: 'right' }}>
                    {playheadOffset >= 0 ? `+${playheadOffset.toFixed(2)}s` : `${playheadOffset.toFixed(2)}s`}
                  </span>
                </div>
              </div>
              {layoutMode === 'horizontal' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 'bold', color: '#94a3b8' }}>Horizontal Zoom</label>
                  <input type="range" min="100" max="1000" className="pro-slider-gold" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} style={{ width: '90px' }} />
                </div>
              )}
          </div>
      </div>

      <div 
        ref={containerRef} 
        className={`pro-svg-view-wrapper ${layoutMode === 'wrapped' ? 'wrapped' : ''}`}
      >
        <svg 
          ref={svgRef} 
          width={layoutMode === 'wrapped' ? rowWidth : svgHorizontalWidth} 
          height={layoutMode === 'wrapped' ? svgWrappedHeight : height} 
          style={{ cursor: 'crosshair', userSelect: 'none', touchAction: 'none' }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          {/* Glowing Filter for Playhead */}
          <defs>
            <filter id="gold-glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {/* Time range selection lasso overlay */}
          {selection && (
            layoutMode === 'wrapped' ? (
              // Multi-line range drawing
              Array.from({ length: numRows }).map((_, rIdx) => {
                const rowTStart = rIdx * measuresPerLine * secsPerMeasure;
                const rowTEnd = (rIdx + 1) * measuresPerLine * secsPerMeasure;
                if (selection.tEnd < rowTStart || selection.tStart > rowTEnd) return null;
                
                const relativeStart = Math.max(rowTStart, selection.tStart) - rowTStart;
                const relativeEnd = Math.min(rowTEnd, selection.tEnd) - rowTStart;
                const rowDuration = measuresPerLine * secsPerMeasure;
                
                const x1 = paddingLeft + (relativeStart / rowDuration) * (rowWidth - paddingLeft);
                const x2 = paddingLeft + (relativeEnd / rowDuration) * (rowWidth - paddingLeft);
                
                return (
                  <rect 
                    key={`selection-row-${rIdx}`}
                    x={x1} 
                    y={rIdx * rowHeight + tabTop} 
                    width={x2 - x1} 
                    height={5 * tabLineSpacing} 
                    fill="rgba(251, 191, 36, 0.08)" 
                    stroke="rgba(251, 191, 36, 0.3)"
                    strokeWidth="1.5"
                    strokeDasharray="4 4"
                  />
                );
              })
            ) : (
              <rect 
                x={paddingLeft + selection.tStart * zoom} 
                y={tabTop} 
                width={(selection.tEnd - selection.tStart) * zoom} 
                height={5 * tabLineSpacing} 
                fill="rgba(251, 191, 36, 0.08)" 
                stroke="rgba(251, 191, 36, 0.3)" 
                strokeWidth="1.5"
                strokeDasharray="4 4"
              />
            )
          )}

          {/* System Rows drawing loop */}
          {layoutMode === 'wrapped' ? (
            Array.from({ length: numRows }).map((_, rIdx) => {
              const rowY = rIdx * rowHeight;
              
              return (
                <g key={`row-${rIdx}`}>
                  {/* repeating TAB clef and time signatures */}
                  <text x="18" y={rowY + tabTop + 68} fontSize="20" fontWeight="900" fill="#fbbf24" style={{ fontFamily: "'Outfit', sans-serif", letterSpacing: '1px' }}>TAB</text>
                  <text x="56" y={rowY + tabTop + 45} fontSize="18" fontWeight="800" fill="#f8fafc" style={{ fontFamily: "'Outfit', sans-serif" }}>{tsNum}</text>
                  <text x="56" y={rowY + tabTop + 85} fontSize="18" fontWeight="800" fill="#f8fafc" style={{ fontFamily: "'Outfit', sans-serif" }}>{tsDenom}</text>

                  {/* measure boundaries & beat dots inside this row */}
                  {Array.from({ length: measuresPerLine }).map((_, mOffset) => {
                    const absMeasureIdx = rIdx * measuresPerLine + mOffset;
                    if (absMeasureIdx >= totalMeasures) return null;
                    const mX = paddingLeft + mOffset * measureWidth;
                    
                    return (
                      <g key={`measure-${absMeasureIdx}`}>
                        {/* start measure line */}
                        <line x1={mX} y1={rowY + tabTop} x2={mX} y2={rowY + tabTop + 5 * tabLineSpacing} stroke="#64748b" strokeWidth="2.5" />
                        {/* measure count tag */}
                        <text x={mX + 6} y={rowY + tabTop - 12} fontSize="12" fontWeight="800" fill="#fbbf24" style={{ fontFamily: "'Outfit', sans-serif" }}>Measure {absMeasureIdx + 1}</text>
                        
                        {/* beats subdivisions */}
                        {Array.from({ length: tsNum }).map((_, bIdx) => {
                          const beatX = mX + (bIdx / tsNum) * measureWidth;
                          return (
                            <circle key={`beat-${bIdx}`} cx={beatX} cy={rowY + tabTop + 5 * tabLineSpacing + 15} r="2.5" fill={bIdx === 0 ? "#fbbf24" : "#475569"} />
                          );
                        })}
                      </g>
                    );
                  })}
                  
                  {/* End measure double boundary for the final measure on the row */}
                  <line x1={rowWidth} y1={rowY + tabTop} x2={rowWidth} y2={rowY + tabTop + 5 * tabLineSpacing} stroke="#64748b" strokeWidth="2.5" />

                  {/* 6 Staff Strings lines */}
                  {[0, 1, 2, 3, 4, 5].map(l => (
                      <line key={`string-${l}`} x1={paddingLeft} y1={rowY + tabTop + l * tabLineSpacing} x2={rowWidth} y2={rowY + tabTop + l * tabLineSpacing} stroke="#334155" strokeWidth="1.2" />
                  ))}
                </g>
              );
            })
          ) : (
            // Horizontal Track rendering
            <g>
              {/* Sticky header masking layer (glassmorphic TAB clef overlay on scroll container) */}
              <text x="18" y={tabTop + 68} fontSize="20" fontWeight="900" fill="#fbbf24" style={{ fontFamily: "'Outfit', sans-serif" }}>TAB</text>
              <text x="56" y={tabTop + 45} fontSize="18" fontWeight="800" fill="#f8fafc" style={{ fontFamily: "'Outfit', sans-serif" }}>{tsNum}</text>
              <text x="56" y={tabTop + 85} fontSize="18" fontWeight="800" fill="#f8fafc" style={{ fontFamily: "'Outfit', sans-serif" }}>{tsDenom}</text>

              {/* 6 continuous staff strings */}
              {[0, 1, 2, 3, 4, 5].map(l => (
                  <line key={l} x1={paddingLeft} y1={tabTop + l * tabLineSpacing} x2={svgHorizontalWidth} y2={tabTop + l * tabLineSpacing} stroke="#334155" strokeWidth="1.2" />
              ))}

              {/* continuous measure lines */}
              {Array.from({ length: totalMeasures + 1 }).map((_, mIdx) => {
                const mX = paddingLeft + (mIdx * secsPerMeasure * zoom);
                return (
                  <g key={mIdx}>
                    <line x1={mX} y1={tabTop} x2={mX} y2={tabTop + 5 * tabLineSpacing} stroke="#64748b" strokeWidth="2.5" />
                    {mIdx < totalMeasures && (
                      <>
                        <text x={mX + 6} y={tabTop - 12} fontSize="12" fontWeight="800" fill="#fbbf24" style={{ fontFamily: "'Outfit', sans-serif" }}>M{mIdx + 1}</text>
                        {Array.from({ length: tsNum }).map((_, bIdx) => {
                          const beatX = mX + (bIdx / tsNum) * secsPerMeasure * zoom;
                          return (
                            <circle key={`beat-${bIdx}`} cx={beatX} cy={tabTop + 5 * tabLineSpacing + 15} r="2.5" fill={bIdx === 0 ? "#fbbf24" : "#475569"} />
                          );
                        })}
                      </>
                    )}
                  </g>
                );
              })}
            </g>
          )}

          {/* Rhythmic stems layer */}
          {rhythmStems.map(stem => (
            <g key={`stem-${stem.key}`}>
              {/* stem vertical line */}
              <line 
                x1={stem.x} 
                y1={stem.yBottomStaff + 8} 
                x2={stem.x} 
                y2={stem.yBottomStaff + 26} 
                stroke="#fbbf24" 
                strokeWidth="1.2" 
              />
              
              {/* stem duration flags */}
              {stem.durationBeats < 0.35 ? ( // Sixteenth note (double flag)
                <path 
                  d={`M ${stem.x} ${stem.yBottomStaff + 26} Q ${stem.x + 5} ${stem.yBottomStaff + 22} ${stem.x + 5} ${stem.yBottomStaff + 16} M ${stem.x} ${stem.yBottomStaff + 21} Q ${stem.x + 5} ${stem.yBottomStaff + 17} ${stem.x + 5} ${stem.yBottomStaff + 11}`} 
                  fill="none" 
                  stroke="#fbbf24" 
                  strokeWidth="1.2" 
                />
              ) : stem.durationBeats < 0.75 ? ( // Eighth note (single flag)
                <path 
                  d={`M ${stem.x} ${stem.yBottomStaff + 26} Q ${stem.x + 5} ${stem.yBottomStaff + 22} ${stem.x + 5} ${stem.yBottomStaff + 16}`} 
                  fill="none" 
                  stroke="#fbbf24" 
                  strokeWidth="1.2" 
                />
              ) : stem.durationBeats >= 1.5 ? ( // Half / Whole notes (hollow indicator)
                <circle 
                  cx={stem.x} 
                  cy={stem.yBottomStaff + 26} 
                  r="3.5" 
                  fill="none" 
                  stroke="#fbbf24" 
                  strokeWidth="1.2" 
                />
              ) : null}
            </g>
          ))}

          {/* Guitar Fret Notes */}
          {alignedNotes.map((n) => {
            let x = 0;
            let rowIndex = 0;

            if (layoutMode === 'wrapped') {
              const m = Math.floor(n.t / secsPerMeasure);
              rowIndex = Math.floor(m / measuresPerLine);
              const localM = m % measuresPerLine;
              const tLocal = n.t % secsPerMeasure;
              x = paddingLeft + (localM * measureWidth) + (tLocal / secsPerMeasure) * measureWidth;
            } else {
              x = paddingLeft + n.t * zoom;
            }

            const rowY = layoutMode === 'wrapped' ? rowIndex * rowHeight : 0;
            const yTab = rowY + tabTop + (n.s - 1) * tabLineSpacing;
            const isEditing = activeEditingNoteId === n.id;
            
            return (
                <g key={n.id}>
                    {/* note clean dark slate background mask circle */}
                    <circle 
                      cx={x} 
                      cy={yTab} 
                      r="14.5" 
                      fill="#080b11" 
                      stroke={isEditing ? '#ef4444' : 'rgba(251, 191, 36, 0.4)'} 
                      strokeWidth={isEditing ? '2' : '1.2'}
                      onClick={(e) => { e.stopPropagation(); setActiveEditingNoteId(isEditing ? null : n.id); }} 
                      style={{ cursor: 'pointer' }} 
                    />
                    
                    {/* fret number text */}
                    <text 
                      x={x} 
                      y={yTab + 6} 
                      textAnchor="middle" 
                      onClick={(e) => { e.stopPropagation(); setActiveEditingNoteId(isEditing ? null : n.id); }} 
                      style={{ 
                        fontSize: '18px', 
                        fontWeight: '900', 
                        fill: isEditing ? '#ef4444' : '#fbbf24', 
                        fontFamily: "'Outfit', -apple-system, BlinkMacSystemFont, sans-serif", 
                        cursor: 'pointer', 
                        userSelect: 'none' 
                      }}
                    >
                      {n.f}
                    </text>
                    
                    {/* alternative string shift selectors popover */}
                    {isEditing && offsets.map((offset, idx) => {
                        const s = idx + 1; if (s === n.s) return null;
                        const f = n.p - offset;
                        
                        if (f >= 0 && f <= 24) {
                            const optY = rowY + tabTop + idx * tabLineSpacing;
                            return (
                                <g 
                                  key={`${n.id}-opt-${s}`} 
                                  onClick={(e) => { 
                                    e.stopPropagation(); 
                                    const newNotes = notes.map(note => note.id === n.id ? { ...note, s, f } : note); 
                                    onUpdateNotes(newNotes); 
                                    setActiveEditingNoteId(null); 
                                  }} 
                                  style={{ cursor: 'pointer' }}
                                >
                                    <circle cx={x} cy={optY} r="12" fill="#ef4444" />
                                    <text 
                                      x={x} 
                                      y={optY + 5} 
                                      textAnchor="middle" 
                                      style={{ 
                                        fontSize: '14px', 
                                        fontWeight: '900', 
                                        fill: '#ffffff', 
                                        fontFamily: "'Outfit', -apple-system, BlinkMacSystemFont, sans-serif", 
                                        userSelect: 'none' 
                                      }}
                                    >
                                      {f}
                                    </text>
                                </g>
                            );
                        }
                        return null;
                    })}
                </g>
            );
          })}

          {/* Glowing Playhead Line */}
          <line 
            ref={playheadRef} 
            x1={0} 
            y1={0} 
            x2={0} 
            y2={0} 
            stroke="#fbbf24" 
            strokeWidth="2.5" 
            filter="url(#gold-glow)"
            className="playhead-line"
            style={{ display: 'none' }}
          />
        </svg>
      </div>
    </div>
  );
};

export default TabRendererSVG;
