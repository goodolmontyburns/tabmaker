import React, { useState, useRef } from 'react';

interface AudioCaptureProps {
  onCapture: (blob: Blob) => void;
}

const AudioCapture: React.FC<AudioCaptureProps> = ({ onCapture }) => {
  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const startRecording = async () => {
    try {
      // Capture system audio via screen sharing
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false
        }
      } as any);

      // We only care about the audio track
      const audioStream = new MediaStream(stream.getAudioTracks());
      
      const mediaRecorder = new MediaRecorder(audioStream);
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/wav' });
        onCapture(blob);
        // Stop all tracks to close the screen sharing prompt
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error("Error capturing audio:", err);
      alert("Failed to capture audio. Make sure you select 'Share Audio' in the browser prompt.");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  return (
    <div className="audio-capture" style={{ margin: '20px 0', padding: '15px', border: '2px dashed #3498db', borderRadius: '8px' }}>
      <h3>Alternative: Capture Audio from Screen</h3>
      <p style={{ fontSize: '0.9rem', color: '#666' }}>
        Play the solo in another tab, click 'Start Capture', and select that tab. 
        <strong> Ensure 'Share Tab Audio' is checked.</strong>
      </p>
      {!isRecording ? (
        <button onClick={startRecording} style={{ background: '#3498db', color: 'white' }}>
          Start Audio Capture
        </button>
      ) : (
        <button onClick={stopRecording} style={{ background: '#e74c3c', color: 'white' }}>
          Stop & Use Captured Audio
        </button>
      )}
    </div>
  );
};

export default AudioCapture;
