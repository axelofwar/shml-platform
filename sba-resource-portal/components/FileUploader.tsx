import React, { ChangeEvent, useState, useCallback } from 'react';
import { Attachment } from '../types';

interface FileUploaderProps {
  onFilesAdded: (files: Attachment[]) => void;
  isProcessing: boolean;
}

interface UploadStatus {
  id: string;
  name: string;
  progress: number; // 0 to 100
  status: 'reading' | 'done' | 'error';
  errorMessage?: string;
}

const FileUploader: React.FC<FileUploaderProps> = ({ onFilesAdded, isProcessing }) => {
  const [uploadQueue, setUploadQueue] = useState<UploadStatus[]>([]);

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const files: File[] = Array.from(e.target.files);

      // Initialize queue items
      const newQueueItems: UploadStatus[] = files.map(file => ({
        id: crypto.randomUUID(),
        name: file.name,
        progress: 0,
        status: 'reading'
      }));

      setUploadQueue(prev => [...prev, ...newQueueItems]);

      // Reset input immediately so the same file can be selected again if needed
      e.target.value = '';

      // Process each file
      newQueueItems.forEach((queueItem, index) => {
        const file = files[index];
        processFile(file, queueItem.id);
      });
    }
  };

  const processFile = (file: File, queueId: string) => {
    // Basic validation
    if (file.type !== 'application/pdf' && !file.type.startsWith('audio/')) {
        updateQueueItem(queueId, {
            status: 'error',
            errorMessage: 'Unsupported file type',
            progress: 100
        });
        removeQueueItemAfterDelay(queueId);
        return;
    }

    const reader = new FileReader();

    reader.onprogress = (event) => {
      if (event.lengthComputable) {
        const percentLoaded = Math.round((event.loaded / event.total) * 100);
        updateQueueItem(queueId, { progress: percentLoaded });
      }
    };

    reader.onload = () => {
        const result = reader.result as string;
        const base64 = result.split(',')[1];

        const attachment: Attachment = {
            id: crypto.randomUUID(),
            name: file.name,
            type: file.type,
            data: base64,
            size: file.size
        };

        // Mark as done
        updateQueueItem(queueId, { progress: 100, status: 'done' });

        // Send to parent
        onFilesAdded([attachment]);

        // Remove from UI after a short delay
        removeQueueItemAfterDelay(queueId);
    };

    reader.onerror = () => {
        updateQueueItem(queueId, {
            status: 'error',
            errorMessage: 'Error reading file',
            progress: 0
        });
        removeQueueItemAfterDelay(queueId);
    };

    reader.readAsDataURL(file);
  };

  const updateQueueItem = (id: string, updates: Partial<UploadStatus>) => {
    setUploadQueue(prev => prev.map(item =>
      item.id === id ? { ...item, ...updates } : item
    ));
  };

  const removeQueueItemAfterDelay = (id: string) => {
    setTimeout(() => {
        setUploadQueue(prev => prev.filter(item => item.id !== id));
    }, 2000); // Keep success/error message visible for 2 seconds
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Upload Button */}
      <label
        className={`flex items-center justify-center w-full p-6 bg-slate-800/50 text-slate-400 rounded-xl border-2 border-dashed border-slate-700 cursor-pointer hover:bg-slate-800 hover:border-slate-500/50 hover:text-slate-300 transition-all hover:scale-[1.02] active:scale-95 group ${isProcessing ? 'opacity-50 pointer-events-none' : ''}`}
        title="Upload Context Files (PDFs or MP3s)"
      >
        <svg xmlns="http://www.w3.org/2000/svg" className="h-10 w-10 transition-transform group-hover:-translate-y-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
        </svg>
        <input
          type="file"
          multiple
          accept=".pdf,audio/*"
          onChange={handleFileChange}
          className="hidden"
          disabled={isProcessing}
        />
      </label>

      {/* Progress List */}
      {uploadQueue.length > 0 && (
        <div className="flex flex-col gap-2">
            {uploadQueue.map(item => (
                <div key={item.id} className="bg-slate-800 rounded-lg p-3 border border-slate-700 shadow-sm animate-in fade-in slide-in-from-top-2 duration-300">
                    <div className="flex justify-between items-center mb-1">
                        <span className="text-xs font-medium text-slate-200 truncate max-w-[150px]">{item.name}</span>
                        <span className={`text-xs font-bold ${item.status === 'error' ? 'text-red-400' : 'text-slate-400'}`}>
                            {item.status === 'error' ? 'Failed' : `${item.progress}%`}
                        </span>
                    </div>

                    {item.status !== 'error' ? (
                        <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden">
                            <div
                                className="bg-slate-500 h-1.5 rounded-full transition-all duration-300 ease-out"
                                style={{ width: `${item.progress}%` }}
                            />
                        </div>
                    ) : (
                         <div className="text-xs text-red-400 mt-1">{item.errorMessage}</div>
                    )}
                </div>
            ))}
        </div>
      )}
    </div>
  );
};

export default FileUploader;
