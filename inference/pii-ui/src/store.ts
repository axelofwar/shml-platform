import { create } from 'zustand';
import { BlurMethod, SegmentationMode, VideoJobResult } from './lib/api';

interface PiiState {
  // File state
  selectedFile: File | null;
  fileType: 'image' | 'video' | null;
  previewUrl: string | null;
  resultUrl: string | null;

  // Processing state
  isProcessing: boolean;
  processingProgress: number;
  error: string | null;

  // Video job
  videoJob: VideoJobResult | null;

  // Detection results
  detectionResults: {
    faces: number;
    plates: number;
    processingTimeMs: number;
  } | null;

  // Settings
  settings: {
    blurMethod: BlurMethod;
    faceBlurStrength: number;
    plateBlurStrength: number;
    faceConfidence: number;
    plateConfidence: number;
    segmentationMode: SegmentationMode;
    trackingMode: 'botsort' | 'bytetrack';
    blurFaces: boolean;
    blurPlates: boolean;
  };

  // Actions
  setFile: (file: File | null) => void;
  setPreviewUrl: (url: string | null) => void;
  setResultUrl: (url: string | null) => void;
  setProcessing: (isProcessing: boolean) => void;
  setProgress: (progress: number) => void;
  setError: (error: string | null) => void;
  setVideoJob: (job: VideoJobResult | null) => void;
  setDetectionResults: (results: { faces: number; plates: number; processingTimeMs: number } | null) => void;
  updateSettings: (settings: Partial<PiiState['settings']>) => void;
  reset: () => void;
}

const initialSettings = {
  blurMethod: 'gaussian' as BlurMethod,
  faceBlurStrength: 50,
  plateBlurStrength: 60,
  faceConfidence: 0.25,
  plateConfidence: 0.30,
  segmentationMode: 'yolo' as SegmentationMode,
  trackingMode: 'botsort' as const,
  blurFaces: true,
  blurPlates: true,
};

export const usePiiStore = create<PiiState>((set) => ({
  // Initial state
  selectedFile: null,
  fileType: null,
  previewUrl: null,
  resultUrl: null,
  isProcessing: false,
  processingProgress: 0,
  error: null,
  videoJob: null,
  detectionResults: null,
  settings: initialSettings,

  // Actions
  setFile: (file) => {
    // Cleanup old URLs
    set((state) => {
      if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
      if (state.resultUrl) URL.revokeObjectURL(state.resultUrl);
      return {};
    });

    if (file) {
      const isVideo = file.type.startsWith('video/');
      set({
        selectedFile: file,
        fileType: isVideo ? 'video' : 'image',
        previewUrl: URL.createObjectURL(file),
        resultUrl: null,
        error: null,
        detectionResults: null,
      });
    } else {
      set({
        selectedFile: null,
        fileType: null,
        previewUrl: null,
        resultUrl: null,
        error: null,
        detectionResults: null,
      });
    }
  },

  setPreviewUrl: (url) => set({ previewUrl: url }),
  setResultUrl: (url) => set({ resultUrl: url }),
  setProcessing: (isProcessing) => set({ isProcessing }),
  setProgress: (progress) => set({ processingProgress: progress }),
  setError: (error) => set({ error, isProcessing: false }),
  setVideoJob: (job) => set({ videoJob: job }),
  setDetectionResults: (results) => set({ detectionResults: results }),
  updateSettings: (newSettings) =>
    set((state) => ({
      settings: { ...state.settings, ...newSettings },
    })),

  reset: () => {
    set((state) => {
      if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
      if (state.resultUrl) URL.revokeObjectURL(state.resultUrl);
      return {
        selectedFile: null,
        fileType: null,
        previewUrl: null,
        resultUrl: null,
        isProcessing: false,
        processingProgress: 0,
        error: null,
        videoJob: null,
        detectionResults: null,
        settings: initialSettings,
      };
    });
  },
}));
