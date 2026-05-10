import React, { useEffect, useRef, useState } from 'react';
import * as alphaTab from '@coderline/alphatab';

interface TabEditorProps {
  alphaTex: string;
}

const TabEditor: React.FC<TabEditorProps> = ({ alphaTex }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<any>(null);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize AlphaTab once
  useEffect(() => {
    if (!containerRef.current || apiRef.current) return;

    console.log("Initializing AlphaTab Engine...");
    try {
      const api = new alphaTab.AlphaTabApi(containerRef.current, {
        core: {
          tex: true,
          fontDirectory: 'https://cdn.jsdelivr.net/npm/@coderline/alphatab@1.8.2/dist/font/'
        },
        display: { staveProfile: 'Tab' }
      });

      api.renderFinished.on(() => {
        console.log("AlphaTab Render Complete");
        setIsReady(true);
        setError(null);
      });

      api.error.on((err: any) => {
        console.error("AlphaTab API Error:", err);
        setError(err.message || "Rendering failed");
      });

      apiRef.current = api;
    } catch (e: any) {
      console.error("Initialization Error:", e);
      setError(e.message);
    }

    return () => {
      if (apiRef.current) {
        apiRef.current.destroy();
        apiRef.current = null;
      }
    };
  }, []);

  // Update notes when alphaTex changes
  useEffect(() => {
    if (apiRef.current && alphaTex) {
      console.log("Pushing Data to AlphaTab...");
      try {
        apiRef.current.tex(alphaTex);
      } catch (e: any) {
        setError("AlphaTex Data Error: " + e.message);
      }
    }
  }, [alphaTex]);

  const forceRender = () => {
    if (apiRef.current && alphaTex) apiRef.current.tex(alphaTex);
  };

  return (
    <div className="tab-editor-container" style={{ marginTop: '50px' }}>
      {error && (
        <div style={{ color: '#721c24', background: '#f8d7da', padding: '15px', borderRadius: '8px', border: '1px solid #f5c6cb', marginBottom: '15px' }}>
          <strong>AlphaTab Error:</strong> {error}
        </div>
      )}

      <div className="tab-toolbar" style={{ marginBottom: '15px', display: 'flex', gap: '10px', justifyContent: 'center' }}>
        <button 
          onClick={() => apiRef.current?.playPause()} 
          style={{ background: '#2ecc71', color: 'white', fontWeight: 'bold' }}
        >
          {isReady ? 'Play / Pause Tab' : 'Loading Engine...'}
        </button>
        <button onClick={forceRender} style={{ background: '#3498db', color: 'white' }}>🔄 Refresh Tab Display</button>
      </div>

      <div 
        ref={containerRef} 
        style={{ 
          border: '3px solid #1e293b', 
          borderRadius: '16px', 
          background: 'white', 
          minHeight: '600px', 
          width: '100%',
          padding: '20px',
          boxShadow: 'inset 0 2px 10px rgba(0,0,0,0.1)'
        }}
      ></div>
    </div>
  );
};

export default TabEditor;
