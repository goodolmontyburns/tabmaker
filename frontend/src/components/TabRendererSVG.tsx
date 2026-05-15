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
  const audioContextRef = useRef<AudioContext | null>(null);
  const requestRef = useRef<number | null>(null);
  const synthStartTimeRef = useRef<number>(0);

  // Editing State
  const [activeEditingNoteId, setActiveEditingNoteId] = useState<string | null>(null);

  const bpm = 65;
  const beatDuration = 60 / bpm;
  const secsPerMeasure = beatDuration * 4;
  const paddingLeft = 80; 
  const width = duration * zoom;
  
  const tabLineSpacing = 20;
  const tabTop = 60;
  const height = 220;

  const offsets = [64, 59, 55, 50, 45, 40]; // High E to Low E

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
    // If clicking the already active note, cancel editing
    if (activeEditingNoteId === noteId) {
        setActiveEditingNoteId(null);
    } else {
        setActiveEditingNoteId(noteId);
    }
  };

  const reassignNote = (noteId: string, newString: number, newFret: number) => {
    const newNotes = notes.map(n => {
        if (n.id !== noteId) return n;
        return { ...n, s: newString, f: newFret };
    });
    onUpdateNotes(newNotes);
    setActiveEditingNoteId(null); // Return note to black
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
            if (currentY + rowHeight > pageHeight - margins) {
                doc.addPage();
                currentY = margins + 20;
            }
            doc.setFontSize(10); doc.text("TAB", margins - 25, currentY + 35);
        }

        const mX = margins + (m % measuresPerLine) * measureWidth;
        doc.setDrawColor(200);
        for (let s = 0; s < 6; s++) {
            doc.line(mX, currentY + s * lineSpacing, mX + measureWidth, currentY + s * lineSpacing);
        }
        doc.setDrawColor(0); doc.setLineWidth(1.5);
        doc.line(mX, currentY, mX, currentY + 5 * lineSpacing);

        const measureNotes = notes.filter(n => n.t >= startTime && n.t < endTime);
        doc.setFontSize(10);
        doc.setFont("courier", "bold");
        measureNotes.forEach(n => {
            const nX = mX + (n.t - startTime) * pdfZoom;
            const nY = currentY + (n.s - 1) * lineSpacing;
            doc.setFillColor(255, 255, 255);
            doc.rect(nX - 5, nY - 5, 10, 10, 'F');
            doc.text(n.f.toString(), nX, nY + 3, { align: 'center' });
        });

        if (m % measuresPerLine === measuresPerLine - 1 || m >= (duration / secsPerMeasure) - 1) {
            currentY += rowHeight;
        }
    }
    doc.save("TabMaker_Transcription.pdf");
  };

  return (
    <div className="pro-tab-view" style={{ textAlign: 'left', marginTop: '40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#f1f5f9', padding: '15px', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
          <div>
            <h3 style={{ margin: 0, color: '#1e293b' }}>Interactive Fingering Editor</h3>
            <p style={{ margin: '5px 0 0 0', fontSize: '0.85rem', color: '#64748b' }}>
                {activeEditingNoteId ? "🔴 Select a red number to move the note to that string." : "💡 Click a note to see all string options."}
            </p>
          </div>
          <div style={{ display: 'flex', gap: '10px' }}>
              <button onClick={exportPDF} style={{ background: '#3b82f6', color: 'white' }}>📄 Save PDF</button>
              <button onClick={startSynth} style={{ background: isSynthPlaying ? '#ef4444' : '#10b981', color: 'white' }}>
                {isSynthPlaying ? 'Stop' : '🎸 Play Synth'}
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: '5px', background: '#fff', padding: '5px 10px', borderRadius: '8px', border: '1px solid #ddd' }}>
                  <label style={{ fontSize: '0.75rem' }}>Zoom: </label>
                  <input type="range" min="100" max="1000" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
              </div>
          </div>
      </div>

      <div ref={containerRef} style={{ width: '100%', overflowX: 'auto', background: '#fff', borderRadius: '16px', border: '3px solid #1e293b', marginTop: '15px' }}>
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
                    {/* Selected Note Head */}
                    <circle cx={x} cy={yTab} r="11" fill="white" />
                    <text 
                        x={x} y={yTab + 5} textAnchor="middle" 
                        style={{ fontSize: '16px', fontWeight: '900', fill: isEditing ? '#ef4444' : '#0f172a', fontFamily: 'monospace' }}
                    >
                        {n.f}
                    </text>

                    {/* Show alternative options in red if editing */}
                    {isEditing && offsets.map((offset, idx) => {
                        const s = idx + 1;
                        if (s === n.s) return null; // Skip current string
                        const f = n.p - offset;
                        if (f >= 0 && f <= 24) {
                            const optY = tabTop + idx * tabLineSpacing;
                            return (
                                <g key={`${n.id}-opt-${s}`} onClick={(e) => { e.stopPropagation(); reassignNote(n.id, s, f); }}>
                                    <circle cx={x} cy={optY} r="10" fill="white" stroke="#ef4444" strokeWidth="1" />
                                    <text x={x} y={optY + 4} textAnchor="middle" style={{ fontSize: '12px', fontWeight: 'bold', fill: '#ef4444', fontFamily: 'monospace' }}>
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
          <line x1={playheadX} y1={0} x2={playheadX} y2={height} stroke="#ef4444" strokeWidth="3" />
        </svg>
      </div>
    </div>
  );
};

export default TabRendererSVG;
