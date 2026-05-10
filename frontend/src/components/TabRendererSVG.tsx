import React, { useEffect, useRef, useState } from 'react';

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
  const [playheadX, setPlayheadX] = useState(50);
  const [currentTimeDisplay, setCurrentTimeDisplay] = useState(0);
  const [zoom, setZoom] = useState(250);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [isSynthPlaying, setIsSynthPlaying] = useState(false);
  const audioContextRef = useRef<AudioContext | null>(null);
  const requestRef = useRef<number | null>(null);
  const synthStartTimeRef = useRef<number>(0);

  const bpm = 65;
  const beatDuration = 60 / bpm;
  const secsPerMeasure = beatDuration * 4;
  const paddingLeft = 50;
  const width = duration * zoom;
  const height = 280;
  const stringSpacing = 30;
  const stemBaseline = height - 40;

  const animate = () => {
    let currentTime = 0;
    if (isSynthPlaying && audioContextRef.current) {
        currentTime = (audioContextRef.current.currentTime - synthStartTimeRef.current) * playbackSpeed;
    } else if (audioRef.current) {
        currentTime = audioRef.current.currentTime;
    }

    if (currentTime <= duration) {
        setCurrentTimeDisplay(currentTime);
        const x = paddingLeft + (currentTime * zoom);
        setPlayheadX(x);
        
        if (containerRef.current) {
            const container = containerRef.current;
            container.scrollLeft = x - (container.clientWidth * 0.4);
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
    // 1. SILENCE IMMEDIATELY by closing the context
    if (audioContextRef.current) {
        audioContextRef.current.close();
        audioContextRef.current = null;
    }
    setIsSynthPlaying(false);
    
    // 2. Stop Reference Audio
    if (audioRef.current) {
        audioRef.current.pause();
    }
    
    // 3. Stop Animation
    if (requestRef.current) {
        cancelAnimationFrame(requestRef.current);
    }
  };

  const playTwangyTone = (pitch: number, time: number, dur: number, ctx: AudioContext) => {
    const freq = 440 * Math.pow(2, (pitch - 69) / 12);
    const osc1 = ctx.createOscillator(); 
    const osc2 = ctx.createOscillator(); 
    const gain = ctx.createGain();
    const filter = ctx.createBiquadFilter();

    osc1.type = 'sawtooth';
    osc1.frequency.setValueAtTime(freq, time);
    osc2.type = 'square';
    osc2.frequency.setValueAtTime(freq, time);
    osc2.detune.setValueAtTime(4, time);

    filter.type = 'lowpass';
    filter.Q.setValueAtTime(5, time);
    filter.frequency.setValueAtTime(4000, time);
    filter.frequency.exponentialRampToValueAtTime(800, time + 0.1);
    filter.frequency.exponentialRampToValueAtTime(200, time + dur);

    gain.gain.setValueAtTime(0, time);
    gain.gain.linearRampToValueAtTime(0.15, time + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.001, time + dur);

    osc1.connect(filter);
    osc2.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);

    osc1.start(time);
    osc2.start(time);
    osc1.stop(time + dur);
    osc2.stop(time + dur);
  };

  const startSynthPlayback = () => {
    if (isSynthPlaying) { stopPlayback(); return; }
    
    // Create NEW context every time for immediate stop capability
    const ctx = new AudioContext();
    audioContextRef.current = ctx;
    const startTime = ctx.currentTime + 0.1;
    synthStartTimeRef.current = startTime;
    
    notes.forEach(n => {
        // Correct for playback speed in the scheduler
        playTwangyTone(n.p, startTime + (n.t / playbackSpeed), n.d / playbackSpeed, ctx);
    });

    setIsSynthPlaying(true);
  };

  return (
    <div className="tab-svg-view" style={{ textAlign: 'left', marginTop: '40px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#f1f3f5', padding: '15px', borderRadius: '12px', flexWrap: 'wrap', gap: '15px' }}>
          <div>
            <h3 style={{ margin: 0 }}>Pro Tablature Audit</h3>
            <p style={{ margin: '5px 0 0 0', fontSize: '0.85rem', color: '#666' }}>Time: {currentTimeDisplay.toFixed(2)}s</p>
          </div>
          
          <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 'bold' }}>Speed: {playbackSpeed}x</label>
                  <input type="range" min="0.5" max="1.5" step="0.1" value={playbackSpeed} onChange={(e) => setPlaybackSpeed(Number(e.target.value))} />
              </div>
              
              <button onClick={startSynthPlayback} style={{ background: isSynthPlaying ? '#ef4444' : '#10b981', color: 'white', padding: '12px 24px', fontSize: '1rem' }}>
                {isSynthPlaying ? '⏹ Stop SILENT' : '🎸 Play Twangy Synth'}
              </button>

              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 'bold' }}>Zoom</label>
                  <input type="range" min="100" max="1500" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
              </div>
          </div>
      </div>

      <div 
        ref={containerRef}
        style={{ width: '100%', overflowX: 'auto', background: '#fff', borderRadius: '16px', border: '3px solid #1e293b', marginTop: '15px', position: 'relative' }}
      >
        <svg width={width + 500} height={height}>
          {Array.from({ length: Math.ceil(duration / secsPerMeasure) + 1 }).map((_, i) => (
              <g key={i}>
                <line x1={paddingLeft + (i * secsPerMeasure * zoom)} y1={stringSpacing} x2={paddingLeft + (i * secsPerMeasure * zoom)} y2={6 * stringSpacing} stroke="#1e293b" strokeWidth="3" />
                <text x={paddingLeft + (i * secsPerMeasure * zoom) + 5} y={stringSpacing - 10} fontSize="12" fontWeight="bold">M{i+1}</text>
              </g>
          ))}

          {[1, 2, 3, 4, 5, 6].map((s) => (
            <line key={s} x1={paddingLeft} y1={s * stringSpacing} x2={width + paddingLeft} y2={s * stringSpacing} stroke="#cbd5e1" strokeWidth="1.5" />
          ))}

          {notes.map((n) => {
            const x = paddingLeft + n.t * zoom;
            const y = n.s * stringSpacing;
            const ratio = n.d / (60/65);
            const rhythm = ratio > 0.75 ? 'quarter' : ratio > 0.35 ? 'eighth' : 'sixteenth';
            return (
                <g key={n.id}>
                    <line x1={x} y1={y + 12} x2={x} y2={stemBaseline} stroke="#334155" strokeWidth="1.5" />
                    {(rhythm === 'eighth' || rhythm === 'sixteenth') && (
                        <path d={`M ${x} ${stemBaseline} q 10 -5 10 -15`} stroke="#334155" fill="none" strokeWidth="2" />
                    )}
                    {rhythm === 'sixteenth' && (
                        <path d={`M ${x} ${stemBaseline - 8} q 10 -5 10 -15`} stroke="#334155" fill="none" strokeWidth="2" />
                    )}
                    <circle cx={x} cy={y} r="11" fill="white" />
                    <text x={x} y={y + 5} textAnchor="middle" style={{ fontSize: '15px', fontWeight: '900', fill: '#0f172a', fontFamily: 'monospace' }}>
                        {n.f}
                    </text>
                </g>
            );
          })}
          
          {/* Playhead */}
          <line x1={playheadX} y1={0} x2={playheadX} y2={height} stroke="#ef4444" strokeWidth="3" />
        </svg>
      </div>
    </div>
  );
};

export default TabRendererSVG;
