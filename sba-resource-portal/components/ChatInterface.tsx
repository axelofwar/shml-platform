import React, { useRef, useEffect } from 'react';
import { ChatMessage } from '../types';

interface ChatInterfaceProps {
  messages: ChatMessage[];
  playingMessageId: string | null;
  onPlayAudio: (base64: string, messageId: string) => void;
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({ messages, playingMessageId, onPlayAudio }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handlePlayClick = (msg: ChatMessage) => {
    if (msg.audioData) {
      onPlayAudio(msg.audioData, msg.id);
    }
  };

  return (
    <div className="flex-grow overflow-y-auto p-4 space-y-6 scrollbar-hide">
      {messages.length === 0 && (
        <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 mt-10">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-16 w-16 mb-4 opacity-30 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
          <p className="text-lg font-medium text-slate-300">No messages yet</p>
          <p className="text-sm text-slate-500">Upload documents or audio, then ask a question.</p>
        </div>
      )}

      {messages.map((msg) => (
        <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
          <div className={`max-w-[85%] lg:max-w-[70%] rounded-2xl px-5 py-4 shadow-sm ${
            msg.role === 'user'
              ? 'bg-slate-700 text-white rounded-br-none shadow-slate-900/50'
              : 'bg-slate-900 text-slate-100 border border-slate-800 rounded-bl-none shadow-slate-950/50'
          }`}>

            <div className="prose prose-sm max-w-none prose-invert">
                {msg.text ? (
                   <div className="whitespace-pre-wrap leading-relaxed">{msg.text}</div>
                ) : (
                    msg.isProcessing && <div className="flex space-x-2 items-center h-6">
                        <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                        <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                        <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                    </div>
                )}
            </div>

            {/* User Message Audio Playback */}
            {msg.role === 'user' && msg.audioData && (
                <div className="mt-3 flex items-center gap-2 border-t border-slate-600/50 pt-2">
                    <button
                        onClick={() => handlePlayClick(msg)}
                        disabled={playingMessageId === msg.id}
                        className={`flex items-center gap-2 text-xs font-medium transition-colors ${
                            playingMessageId === msg.id
                            ? 'text-green-300 cursor-default'
                            : 'text-slate-300 hover:text-white'
                        }`}
                    >
                        {playingMessageId === msg.id ? (
                            <>
                                <span className="relative flex h-2 w-2">
                                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                                  <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                                </span>
                                Playing...
                            </>
                        ) : (
                            <>
                                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-1.5a1 1 0 000-1.664l-3-1.5z" clipRule="evenodd" />
                                </svg>
                                Play Voice Query
                            </>
                        )}
                    </button>
                </div>
            )}

            {/* Model Message Footer */}
            {msg.role === 'model' && !msg.isProcessing && (
                <div className="mt-3 flex items-center gap-2 border-t border-slate-800 pt-2">
                    {msg.audioData ? (
                        <button
                            onClick={() => handlePlayClick(msg)}
                            disabled={playingMessageId === msg.id}
                            className={`flex items-center gap-2 text-xs font-medium transition-colors ${
                                playingMessageId === msg.id
                                ? 'text-green-400 cursor-default'
                                : 'text-slate-400 hover:text-slate-200'
                            }`}
                        >
                            {playingMessageId === msg.id ? (
                                <>
                                    <span className="relative flex h-2 w-2">
                                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                                      <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                                    </span>
                                    Playing...
                                </>
                            ) : (
                                <>
                                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-1.5a1 1 0 000-1.664l-3-1.5z" clipRule="evenodd" />
                                    </svg>
                                    Play Response
                                </>
                            )}
                        </button>
                    ) : (
                        <div className="flex items-center gap-2 text-xs text-slate-500 font-medium">
                            <span>Text only</span>
                        </div>
                    )}
                </div>
            )}
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
};

export default ChatInterface;
