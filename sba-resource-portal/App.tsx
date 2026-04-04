import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Attachment, ChatMessage, RecorderState } from './types';
import FileUploader from './components/FileUploader';
import ChatInterface from './components/ChatInterface';
import InputArea from './components/InputArea';
import SettingsModal from './components/SettingsModal';
import ProjectBoard from './components/ProjectBoard';
import { generateAnswer, generateSpeech, decode, decodeAudioData } from './services/geminiService';

const App: React.FC = () => {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  // Single Q&A pair - only show current question and response
  const [currentQuestion, setCurrentQuestion] = useState<ChatMessage | null>(null);
  const [currentResponse, setCurrentResponse] = useState<ChatMessage | null>(null);
  const [recorderState, setRecorderState] = useState<RecorderState>(RecorderState.Idle);
  const [playingMessageId, setPlayingMessageId] = useState<string | null>(null);
  const [activeAudioId, setActiveAudioId] = useState<string>('');
  const [currentTime, setCurrentTime] = useState(new Date());
  const [showSettings, setShowSettings] = useState(false);
  const [showProjectBoard, setShowProjectBoard] = useState(false);

  // Audio control state
  const [autoPlayEnabled, setAutoPlayEnabled] = useState(true);
  const audioSourceRef = useRef<AudioBufferSourceNode | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);

  // Update clock every second
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      stopCurrentAudio();
    };
  }, []);

  // Stop any currently playing audio
  const stopCurrentAudio = useCallback(() => {
    if (audioSourceRef.current) {
      try {
        audioSourceRef.current.stop();
        audioSourceRef.current.disconnect();
      } catch (e) {
        // Already stopped
      }
      audioSourceRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    setPlayingMessageId(null);
  }, []);

  // Filter for audio files
  const audioFiles = attachments.filter(f => f.type.startsWith('audio/'));
  const activeAudio = audioFiles.find(f => f.id === activeAudioId);

  // Reset selection if files are cleared or removed
  useEffect(() => {
    if (activeAudioId && !audioFiles.find(f => f.id === activeAudioId)) {
        setActiveAudioId('');
    }
  }, [attachments, activeAudioId, audioFiles]);

  const handleFilesAdded = (newFiles: Attachment[]) => {
    setAttachments((prev) => [...prev, ...newFiles]);
  };

  const clearSession = () => {
    if (window.confirm("Are you sure you want to clear all files and the current Q&A?")) {
      stopCurrentAudio();
      setAttachments([]);
      setCurrentQuestion(null);
      setCurrentResponse(null);
      setActiveAudioId('');
    }
  };

  // Export Q&A session as formatted text
  const exportCallNotes = () => {
    if (!currentQuestion && !currentResponse) {
      alert("No Q&A session to export. Ask a question first!");
      return;
    }

    const timestamp = new Date().toISOString();
    const dateStr = new Date().toLocaleString(undefined, {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });

    let formattedText = `SBA RESOURCE PORTAL - CALL NOTES\n`;
    formattedText += `Generated: ${dateStr}\n`;
    formattedText += `Session ID: ${timestamp.split('T')[1].split('.')[0]}\n`;
    formattedText += `="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="="\n\n`;

    if (currentQuestion?.text) {
      formattedText += `CUSTOMER QUESTION:\n${currentQuestion.text}\n\n`;
    }

    if (currentResponse?.text) {
      formattedText += `AI RESPONSE:\n${currentResponse.text}\n\n`;
    }

    // Copy to clipboard
    navigator.clipboard.writeText(formattedText).then(() => {
      alert("Call notes copied to clipboard!\n\nYou can now paste directly into your CRM.");
    }).catch(err => {
      console.error("Failed to copy to clipboard:", err);
      alert("Failed to copy to clipboard. Downloading file instead.");
      downloadNotes(formattedText, `call-notes-${Date.now()}`);
    });

    // Also download as .txt file
    downloadNotes(formattedText, `call-notes-${Date.now()}`);
  };

  const downloadNotes = (content: string, filename: string) => {
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${filename}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Check if there's content to export
  const hasContentToExport = currentQuestion?.text || currentResponse?.text;

  const playAudioData = useCallback(async (base64Data: string, messageId: string) => {
    try {
      // Stop any currently playing audio first
      stopCurrentAudio();

      setPlayingMessageId(messageId);

      audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 24000 });
      const audioBuffer = await decodeAudioData(decode(base64Data), audioContextRef.current, 24000, 1);

      const source = audioContextRef.current.createBufferSource();
      audioSourceRef.current = source;
      source.buffer = audioBuffer;
      source.connect(audioContextRef.current.destination);
      source.onended = () => {
        setPlayingMessageId(prev => prev === messageId ? null : prev);
        audioSourceRef.current = null;
      };
      source.start();
    } catch (e) {
      console.error("Audio playback error", e);
      setPlayingMessageId(null);
      audioSourceRef.current = null;
    }
  }, [stopCurrentAudio]);

  const handleSendMessage = useCallback(async (text: string | null, audioBlob: Blob | null) => {
    // Stop any currently playing audio before new query
    stopCurrentAudio();

    // 1. Create User Message (replaces previous Q&A)
    const userMsgId = crypto.randomUUID();
    let audioBase64: string | null = null;

    if (audioBlob) {
       const reader = new FileReader();
       reader.readAsDataURL(audioBlob);
       await new Promise<void>((resolve) => {
          reader.onloadend = () => {
             const res = reader.result as string;
             audioBase64 = res.split(',')[1];
             resolve();
          };
       });
    }

    const newUserMessage: ChatMessage = {
      id: userMsgId,
      role: 'user',
      text: text,
      audioData: audioBase64 || undefined,
      timestamp: Date.now()
    };

    // Replace previous question with new one
    setCurrentQuestion(newUserMessage);
    setRecorderState(RecorderState.Idle);

    // 2. Create Placeholder Response
    const modelMsgId = crypto.randomUUID();
    const loadingMessage: ChatMessage = {
        id: modelMsgId,
        role: 'model',
        text: null,
        timestamp: Date.now(),
        isProcessing: true
    };
    setCurrentResponse(loadingMessage);

    // 3. Call API
    try {
        const answerText = await generateAnswer(text, audioBase64, attachments);

        // Update response with text
        const updatedResponse: ChatMessage = {
            ...loadingMessage,
            text: answerText,
            isProcessing: false
        };
        setCurrentResponse(updatedResponse);

        // 4. Generate Speech and Autoplay if enabled
        if (answerText) {
            const speechResult = await generateSpeech(answerText);

            if (speechResult) {
                // Store audio data in the response
                const responseWithAudio: ChatMessage = {
                    ...updatedResponse,
                    audioData: speechResult.base64
                };
                setCurrentResponse(responseWithAudio);

                // Only auto-play if enabled
                if (autoPlayEnabled) {
                    setPlayingMessageId(modelMsgId);
                    audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 24000 });
                    const source = audioContextRef.current.createBufferSource();
                    audioSourceRef.current = source;
                    source.buffer = speechResult.buffer;
                    source.connect(audioContextRef.current.destination);
                    source.onended = () => {
                        setPlayingMessageId(prev => prev === modelMsgId ? null : prev);
                        audioSourceRef.current = null;
                    };
                    source.start();
                }
            }
        }

    } catch (error) {
        setCurrentResponse({
            ...loadingMessage,
            text: "Sorry, I encountered an error processing your request.",
            isProcessing: false
        });
    }
  }, [attachments, autoPlayEnabled, stopCurrentAudio]);

  // Build messages array for ChatInterface (single Q&A pair)
  const messages: ChatMessage[] = [];
  if (currentQuestion) messages.push(currentQuestion);
  if (currentResponse) messages.push(currentResponse);

  return (
    <div className="flex flex-col h-screen bg-slate-950 font-sans text-slate-50">

      {/* Settings Modal */}
      <SettingsModal isOpen={showSettings} onClose={() => setShowSettings(false)} />

      {/* Project Board Modal */}
      <ProjectBoard isOpen={showProjectBoard} onClose={() => setShowProjectBoard(false)} />

      {/* Header */}
      <header className="bg-slate-900 border-b border-slate-800 px-6 py-4 relative flex items-center justify-center sticky top-0 z-20 shadow-md shadow-slate-950/50">
        {/* Settings Button - Left Side */}
        <div className="absolute left-6 top-1/2 -translate-y-1/2 flex items-center gap-2">
          <button
            onClick={() => setShowSettings(true)}
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-400 hover:text-slate-200 transition-colors"
            title="Settings"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>

          {/* Project Board Button */}
          <button
            onClick={() => setShowProjectBoard(true)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-purple-900/30 hover:bg-purple-900/50 border border-purple-700/50 text-purple-400 hover:text-purple-300 transition-colors"
            title="Project Board - View feature roadmap"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
            </svg>
            <span className="text-xs font-medium hidden sm:inline">Roadmap</span>
          </button>

          {/* Auto-Play Toggle */}
          <button
            onClick={() => {
              if (autoPlayEnabled) stopCurrentAudio();
              setAutoPlayEnabled(!autoPlayEnabled);
            }}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-colors ${
              autoPlayEnabled
                ? 'bg-emerald-900/30 border-emerald-700/50 text-emerald-400 hover:bg-emerald-900/50'
                : 'bg-slate-800 border-slate-700 text-slate-400 hover:bg-slate-700'
            }`}
            title={autoPlayEnabled ? 'Auto-play ON - Click to disable' : 'Auto-play OFF - Click to enable'}
          >
            {autoPlayEnabled ? (
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
              </svg>
            ) : (
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/>
              </svg>
            )}
            <span className="text-xs font-medium hidden sm:inline">
              {autoPlayEnabled ? 'Auto' : 'Manual'}
            </span>
          </button>

          {/* Stop Audio Button - Only show when playing */}
          {playingMessageId && (
            <button
              onClick={stopCurrentAudio}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-900/30 border border-red-700/50 text-red-400 hover:bg-red-900/50 transition-colors"
              title="Stop audio"
            >
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M6 6h12v12H6z"/>
              </svg>
              <span className="text-xs font-medium hidden sm:inline">Stop</span>
            </button>
          )}

          {/* Export Call Notes Button */}
          <button
            onClick={exportCallNotes}
            disabled={!hasContentToExport}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-900/30 hover:bg-blue-900/50 border border-blue-700/50 text-blue-400 hover:text-blue-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title="Export Q&A session for CRM"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2" />
            </svg>
            <span className="text-xs font-medium hidden sm:inline">Export</span>
          </button>
        </div>

        {/* Centered Title Group */}
        <div className="flex items-center gap-3">
            <div className="bg-slate-800 p-2 rounded-lg shadow-lg shadow-slate-900/50 border border-slate-700">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6 text-slate-200" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
            </div>
            <div>
                <h1 className="text-xl font-bold text-slate-50 tracking-tight">SBA Resource Portal</h1>
                <p className="text-xs text-slate-400 font-medium">AI-Powered Voice Assistant</p>
            </div>
        </div>

        {/* Right Side: Date/Time + Logo */}
        <div className="absolute right-6 top-1/2 -translate-y-1/2 flex items-center gap-4">
            <div className="hidden lg:flex flex-col items-end">
                <span className="text-xs font-medium text-slate-400">
                    {currentTime.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}
                </span>
                <span className="text-sm font-bold text-slate-200 tabular-nums">
                    {currentTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
            </div>
            {/* Generational Group Logo */}
            <svg className="h-10 w-auto" viewBox="0 0 220 50" fill="none" xmlns="http://www.w3.org/2000/svg">
                {/* Icon Part */}
                <g>
                    {/* Concentric Circles/Arcs simulating the 'G' icon */}
                    <path d="M40 25C40 33.2843 33.2843 40 25 40C16.7157 40 10 33.2843 10 25C10 16.7157 16.7157 10 25 10" stroke="#0f2b4c" strokeWidth="3" strokeLinecap="round"/>
                    <path d="M35 25C35 30.5228 30.5228 35 25 35C19.4772 35 15 30.5228 15 25C15 19.4772 19.4772 15 25 15" stroke="#0f2b4c" strokeWidth="3" strokeLinecap="round"/>
                    <path d="M30 25C30 27.7614 27.7614 30 25 30C22.2386 30 20 27.7614 20 25C20 22.2386 22.2386 20 25 20" stroke="#0f2b4c" strokeWidth="3" strokeLinecap="round"/>
                    {/* Yellow Arrow */}
                    <path d="M25 13L28 19H34L25 24L26.5 16L25 13Z" fill="#ffc72c" transform="translate(4 -4) scale(1.2)"/>
                    <path d="M28 20L40 20L34 13L28 20Z" fill="#ffc72c"/>
                </g>

                {/* Text Part */}
                <text x="50" y="22" className="font-bold text-lg" fill="#0f2b4c" style={{ fontFamily: 'Inter, sans-serif', letterSpacing: '0.05em' }}>GENERATIONAL</text>
                <text x="50" y="40" className="font-bold text-lg" fill="#ffc72c" style={{ fontFamily: 'Inter, sans-serif', letterSpacing: '0.1em' }}>EQUITY</text>
            </svg>
        </div>
      </header>

      <div className="flex-grow flex flex-col md:flex-row overflow-hidden">

        {/* Sidebar / File Context Manager */}
        <aside className="w-full md:w-80 bg-slate-900 border-r border-slate-800 flex flex-col z-10 md:h-full">
            <div className="p-6 flex flex-col gap-4">
                <FileUploader onFilesAdded={handleFilesAdded} isProcessing={recorderState !== RecorderState.Idle} />

                {attachments.length > 0 && (
                     <div className="text-center">
                        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-300 border border-slate-700">
                           {attachments.length} File{attachments.length !== 1 ? 's' : ''} Uploaded
                        </span>
                     </div>
                )}

                {/* Audio Player Section */}
                {audioFiles.length > 0 && (
                    <div className="mt-2 p-4 rounded-xl bg-slate-800/50 border border-slate-800">
                        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Audio Player</h3>
                        <div className="space-y-3">
                            <select
                                value={activeAudioId}
                                onChange={(e) => setActiveAudioId(e.target.value)}
                                className="w-full bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg p-2.5 focus:ring-1 focus:ring-slate-500 focus:border-slate-500 outline-none transition-colors"
                            >
                                <option value="">Select audio file...</option>
                                {audioFiles.map(file => (
                                    <option key={file.id} value={file.id}>{file.name}</option>
                                ))}
                            </select>

                            {activeAudio && (
                                <audio
                                    controls
                                    src={`data:${activeAudio.type};base64,${activeAudio.data}`}
                                    className="w-full h-8 rounded-lg opacity-90 hover:opacity-100 transition-opacity"
                                />
                            )}
                        </div>
                    </div>
                )}
            </div>

            <div className="flex-grow"></div>

            {/* Clear Session Button */}
            <div className="p-4 border-t border-slate-800 bg-slate-900">
                <button
                    onClick={clearSession}
                    disabled={(attachments.length === 0 && messages.length === 0) || recorderState !== RecorderState.Idle}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-slate-800 hover:bg-red-900/30 text-slate-300 hover:text-red-300 border border-slate-700 hover:border-red-900/50 rounded-lg transition-all text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-slate-800 disabled:hover:text-slate-300 disabled:hover:border-slate-700"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                    Clear Session
                </button>
            </div>
        </aside>

        {/* Chat Area */}
        <main className="flex-grow flex flex-col bg-slate-950 relative">
            <ChatInterface
                messages={messages}
                playingMessageId={playingMessageId}
                onPlayAudio={playAudioData}
            />
            <InputArea
                onSendMessage={handleSendMessage}
                recorderState={recorderState}
                setRecorderState={setRecorderState}
            />
        </main>

      </div>
    </div>
  );
};

export default App;
