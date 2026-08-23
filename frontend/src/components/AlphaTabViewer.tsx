import React, { useEffect, useRef, useState } from 'react';
import * as alphaTab from '@coderline/alphatab';
import type { NoteItem } from './CleanTabScore';
import { OFFICIAL_CLAPTON_ALPHATEX } from '../utils/officialClaptonAlphaTex';
import { convertNotesToAlphaTex } from '../utils/alphaTexConverter';

interface AlphaTabViewerProps {
  notes: NoteItem[];
  songKey?: string;
  title?: string;
  duration?: number;
  isGroundTruth?: boolean;
  audioRef?: React.RefObject<HTMLAudioElement | null>;
}

export const AlphaTabViewer: React.FC<AlphaTabViewerProps> = ({
  notes,
  songKey = 'C Blues',
  title = 'Guitar Solo (AI Transcription)',
  duration = 0,
  isGroundTruth = false,
  audioRef
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<alphaTab.AlphaTabApi | null>(null);

  const [activeTabMode, setActiveTabMode] = useState<'official' | 'transcribed'>(
    isGroundTruth ? 'official' : 'transcribed'
  );
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1.0);
  const [isScoreReady, setIsScoreReady] = useState(false);

  const currentAlphaTex = isGroundTruth && activeTabMode === 'official'
    ? OFFICIAL_CLAPTON_ALPHATEX
    : convertNotesToAlphaTex(notes, title, 'TabMaker AI', 131, duration, isGroundTruth);

  useEffect(() => {
    if (!containerRef.current) return;

    // Configure AlphaTab to match Ultimate Guitar layout
    const settings = new alphaTab.Settings();
    settings.core.engine = 'svg';
    settings.core.fontDirectory = '/font/';
    settings.core.useWorkers = false; // Run directly in main thread for instant rendering
    settings.core.tex = true;
    settings.display.layoutMode = alphaTab.LayoutMode.Page;
    settings.display.staveProfile = alphaTab.StaveProfile.ScoreTab; // Standard notation + Tab clef
    settings.player.enablePlayer = true;
    settings.player.soundFont = '/soundfont/sonivox.sf2';

    try {
      if (apiRef.current) {
        apiRef.current.destroy();
      }

      const api = new alphaTab.AlphaTabApi(containerRef.current, settings);
      apiRef.current = api;

      api.scoreLoaded.on(() => {
        setIsScoreReady(true);
      });

      api.playerStateChanged.on((args) => {
        setIsPlaying(args.state === alphaTab.synth.PlayerState.Playing);
      });

      api.tex(currentAlphaTex);
    } catch (err) {
      console.error('Error initializing AlphaTab:', err);
    }

    return () => {
      if (apiRef.current) {
        apiRef.current.destroy();
        apiRef.current = null;
      }
    };
  }, []);

  // Sync with audioRef element
  useEffect(() => {
    const audio = audioRef?.current;
    if (!audio) return;

    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);

    audio.addEventListener('play', handlePlay);
    audio.addEventListener('pause', handlePause);

    return () => {
      audio.removeEventListener('play', handlePlay);
      audio.removeEventListener('pause', handlePause);
    };
  }, [audioRef?.current]);

  // Update score when notes or active mode changes
  useEffect(() => {
    if (apiRef.current && isScoreReady) {
      try {
        apiRef.current.tex(currentAlphaTex);
      } catch (err) {
        console.error('Error rendering AlphaTex:', err);
      }
    }
  }, [currentAlphaTex, isScoreReady]);

  const togglePlay = () => {
    const audio = audioRef?.current;
    if (audio && audio.src && audio.src.length > 0) {
      if (audio.paused) {
        audio.play().then(() => setIsPlaying(true)).catch((e) => {
          console.warn('Audio play failed:', e);
          if (apiRef.current) apiRef.current.playPause();
        });
      } else {
        audio.pause();
        setIsPlaying(false);
      }
    } else if (apiRef.current) {
      apiRef.current.playPause();
    }
  };

  const handleSpeedChange = (speed: number) => {
    setPlaybackSpeed(speed);
    if (audioRef?.current) {
      audioRef.current.playbackRate = speed;
    }
    if (apiRef.current) {
      apiRef.current.playbackSpeed = speed;
    }
  };

  const exportAlphaTexFile = () => {
    const blob = new Blob([currentAlphaTex], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${title.replace(/\s+/g, '_')}.alphatex`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ marginTop: '20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px', boxShadow: '0 1px 3px rgba(0,0,0,0.05)', overflow: 'hidden' }}>
      {/* Ultimate Guitar Style Toolbar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '14px 20px',
          background: '#f8fafc',
          borderBottom: '1px solid #e2e8f0',
          flexWrap: 'wrap',
          gap: '12px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 'bold', color: '#0f172a', letterSpacing: '-0.01em', fontFamily: 'Georgia, serif' }}>
              {title}
            </h3>
            <span style={{ fontSize: '0.85rem', color: '#64748b' }}>
              Key: <strong>{songKey}</strong> | Standard 4/4 {duration > 0 ? `| Duration: ${duration.toFixed(1)}s` : ''}
            </span>
          </div>

          {/* If Ground Truth Benchmark session, show mode switcher; otherwise show AI Transcribed Badge */}
          {isGroundTruth ? (
            <div style={{ display: 'flex', gap: '6px', background: '#e2e8f0', padding: '3px', borderRadius: '6px' }}>
              <button
                onClick={() => setActiveTabMode('official')}
                style={{
                  background: activeTabMode === 'official' ? '#ffffff' : 'transparent',
                  color: activeTabMode === 'official' ? '#0f172a' : '#64748b',
                  border: 'none',
                  borderRadius: '4px',
                  padding: '4px 10px',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  boxShadow: activeTabMode === 'official' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none'
                }}
              >
                ★ Official UG Score
              </button>
              <button
                onClick={() => setActiveTabMode('transcribed')}
                style={{
                  background: activeTabMode === 'transcribed' ? '#ffffff' : 'transparent',
                  color: activeTabMode === 'transcribed' ? '#0f172a' : '#64748b',
                  border: 'none',
                  borderRadius: '4px',
                  padding: '4px 10px',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  boxShadow: activeTabMode === 'transcribed' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none'
                }}
              >
                AI Audio Transcription
              </button>
            </div>
          ) : (
            <span style={{ fontSize: '0.8rem', background: '#e0f2fe', color: '#0369a1', padding: '4px 10px', borderRadius: '6px', fontWeight: 600 }}>
              AI Transcribed Score
            </span>
          )}
        </div>

        {/* Playback & Export Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={togglePlay}
            style={{
              background: isPlaying ? '#dc2626' : '#2563eb',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              padding: '7px 16px',
              fontSize: '0.9rem',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer'
            }}
          >
            {isPlaying ? '■ Pause' : '▶ Play Soundtrack'}
          </button>

          <div style={{ display: 'flex', alignItems: 'center', background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: '6px', overflow: 'hidden' }}>
            <span style={{ padding: '0 8px', fontSize: '0.75rem', color: '#64748b', fontWeight: 600 }}>Speed:</span>
            {[0.75, 1.0].map((s) => (
              <button
                key={s}
                onClick={() => handleSpeedChange(s)}
                style={{
                  background: playbackSpeed === s ? '#2563eb' : 'transparent',
                  color: playbackSpeed === s ? '#ffffff' : '#334155',
                  border: 'none',
                  padding: '5px 8px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                {s}x
              </button>
            ))}
          </div>

          <button
            onClick={exportAlphaTexFile}
            style={{
              background: '#f8fafc',
              color: '#334155',
              border: '1px solid #cbd5e1',
              borderRadius: '6px',
              padding: '6px 12px',
              fontSize: '0.85rem',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer'
            }}
            title="Download Guitar Pro / Ultimate Guitar compatible AlphaTex format"
          >
            🎸 Download AlphaTex
          </button>
        </div>
      </div>

      {/* AlphaTab Render Surface */}
      <div style={{ padding: '24px 16px', background: '#ffffff', minHeight: '600px', display: 'flex', justifyContent: 'center' }}>
        <div
          ref={containerRef}
          style={{ width: '100%', maxWidth: '1020px' }}
        />
      </div>

      {/* Subtle Footer Note */}
      <div style={{ padding: '8px 20px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: '0.75rem', color: '#94a3b8', textAlign: 'center' }}>
        Standard Notation + Tablature • Engraved dynamically by AlphaTab Core Engine
      </div>
    </div>
  );
};
