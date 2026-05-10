import React, { useEffect, useRef, useState } from 'react';

interface SoloVisionProps {
  visionLayers: Record<string, number[][]> | null;
  spectrogramData: number[][] | null;
  duration: number;
  audioRef: React.RefObject<HTMLAudioElement | null>;
  onSelect: (minMidi: number, maxMidi: number, t1: number, t2: number) => void;
  onPreview: (minMidi: number, maxMidi: number, t1: number, t2: number) => void;
}

const SoloVision: React.FC<SoloVisionProps> = ({ visionLayers, spectrogramData, duration, audioRef, onSelect, onPreview }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [visibleLayers, setVisibleLayers] = useState<Record<string, boolean>>({ guitar: true });
  const [selection, setSelection] = useState<{ x1: number, y1: number, x2: number, y2: number } | null>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [playheadX, setPlayheadX] = useState(0);

  const colors: Record<string, string> = {
    guitar: '255, 20, 147',
    piano: '52, 152, 219',
    vocals: '241, 196, 15',
    other: '155, 89, 182',
    bass: '46, 204, 113'
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !spectrogramData || !spectrogramData.length) return;
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
            const val = (spectrogramData[i][j] + 80) / 80;
            if (val > 0.1) {
                const intensity = Math.floor(val * 100);
                ctx.fillStyle = `rgb(0, ${intensity}, ${intensity})`; 
                ctx.fillRect(j * cellW, canvas.height - (i * cellH), cellW + 1, cellH + 1);
            }
        }
    }

    if (visionLayers) {
        Object.entries(visionLayers).forEach(([stem, data]) => {
            if (!visibleLayers[stem] || !data) return;
            const vFrames = data.length;
            const vCellW = canvas.width / vFrames;
            const vCellH = canvas.height / 88;
            const color = colors[stem] || '255, 255, 255';
            for (let f = 0; f < vFrames; f++) {
                for (let n = 0; n < 88; n++) {
                    const prob = data[f][n];
                    if (prob > 0.15) {
                        ctx.fillStyle = `rgba(${color}, ${prob})`;
                        ctx.fillRect(f * vCellW, canvas.height - (n * vCellH), vCellW + 1, vCellH + 1);
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

    ctx.strokeStyle = '#fff';
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(playheadX, 0);
    ctx.lineTo(playheadX, canvas.height);
    ctx.stroke();

  }, [spectrogramData, visionLayers, visibleLayers, selection, playheadX]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const update = () => {
        const ratio = audio.currentTime / duration;
        setPlayheadX(ratio * (canvasRef.current?.width || 0));
    };
    audio.addEventListener('timeupdate', update);
    return () => audio.removeEventListener('timeupdate', update);
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
        <canvas 
            ref={canvasRef} width={1200} height={400} 
            onMouseDown={handleMouseDown} onMouseMove={handleMouseMove} onMouseUp={handleMouseUp}
            style={{ width: '100%', height: '400px', cursor: 'crosshair', borderRadius: '8px', border: '1px solid #444' }}
        />
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
