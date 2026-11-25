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
  tempo?: number;
  beats?: number[];
  downbeats?: number[];
  isGroundTruth?: boolean;
  audioRef?: React.RefObject<HTMLAudioElement | null>;
}

export const AlphaTabViewer: React.FC<AlphaTabViewerProps> = ({
  notes,
  songKey = 'C Blues',
  title = 'Guitar Solo',
  duration = 0,
  tempo = 120,
  beats = [],
  downbeats = [],
  isGroundTruth = false,
  audioRef
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<alphaTab.AlphaTabApi | null>(null);
  const scoreEndTickRef = useRef<number>(0);

  const [activeTabMode, setActiveTabMode] = useState<'official' | 'transcribed'>(
    isGroundTruth ? 'official' : 'transcribed'
  );
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1.0);
  const [isScoreReady, setIsScoreReady] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);

  const safeTempo = isGroundTruth ? 131 : Math.max(40, Math.min(240, Math.round(tempo || 120)));

  const currentAlphaTex = isGroundTruth && activeTabMode === 'official'
    ? OFFICIAL_CLAPTON_ALPHATEX
    : convertNotesToAlphaTex(notes, title, 'TabMaker', safeTempo, duration, isGroundTruth, beats, downbeats);

  useEffect(() => {
    if (!containerRef.current) return;

    const settings = new alphaTab.Settings();
    settings.core.engine = 'svg';
    settings.core.fontDirectory = '/font/';
    settings.core.useWorkers = false;
    settings.core.tex = true;
    settings.display.layoutMode = alphaTab.LayoutMode.Page;
    settings.display.staveProfile = alphaTab.StaveProfile.ScoreTab;
    settings.player.enablePlayer = true;
    settings.player.enableCursor = true;
    settings.player.soundFont = '/soundfont/sonivox.sf2';

    try {
      if (apiRef.current) {
        apiRef.current.destroy();
      }

      const api = new alphaTab.AlphaTabApi(containerRef.current, settings);
      apiRef.current = api;

      api.scoreLoaded.on((score) => {
        setIsScoreReady(true);
        setRenderError(null);
        if (score && score.masterBars && score.masterBars.length > 0) {
          const lastBar = score.masterBars[score.masterBars.length - 1];
          scoreEndTickRef.current = lastBar.start + lastBar.calculateDuration();
        }
      });

      api.error.on((err) => {
        console.error('AlphaTab API Error:', err);
        setRenderError(err?.message || 'AlphaTab render error');
      });

      api.playerStateChanged.on((args) => {
        setIsPlaying(args.state === alphaTab.synth.PlayerState.Playing);
      });

      api.tex(currentAlphaTex);
    } catch (err: any) {
      console.error('Error initializing AlphaTab:', err);
      setRenderError(err?.message || 'Failed to initialize AlphaTab');
    }

    return () => {
      if (apiRef.current) {
        apiRef.current.destroy();
        apiRef.current = null;
      }
    };
  }, []);

  // Sync AlphaTab cursor continuously with HTML <audio> playback
  useEffect(() => {
    const audio = audioRef?.current;
    if (!audio) return;

    let rafId = 0;

    const syncCursorToAudio = () => {
      const api = apiRef.current;
      const totalDur = Math.max(duration || audio.duration || 1, 0.5);
      if (api && scoreEndTickRef.current > 0) {
        const ratio = Math.max(0, Math.min(1, audio.currentTime / totalDur));
        try {
          api.tickPosition = Math.floor(ratio * scoreEndTickRef.current);
        } catch {
          // Ignore while player initializes
        }
      }
      if (!audio.paused && !audio.ended) {
        rafId = requestAnimationFrame(syncCursorToAudio);
      }
    };

    const handlePlay = () => {
      setIsPlaying(true);
      if (rafId) cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(syncCursorToAudio);
    };
    const handlePause = () => {
      setIsPlaying(false);
      if (rafId) cancelAnimationFrame(rafId);
    };
    const handleSeeked = () => {
      syncCursorToAudio();
    };

    audio.addEventListener('play', handlePlay);
    audio.addEventListener('pause', handlePause);
    audio.addEventListener('ended', handlePause);
    audio.addEventListener('seeked', handleSeeked);

    return () => {
      if (rafId) cancelAnimationFrame(rafId);
      audio.removeEventListener('play', handlePlay);
      audio.removeEventListener('pause', handlePause);
      audio.removeEventListener('ended', handlePause);
      audio.removeEventListener('seeked', handleSeeked);
    };
  }, [audioRef?.current, duration]);

  useEffect(() => {
    if (apiRef.current && isScoreReady) {
      try {
        setRenderError(null);
        apiRef.current.tex(currentAlphaTex);
      } catch (err: any) {
        console.error('Error rendering AlphaTex:', err);
        setRenderError(err?.message || 'AlphaTex parse error');
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

  const toggleTabSynth = () => {
    const audio = audioRef?.current;
    if (audio && !audio.paused) {
      audio.pause();
    }
    if (apiRef.current) {
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
    const safeName = (title || 'Guitar_Solo').replace(/[^a-zA-Z0-9_-]+/g, '_').replace(/^_+|_+$/g, '') || 'Guitar_Solo';
    const blob = new Blob([currentAlphaTex], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${safeName}.alphatex`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ marginTop: '20px', background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px', boxShadow: '0 1px 3px rgba(0,0,0,0.05)', overflow: 'hidden' }}>
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 'bold', color: '#0f172a', letterSpacing: '-0.01em', fontFamily: 'Georgia, serif' }}>
              {title}
            </h3>
            <span style={{ fontSize: '0.85rem', color: '#64748b' }}>
              Key: <strong>{songKey}</strong> | Tempo: <strong>{safeTempo} BPM</strong> | Standard 4/4 {duration > 0 ? `| Duration: ${duration.toFixed(1)}s` : ''}
            </span>
          </div>

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
                Official Score
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
                AI Transcription
              </button>
            </div>
          ) : (
            <span style={{ fontSize: '0.8rem', background: '#e0f2fe', color: '#0369a1', padding: '4px 10px', borderRadius: '6px', fontWeight: 600 }}>
              Transcribed Score
            </span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <button
            onClick={togglePlay}
            style={{
              background: isPlaying ? '#dc2626' : '#2563eb',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              padding: '7px 14px',
              fontSize: '0.85rem',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            {isPlaying ? '■ Pause Audio' : '▶ Play Audio'}
          </button>

          <button
            onClick={toggleTabSynth}
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
            Play Tab Synth
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
              cursor: 'pointer'
            }}
          >
            Download AlphaTex
          </button>
        </div>
      </div>

      {renderError && (
        <div style={{ margin: '12px 20px 0 20px', padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b', borderRadius: '6px', fontSize: '0.85rem' }}>
          Score render issue: {renderError}
        </div>
      )}

      <div style={{ padding: '24px 16px', background: '#ffffff', minHeight: '500px', display: 'flex', justifyContent: 'center' }}>
        <div ref={containerRef} style={{ width: '100%', maxWidth: '1020px' }} />
      </div>

      <div style={{ padding: '8px 20px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', fontSize: '0.75rem', color: '#94a3b8', textAlign: 'center' }}>
        Standard Notation + Tablature • Engraved by AlphaTab
      </div>
    </div>
  );
};
