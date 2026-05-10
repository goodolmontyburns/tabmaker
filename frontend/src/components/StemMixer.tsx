import React from 'react';

interface StemMixerProps {
  stems: Record<string, string>;
  original?: string;
  onTranscribe: (name: string) => void;
  isRetranscribing: boolean;
}

const StemMixer: React.FC<StemMixerProps> = ({ stems, original, onTranscribe, isRetranscribing }) => {
  const download = (url: string, filename: string) => {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
  };

  return (
    <div className="stem-mixer" style={{ margin: '20px 0', padding: '20px', background: '#f8f9fa', borderRadius: '12px', border: '1px solid #dee2e6' }}>
      <h3 style={{ marginTop: 0, color: '#333' }}>AI Stem Mixer & Export</h3>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '15px', marginTop: '15px' }}>
        {Object.entries(stems).map(([name, url]) => (
          <div key={name} style={{ background: 'white', padding: '15px', borderRadius: '8px', border: '1px solid #eee' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong style={{ textTransform: 'capitalize', color: '#444' }}>{name}</strong>
                <div style={{ display: 'flex', gap: '5px' }}>
                    <button 
                        onClick={() => onTranscribe(name)}
                        disabled={isRetranscribing}
                        style={{ fontSize: '0.7rem', padding: '4px 8px', background: '#3498db', color: 'white', border: 'none' }}
                    >
                        {isRetranscribing ? '...' : 'Transcribe'}
                    </button>
                    <button onClick={() => download(url, `${name}.wav`)} style={{ fontSize: '0.7rem', padding: '4px 8px', background: '#eee' }}>💾</button>
                </div>
            </div>
            <audio controls src={url} style={{ width: '100%', marginTop: '10px', height: '35px' }} />
          </div>
        ))}
        {original && (
          <div style={{ background: '#e9ecef', padding: '15px', borderRadius: '8px', border: '1px solid #dee2e6' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong style={{ color: '#444' }}>Original (Cropped)</strong>
                <div style={{ display: 'flex', gap: '5px' }}>
                    <button 
                        onClick={() => onTranscribe('cropped')}
                        disabled={isRetranscribing}
                        style={{ fontSize: '0.7rem', padding: '4px 8px', background: '#666', color: 'white', border: 'none' }}
                    >
                        {isRetranscribing ? '...' : 'Transcribe'}
                    </button>
                    <button onClick={() => download(original, `original.wav`)} style={{ fontSize: '0.7rem', padding: '4px 8px', background: '#ccc' }}>💾</button>
                </div>
            </div>
            <audio controls src={original} style={{ width: '100%', marginTop: '10px', height: '35px' }} />
          </div>
        )}
      </div>
    </div>
  );
};

export default StemMixer;
