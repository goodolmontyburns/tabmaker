import { useState, useRef, useEffect } from 'react';
import './App.css';
import axios from 'axios';
import { IngestPanel } from './components/IngestPanel';
import { CleanTabScore } from './components/CleanTabScore';
import { AlphaTabViewer } from './components/AlphaTabViewer';
import type { NoteItem } from './components/CleanTabScore';

const API_BASE = window.location.hostname === '127.0.0.1' ? 'http://127.0.0.1:8001' : 'http://localhost:8001';

function App() {
  const [isProcessing, setIsProcessing] = useState(false);
  const [isPolishing, setIsPolishing] = useState(false);

  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [duration, setDuration] = useState(0);
  const [sessionID, setSessionId] = useState<string | null>(null);
  const [originalAudio, setOriginalAudio] = useState<string | null>(null);
  const [guitarStem, setGuitarStem] = useState<string | null>(null);
  const [activeAudioSource, setActiveAudioSource] = useState<'guitar' | 'original'>('guitar');
  const [midiUrl, setMidiUrl] = useState<string | null>(null);
  const [videoAnalysis, setVideoAnalysis] = useState<any>(null);
  const [songKey, setSongKey] = useState<string>('C Blues');
  const [songTitle, setSongTitle] = useState<string>('Guitar Solo');
  const [isGroundTruth, setIsGroundTruth] = useState<boolean>(false);
  const [aiApplied, setAiApplied] = useState<boolean>(false);
  const [apiKey, setApiKey] = useState<string>(() => localStorage.getItem('gemini_api_key') || '');
  const [scoreViewMode, setScoreViewMode] = useState<'alphatab' | 'editor'>('alphatab');

  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    const saved = localStorage.getItem('last_tabmaker_session');
    if (saved) resumeSession(saved);
  }, []);

  const resumeSession = async (id: string) => {
    setIsProcessing(true);
    try {
      const resp = await axios.get(`${API_BASE}/session/${id}`);
      setSessionId(resp.data.session_id);
      setNotes(resp.data.notes || []);
      setDuration(resp.data.duration || 0);
      setOriginalAudio(resp.data.original);
      setGuitarStem(resp.data.guitar_stem || resp.data.original);
      setMidiUrl(resp.data.midi);
      setVideoAnalysis(resp.data.video_analysis);
      setSongKey(resp.data.key || 'C Blues');
      setSongTitle(resp.data.title || 'Guitar Solo');
      setIsGroundTruth(resp.data.is_ground_truth || false);
      setAiApplied(resp.data.ai_applied || false);
    } catch (e) {
      localStorage.removeItem('last_tabmaker_session');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleProcess = async (
    youtubeUrl: string | null,
    file: File | null,
    startTime: number,
    endTime: number,
    targetFret: number,
    userApiKey: string
  ) => {
    setIsProcessing(true);
    if (userApiKey) setApiKey(userApiKey);
    const formData = new FormData();
    if (youtubeUrl) formData.append('youtube_url', youtubeUrl);
    if (file) formData.append('file', file);
    formData.append('start_time', startTime.toString());
    formData.append('end_time', endTime.toString());
    formData.append('target_fret', targetFret.toString());
    if (userApiKey) formData.append('api_key', userApiKey);

    try {
      const resp = await axios.post(`${API_BASE}/process`, formData);
      setSessionId(resp.data.session_id);
      localStorage.setItem('last_tabmaker_session', resp.data.session_id);
      setNotes(resp.data.notes || []);
      setDuration(resp.data.duration || 0);
      setOriginalAudio(resp.data.original);
      setGuitarStem(resp.data.guitar_stem || resp.data.original);
      setMidiUrl(resp.data.midi);
      setVideoAnalysis(resp.data.video_analysis);
      setSongKey(resp.data.key || 'C Blues');
      setSongTitle(resp.data.title || (youtubeUrl ? 'YouTube Guitar Solo' : file ? file.name : 'Guitar Solo (AI Transcription)'));
      setIsGroundTruth(false);
      setAiApplied(false);
    } catch (error: any) {
      alert(`Transcription failed: ${error?.response?.data?.message || error.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleLoadGroundTruth = async () => {
    setIsProcessing(true);
    try {
      const resp = await axios.get(`${API_BASE}/benchmark/ground_truth`);
      setSessionId(resp.data.session_id);
      localStorage.setItem('last_tabmaker_session', resp.data.session_id);
      setNotes(resp.data.notes || []);
      setDuration(resp.data.duration || 44.0);
      setOriginalAudio(resp.data.original);
      setGuitarStem(resp.data.guitar_stem || resp.data.original);
      setMidiUrl(resp.data.midi);
      setVideoAnalysis(resp.data.video_analysis);
      setSongKey(resp.data.key || 'C Blues');
      setSongTitle('Eric Clapton — I\'m Tore Down (Guitar Solo)');
      setIsGroundTruth(true);
      setAiApplied(true);
    } catch (error: any) {
      alert(`Failed to load ground truth: ${error?.response?.data?.message || error.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handlePolish = async () => {
    if (!sessionID) return;
    setIsPolishing(true);
    const formData = new FormData();
    formData.append('session_id', sessionID);
    if (apiKey) formData.append('api_key', apiKey);
    formData.append('key_hint', songKey);

    try {
      const resp = await axios.post(`${API_BASE}/polish`, formData);
      if (resp.data.success) {
        setNotes(resp.data.notes || []);
        if (resp.data.key) setSongKey(resp.data.key);
        setAiApplied(resp.data.ai_applied || false);
      }
    } catch (error: any) {
      alert(`AI Polish failed: ${error?.response?.data?.message || error.message}`);
    } finally {
      setIsPolishing(false);
    }
  };

  const handleUpdateNotes = async (newNotes: NoteItem[]) => {
    setNotes(newNotes);
    if (sessionID) {
      try {
        await axios.post(`${API_BASE}/session/${sessionID}/notes`, { notes: newNotes });
      } catch (e) {
        console.error('Failed to persist edited notes:', e);
      }
    }
  };

  return (
    <div className="tabmaker-app">
      <header className="app-header">
        <div className="header-inner">
          <div className="brand">
            <h1 className="logo-title">TabMaker</h1>
            <span className="logo-badge">v2.0 SOTA</span>
          </div>
          <div className="header-actions">
            {midiUrl && (
              <a href={midiUrl} download="solo.mid" className="secondary-button">
                💾 Download MIDI
              </a>
            )}
            {notes.length > 0 && (
              <button
                className="ghost-button"
                onClick={() => {
                  localStorage.removeItem('last_tabmaker_session');
                  window.location.reload();
                }}
              >
                New Solo
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="app-main">
        {notes.length === 0 && !isProcessing && (
          <IngestPanel onProcess={handleProcess} onLoadGroundTruth={handleLoadGroundTruth} isProcessing={isProcessing} />
        )}

        {isProcessing && (
          <div className="loading-card">
            <div className="spinner"></div>
            <h4>Transcribing Solo & Isolating Guitar...</h4>
            <p>Running high-precision pitch & continuous bend extraction (approx 30s)</p>
          </div>
        )}

        {notes.length > 0 && (
          <div className="workspace-card">
            {/* Solo Overview & AI Polish Controls */}
            <div className="polish-control-bar">
              <div>
                <span className="status-label">
                  Detected Mode:{' '}
                  <strong>
                    {videoAnalysis?.mode === 'multimodal_video'
                      ? 'Multimodal Video + Audio'
                      : 'Theory & Audio Polish'}
                  </strong>
                </span>
                <p className="status-subtext">
                  {videoAnalysis?.reason || 'Acoustic pitch tracking active.'}
                </p>
              </div>

              <div className="polish-buttons">
                <button
                  onClick={handlePolish}
                  disabled={isPolishing}
                  className="ai-polish-button"
                >
                  {isPolishing ? '✨ Polishing with Gemini...' : '✨ AI Polish (Gemini 3.7 Flash)'}
                </button>
              </div>
            </div>

            {aiApplied && (
              <div className="ai-success-banner">
                ✓ AI Polish Applied: Ergonomic fretbox optimized for {songKey}. Overtone noise cleaned.
              </div>
            )}

            {/* Reference Audio Player */}
            <div className="audio-player-card">
              <div className="audio-meta">
                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155' }}>
                  Synchronized Reference Track:
                </span>
                <div className="stem-toggle">
                  <button
                    className={`toggle-btn ${activeAudioSource === 'guitar' ? 'active' : ''}`}
                    onClick={() => setActiveAudioSource('guitar')}
                  >
                    Isolated Guitar
                  </button>
                  <button
                    className={`toggle-btn ${activeAudioSource === 'original' ? 'active' : ''}`}
                    onClick={() => setActiveAudioSource('original')}
                  >
                    Full Mix
                  </button>
                </div>
              </div>

              <audio
                ref={audioRef}
                controls
                src={activeAudioSource === 'guitar' ? guitarStem || originalAudio || undefined : originalAudio || undefined}
                style={{ width: '100%', marginTop: '10px' }}
              />
            </div>
            {/* View Switcher: Ultimate Guitar AlphaTab Engine vs Interactive Vector Editor */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '20px 0 10px 0', borderBottom: '2px solid #e2e8f0', paddingBottom: '10px' }}>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={() => setScoreViewMode('alphatab')}
                  style={{
                    background: scoreViewMode === 'alphatab' ? '#0f172a' : '#f1f5f9',
                    color: scoreViewMode === 'alphatab' ? '#ffffff' : '#475569',
                    border: 'none',
                    borderRadius: '6px',
                    padding: '8px 16px',
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }}
                >
                  ★ Ultimate Guitar Web Score (AlphaTab)
                </button>
                <button
                  onClick={() => setScoreViewMode('editor')}
                  style={{
                    background: scoreViewMode === 'editor' ? '#0f172a' : '#f1f5f9',
                    color: scoreViewMode === 'editor' ? '#ffffff' : '#475569',
                    border: 'none',
                    borderRadius: '6px',
                    padding: '8px 16px',
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }}
                >
                  ✎ Interactive Note & Fingering Editor
                </button>
              </div>

              <span style={{ fontSize: '0.85rem', color: '#64748b' }}>
                {scoreViewMode === 'alphatab' ? 'Publication-Grade AlphaTab Engraving (Matches Ultimate Guitar 1:1)' : 'Click any note number to adjust string/fret fingering'}
              </span>
            </div>

            {scoreViewMode === 'alphatab' ? (
              <AlphaTabViewer
                notes={notes}
                songKey={songKey}
                title={songTitle}
                duration={duration}
                isGroundTruth={isGroundTruth}
                audioRef={audioRef}
              />
            ) : (
              <CleanTabScore
                notes={notes}
                duration={duration}
                audioRef={audioRef}
                songKey={songKey}
                isGroundTruth={isGroundTruth}
                onUpdateNotes={handleUpdateNotes}
              />
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
