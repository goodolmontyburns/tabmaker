import { useState, useRef, useEffect } from 'react'
import './App.css'
import AudioTrimmer from './components/AudioTrimmer'
import TabRendererSVG from './components/TabRendererSVG'
import AudioCapture from './components/AudioCapture'
import StemMixer from './components/StemMixer'
import SoloVision from './components/SoloVision'
import axios from 'axios'

function App() {
  const [isProcessing, setIsProcessing] = useState(false);
  const [isRetranscribing, setIsRetranscribing] = useState(false);
  
  // UNIFIED STATE (Removed tabData/alphaTex)
  const [notes, setNotes] = useState<any[]>([]);
  const [stems, setStems] = useState<any>(null);
  const [visionLayers, setVisionLayers] = useState<Record<string, number[][]> | null>(null);
  const [spectrogram, setSpectrogram] = useState<number[][] | null>(null);
  const [originalAudio, setOriginalAudio] = useState<string | null>(null);
  const [midiUrl, setMidiUrl] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);
  const [sessionID, setSessionId] = useState<string | null>(null);
  const [capturedFile, setCapturedFile] = useState<File | null>(null);
  
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement>(null);
  const [selectionParams, setSelectionParams] = useState<any>(null);
  const [playheadOffset, setPlayheadOffset] = useState<number>(() => {
    const saved = localStorage.getItem('tabmaker_playhead_offset');
    return saved ? parseFloat(saved) : 0.0; // 0.0s default lead (perfect alignment)
  });

  useEffect(() => {
    const saved = localStorage.getItem('last_tabmaker_session');
    if (saved) resumeSession(saved);
  }, []);

  const resumeSession = async (id: string) => {
    setIsProcessing(true);
    try {
        const resp = await axios.get(`http://localhost:8000/session/${id}`);
        setSessionId(resp.data.session_id);
        setNotes(resp.data.notes || []);
        setStems(resp.data.stems);
        setVisionLayers(resp.data.vision_layers);
        setSpectrogram(resp.data.spectrogram);
        setOriginalAudio(resp.data.original);
        setMidiUrl(resp.data.midi);
        setDuration(resp.data.duration);
    } catch (e) {
        localStorage.removeItem('last_tabmaker_session');
    } finally { setIsProcessing(false); }
  };

  const handleTrimAndProcess = async (startTime: number, endTime: number, file: File | null, youtubeUrl?: string) => {
    setIsProcessing(true);
    const formData = new FormData();
    if (file) formData.append('file', file);
    if (youtubeUrl) formData.append('youtube_url', youtubeUrl);
    formData.append('start_time', startTime.toString());
    formData.append('end_time', endTime.toString());

    try {
      const response = await axios.post('http://localhost:8000/process', formData);
      setSessionId(response.data.session_id);
      localStorage.setItem('last_tabmaker_session', response.data.session_id);
      setNotes(response.data.notes || []);
      setStems(response.data.stems);
      setVisionLayers(response.data.vision_layers);
      setSpectrogram(response.data.spectrogram);
      setOriginalAudio(response.data.original);
      setMidiUrl(response.data.midi);
      setDuration(response.data.duration);
    } catch (error) { alert('Process failed.'); }
    finally { setIsProcessing(false); }
  };

  const handlePreview = async (min: number, max: number, t1: number, t2: number) => {
    if (!sessionID) return;
    try {
        const formData = new FormData();
        formData.append('session_id', sessionID);
        formData.append('start_time', t1.toString());
        formData.append('end_time', t2.toString());
        formData.append('min_midi', min.toString());
        formData.append('max_midi', max.toString());
        const resp = await axios.post('http://localhost:8000/preview_selection', formData);
        setPreviewUrl(resp.data.preview_url);
        setSelectionParams({ min, max, t1, t2 });
    } catch (e) { alert("Preview failed"); }
  };

  const handleRetranscribe = async (target: string) => {
    if (!sessionID) return;
    setIsRetranscribing(true);
    try {
        const formData = new FormData();
        formData.append('session_id', sessionID);
        formData.append('target', target); 
        const response = await axios.post('http://localhost:8000/retranscribe', formData);
        setNotes(response.data.notes || []);
    } catch (error) { alert("Retranscription failed."); }
    finally { setIsRetranscribing(false); }
  };

  const handleUpdateNotes = async (newNotes: any[]) => {
    setNotes(newNotes);
    if (sessionID) {
      try {
        await axios.post(`http://localhost:8000/session/${sessionID}/notes`, { notes: newNotes });
      } catch (e) {
        console.error("Failed to save notes to backend session:", e);
      }
    }
  };

  return (
    <div className="App">
      <h1>TabMaker</h1>
      
      {(!notes || notes.length === 0) && !isProcessing && (
        <div className="upload-section">
          <h2>Step 1: Get Audio</h2>
          <AudioCapture onCapture={(blob) => setCapturedFile(new File([blob], "captured.wav"))} />
          <div style={{ margin: '20px 0', borderTop: '1px solid #ccc', paddingTop: '20px' }}>
            <p>OR use a link/file below:</p>
            <AudioTrimmer onTrim={handleTrimAndProcess} externalFile={capturedFile} />
          </div>
        </div>
      )}

      {isProcessing && (
        <div className="processing-indicator">
          <div className="loader"></div>
          <p>Analyzing Solo... (Approx 1 min)</p>
        </div>
      )}

      {notes && notes.length > 0 && (
        <div className="editor-section">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
            <h2>Step 2: Verify & Refine Solo</h2>
            <div className="save-panel">
                {midiUrl && <a href={midiUrl} download="solo.mid" className="button" style={{ background: '#8e44ad', color: 'white', textDecoration: 'none', padding: '10px 15px', borderRadius: '8px', marginLeft: '10px', fontSize: '0.9rem', fontWeight: 'bold' }}>💾 Download MIDI</a>}
            </div>
          </div>
          
          {spectrogram && (
            <SoloVision 
                visionLayers={visionLayers} 
                spectrogramData={spectrogram} 
                duration={duration}
                audioRef={previewAudioRef}
                playheadOffset={playheadOffset}
                onSelect={() => {}}
                onPreview={handlePreview}
            />
          )}

          <div style={{ margin: '20px 0', padding: '15px', background: '#f8f9fa', borderRadius: '12px', border: '1px solid #dee2e6' }}>
            <strong>Reference Audio:</strong><br/>
            <audio id="reference-audio" ref={previewAudioRef} controls src={previewUrl || originalAudio || undefined} style={{ width: '100%', marginTop: '5px' }} />
          </div>

          {selectionParams && (
            <div style={{ margin: '20px 0', padding: '20px', background: '#eef2f3', borderRadius: '12px', border: '2px solid #3498db' }}>
                <h4 style={{ margin: 0 }}>Step 3: Transcribe This Lasso</h4>
                <button onClick={() => handleRetranscribe('lasso_preview')} disabled={isRetranscribing} style={{ background: '#3498db', color: 'white', marginTop: '10px' }}>
                    {isRetranscribing ? 'Transcribing Lasso...' : 'Assign Selection as Solo'}
                </button>
            </div>
          )}

          {stems && (
            <StemMixer 
                stems={stems} 
                original={originalAudio || undefined} 
                onTranscribe={handleRetranscribe}
                isRetranscribing={isRetranscribing}
            />
          )}
          
          <TabRendererSVG 
            notes={notes} 
            duration={duration} 
            audioRef={previewAudioRef} 
            playheadOffset={playheadOffset}
            setPlayheadOffset={setPlayheadOffset}
            onUpdateNotes={handleUpdateNotes} 
          />
          
          <div style={{ marginTop: '40px' }}>
            <button onClick={() => { 
                localStorage.removeItem('last_tabmaker_session');
                window.location.reload(); 
            }}>Start Over</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
