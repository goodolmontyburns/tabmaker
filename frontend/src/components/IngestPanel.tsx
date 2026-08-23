import React, { useState } from 'react';

interface IngestPanelProps {
  onProcess: (
    youtubeUrl: string | null,
    file: File | null,
    startTime: number,
    endTime: number,
    targetFret: number,
    apiKey: string
  ) => void;
  onLoadGroundTruth?: () => void;
  isProcessing: boolean;
}

export const IngestPanel: React.FC<IngestPanelProps> = ({ onProcess, onLoadGroundTruth, isProcessing }) => {
  const [youtubeUrl, setYoutubeUrl] = useState('https://www.youtube.com/watch?v=vRcUufCKwOo');
  const [startTime, setStartTime] = useState('79');   // 1:19 = 79s
  const [endTime, setEndTime] = useState('123');     // 2:03 = 123s
  const [targetFret, setTargetFret] = useState(8);
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('gemini_api_key') || '');
  const [file, setFile] = useState<File | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const s = parseFloat(startTime) || 0;
    const end = parseFloat(endTime) || 0;
    if (end <= s) {
      alert('End time must be greater than start time.');
      return;
    }
    if (apiKey) {
      localStorage.setItem('gemini_api_key', apiKey.trim());
    }
    onProcess(
      file ? null : youtubeUrl.trim(),
      file,
      s,
      end,
      targetFret,
      apiKey.trim()
    );
  };

  const handleUrlChange = (newUrl: string) => {
    setYoutubeUrl(newUrl);
    if (!newUrl.includes('vRcUufCKwOo') && startTime === '79' && endTime === '123') {
      setStartTime('0');
      setEndTime('30');
    }
  };

  const handleSetExampleClapton = () => {
    setYoutubeUrl('https://www.youtube.com/watch?v=vRcUufCKwOo');
    setStartTime('79');
    setEndTime('123');
    setTargetFret(8);
    setFile(null);
  };

  return (
    <div
      className="ingest-panel"
      style={{
        background: '#ffffff',
        border: '1px solid #e2e8f0',
        borderRadius: '10px',
        padding: '20px',
        textAlign: 'left',
        maxWidth: '800px',
        margin: '0 auto 25px auto',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px', flexWrap: 'wrap', gap: '8px' }}>
        <h3 style={{ margin: 0, fontSize: '1.1rem', color: '#0f172a' }}>1. Select Audio / Video Source</h3>
        <div style={{ display: 'flex', gap: '8px' }}>
          {onLoadGroundTruth && (
            <button
              type="button"
              onClick={onLoadGroundTruth}
              style={{
                background: '#e0e7ff',
                border: '1px solid #c7d2fe',
                borderRadius: '6px',
                padding: '5px 12px',
                fontSize: '0.75rem',
                fontWeight: 600,
                color: '#3730a3',
                cursor: 'pointer'
              }}
            >
              ★ View Official Guitar Pro 3 Ground Truth (Measures 45–69)
            </button>
          )}
          <button
            type="button"
            onClick={handleSetExampleClapton}
            style={{
              background: '#f1f5f9',
              border: '1px solid #cbd5e1',
              borderRadius: '6px',
              padding: '5px 12px',
              fontSize: '0.75rem',
              color: '#475569',
              cursor: 'pointer'
            }}
          >
            Use Clapton YouTube Example
          </button>
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '5px' }}>
            YouTube Video URL
          </label>
          <input
            type="text"
            value={youtubeUrl}
            onChange={(e) => {
              handleUrlChange(e.target.value);
              if (file) setFile(null);
            }}
            placeholder="https://www.youtube.com/watch?v=..."
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid #cbd5e1',
              borderRadius: '6px',
              fontSize: '0.9rem',
              boxSizing: 'border-box'
            }}
          />
        </div>

        <div style={{ display: 'flex', gap: '15px', alignItems: 'center', margin: '15px 0', fontSize: '0.85rem', color: '#64748b' }}>
          <span>— OR upload audio file —</span>
          <input
            type="file"
            accept="audio/*"
            onChange={(e) => {
              const selected = e.target.files?.[0];
              if (selected) {
                setFile(selected);
                setYoutubeUrl('');
              }
            }}
            style={{ fontSize: '0.85rem' }}
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '15px', marginTop: '15px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#334155', marginBottom: '4px' }}>
              Start Time (sec)
            </label>
            <input
              type="number"
              step="0.5"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 10px',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
                fontSize: '0.85rem',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#334155', marginBottom: '4px' }}>
              End Time (sec)
            </label>
            <input
              type="number"
              step="0.5"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 10px',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
                fontSize: '0.85rem',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#334155', marginBottom: '4px' }}>
              Target Fret Box
            </label>
            <input
              type="number"
              min="0"
              max="17"
              value={targetFret}
              onChange={(e) => setTargetFret(parseInt(e.target.value, 10) || 8)}
              style={{
                width: '100%',
                padding: '6px 10px',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
                fontSize: '0.85rem',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#334155', marginBottom: '4px' }}>
              Gemini API Key (Optional)
            </label>
            <input
              type="password"
              placeholder="Detected from env or paste"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 10px',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
                fontSize: '0.85rem',
                boxSizing: 'border-box'
              }}
            />
          </div>
        </div>

        <div style={{ marginTop: '20px', textAlign: 'right' }}>
          <button
            type="submit"
            disabled={isProcessing}
            style={{
              background: isProcessing ? '#94a3b8' : '#0f172a',
              color: '#ffffff',
              border: 'none',
              borderRadius: '6px',
              padding: '10px 20px',
              fontSize: '0.9rem',
              fontWeight: 600,
              cursor: isProcessing ? 'not-allowed' : 'pointer'
            }}
          >
            {isProcessing ? 'Analyzing Solo...' : '⚡ Transcribe Solo'}
          </button>
        </div>
      </form>
    </div>
  );
};
