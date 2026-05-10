import React, { useEffect, useRef, useState } from 'react';
import WaveSurfer from 'wavesurfer.js';
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.js';

interface AudioTrimmerProps {
  onTrim: (startTime: number, endTime: number, file: File | null, youtubeUrl?: string) => void;
  externalFile?: File | null;
}

const AudioTrimmer: React.FC<AudioTrimmerProps> = ({ onTrim, externalFile }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const wavesurferRef = useRef<WaveSurfer | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [youtubeUrl, setYoutubeUrl] = useState('');
  const [isPlaying, setIsPlaying] = useState(false);

  // Manual time states as strings to fix the "persistent zero" bug
  const [startTime, setStartTime] = useState<string>('0');
  const [endTime, setEndTime] = useState<string>('0');

  const [regions, setRegions] = useState<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const wavesurfer = WaveSurfer.create({
      container: containerRef.current,
      waveColor: '#4F4A85',
      progressColor: '#383351',
      cursorColor: '#383351',
      barWidth: 2,
      barRadius: 3,
      height: 100,
    });

    const regionsPlugin = wavesurfer.registerPlugin(RegionsPlugin.create());
    setRegions(regionsPlugin);

    wavesurfer.on('ready', () => {
      const d = wavesurfer.getDuration();
      setEndTime(d.toFixed(2));
      
      regionsPlugin.addRegion({
        start: 0,
        end: Math.min(d, 30),
        color: 'rgba(0, 255, 0, 0.1)',
        drag: true,
        resize: true,
      });
    });

    wavesurfer.on('play', () => setIsPlaying(true));
    wavesurfer.on('pause', () => setIsPlaying(false));

    wavesurferRef.current = wavesurfer;

    return () => wavesurfer.destroy();
  }, []);

  useEffect(() => {
    if (externalFile && wavesurferRef.current) {
      setFile(externalFile);
      setYoutubeUrl('');
      const url = URL.createObjectURL(externalFile);
      wavesurferRef.current.load(url);
    }
  }, [externalFile]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile && wavesurferRef.current) {
      setFile(selectedFile);
      setYoutubeUrl('');
      const url = URL.createObjectURL(selectedFile);
      wavesurferRef.current.load(url);
    }
  };

  const handleProcess = () => {
    const startVal = parseFloat(startTime) || 0;
    const endVal = parseFloat(endTime) || 0;

    let start = startVal;
    let end = endVal;

    const regionData = regions?.getRegions()[0];
    if (file && regionData) {
      start = regionData.start;
      end = regionData.end;
    }

    if (file) {
      onTrim(start, end, file);
    } else if (youtubeUrl) {
      if (end <= start) {
         alert("End time must be greater than start time.");
         return;
      }
      onTrim(start, end, null, youtubeUrl);
    }
  };

  return (
    <div className="audio-trimmer">
      <div style={{ marginBottom: '20px', display: 'flex', gap: '10px', flexDirection: 'column', alignItems: 'center' }}>
        <input 
          type="text" 
          placeholder="Paste YouTube URL here..." 
          value={youtubeUrl} 
          onChange={(e) => setYoutubeUrl(e.target.value)}
          style={{ padding: '8px', width: '400px', borderRadius: '4px', border: '1px solid #ccc' }}
        />
        <div>OR</div>
        <input type="file" accept="audio/*" onChange={handleFileChange} />
      </div>

      <div style={{ marginBottom: '20px', display: 'flex', gap: '20px', justifyContent: 'center', background: '#eee', padding: '15px', borderRadius: '8px' }}>
        <div>
          <label>Start (sec): </label>
          <input 
            type="number" 
            value={startTime} 
            onChange={(e) => setStartTime(e.target.value)}
            style={{ width: '80px', padding: '5px' }}
          />
        </div>
        <div>
          <label>End (sec): </label>
          <input 
            type="number" 
            value={endTime} 
            onChange={(e) => setEndTime(e.target.value)}
            style={{ width: '80px', padding: '5px' }}
          />
        </div>
        {file && <span style={{ color: '#666' }}>(Or use the slider below)</span>}
      </div>

      <div ref={containerRef} style={{ margin: '20px 0', border: '1px solid #ccc', borderRadius: '4px', background: '#fff' }} />
      
      {(file || youtubeUrl) && (
        <div className="controls">
          {file && (
            <button onClick={() => wavesurferRef.current?.playPause()}>
              {isPlaying ? 'Pause' : 'Play'}
            </button>
          )}
          <button onClick={handleProcess} style={{ marginLeft: '10px', backgroundColor: '#4CAF50', color: 'white', border: 'none', padding: '10px 20px', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}>
            Transcribe Selection
          </button>
        </div>
      )}
    </div>
  );
};

export default AudioTrimmer;
