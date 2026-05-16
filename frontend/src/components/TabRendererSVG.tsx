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
  const [playheadX, setPlayheadX] = useState(60);
  const [currentTime, setCurrentTime] = useState(0);
  const [zoom, setZoom] = useState(250);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [isSynthPlaying, setIsSynthPlaying] = useState(false);
  const [targetFret, setTargetFret] = useState(10); // Default to 10th fret box
  const audioContextRef = useRef<AudioContext | null>(null);
  const requestRef = useRef<number | null>(null);
  const synthStartTimeRef = useRef<number>(0);

  const [activeEditingNoteId, setActiveEditingNoteId] = useState<string | null>(null);

  const bpm = 65;
  const beatDuration = 60 / bpm;
  const secsPerMeasure = beatDuration * 4;
  const paddingLeft = 80; 
  const width = duration * zoom;
  const height = 220;
  const tabLineSpacing = 20;
  const tabTop = 60;

  const offsets = [64, 59, 55, 50, 45, 40]; // High E to Low E

  // --- Optimization Logic ---
  const optimizePositions = (target: number) => {
    // Group notes by time to handle chords (prevent overlaps)
    const timeGroups: Record<number, Note[]> = {};
    notes.forEach(n => {
      const roundedT = Math.round(n.t * 100) / 100;
      if (!timeGroups[roundedT]) timeGroups[roundedT] = [];
      timeGroups[roundedT].push(n);
    });

    const newNotes: Note[] = [];

    Object.values(timeGroups).forEach(group => {
      const usedStrings = new Set<number>();
      
      // Sort notes in chord by pitch to assign highest pitch to highest string
      group.sort((a, b) => b.p - a.p).forEach(n => {
        let bestString = n.s;
        let bestFret = n.f;
        let minDistance = 999;

        // Check all 6 strings
        for (let sIdx = 0; sIdx < 6; sIdx++) {
          const stringNum = sIdx + 1;
          if (usedStrings.has(stringNum)) continue;

          const fret = n.p - offsets[sIdx];
          if (fret >= 0 && fret <= 24) {
            const distance = Math.abs(fret - target);
            if (distance < minDistance) {
              minDistance = distance;
              bestString = stringNum;
              bestFret = fret;
            }
          }
        }
        
        usedStrings.add(bestString);
        newNotes.push({ ...n, s: bestString, f: bestFret });
      });
    });

    onUpdateNotes(newNotes.sort((a, b) => a.t - b.t));
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
        if (containerRef.current) {
            containerRef.current.scrollLeft = x - (containerRef.current.clientWidth * 0.4);
        }
        requestRef.current = requestAnimationFrame(animate);
    } else {
        stopPlayback();
    }
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

  const handleNoteClick = (noteId: string) => {
    if (activeEditingNoteId === noteId) setActiveEditingNoteId(null);
    else setActiveEditingNoteId(noteId);
  };

  const reassignNote = (noteId: string, newString: number, newFret: number) => {
    const newNotes = notes.map(n => n.id === noteId ? { ...n, s: newString, f: newFret } : n);
    onUpdateNotes(newNotes);
    setActiveEditingNoteId(null);
  };

  const playTone = (pitch: number, time: number, dur: number, ctx: AudioContext) => {
    const freq = 440 * Math.pow(2, (pitch - 69) / 12);
    const osc1 = ctx.createOscillator();
    const gain = ctx.createGain();
    const filter = ctx.createBiquadFilter();
    osc1.type = 'sawtooth';
    osc1.frequency.setValueAtTime(freq, time);
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(3000, time);
    filter.frequency.exponentialRampToValueAtTime(400, time + 0.1);
    gain.gain.setValueAtTime(0, time);
    gain.gain.linearRampToValueAtTime(0.15, time + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.001, time + dur);
    osc1.connect(filter); filter.connect(gain); gain.connect(ctx.destination);
    osc1.start(time); osc1.stop(time + dur);
  };

  const startSynth = () => {
    if (isSynthPlaying) { stopPlayback(); return; }
    const ctx = new AudioContext();
    audioContextRef.current = ctx;
    const startTime = ctx.currentTime + 0.1;
    synthStartTimeRef.current = startTime;
    notes.forEach(n => playTone(n.p, startTime + (n.t / playbackSpeed), n.d / playbackSpeed, ctx));
    setIsSynthPlaying(true);
  };

  const exportPDF = () => {
    const doc = jsPDF({ orientation: 'p', unit: 'pt', format: 'a4' });
    const pageWidth = doc.internal.pageSize.getWidth();
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
            if (currentY + rowHeight > doc.internal.pageSize.getHeight() - margins) { doc.addPage(); currentY = margins + 20; }
            doc.setFontSize(10); doc.text("TAB", margins - 25, currentY + 35);
        }
        const mX = margins + (m % measuresPerLine) * measureWidth;
        doc.setDrawColor(200);
        for (let s = 0; s < 6; s++) doc.line(mX, currentY + s * lineSpacing, mX + measureWidth, currentY + s * lineSpacing);
        doc.setDrawColor(0); doc.setLineWidth(1.5); doc.line(mX, currentY, mX, currentY + 5 * lineSpacing);
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

  return (
    <div className="pro-tab-view" style={{ textAlign: 'left', marginTop: '40px' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', background: '#f8fafc', padding: '20px', borderRadius: '16px', border: '1px solid #e2e8f0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, color: '#1e293b' }}>Neck Position & Fingering Optimization</h3>
            <div style={{ display: 'flex', gap: '10px' }}>
                <button onClick={exportPDF} style={{ background: '#3b82f6', color: 'white' }}>📄 Save PDF</button>
                <button onClick={startSynth} style={{ background: isSynthPlaying ? '#ef4444' : '#10b981', color: 'white' }}>
                    {isSynthPlaying ? 'Stop' : '🎸 Play Synth'}
                </button>
            </div>
          </div>
          
          <div style={{ display: 'flex', gap: '30px', alignItems: 'center', background: '#fff', padding: '15px', borderRadius: '12px', border: '1px solid #cbd5e1' }}>
              <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <label style={{ fontWeight: 'bold', color: '#475569' }}>Target Neck Position (Fret {targetFret})</label>
                    <span style={{ fontSize: '0.8rem', color: '#64748b' }}>Move this to shift the whole solo to a new box</span>
                  </div>
                  <input 
                    type="range" min="0" max="17" step="1" value={targetFret} 
                    onChange={(e) => {
                        const val = Number(e.target.value);
                        setTargetFret(val);
                        optimizePositions(val);
                    }} 
                    style={{ width: '100%', marginTop: '10px', height: '8px', cursor: 'pointer' }}
                  />
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '5px', fontSize: '0.7rem', color: '#94a3b8' }}>
                      <span>Open</span><span>Fret 5</span><span>Fret 10</span><span>Fret 15</span>
                  </div>
              </div>
              <div style={{ width: '1px', height: '40px', background: '#e2e8f0' }}></div>
              <div style={{ display: 'flex', gap: '20px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <label style={{ fontSize: '0.75rem', fontWeight: 'bold' }}>Speed: {playbackSpeed}x</label>
                    <input type="range" min="0.5" max="1.5" step="0.1" value={playbackSpeed} onChange={(e) => setPlaybackSpeed(Number(e.target.value))} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <label style={{ fontSize: '0.75rem', fontWeight: 'bold' }}>Zoom</label>
                    <input type="range" min="100" max="1500" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
                  </div>
              </div>
          </div>
      </div>

      <div ref={containerRef} style={{ width: '100%', overflowX: 'auto', background: '#fff', borderRadius: '16px', border: '3px solid #1e293b', marginTop: '15px', position: 'relative' }}>
        <svg width={width + 500} height={height}>
          <text x="15" y={tabTop + 25} fontSize="35" fontWeight="bold" fill="#1e293b">𝄞</text>
          <text x="15" y={tabTop + 85} fontSize="14" fontWeight="bold" fill="#1e293b">TAB</text>
          <text x="55" y={tabTop + 35} fontSize="20" fontWeight="bold">12</text>
          <text x="55" y={tabTop + 65} fontSize="20" fontWeight="bold">8</text>

          {Array.from({ length: Math.ceil(duration / secsPerMeasure) + 1 }).map((_, i) => (
              <g key={i}>
                <line x1={paddingLeft + (i * secsPerMeasure * zoom)} y1={tabTop} x2={paddingLeft + (i * secsPerMeasure * zoom)} y2={tabTop + (5 * tabLineSpacing)} stroke="#1e293b" strokeWidth="2.5" />
                <text x={paddingLeft + (i * secsPerMeasure * zoom) + 5} y={tabTop - 15} fontSize="12" fontWeight="bold">M{i+1}</text>
              </g>
          ))}

          {[0, 1, 2, 3, 4, 5].map(l => (
              <line key={l} x1={paddingLeft} y1={tabTop + l * tabLineSpacing} x2={width + paddingLeft} y2={tabTop + l * tabLineSpacing} stroke="#cbd5e1" strokeWidth="1.5" />
          ))}

          {notes.map((n) => {
            const x = paddingLeft + n.t * zoom;
            const yTab = tabTop + (n.s - 1) * tabLineSpacing;
            const isEditing = activeEditingNoteId === n.id;
            return (
                <g key={n.id} onClick={() => handleNoteClick(n.id)} style={{ cursor: 'pointer' }}>
                    <circle cx={x} cy={yTab} r="11" fill="white" />
                    <text x={x} y={yTab + 5} textAnchor="middle" style={{ fontSize: '16px', fontWeight: '900', fill: isEditing ? '#ef4444' : '#0f172a', fontFamily: 'monospace' }}>
                        {n.f}
                    </text>
                    {isEditing && offsets.map((offset, idx) => {
                        const s = idx + 1;
                        if (s === n.s) return null;
                        const f = n.p - offset;
                        if (f >= 0 && f <= 24) {
                            const optY = tabTop + idx * tabLineSpacing;
                            return (
                                <g key={`${n.id}-opt-${s}`} onClick={(e) => { e.stopPropagation(); reassignNote(n.id, s, f); }}>
                                    <circle cx={x} cy={optY} r="10" fill="white" stroke="#ef4444" strokeWidth="1" />
                                    <text x={x} y={optY + 4} textAnchor="middle" style={{ fontSize: '12px', fontWeight: 'bold', fill: '#ef4444', fontFamily: 'monospace' }}>{f}</text>
                                </g>
                            );
                        }
                        return null;
                    })}
                </g>
            );
          })}
          <line x1={playheadX} y1={0} x2={playheadX} y2={height} stroke="#ef4444" strokeWidth="3" />
        </svg>
      </div>
    </div>
  );
};

export default TabRendererSVG;
