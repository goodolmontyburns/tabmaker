import React, { useEffect, useRef, useState } from 'react';
import { jsPDF } from 'jspdf';
import { convertNotesToAlphaTex } from '../utils/alphaTexConverter';

export interface NoteItem {
  id: string;
  p: number;      // MIDI pitch
  t: number;      // start time (s)
  d: number;      // duration (s)
  s: number;      // string 1..6
  f: number;      // fret 0..24
  bend?: {
    type: string;
    semitones: number;
    target_pitch: number;
  };
  slide?: string;
  vibrato?: boolean;
  articulation?: string;
  measure?: number;
}

interface CleanTabScoreProps {
  notes: NoteItem[];
  duration: number;
  audioRef: React.RefObject<HTMLAudioElement | null>;
  songKey?: string;
  title?: string;
  tempo?: number;
  beats?: number[];
  downbeats?: number[];
  isGroundTruth?: boolean;
  onUpdateNotes: (newNotes: NoteItem[]) => void;
}

const TUNING_OFFSETS = [64, 59, 55, 50, 45, 40]; // 1: high e, 2: B, 3: G, 4: D, 5: A, 6: low E

export const CleanTabScore: React.FC<CleanTabScoreProps> = ({
  notes,
  duration,
  audioRef,
  songKey = 'C Blues',
  title = 'Guitar Solo',
  tempo = 120,
  beats = [],
  downbeats = [],
  isGroundTruth = false,
  onUpdateNotes
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const playheadRef = useRef<SVGLineElement>(null);

  const [activeEditingNoteId, setActiveEditingNoteId] = useState<string | null>(null);
  const [isPlayingSynth, setIsPlayingSynth] = useState(false);
  const [activeTime, setActiveTime] = useState(0.0);

  const audioContextRef = useRef<AudioContext | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const refAnimFrameRef = useRef<number | null>(null);
  const synthStartRef = useRef<number>(0);
  const synthOffsetRef = useRef<number>(0);
  const scheduledNotesRef = useRef<Set<string>>(new Set());

  const safeTempo = isGroundTruth ? 131 : Math.max(40, Math.min(240, Math.round(tempo || 120)));
  const measureDur = (60.0 / safeTempo) * 4.0;
  const maxNoteTime = notes.reduce((max, n) => Math.max(max, n.t + n.d), 0);
  const effectiveDuration = Math.max(duration > 0 ? duration : 0, maxNoteTime, 4.0);
  const totalMeasures = isGroundTruth ? 25 : Math.max(1, Math.ceil(effectiveDuration / measureDur));
  const startMeasureNumber = isGroundTruth ? 45 : 1;

  const paddingLeft = 45;
  const paddingRight = 35;
  const rowWidth = 980;
  const stringSpacing = 13;
  const tabTop = 45;
  const stemHeight = 28;
  const rowHeight = tabTop + 5 * stringSpacing + stemHeight + 35;
  const measuresPerRow = 3;
  const measureWidth = (rowWidth - paddingLeft - paddingRight) / measuresPerRow;
  const numRows = Math.ceil(totalMeasures / measuresPerRow);
  const svgHeight = numRows * rowHeight + 30;

  const cancelAnim = () => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
  };

  const updatePlayhead = (t: number) => {
    if (!playheadRef.current) return;
    const clampedT = Math.max(0, Math.min(effectiveDuration, t));
    const m = Math.min(totalMeasures - 1, Math.floor(clampedT / measureDur));
    const rowIndex = Math.floor(m / measuresPerRow);
    const localM = m % measuresPerRow;
    const tLocal = clampedT - m * measureDur;

    const x = paddingLeft + localM * measureWidth + (tLocal / measureDur) * measureWidth;
    const yStart = rowIndex * rowHeight + tabTop - 10;
    const yEnd = yStart + 5 * stringSpacing + stemHeight + 14;

    playheadRef.current.setAttribute('x1', x.toString());
    playheadRef.current.setAttribute('x2', x.toString());
    playheadRef.current.setAttribute('y1', yStart.toString());
    playheadRef.current.setAttribute('y2', yEnd.toString());
    playheadRef.current.style.display = 'block';
  };

  // Sync playhead with reference HTMLAudioElement at 60 FPS
  useEffect(() => {
    const audio = audioRef?.current;
    if (!audio) return;

    const cancelRefLoop = () => {
      if (refAnimFrameRef.current) {
        cancelAnimationFrame(refAnimFrameRef.current);
        refAnimFrameRef.current = null;
      }
    };

    const tick = () => {
      if (!audio.paused && !audio.ended) {
        updatePlayhead(audio.currentTime);
        setActiveTime(audio.currentTime);
        refAnimFrameRef.current = requestAnimationFrame(tick);
      }
    };

    const onPlay = () => {
      cancelRefLoop();
      refAnimFrameRef.current = requestAnimationFrame(tick);
    };
    const onPause = () => cancelRefLoop();
    const onSeeked = () => {
      updatePlayhead(audio.currentTime);
      setActiveTime(audio.currentTime);
    };

    audio.addEventListener('play', onPlay);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('ended', onPause);
    audio.addEventListener('seeked', onSeeked);

    if (!audio.paused) {
      onPlay();
    }

    return () => {
      cancelRefLoop();
      audio.removeEventListener('play', onPlay);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('ended', onPause);
      audio.removeEventListener('seeked', onSeeked);
    };
  }, [audioRef?.current, effectiveDuration, measureDur, totalMeasures]);

  const toggleMidiPlayback = () => {
    if (isPlayingSynth) {
      stopMidiSynth();
    } else {
      startMidiSynth();
    }
  };

  const startMidiSynth = () => {
    if (audioRef.current && !audioRef.current.paused) {
      audioRef.current.pause();
    }

    if (!audioContextRef.current) {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      audioContextRef.current = new AudioCtx();
    }
    const ctx = audioContextRef.current;
    if (ctx.state === 'suspended') {
      ctx.resume();
    }

    setIsPlayingSynth(true);
    synthStartRef.current = ctx.currentTime;
    synthOffsetRef.current = activeTime >= effectiveDuration ? 0 : activeTime;
    scheduledNotesRef.current.clear();

    const synthLoop = () => {
      if (!audioContextRef.current) return;
      const currentSynthT = synthOffsetRef.current + (audioContextRef.current.currentTime - synthStartRef.current);
      updatePlayhead(currentSynthT);
      setActiveTime(currentSynthT);

      if (currentSynthT >= effectiveDuration) {
        stopMidiSynth();
        return;
      }

      notes.forEach((n) => {
        if (n.t >= currentSynthT && n.t < currentSynthT + 0.12 && !scheduledNotesRef.current.has(n.id)) {
          scheduledNotesRef.current.add(n.id);
          playPluck(n, Math.max(0, n.t - currentSynthT));
        }
      });

      animFrameRef.current = requestAnimationFrame(synthLoop);
    };

    cancelAnim();
    animFrameRef.current = requestAnimationFrame(synthLoop);
  };

  const stopMidiSynth = () => {
    cancelAnim();
    setIsPlayingSynth(false);
    scheduledNotesRef.current.clear();
  };

  const playPluck = (note: NoteItem, delay: number) => {
    const ctx = audioContextRef.current;
    if (!ctx) return;

    const now = ctx.currentTime + delay;
    const baseFreq = 440 * Math.pow(2, (note.p - 69) / 12);

    const osc1 = ctx.createOscillator();
    osc1.type = 'triangle';
    osc1.frequency.setValueAtTime(baseFreq, now);

    const osc2 = ctx.createOscillator();
    osc2.type = 'sawtooth';
    osc2.frequency.setValueAtTime(baseFreq, now);

    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(2200, now);
    filter.frequency.exponentialRampToValueAtTime(800, now + Math.max(0.08, note.d));

    if (note.bend) {
      const bendSemitones = note.bend.semitones || (note.bend.type === 'full' ? 2 : note.bend.type === 'half' ? 1 : 0.5);
      const targetFreq = 440 * Math.pow(2, (note.p + bendSemitones - 69) / 12);
      if (note.bend.type === 'release') {
        osc1.frequency.setValueAtTime(targetFreq, now);
        osc2.frequency.setValueAtTime(targetFreq, now);
        osc1.frequency.linearRampToValueAtTime(baseFreq, now + Math.min(note.d * 0.6, 0.25));
        osc2.frequency.linearRampToValueAtTime(baseFreq, now + Math.min(note.d * 0.6, 0.25));
      } else {
        osc1.frequency.linearRampToValueAtTime(targetFreq, now + Math.min(note.d * 0.6, 0.25));
        osc2.frequency.linearRampToValueAtTime(targetFreq, now + Math.min(note.d * 0.6, 0.25));
      }
    }

    if (note.vibrato) {
      const lfo = ctx.createOscillator();
      const lfoGain = ctx.createGain();
      lfo.frequency.setValueAtTime(5.5, now);
      lfoGain.gain.setValueAtTime(baseFreq * 0.02, now);
      lfo.connect(lfoGain);
      lfoGain.connect(osc1.frequency);
      lfoGain.connect(osc2.frequency);
      lfo.start(now + 0.1);
      lfo.stop(now + Math.max(0.15, note.d));
    }

    const gain1 = ctx.createGain();
    const gain2 = ctx.createGain();
    const masterGain = ctx.createGain();

    gain1.gain.setValueAtTime(0.001, now);
    gain1.gain.exponentialRampToValueAtTime(0.25, now + 0.005);
    gain1.gain.exponentialRampToValueAtTime(0.0001, now + Math.max(0.08, note.d));

    gain2.gain.setValueAtTime(0.001, now);
    gain2.gain.exponentialRampToValueAtTime(0.08, now + 0.005);
    gain2.gain.exponentialRampToValueAtTime(0.0001, now + Math.max(0.08, note.d * 0.7));

    osc1.connect(gain1);
    osc2.connect(gain2);
    gain1.connect(filter);
    gain2.connect(filter);

    filter.connect(masterGain);
    masterGain.connect(ctx.destination);

    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + Math.max(0.08, note.d));
    osc2.stop(now + Math.max(0.08, note.d));
  };

  const handleScoreClick = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const clientX = e.clientX - rect.left;
    const clientY = e.clientY - rect.top;

    const rowIndex = Math.floor(clientY / rowHeight);
    if (rowIndex < 0 || rowIndex >= numRows) return;

    const rowLocalX = clientX - paddingLeft;
    if (rowLocalX < 0 || rowLocalX > rowWidth - paddingLeft - paddingRight) return;

    const localM = Math.floor(rowLocalX / measureWidth);
    const m = rowIndex * measuresPerRow + localM;
    if (m >= totalMeasures) return;

    const inMeasureX = rowLocalX - localM * measureWidth;
    const frac = Math.max(0, Math.min(1, inMeasureX / measureWidth));
    const targetT = m * measureDur + frac * measureDur;

    setActiveTime(targetT);
    updatePlayhead(targetT);

    if (audioRef.current && audioRef.current.src) {
      audioRef.current.currentTime = Math.min(audioRef.current.duration || targetT, targetT);
    }

    if (isPlayingSynth && audioContextRef.current) {
      synthStartRef.current = audioContextRef.current.currentTime;
      synthOffsetRef.current = targetT;
      scheduledNotesRef.current.clear();
    }
  };

  const safeFileBase = (title || 'Guitar_Solo').replace(/[^a-zA-Z0-9_-]+/g, '_').replace(/^_+|_+$/g, '') || 'Guitar_Solo';

  const exportToPDF = () => {
    const svgElement = svgRef.current;
    if (!svgElement) return;

    const svgString = new XMLSerializer().serializeToString(svgElement);
    const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
    const URLObject = window.URL || window.webkitURL || window;
    const blobURL = URLObject.createObjectURL(svgBlob);

    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = svgElement.clientWidth * 2;
      canvas.height = svgElement.clientHeight * 2;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);

      const imgData = canvas.toDataURL('image/png');
      const doc = new jsPDF({
        orientation: 'landscape',
        unit: 'pt',
        format: [canvas.width / 2, canvas.height / 2]
      });

      doc.addImage(imgData, 'PNG', 0, 0, canvas.width / 2, canvas.height / 2);
      doc.save(`${safeFileBase}_Tab.pdf`);
      URLObject.revokeObjectURL(blobURL);
    };
    image.src = blobURL;
  };

  const exportAlphaTex = () => {
    const alphaTexString = convertNotesToAlphaTex(notes, title, 'TabMaker', safeTempo, duration, isGroundTruth, beats, downbeats);
    const blob = new Blob([alphaTexString], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${safeFileBase}.alphatex`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const clusteredNotes: { main: NoteItem; chord: NoteItem[]; x: number; y: number; rowIndex: number }[] = [];
  const processedNoteIds = new Set<string>();

  notes.forEach((n) => {
    if (processedNoteIds.has(n.id)) return;
    const chord = notes.filter((other) => Math.abs(other.t - n.t) <= 0.055);
    chord.forEach((c) => processedNoteIds.add(c.id));

    const m = Math.min(totalMeasures - 1, Math.floor(n.t / measureDur));
    const rowIndex = Math.floor(m / measuresPerRow);
    const localM = m % measuresPerRow;
    const tLocal = n.t - m * measureDur;

    const x = paddingLeft + localM * measureWidth + (tLocal / measureDur) * measureWidth;
    const rowY = rowIndex * rowHeight;
    const y = rowY + tabTop + (n.s - 1) * stringSpacing;

    clusteredNotes.push({ main: n, chord, x, y, rowIndex });
  });

  return (
    <div style={{ marginTop: '20px' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '12px',
          padding: '0 4px',
          flexWrap: 'wrap',
          gap: '8px'
        }}
      >
        <div>
          <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 'bold', color: '#111827', letterSpacing: '-0.01em', fontFamily: 'Georgia, serif' }}>
            {title} — Interactive Note &amp; Fingering Editor
          </h3>
          <span style={{ fontSize: '0.85rem', color: '#4b5563', fontFamily: '-apple-system, sans-serif' }}>
            Key: <strong>{songKey}</strong> | Tempo: <strong>{safeTempo} BPM</strong> | 4/4 | {isGroundTruth ? 'Measures 45–69' : `${totalMeasures} Measures`}
          </span>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={toggleMidiPlayback}
            style={{
              background: isPlayingSynth ? '#dc2626' : '#2563eb',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              padding: '6px 14px',
              fontSize: '0.85rem',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            {isPlayingSynth ? '■ Stop MIDI Synth' : '▶ Play MIDI Solo'}
          </button>
          <button
            onClick={exportAlphaTex}
            style={{
              background: '#f8fafc',
              color: '#334155',
              border: '1px solid #cbd5e1',
              borderRadius: '6px',
              padding: '6px 12px',
              fontSize: '0.85rem',
              fontWeight: 500,
              cursor: 'pointer'
            }}
          >
            Export AlphaTex
          </button>
          <button
            onClick={exportToPDF}
            style={{
              background: '#f8fafc',
              color: '#334155',
              border: '1px solid #cbd5e1',
              borderRadius: '6px',
              padding: '6px 12px',
              fontSize: '0.85rem',
              fontWeight: 500,
              cursor: 'pointer'
            }}
          >
            Export PDF
          </button>
        </div>
      </div>

      <div
        ref={containerRef}
        style={{
          width: '100%',
          overflowX: 'auto',
          background: '#ffffff',
          border: '1px solid #d1d5db',
          borderRadius: '6px',
          padding: '16px 0',
          boxShadow: '0 1px 4px rgba(0,0,0,0.06)'
        }}
      >
        <svg
          ref={svgRef}
          width={rowWidth}
          height={svgHeight}
          onClick={handleScoreClick}
          style={{ cursor: 'pointer', userSelect: 'none', display: 'block', margin: '0 auto', background: '#ffffff' }}
        >
          {Array.from({ length: numRows }).map((_, rIdx) => {
            const rowY = rIdx * rowHeight;
            return (
              <g key={`row-${rIdx}`}>
                {rIdx === 0 && (
                  <text
                    x={paddingLeft}
                    y={rowY + tabTop - 24}
                    fontSize="13"
                    fontWeight="bold"
                    fontFamily="Georgia, serif"
                    fill="#000000"
                  >
                    Solo
                  </text>
                )}

                {[0, 1, 2, 3, 4, 5].map((s) => (
                  <line
                    key={`string-${rIdx}-${s}`}
                    x1={paddingLeft}
                    y1={rowY + tabTop + s * stringSpacing}
                    x2={rowWidth - paddingRight}
                    y2={rowY + tabTop + s * stringSpacing}
                    stroke="#000000"
                    strokeWidth="0.8"
                  />
                ))}

                {Array.from({ length: measuresPerRow }).map((_, mOffset) => {
                  const absM = rIdx * measuresPerRow + mOffset;
                  if (absM >= totalMeasures) return null;
                  const mX = paddingLeft + mOffset * measureWidth;
                  const measureNumber = startMeasureNumber + absM;

                  return (
                    <g key={`measure-${absM}`}>
                      <line
                        x1={mX}
                        y1={rowY + tabTop}
                        x2={mX}
                        y2={rowY + tabTop + 5 * stringSpacing}
                        stroke="#000000"
                        strokeWidth="1.0"
                      />
                      <text
                        x={mX + 4}
                        y={rowY + tabTop - 6}
                        fontSize="10"
                        fontStyle="italic"
                        fontFamily="Georgia, serif"
                        fill="#4b5563"
                      >
                        {isGroundTruth && measureNumber === 45 ? '45 (Pickup)' : measureNumber}
                      </text>
                    </g>
                  );
                })}

                <line
                  x1={rowWidth - paddingRight}
                  y1={rowY + tabTop}
                  x2={rowWidth - paddingRight}
                  y2={rowY + tabTop + 5 * stringSpacing}
                  stroke="#000000"
                  strokeWidth="1.0"
                />
              </g>
            );
          })}

          {clusteredNotes.map(({ main, chord, x, rowIndex }) => {
            const rowY = rowIndex * rowHeight;

            return (
              <g key={`cluster-${main.id}`} className="note-group">
                <line
                  x1={x}
                  y1={rowY + tabTop + 5 * stringSpacing + 2}
                  x2={x}
                  y2={rowY + tabTop + 5 * stringSpacing + stemHeight}
                  stroke="#000000"
                  strokeWidth="1.0"
                />
                <line
                  x1={x}
                  y1={rowY + tabTop + 5 * stringSpacing + stemHeight}
                  x2={x + 5}
                  y2={rowY + tabTop + 5 * stringSpacing + stemHeight - 6}
                  stroke="#000000"
                  strokeWidth="1.2"
                />

                {chord.map((n) => {
                  const y = rowY + tabTop + (n.s - 1) * stringSpacing;
                  const fretStr = n.f.toString();
                  const textWidth = fretStr.length > 1 ? 14 : 9;
                  const isThisNoteEditing = activeEditingNoteId === n.id;

                  return (
                    <g key={n.id}>
                      <rect
                        x={x - textWidth / 2 - 1.5}
                        y={y - 6}
                        width={textWidth + 3}
                        height={12}
                        fill="#ffffff"
                      />
                      <text
                        x={x}
                        y={y + 4}
                        textAnchor="middle"
                        fontSize="12"
                        fontWeight="bold"
                        fill={isThisNoteEditing ? '#dc2626' : '#000000'}
                        fontFamily="Georgia, 'Times New Roman', serif"
                        onClick={(e) => {
                          e.stopPropagation();
                          setActiveEditingNoteId(isThisNoteEditing ? null : n.id);
                        }}
                        style={{ cursor: 'pointer', userSelect: 'none' }}
                      >
                        {n.f}
                      </text>

                      {n.bend && (
                        <g>
                          <path
                            d={`M ${x + 2} ${y - 6} C ${x + 4} ${y - 18}, ${x + 8} ${y - 24}, ${x + 10} ${y - 26}`}
                            fill="none"
                            stroke="#000000"
                            strokeWidth="1.0"
                          />
                          <polygon
                            points={`${x + 10},${y - 28} ${x + 7},${y - 22} ${x + 13},${y - 23}`}
                            fill="#000000"
                          />
                          <text
                            x={x + 11}
                            y={y - 30}
                            fontSize="10"
                            fontFamily="Georgia, serif"
                            fill="#000000"
                            textAnchor="middle"
                          >
                            {n.bend.type === 'full' ? '1' : n.bend.type === 'half' ? '1/2' : n.bend.type === 'quarter' ? '1/4' : `${n.bend.semitones / 2}`}
                          </text>
                        </g>
                      )}

                      {isThisNoteEditing &&
                        TUNING_OFFSETS.map((off, sIdx) => {
                          const altS = sIdx + 1;
                          if (altS === n.s) return null;
                          const altF = n.p - off;
                          if (altF >= 0 && altF <= 24) {
                            const optY = rowY + tabTop + sIdx * stringSpacing;
                            return (
                              <g
                                key={`opt-${n.id}-${altS}`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  const updated = notes.map((item) =>
                                    item.id === n.id ? { ...item, s: altS, f: altF } : item
                                  );
                                  onUpdateNotes(updated);
                                  setActiveEditingNoteId(null);
                                }}
                                style={{ cursor: 'pointer' }}
                              >
                                <circle cx={x} cy={optY} r="7" fill="#dc2626" />
                                <text
                                  x={x}
                                  y={optY + 3.5}
                                  textAnchor="middle"
                                  fontSize="9"
                                  fontWeight="bold"
                                  fill="#ffffff"
                                >
                                  {altF}
                                </text>
                              </g>
                            );
                          }
                          return null;
                        })}
                    </g>
                  );
                })}
              </g>
            );
          })}

          <line
            ref={playheadRef}
            x1={0}
            y1={0}
            x2={0}
            y2={0}
            stroke="#dc2626"
            strokeWidth="1.5"
            style={{ display: 'none', pointerEvents: 'none' }}
          />
        </svg>
      </div>
    </div>
  );
};
