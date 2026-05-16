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
  onUpdateNotes: (newNotes: Note[]) => void;
}

const TabRendererSVG: React.FC<TabRendererSVGProps> = ({ notes, duration, audioRef, onUpdateNotes }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [playheadX, setPlayheadX] = useState(60);
  const [currentTime, setCurrentTime] = useState(0);
  const [zoom, setZoom] = useState(250);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [isSynthPlaying, setIsSynthPlaying] = useState(false);
  const [targetFret, setTargetFret] = useState(10);
  const [preferOpen, setPreferOpen] = useState(true); // New Toggle State
  const audioContextRef = useRef<AudioContext | null>(null);
  const requestRef = useRef<number | null>(null);
  const synthStartTimeRef = useRef<number>(0);

  const [selection, setSelection] = useState<{ tStart: number, tEnd: number } | null>(null);
  const [isSelecting, setIsSelecting] = useState(false);
  const [dragStartPos, setDragStartPos] = useState<number | null>(null);
  const [activeEditingNoteId, setActiveEditingNoteId] = useState<string | null>(null);

  const bpm = 65;
  const beatDuration = 60 / bpm;
  const secsPerMeasure = beatDuration * 4;
  const paddingLeft = 80; 
  const width = duration * zoom;
  const tabLineSpacing = 20;
  const tabTop = 60;
  const height = 220;

  const offsets = [64, 59, 55, 50, 45, 40];

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

  const animate = () => {
    let current = 0;
    if (isSynthPlaying && audioContextRef.current) {
        current = (audioContextRef.current.currentTime - synthStartTimeRef.current) * playbackSpeed;
    } else if (audioRef.current) {
        current = audioRef.current.currentTime;
    }
    if (current <= duration) {
        setCurrentTime(current);
        const x = paddingLeft + (current * zoom);
        setPlayheadX(x);
        if (containerRef.current) containerRef.current.scrollLeft = x - (containerRef.current.clientWidth * 0.4);
        requestRef.current = requestAnimationFrame(animate);
    } else { stopPlayback(); }
  };

  useEffect(() => {
    if (isSynthPlaying || (audioRef.current && !audioRef.current.paused)) {
        requestRef.current = requestAnimationFrame(animate);
    }
    return () => { if (requestRef.current) cancelAnimationFrame(requestRef.current); };
  }, [isSynthPlaying, zoom, playbackSpeed]);

  const stopPlayback = () => {
    if (audioContextRef.current) { audioContextRef.current.close(); audioContextRef.current = null; }
    setIsSynthPlaying(false);
    if (audioRef.current) audioRef.current.pause();
    if (requestRef.current) cancelAnimationFrame(requestRef.current);
  };

  const exportPDF = () => {
    const doc = jsPDF({ orientation: 'p', unit: 'pt', format: 'a4' });
    const pageWidth = doc.internal.pageSize.getWidth();
    const pageHeight = doc.internal.pageSize.getHeight();
    const margins = 50;
    const printableWidth = pageWidth - margins * 2;
    doc.setFontSize(22); doc.text("Transcribed Blues Solo", margins, 60);
    doc.setFontSize(10); doc.text("Tuning: E A D G B E | Tempo: 65 BPM", margins, 80);

    const rowHeight = 100;
    const lineSpacing = 12;
    const measuresPerLine = 2;
    const measureWidth = printableWidth / measuresPerLine;
    const pdfZoom = measureWidth / secsPerMeasure;
    let currentY = 120;

    for (let m = 0; m < duration / secsPerMeasure; m++) {
        const startTime = m * secsPerMeasure;
        const endTime = (m + 1) * secsPerMeasure;
        if (m % measuresPerLine === 0) {
            if (currentY + rowHeight > pageHeight - margins) { doc.addPage(); currentY = margins + 20; }
            doc.setFontSize(10); doc.text("TAB", margins - 25, currentY + 35);
        }
        const mX = margins + (m % measuresPerLine) * measureWidth;
        doc.setDrawColor(200);
        for (let s = 0; s < 6; s++) doc.line(mX, currentY + s * lineSpacing, mX + measureWidth, currentY + s * lineSpacing);
        doc.setDrawColor(0); doc.setLineWidth(1.5);
        doc.line(mX, currentY, mX, currentY + 5 * lineSpacing);
        notes.filter(n => n.t >= startTime && n.t < endTime).forEach(n => {
            const nX = mX + (n.t - startTime) * pdfZoom;
            const nY = currentY + (n.s - 1) * lineSpacing;
            doc.setFillColor(255, 255, 255); doc.rect(nX - 5, nY - 5, 10, 10, 'F');
            doc.text(n.f.toString(), nX, nY + 3, { align: 'center' });
        });
        if (m % measuresPerLine === measuresPerLine - 1 || m >= (duration / secsPerMeasure) - 1) currentY += rowHeight;
    }
    doc.save("TabMaker_Transcription.pdf");
  };

  const startSynth = () => {
    if (isSynthPlaying) { stopPlayback(); return; }
    const ctx = new AudioContext(); audioContextRef.current = ctx;
    const startTime = ctx.currentTime + 0.1;
    synthStartTimeRef.current = startTime;
    notes.forEach(n => {
        const freq = 440 * Math.pow(2, (n.p - 69) / 12);
        const osc = ctx.createOscillator(); const gain = ctx.createGain(); const filter = ctx.createBiquadFilter();
        osc.type = 'sawtooth'; osc.frequency.setValueAtTime(freq, startTime + (n.t / playbackSpeed));
        filter.type = 'lowpass'; filter.frequency.setValueAtTime(3000, startTime + (n.t / playbackSpeed));
        gain.gain.setValueAtTime(0, startTime + (n.t / playbackSpeed));
        gain.gain.linearRampToValueAtTime(0.15, startTime + (n.t / playbackSpeed) + 0.005);
        gain.gain.exponentialRampToValueAtTime(0.001, startTime + (n.t / playbackSpeed) + (n.d / playbackSpeed));
        osc.connect(filter); filter.connect(gain); gain.connect(ctx.destination);
        osc.start(startTime + (n.t / playbackSpeed)); osc.stop(startTime + (n.t / playbackSpeed) + (n.d / playbackSpeed));
    });
    setIsSynthPlaying(true);
  };

  return (
    <div className="pro-tab-view" style={{ textAlign: 'left', marginTop: '40px' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', background: '#f1f5f9', padding: '20px', borderRadius: '16px', border: '1px solid #e2e8f0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, color: '#1e293b' }}>Interactive Score Editor</h3>
            <div style={{ display: 'flex', gap: '10px' }}>
                <button onClick={exportPDF} style={{ background: '#3b82f6', color: 'white' }}>📄 Save PDF</button>
                <button onClick={startSynth} style={{ background: isSynthPlaying ? '#ef4444' : '#10b981', color: 'white' }}>
                    {isSynthPlaying ? 'Stop' : '🎸 Play Synth'}
                </button>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '30px', alignItems: 'center', background: '#fff', padding: '15px', borderRadius: '12px', border: '1px solid #cbd5e1' }}>
              <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <label style={{ fontWeight: 'bold' }}>Neck Position Shift ({selection ? "Selected Area" : "All"}): Fret {targetFret}</label>
                      <label style={{ cursor: 'pointer', background: '#eef2f7', padding: '4px 10px', borderRadius: '6px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '5px' }}>
                          <input 
                            type="checkbox" 
                            checked={preferOpen} 
                            onChange={(e) => {
                                const val = e.target.checked;
                                setPreferOpen(val);
                                optimizePositions(targetFret, val);
                            }} 
                          />
                          Prefer Open Strings (for Bass)
                      </label>
                  </div>
                  <input type="range" min="0" max="17" value={targetFret} onChange={(e) => { setTargetFret(Number(e.target.value)); optimizePositions(Number(e.target.value), preferOpen); }} style={{ width: '100%', marginTop: '10px' }} />
              </div>
              <div style={{ display: 'flex', gap: '15px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <label style={{ fontSize: '0.7rem', fontWeight: 'bold' }}>Speed</label>
                    <input type="range" min="0.5" max="1.5" step="0.1" value={playbackSpeed} onChange={(e) => setPlaybackSpeed(Number(e.target.value))} style={{ width: '80px' }} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <label style={{ fontSize: '0.7rem', fontWeight: 'bold' }}>Zoom</label>
                    <input type="range" min="100" max="1000" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} style={{ width: '80px' }} />
                  </div>
              </div>
          </div>
      </div>

      <div ref={containerRef} style={{ width: '100%', overflowX: 'auto', background: '#fff', borderRadius: '16px', border: '3px solid #1e293b', marginTop: '15px', position: 'relative' }}>
        <svg ref={svgRef} width={width + 500} height={height} onMouseDown={(e) => { if (e.button === 0) { const rect = svgRef.current!.getBoundingClientRect(); setDragStartPos(e.clientX - rect.left); setIsSelecting(true); setSelection(null); } }} onMouseMove={(e) => { if (isSelecting && dragStartPos !== null) { const rect = svgRef.current!.getBoundingClientRect(); const xCurrent = e.clientX - rect.left; setSelection({ tStart: Math.max(0, (Math.min(dragStartPos, xCurrent) - paddingLeft) / zoom), tEnd: Math.min(duration, (Math.max(dragStartPos, xCurrent) - paddingLeft) / zoom) }); } }} onMouseUp={() => setIsSelecting(false)} onMouseLeave={() => setIsSelecting(false)}>
          {selection && <rect x={paddingLeft + selection.tStart * zoom} y={0} width={(selection.tEnd - selection.tStart) * zoom} height={height} fill="rgba(59, 130, 246, 0.1)" stroke="rgba(59, 130, 246, 0.3)" />}
          <text x="15" y={tabTop + 50} fontSize="14" fontWeight="bold" fill="#1e293b">TAB</text>
          <text x="55" y={tabTop + 15} fontSize="18" fontWeight="bold">12</text>
          <text x="55" y={tabTop + 45} fontSize="18" fontWeight="bold">8</text>

          {Array.from({ length: Math.ceil(duration / secsPerMeasure) + 1 }).map((_, i) => (
              <g key={i}>
                <line x1={paddingLeft + (i * secsPerMeasure * zoom)} y1={tabTop} x2={paddingLeft + (i * secsPerMeasure * zoom)} y2={tabTop + (5 * tabLineSpacing)} stroke="#1e293b" strokeWidth="2" />
                <text x={paddingLeft + (i * secsPerMeasure * zoom) + 5} y={tabTop - 15} fontSize="11" fontWeight="bold">M{i+1}</text>
              </g>
          ))}

          {[0, 1, 2, 3, 4, 5].map(l => (
              <line key={l} x1={paddingLeft} y1={tabTop + l * tabLineSpacing} x2={width + paddingLeft} y2={tabTop + l * tabLineSpacing} stroke="#cbd5e1" strokeWidth="1" />
          ))}

          {notes.map((n) => {
            const x = paddingLeft + n.t * zoom;
            const yTab = tabTop + (n.s - 1) * tabLineSpacing;
            const isEditing = activeEditingNoteId === n.id;
            return (
                <g key={n.id}>
                    <circle cx={x} cy={yTab} r="10" fill="white" onClick={(e) => { e.stopPropagation(); setActiveEditingNoteId(isEditing ? null : n.id); }} style={{ cursor: 'pointer' }} />
                    <text x={x} y={yTab + 5} textAnchor="middle" onClick={(e) => { e.stopPropagation(); setActiveEditingNoteId(isEditing ? null : n.id); }} style={{ fontSize: '15px', fontWeight: '800', fill: isEditing ? '#ef4444' : '#0f172a', fontFamily: 'monospace', cursor: 'pointer', userSelect: 'none' }}>{n.f}</text>
                    {isEditing && offsets.map((offset, idx) => {
                        const s = idx + 1; if (s === n.s) return null;
                        const f = n.p - offset;
                        if (f >= 0 && f <= 24) {
                            const optY = tabTop + idx * tabLineSpacing;
                            return (
                                <g key={`${n.id}-opt-${s}`} onClick={(e) => { e.stopPropagation(); reassignNote(n.id, s, f); }} style={{ cursor: 'pointer' }}>
                                    <circle cx={x} cy={optY} r="9" fill="white" stroke="#ef4444" strokeWidth="1" />
                                    <text x={x} y={optY + 4} textAnchor="middle" style={{ fontSize: '11px', fontWeight: 'bold', fill: '#ef4444', fontFamily: 'monospace', userSelect: 'none' }}>{f}</text>
                                </g>
                            );
                        }
                        return null;
                    })}
                </g>
            );
          })}
          <line x1={playheadX} y1={0} x2={playheadX} y2={height} stroke="#ef4444" strokeWidth="2" />
        </svg>
      </div>
    </div>
  );
};

export default TabRendererSVG;
