import { useCallback, useEffect, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload,
  Image as ImageIcon,
  Video,
  Settings2,
  Download,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Eye,
  EyeOff,
  Loader2,
  Shield,
  Car,
  User,
} from 'lucide-react';
import { Toaster, toast } from 'sonner';

import { usePiiStore } from './store';
import piiApi, { BlurMethod, SegmentationMode } from './lib/api';
import { cn, formatBytes } from './lib/utils';

// Blur method options
const BLUR_METHODS: { value: BlurMethod; label: string; icon: string }[] = [
  { value: 'gaussian', label: 'Gaussian Blur', icon: '🌫️' },
  { value: 'pixelate', label: 'Pixelate', icon: '🔲' },
  { value: 'emoji', label: 'Emoji Face', icon: '😊' },
  { value: 'vintage', label: 'Vintage', icon: '📷' },
  { value: 'black_bar', label: 'Black Bar', icon: '⬛' },
];

const SEGMENTATION_MODES: { value: SegmentationMode; label: string; desc: string }[] = [
  { value: 'yolo', label: 'Fast (YOLO)', desc: '~90% accuracy, 100 FPS' },
  { value: 'segformer', label: 'Quality (SegFormer)', desc: '93% accuracy, 30 FPS' },
];

function App() {
  const {
    selectedFile,
    fileType,
    previewUrl,
    resultUrl,
    isProcessing,
    error,
    detectionResults,
    settings,
    videoJob,
    setFile,
    setResultUrl,
    setProcessing,
    setError,
    setDetectionResults,
    setVideoJob,
    setProgress,
    updateSettings,
    reset,
  } = usePiiStore();

  const [showSettings, setShowSettings] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);
  const [healthStatus, setHealthStatus] = useState<'loading' | 'healthy' | 'error'>('loading');

  // Check API health on mount
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const health = await piiApi.getHealth();
        if (health.status === 'healthy') {
          setHealthStatus('healthy');
          toast.success('PII API connected', {
            description: `Models: ${health.models.yolo_face_loaded ? '✓' : '✗'} Face | ${health.settings.device}`,
          });
        } else {
          setHealthStatus('error');
        }
      } catch {
        setHealthStatus('error');
        toast.error('PII API not available', {
          description: 'Make sure the pii-blur service is running',
        });
      }
    };
    checkHealth();
  }, []);

  // Dropzone
  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      const file = acceptedFiles[0];
      if (file) {
        setFile(file);
        toast.info(`Selected: ${file.name}`, {
          description: formatBytes(file.size),
        });
      }
    },
    [setFile]
  );

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    accept: {
      'image/*': ['.jpg', '.jpeg', '.png', '.webp', '.gif'],
      'video/*': ['.mp4', '.mov', '.avi', '.mkv', '.webm'],
    },
    maxSize: 500 * 1024 * 1024, // 500MB
    multiple: false,
  });

  // Process file
  const handleProcess = async () => {
    if (!selectedFile) return;

    setProcessing(true);
    setError(null);

    try {
      if (fileType === 'image') {
        // Process image
        const result = await piiApi.blurAllPii(selectedFile, {
          blurMethod: settings.blurMethod,
          faceBlurStrength: settings.faceBlurStrength,
          plateBlurStrength: settings.plateBlurStrength,
          faceConfidence: settings.faceConfidence,
          plateConfidence: settings.plateConfidence,
          segmentationMode: settings.segmentationMode,
          blurFaces: settings.blurFaces,
          blurPlates: settings.blurPlates,
        });

        const url = URL.createObjectURL(result.blob);
        setResultUrl(url);
        setDetectionResults({
          faces: parseInt(result.headers.facesBlurred),
          plates: parseInt(result.headers.platesBlurred),
          processingTimeMs: parseFloat(result.headers.processingTimeMs),
        });

        toast.success('Image processed!', {
          description: `${result.headers.facesBlurred} faces, ${result.headers.platesBlurred} plates blurred`,
        });
      } else {
        // Process video (async)
        const job = await piiApi.blurVideo(selectedFile, {
          blurMethod: settings.blurMethod,
          blurStrength: settings.faceBlurStrength,
          confidenceThreshold: settings.faceConfidence,
          trackingMode: settings.trackingMode,
        });

        setVideoJob(job);
        toast.info('Video processing started', {
          description: `Job ID: ${job.job_id}`,
        });

        // Poll for status
        const pollInterval = setInterval(async () => {
          try {
            const status = await piiApi.getVideoJobStatus(job.job_id);
            setVideoJob(status);
            setProgress(status.progress * 100);

            if (status.status === 'completed') {
              clearInterval(pollInterval);
              const blob = await piiApi.downloadVideo(job.job_id);
              const url = URL.createObjectURL(blob);
              setResultUrl(url);
              setProcessing(false);
              toast.success('Video processed!', {
                description: `${status.frames_processed} frames processed`,
              });
            } else if (status.status.startsWith('failed')) {
              clearInterval(pollInterval);
              setError(status.status);
              toast.error('Video processing failed', {
                description: status.status,
              });
            }
          } catch (err) {
            clearInterval(pollInterval);
            setError('Failed to check job status');
          }
        }, 2000);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Processing failed';
      setError(message);
      toast.error('Processing failed', { description: message });
    } finally {
      if (fileType === 'image') {
        setProcessing(false);
      }
    }
  };

  // Download result
  const handleDownload = () => {
    if (!resultUrl || !selectedFile) return;

    const a = document.createElement('a');
    a.href = resultUrl;
    a.download = `pii_blurred_${selectedFile.name}`;
    a.click();
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
      <Toaster position="top-right" richColors />

      {/* Header */}
      <header className="border-b border-white/10 bg-black/20 backdrop-blur-sm">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Shield className="w-8 h-8 text-purple-400" />
            <div>
              <h1 className="text-xl font-bold text-white">PII Blur</h1>
              <p className="text-xs text-slate-400">Face & License Plate Privacy</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {/* Health indicator */}
            <div
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-full text-sm',
                healthStatus === 'healthy' && 'bg-green-500/20 text-green-400',
                healthStatus === 'loading' && 'bg-yellow-500/20 text-yellow-400',
                healthStatus === 'error' && 'bg-red-500/20 text-red-400'
              )}
            >
              {healthStatus === 'loading' && <Loader2 className="w-4 h-4 animate-spin" />}
              {healthStatus === 'healthy' && <CheckCircle2 className="w-4 h-4" />}
              {healthStatus === 'error' && <AlertCircle className="w-4 h-4" />}
              <span className="hidden sm:inline">
                {healthStatus === 'loading' && 'Connecting...'}
                {healthStatus === 'healthy' && 'API Ready'}
                {healthStatus === 'error' && 'API Offline'}
              </span>
            </div>

            {/* Settings toggle */}
            <button
              onClick={() => setShowSettings(!showSettings)}
              className={cn(
                'p-2 rounded-lg transition-colors',
                showSettings ? 'bg-purple-500 text-white' : 'bg-white/10 text-slate-300 hover:bg-white/20'
              )}
            >
              <Settings2 className="w-5 h-5" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-8">
        <div className="grid lg:grid-cols-3 gap-6">
          {/* Left Panel - Upload & Preview */}
          <div className="lg:col-span-2 space-y-6">
            {/* Dropzone */}
            <div
              {...getRootProps()}
              className={cn(
                'dropzone',
                isDragActive && 'active',
                isDragReject && 'reject',
                'min-h-[200px] flex flex-col items-center justify-center bg-white/5'
              )}
            >
              <input {...getInputProps()} />
              <Upload className="w-12 h-12 text-slate-400 mb-4" />
              <p className="text-lg text-slate-300 mb-2">
                {isDragActive ? 'Drop file here...' : 'Drag & drop image or video'}
              </p>
              <p className="text-sm text-slate-500">or click to browse (max 500MB)</p>
            </div>

            {/* Preview */}
            <AnimatePresence mode="wait">
              {previewUrl && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  className="relative rounded-xl overflow-hidden bg-black/30 border border-white/10"
                >
                  {/* Toggle original/result */}
                  {resultUrl && (
                    <button
                      onClick={() => setShowOriginal(!showOriginal)}
                      className="absolute top-4 right-4 z-10 px-3 py-1.5 rounded-lg bg-black/50 backdrop-blur-sm text-white text-sm flex items-center gap-2 hover:bg-black/70 transition-colors"
                    >
                      {showOriginal ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                      {showOriginal ? 'Original' : 'Result'}
                    </button>
                  )}

                  {/* Media preview */}
                  {fileType === 'image' ? (
                    <img
                      src={showOriginal || !resultUrl ? previewUrl : resultUrl}
                      alt="Preview"
                      className="w-full h-auto max-h-[500px] object-contain"
                    />
                  ) : (
                    <video
                      src={showOriginal || !resultUrl ? previewUrl : resultUrl}
                      controls
                      className="w-full h-auto max-h-[500px]"
                    />
                  )}

                  {/* File info */}
                  <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-black/80 to-transparent">
                    <div className="flex items-center justify-between text-white">
                      <div className="flex items-center gap-2">
                        {fileType === 'image' ? (
                          <ImageIcon className="w-4 h-4" />
                        ) : (
                          <Video className="w-4 h-4" />
                        )}
                        <span className="text-sm truncate max-w-[200px]">{selectedFile?.name}</span>
                      </div>
                      <span className="text-sm text-slate-400">
                        {selectedFile && formatBytes(selectedFile.size)}
                      </span>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Results summary */}
            {detectionResults && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="grid grid-cols-3 gap-4"
              >
                <div className="bg-white/5 rounded-lg p-4 border border-white/10">
                  <div className="flex items-center gap-2 text-purple-400 mb-2">
                    <User className="w-5 h-5" />
                    <span className="text-sm font-medium">Faces Blurred</span>
                  </div>
                  <p className="text-2xl font-bold text-white">{detectionResults.faces}</p>
                </div>
                <div className="bg-white/5 rounded-lg p-4 border border-white/10">
                  <div className="flex items-center gap-2 text-blue-400 mb-2">
                    <Car className="w-5 h-5" />
                    <span className="text-sm font-medium">Plates Blurred</span>
                  </div>
                  <p className="text-2xl font-bold text-white">{detectionResults.plates}</p>
                </div>
                <div className="bg-white/5 rounded-lg p-4 border border-white/10">
                  <div className="flex items-center gap-2 text-green-400 mb-2">
                    <CheckCircle2 className="w-5 h-5" />
                    <span className="text-sm font-medium">Processing Time</span>
                  </div>
                  <p className="text-2xl font-bold text-white">
                    {detectionResults.processingTimeMs.toFixed(0)}
                    <span className="text-sm text-slate-400 ml-1">ms</span>
                  </p>
                </div>
              </motion.div>
            )}

            {/* Video progress */}
            {videoJob && isProcessing && (
              <div className="bg-white/5 rounded-lg p-4 border border-white/10">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-slate-300">Processing video...</span>
                  <span className="text-sm text-purple-400">{Math.round(videoJob.progress * 100)}%</span>
                </div>
                <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-purple-500 progress-stripe transition-all duration-300"
                    style={{ width: `${videoJob.progress * 100}%` }}
                  />
                </div>
                <p className="text-xs text-slate-500 mt-2">
                  {videoJob.frames_processed} / {videoJob.total_frames} frames
                </p>
              </div>
            )}

            {/* Error message */}
            {error && (
              <div className="bg-red-500/20 border border-red-500/30 rounded-lg p-4 flex items-center gap-3">
                <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
                <p className="text-red-300 text-sm">{error}</p>
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-4">
              <button
                onClick={handleProcess}
                disabled={!selectedFile || isProcessing || healthStatus !== 'healthy'}
                className={cn(
                  'flex-1 py-3 px-6 rounded-lg font-medium flex items-center justify-center gap-2 transition-all',
                  selectedFile && !isProcessing && healthStatus === 'healthy'
                    ? 'bg-purple-500 hover:bg-purple-600 text-white'
                    : 'bg-white/10 text-slate-500 cursor-not-allowed'
                )}
              >
                {isProcessing ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Processing...
                  </>
                ) : (
                  <>
                    <Shield className="w-5 h-5" />
                    Blur PII
                  </>
                )}
              </button>

              {resultUrl && (
                <button
                  onClick={handleDownload}
                  className="py-3 px-6 rounded-lg font-medium bg-green-500 hover:bg-green-600 text-white flex items-center gap-2 transition-colors"
                >
                  <Download className="w-5 h-5" />
                  Download
                </button>
              )}

              <button
                onClick={reset}
                className="py-3 px-4 rounded-lg bg-white/10 hover:bg-white/20 text-slate-300 transition-colors"
              >
                <RefreshCw className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Right Panel - Settings */}
          <AnimatePresence>
            {showSettings && (
              <motion.div
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20 }}
                className="bg-white/5 rounded-xl border border-white/10 p-6 space-y-6 h-fit"
              >
                <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                  <Settings2 className="w-5 h-5" />
                  Settings
                </h2>

                {/* What to blur */}
                <div className="space-y-3">
                  <label className="text-sm font-medium text-slate-300">What to Blur</label>
                  <div className="space-y-2">
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={settings.blurFaces}
                        onChange={(e) => updateSettings({ blurFaces: e.target.checked })}
                        className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-purple-500 focus:ring-purple-500"
                      />
                      <User className="w-4 h-4 text-purple-400" />
                      <span className="text-sm text-slate-300">Faces</span>
                    </label>
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={settings.blurPlates}
                        onChange={(e) => updateSettings({ blurPlates: e.target.checked })}
                        className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                      />
                      <Car className="w-4 h-4 text-blue-400" />
                      <span className="text-sm text-slate-300">License Plates</span>
                    </label>
                  </div>
                </div>

                {/* Blur method */}
                <div className="space-y-3">
                  <label className="text-sm font-medium text-slate-300">Blur Method</label>
                  <div className="grid grid-cols-2 gap-2">
                    {BLUR_METHODS.map((method) => (
                      <button
                        key={method.value}
                        onClick={() => updateSettings({ blurMethod: method.value })}
                        className={cn(
                          'p-2 rounded-lg text-sm flex items-center gap-2 transition-colors',
                          settings.blurMethod === method.value
                            ? 'bg-purple-500 text-white'
                            : 'bg-white/10 text-slate-300 hover:bg-white/20'
                        )}
                      >
                        <span>{method.icon}</span>
                        {method.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Blur strength - Faces */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-slate-300">Face Blur Strength</label>
                    <span className="text-sm text-purple-400">{settings.faceBlurStrength}</span>
                  </div>
                  <input
                    type="range"
                    min="10"
                    max="100"
                    value={settings.faceBlurStrength}
                    onChange={(e) => updateSettings({ faceBlurStrength: parseInt(e.target.value) })}
                    className="w-full h-2 bg-white/10 rounded-lg appearance-none cursor-pointer accent-purple-500"
                  />
                </div>

                {/* Blur strength - Plates */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-slate-300">Plate Blur Strength</label>
                    <span className="text-sm text-blue-400">{settings.plateBlurStrength}</span>
                  </div>
                  <input
                    type="range"
                    min="10"
                    max="100"
                    value={settings.plateBlurStrength}
                    onChange={(e) => updateSettings({ plateBlurStrength: parseInt(e.target.value) })}
                    className="w-full h-2 bg-white/10 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
                </div>

                {/* Confidence thresholds */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-slate-300">Face Confidence</label>
                    <span className="text-sm text-slate-400">{(settings.faceConfidence * 100).toFixed(0)}%</span>
                  </div>
                  <input
                    type="range"
                    min="0.1"
                    max="0.9"
                    step="0.05"
                    value={settings.faceConfidence}
                    onChange={(e) => updateSettings({ faceConfidence: parseFloat(e.target.value) })}
                    className="w-full h-2 bg-white/10 rounded-lg appearance-none cursor-pointer accent-purple-500"
                  />
                  <p className="text-xs text-slate-500">Lower = more detections (may have false positives)</p>
                </div>

                {/* Segmentation mode */}
                <div className="space-y-3">
                  <label className="text-sm font-medium text-slate-300">Segmentation Quality</label>
                  <div className="space-y-2">
                    {SEGMENTATION_MODES.map((mode) => (
                      <button
                        key={mode.value}
                        onClick={() => updateSettings({ segmentationMode: mode.value })}
                        className={cn(
                          'w-full p-3 rounded-lg text-left transition-colors',
                          settings.segmentationMode === mode.value
                            ? 'bg-purple-500/20 border border-purple-500'
                            : 'bg-white/5 border border-white/10 hover:bg-white/10'
                        )}
                      >
                        <div className="font-medium text-white text-sm">{mode.label}</div>
                        <div className="text-xs text-slate-400">{mode.desc}</div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Video tracking mode */}
                <div className="space-y-3">
                  <label className="text-sm font-medium text-slate-300">Video Tracking</label>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      onClick={() => updateSettings({ trackingMode: 'botsort' })}
                      className={cn(
                        'p-2 rounded-lg text-sm transition-colors',
                        settings.trackingMode === 'botsort'
                          ? 'bg-purple-500 text-white'
                          : 'bg-white/10 text-slate-300 hover:bg-white/20'
                      )}
                    >
                      BoT-SORT
                      <div className="text-xs opacity-70">Re-ID</div>
                    </button>
                    <button
                      onClick={() => updateSettings({ trackingMode: 'bytetrack' })}
                      className={cn(
                        'p-2 rounded-lg text-sm transition-colors',
                        settings.trackingMode === 'bytetrack'
                          ? 'bg-purple-500 text-white'
                          : 'bg-white/10 text-slate-300 hover:bg-white/20'
                      )}
                    >
                      ByteTrack
                      <div className="text-xs opacity-70">Fast</div>
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-white/10 mt-12">
        <div className="max-w-6xl mx-auto px-4 py-4 text-center text-sm text-slate-500">
          <p>
            Powered by YOLOv11m-Face + RF-DETR (DINOv2) + SegFormer | Privacy-first, self-hosted
          </p>
        </div>
      </footer>
    </div>
  );
}

export default App;
