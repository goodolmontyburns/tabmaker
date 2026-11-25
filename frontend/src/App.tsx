import { useState, useRef, useEffect } from 'react';
import './App.css';
import axios from 'axios';
import { IngestPanel } from './components/IngestPanel';
import { CleanTabScore } from './components/CleanTabScore';
import { AlphaTabViewer } from './components/AlphaTabViewer';
import type { NoteItem } from './components/CleanTabScore';

const API_BASE = import.meta.env.VITE_API_BASE || '';

function App() {
  const [isProcessing, setIsProcessing] = useState(false);
  const [jobStage, setJobStage] = useState('Starting transcription...');
  const [jobProgress, setJobProgress] = useState(0);
  const [isPolishing, setIsPolishing] = useState(false);

  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [duration, setDuration] = useState(0);
  const [bpm, setBpm] = useState(120);
  const [beats, setBeats] = useState<number[]>([]);
  const [downbeats, setDownbeats] = useState<number[]>([]);
  const [sessionID, setSessionId] = useState<string | null>(null);
  const [originalAudio, setOriginalAudio] = useState<string | null>(null);
  const [guitarStem, setGuitarStem] = useState<string | null>(null);
  const [backingStem, setBackingStem] = useState<string | null>(null);
  const [hasIsolatedStem, setHasIsolatedStem] = useState(false);
  const [activeAudioSource, setActiveAudioSource] = useState<'guitar' | 'backing' | 'original'>('guitar');
  const [midiUrl, setMidiUrl] = useState<string | null>(null);
  const [videoAnalysis, setVideoAnalysis] = useState<any>(null);
  const [songKey, setSongKey] = useState<string>('C Blues');
  const [songTitle, setSongTitle] = useState<string>('Guitar Solo');
  const [isGroundTruth, setIsGroundTruth] = useState<boolean>(false);
  const [aiApplied, setAiApplied] = useState<boolean>(false);
  const [apiKey, setApiKey] = useState<string>(() => localStorage.getItem('gemini_api_key') || '');
  const [scoreViewMode, setScoreViewMode] = useState<'alphatab' | 'editor'>('alphatab');

  const audioRef = useRef<HTMLAudioElement>(null);

  const applySessionData = (data: any, fallbackTitle: string = 'Guitar Solo') => {
    setSessionId(data.session_id);
    setNotes(data.notes || []);
    setDuration(data.duration || 0);
    setBpm(data.bpm || 120);
    setBeats(data.beats || []);
    setDownbeats(data.downbeats || []);
    setOriginalAudio(data.original);
    setGuitarStem(data.guitar_stem || data.original);
    setBackingStem(data.backing_stem || null);
    setHasIsolatedStem(Boolean(data.has_isolated_stem));
    setActiveAudioSource(data.has_isolated_stem ? 'guitar' : 'original');
    setMidiUrl(data.midi);
    setVideoAnalysis(data.video_analysis);
    setSongKey(data.key || 'C Blues');
    setSongTitle(data.title || fallbackTitle);
    setIsGroundTruth(Boolean(data.is_ground_truth));
    setAiApplied(Boolean(data.ai_applied));
  };

  useEffect(() => {
    const saved = localStorage.getItem('last_tabmaker_session');
    if (saved) resumeSession(saved);
  }, []);

  const resumeSession = async (id: string) => {
    setIsProcessing(true);
    setJobStage('Loading saved session...');
    try {
      const resp = await axios.get(`${API_BASE}/session/${id}`);
      applySessionData(resp.data);
    } catch {
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
    targetFret: number | null,
    userApiKey: string
  ) => {
    setIsProcessing(true);
    setJobStage('Downloading targeted solo slice...');
    setJobProgress(10);
    if (userApiKey) setApiKey(userApiKey);

    const formData = new FormData();
    if (youtubeUrl) formData.append('youtube_url', youtubeUrl);
    if (file) formData.append('file', file);
    formData.append('start_time', startTime.toString());
    formData.append('end_time', endTime.toString());
    if (targetFret !== null && !Number.isNaN(targetFret)) {
      formData.append('target_fret', targetFret.toString());
    }
    if (userApiKey) formData.append('api_key', userApiKey);

    try {
      const startResp = await axios.post(`${API_BASE}/process_async`, formData);
      const { job_id } = startResp.data;

      // Poll job progress until completed or failed
      let finished = false;
      while (!finished) {
        await new Promise((r) => setTimeout(r, 1200));
        const jobResp = await axios.get(`${API_BASE}/jobs/${job_id}`);
        const job = jobResp.data;
        setJobStage(job.stage || 'Processing...');
        setJobProgress(job.progress || 25);

        if (job.status === 'completed' && job.result) {
          localStorage.setItem('last_tabmaker_session', job.result.session_id);
          applySessionData(job.result, file ? file.name : 'YouTube Guitar Solo');
          finished = true;
        } else if (job.status === 'failed') {
          throw new Error(job.error || 'Transcription job failed');
        }
      }
    } catch (error: any) {
      alert(`Transcription failed: ${error?.response?.data?.detail || error?.response?.data?.message || error.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleLoadGroundTruth = async () => {
    setIsProcessing(true);
    setJobStage('Loading Clapton reference benchmark...');
    try {
      const resp = await axios.get(`${API_BASE}/benchmark/ground_truth`);
      localStorage.setItem('last_tabmaker_session', resp.data.session_id);
      applySessionData({ ...resp.data, bpm: 131, is_ground_truth: true, ai_applied: true });
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
        if (resp.data.tempo_bpm) setBpm(resp.data.tempo_bpm);
        setAiApplied(Boolean(resp.data.ai_applied));
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

  const activeAudioSrc =
    activeAudioSource === 'guitar'
      ? guitarStem || originalAudio || undefined
      : activeAudioSource === 'backing'
      ? backingStem || originalAudio || undefined
      : originalAudio || undefined;

  return (
    <div className="tabmaker-app">
      <header className="app-header">
        <div className="header-inner">
          <div className="brand">
            <h1 className="logo-title">TabMaker</h1>
            <span className="logo-badge">Cloud GPU + Gemini 4</span>
          </div>
          <div className="header-actions">
            {midiUrl && (
              <a href={midiUrl} download="solo.mid" className="secondary-button">
                Download MIDI
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
            <h4>{jobStage}</h4>
            <div style={{ width: '100%', maxWidth: '340px', height: '6px', background: '#e2e8f0', borderRadius: '999px', margin: '12px auto', overflow: 'hidden' }}>
              <div style={{ width: `${jobProgress}%`, height: '100%', background: '#2563eb', transition: 'width 0.3s ease' }} />
            </div>
            <p>Isolating lead guitar, tracking beats &amp; bends, and optimizing 6-string fingerings</p>
          </div>
        )}

        {notes.length > 0 && (
          <div className="workspace-card">
            <div className="polish-control-bar">
              <div>
                <span className="status-label">
                  Analysis Mode:{' '}
                  <strong>
                    {videoAnalysis?.mode === 'multimodal_video'
                      ? 'Multimodal Video + Audio'
                      : 'Audio + Music Theory'}
                  </strong>
                </span>
                <p className="status-subtext">
                  {videoAnalysis?.reason || 'Acoustic pitch & bend tracking active.'}
                </p>
              </div>

              <div className="polish-buttons">
                <button
                  onClick={handlePolish}
                  disabled={isPolishing}
                  className="ai-polish-button"
                >
                  {isPolishing ? 'Polishing with Gemini 4...' : 'AI Polish (Gemini 4)'}
                </button>
              </div>
            </div>

            {aiApplied && (
              <div className="ai-success-banner">
                AI Polish Applied: 6-string fretboard and articulations verified for {songKey}.
              </div>
            )}

            <div className="audio-player-card">
              <div className="audio-meta">
                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155' }}>
                  Synchronized Reference Track:
                </span>
                <div className="stem-toggle">
                  {hasIsolatedStem && (
                    <button
                      className={`toggle-btn ${activeAudioSource === 'guitar' ? 'active' : ''}`}
                      onClick={() => setActiveAudioSource('guitar')}
                    >
                      Lead Guitar
                    </button>
                  )}
                  {backingStem && (
                    <button
                      className={`toggle-btn ${activeAudioSource === 'backing' ? 'active' : ''}`}
                      onClick={() => setActiveAudioSource('backing')}
                    >
                      Backing Track
                    </button>
                  )}
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
                src={activeAudioSrc}
                style={{ width: '100%', marginTop: '10px' }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '20px 0 10px 0', borderBottom: '2px solid #e2e8f0', paddingBottom: '10px', flexWrap: 'wrap', gap: '8px' }}>
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
                  Engraved Score (AlphaTab)
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
                  Interactive 6-String Editor
                </button>
              </div>

              <span style={{ fontSize: '0.85rem', color: '#64748b' }}>
                {scoreViewMode === 'alphatab'
                  ? 'Standard Notation + Tablature synchronized with audio'
                  : 'Click any fret digit to move note across strings 1–6'}
              </span>
            </div>

            {scoreViewMode === 'alphatab' ? (
              <AlphaTabViewer
                notes={notes}
                songKey={songKey}
                title={songTitle}
                duration={duration}
                tempo={bpm}
                beats={beats}
                downbeats={downbeats}
                isGroundTruth={isGroundTruth}
                audioRef={audioRef}
              />
            ) : (
              <CleanTabScore
                notes={notes}
                duration={duration}
                audioRef={audioRef}
                songKey={songKey}
                title={songTitle}
                tempo={bpm}
                beats={beats}
                downbeats={downbeats}
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
