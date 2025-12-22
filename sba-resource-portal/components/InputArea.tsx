import React, { useState, useRef, useEffect } from 'react';
import { RecorderState } from '../types';

interface InputAreaProps {
  onSendMessage: (text: string | null, audioBlob: Blob | null) => void;
  recorderState: RecorderState;
  setRecorderState: (state: RecorderState) => void;
}

const InputArea: React.FC<InputAreaProps> = ({ onSendMessage, recorderState, setRecorderState }) => {
  const [inputText, setInputText] = useState('');
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Use standard mime types supported by browsers
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/mp4';

      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
        onSendMessage(null, audioBlob);

        // Stop all tracks
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorder.start();
      setRecorderState(RecorderState.Recording);
    } catch (err) {
      console.error("Error accessing microphone:", err);
      alert("Could not access microphone. Please check permissions.");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
      setRecorderState(RecorderState.Processing);
    }
  };

  const handleSendText = () => {
    if (!inputText.trim()) return;
    onSendMessage(inputText, null);
    setInputText('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendText();
    }
  };

  return (
    <div className="bg-slate-900 border-t border-slate-800 p-4 sticky bottom-0 z-10 shadow-lg shadow-slate-950/50">
      <div className="max-w-4xl mx-auto flex items-center gap-3">
        {/* Microphone Button */}
        <button
          onClick={recorderState === RecorderState.Recording ? stopRecording : startRecording}
          disabled={recorderState === RecorderState.Processing}
          className={`flex-shrink-0 w-12 h-12 rounded-full flex items-center justify-center transition-all shadow-md ${
            recorderState === RecorderState.Recording
              ? 'bg-red-500 text-white animate-pulse shadow-red-900/50'
              : 'bg-slate-700 text-white hover:bg-slate-600 shadow-slate-900/50'
          } ${recorderState === RecorderState.Processing ? 'bg-slate-800 cursor-not-allowed shadow-none' : ''}`}
          title={recorderState === RecorderState.Recording ? "Stop Recording" : "Start Voice Query"}
        >
          {recorderState === RecorderState.Recording ? (
            <div className="w-4 h-4 bg-white rounded-sm" />
          ) : (
            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
          )}
        </button>

        {/* Text Input */}
        <div className="flex-grow relative">
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={recorderState === RecorderState.Recording ? "Listening..." : "Ask a question about your files..."}
            disabled={recorderState !== RecorderState.Idle}
            className="w-full pl-4 pr-12 py-3 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 focus:border-slate-600 focus:ring-2 focus:ring-slate-800 outline-none transition-all shadow-sm placeholder-slate-500 disabled:bg-slate-900 disabled:text-slate-600"
          />
          <button
            onClick={handleSendText}
            disabled={!inputText.trim() || recorderState !== RecorderState.Idle}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-slate-400 hover:text-slate-300 disabled:text-slate-700 transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      </div>
      {recorderState === RecorderState.Recording && (
        <div className="text-center text-xs text-red-400 mt-2 font-medium">
          Recording... Tap stop to send.
        </div>
      )}
      {recorderState === RecorderState.Processing && (
        <div className="text-center text-xs text-slate-400 mt-2 font-medium animate-pulse">
          Processing voice query...
        </div>
      )}
    </div>
  );
};

export default InputArea;
