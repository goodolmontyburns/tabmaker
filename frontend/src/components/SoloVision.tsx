import React, { useEffect, useRef, useState } from 'react';

interface SoloVisionProps {
  visionLayers: Record<string, number[][]> | null;
  spectrogramData: number[][] | null;
  duration: number;
  audioRef: React.RefObject<HTMLAudioElement | null>;
  playheadOffset: number;
  onSelect: (minMidi: number, maxMidi: number, t1: number, t2: number) => void;
  onPreview: (minMidi: number, maxMidi: number, t1: number, t2: number) => void;
}

const SoloVision: React.FC<SoloVisionProps> = ({ visionLayers, spectrogramData, duration, audioRef, playheadOffset, onSelect, onPreview }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const playheadOverlayRef = useRef<HTMLDivElement>(null);
  const [visibleLayers, setVisibleLayers] = useState<Record<string, boolean>>({
    guitar: true,
    piano: true,
    vocals: true,
    other: true,
    bass: true
  });
  const [selection, setSelection] = useState<{ x1: number, y1: number, x2: number, y2: number } | null>(null);
  const [isDrawing, setIsDrawing] = useState(false);

  const colors: Record<string, string> = {
    guitar: '255, 20, 147',
    piano: '52, 152, 219',
    vocals: '241, 196, 15',
    other: '155, 89, 182',
    bass: '46, 204, 113'
  };

  const updatePlayheadDOM = (time: number) => {
    if (!playheadOverlayRef.current) return;
    const ratio = Math.max(0, Math.min(duration, time)) / duration;
    playheadOverlayRef.current.style.left = `${ratio * 100}%`;
    playheadOverlayRef.current.style.display = 'block';
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !spectrogramData || !spectrogramData.length || !spectrogramData[0]) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const freqs = spectrogramData.length;
    const frames = spectrogramData[0].length;
    const cellW = canvas.width / frames;
    const cellH = canvas.height / freqs;

    for (let i = 0; i < freqs; i++) {
        for (let j = 0; j < frames; j++) {
            if (spectrogramData[i] && spectrogramData[i][j] !== undefined) {
                const val = (spectrogramData[i][j] + 80) / 80;
                if (val > 0.1) {
                    const intensity = Math.floor(val * 100);
                    ctx.fillStyle = `rgb(0, ${intensity}, ${intensity})`; 
                    ctx.fillRect(j * cellW, canvas.height - (i * cellH), cellW + 1, cellH + 1);
                }
            }
        }
    }

    if (visionLayers) {
        Object.entries(visionLayers).forEach(([stem, data]) => {
            if (!visibleLayers[stem] || !data || !data.length) return;
            const vFrames = data.length;
            const vCellW = canvas.width / vFrames;
            const vCellH = canvas.height / 88;
            const color = colors[stem] || '255, 255, 255';
            for (let f = 0; f < vFrames; f++) {
                if (data[f]) {
                    for (let n = 0; n < 88; n++) {
                        const prob = data[f][n];
                        if (prob > 0.15) {
                            ctx.fillStyle = `rgba(${color}, ${prob})`;
                            ctx.fillRect(f * vCellW, canvas.height - (n * vCellH), vCellW + 1, vCellH + 1);
                        }
                    }
                }
            }
        });
    }

    if (selection) {
        ctx.strokeStyle = '#00ff00';
        ctx.setLineDash([5, 5]);
        ctx.strokeRect(Math.min(selection.x1, selection.x2), Math.min(selection.y1, selection.y2), Math.abs(selection.x2 - selection.x1), Math.abs(selection.y2 - selection.y1));
        ctx.fillStyle = 'rgba(0, 255, 0, 0.1)';
        ctx.fillRect(Math.min(selection.x1, selection.x2), Math.min(selection.y1, selection.y2), Math.abs(selection.x2 - selection.x1), Math.abs(selection.y2 - selection.y1));
    }

  }, [spectrogramData, visionLayers, visibleLayers, selection]);

  const playheadOffsetRef = useRef<number>(playheadOffset);
  useEffect(() => {
    playheadOffsetRef.current = playheadOffset;
  }, [playheadOffset]);

  // Instantly sync playhead when playheadOffset or duration changes (while paused)
  useEffect(() => {
    const audio = document.getElementById('reference-audio') as HTMLAudioElement;
    if (audio && audio.paused) {
      updatePlayheadDOM(audio.currentTime - playheadOffset);
    }
  }, [playheadOffset, duration]);

  useEffect(() => {
    const audio = document.getElementById('reference-audio') as HTMLAudioElement || audioRef.current;
    if (!audio) return;
    
    let lastAudioTime = audio.currentTime;
    let lastSyncTime = performance.now();
    let animationFrameId: number = 0;

    const cancelAnimation = () => {
      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
        animationFrameId = 0;
      }
    };

    const animatePlayhead = () => {
      const now = performance.now();
      if (audio.currentTime !== lastAudioTime) {
        lastAudioTime = audio.currentTime;
        lastSyncTime = now;
      }
      const elapsedSinceSync = (now - lastSyncTime) / 1000;
      const interpolated = lastAudioTime + Math.min(0.5, elapsedSinceSync * audio.playbackRate);
      
      const visualTime = Math.max(0, Math.min(duration, interpolated - playheadOffsetRef.current));
      updatePlayheadDOM(visualTime);
      
      if (!audio.paused) {
        cancelAnimation();
        animationFrameId = requestAnimationFrame(animatePlayhead);
      }
    };

    const handlePlay = () => {
      lastAudioTime = audio.currentTime;
      lastSyncTime = performance.now();
      cancelAnimation();
      animationFrameId = requestAnimationFrame(animatePlayhead);
    };

    const handlePause = () => {
      cancelAnimation();
      updatePlayheadDOM(audio.currentTime - playheadOffsetRef.current);
    };

    const handleSeeked = () => {
      updatePlayheadDOM(audio.currentTime - playheadOffsetRef.current);
    };

    audio.addEventListener('play', handlePlay);
    audio.addEventListener('pause', handlePause);
    audio.addEventListener('seeked', handleSeeked);

    // Initial sync
    updatePlayheadDOM(audio.currentTime - playheadOffsetRef.current);

    // If already playing, start animation loop
    if (!audio.paused) {
      cancelAnimation();
      animationFrameId = requestAnimationFrame(animatePlayhead);
    }

    return () => {
      cancelAnimation();
      audio.removeEventListener('play', handlePlay);
      audio.removeEventListener('pause', handlePause);
      audio.removeEventListener('seeked', handleSeeked);
    };
  }, [duration, audioRef]);

  const handleMouseDown = (e: React.MouseEvent) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setSelection({ x1: x, y1: y, x2: x, y2: y });
    setIsDrawing(true);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDrawing || !selection) return;
    const rect = canvasRef.current!.getBoundingClientRect();
    setSelection({ ...selection, x2: e.clientX - rect.left, y2: e.clientY - rect.top });
  };

  const handleMouseUp = () => {
    setIsDrawing(false);
    if (selection) {
        const rect = canvasRef.current!.getBoundingClientRect();
        const t1 = (Math.min(selection.x1, selection.x2) / rect.width) * duration;
        const t2 = (Math.max(selection.x1, selection.x2) / rect.width) * duration;
        const minMidi = Math.floor((1 - Math.max(selection.y1, selection.y2) / rect.height) * 88) + 21;
        const maxMidi = Math.floor((1 - Math.min(selection.y1, selection.y2) / rect.height) * 88) + 21;
        onSelect(minMidi, maxMidi, t1, t2);
    }
  };

  const stemKeys = visionLayers ? Object.keys(visionLayers) : [];

  return (
    <div className="spectral-pro" style={{ background: '#1e1e1e', padding: '25px', borderRadius: '16px' }}>
        <div style={{ display: 'flex', gap: '20px', color: 'white', marginBottom: '15px', flexWrap: 'wrap' }}>
            <strong>Toggle Overlays:</strong>
            {stemKeys.map(stem => (
                <label key={stem} style={{ cursor: 'pointer', display: 'flex', alignItems: 'center' }}>
                    <input 
                        type="checkbox" 
                        checked={visibleLayers[stem] || false} 
                        onChange={() => setVisibleLayers({...visibleLayers, [stem]: !visibleLayers[stem]})}
                    />
                    <span style={{ marginLeft: '5px', color: `rgb(${colors[stem]})`, textTransform: 'capitalize' }}>{stem}</span>
                </label>
            ))}
        </div>
        <div style={{ position: 'relative', width: '100%', height: '400px' }}>
            <canvas 
                ref={canvasRef} width={1200} height={400} 
                onMouseDown={handleMouseDown} onMouseMove={handleMouseMove} onMouseUp={handleMouseUp}
                style={{ width: '100%', height: '400px', cursor: 'crosshair', borderRadius: '8px', border: '1px solid #444' }}
            />
            <div 
                ref={playheadOverlayRef} 
                style={{ 
                    position: 'absolute', 
                    top: 0, 
                    bottom: 0, 
                    left: 0, 
                    width: '2px', 
                    backgroundColor: '#fff', 
                    pointerEvents: 'none', 
                    transition: 'none',
                    display: 'none',
                    boxShadow: '0 0 8px #fff'
                }} 
            />
        </div>
        <div style={{ marginTop: '15px', display: 'flex', gap: '15px' }}>
            <button onClick={() => {
                if (selection) {
                    const rect = canvasRef.current!.getBoundingClientRect();
                    const t1 = (Math.min(selection.x1, selection.x2) / rect.width) * duration;
                    const t2 = (Math.max(selection.x1, selection.x2) / rect.width) * duration;
                    const min = Math.floor((1 - Math.max(selection.y1, selection.y2) / rect.height) * 88) + 21;
                    const max = Math.floor((1 - Math.min(selection.y1, selection.y2) / rect.height) * 88) + 21;
                    onPreview(min, max, t1, t2);
                }
            }} style={{ background: '#f39c12', color: 'white' }}>Listen to Selection</button>
            <button onClick={() => setSelection(null)} style={{ background: '#666', color: 'white' }}>Clear</button>
        </div>
    </div>
  );
};

export default SoloVision;
