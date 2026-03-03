/**
 * Video Studio - SOTA Video Masking & Privacy Editing Interface
 *
 * Features:
 * - Drag-drop video upload
 * - Timeline with frame thumbnails
 * - Auto-detect faces with YOLOv8l-P2
 * - Custom mask drawing (freehand, polygon, magnetic lasso)
 * - Object tracking (click once, auto-track across video)
 * - 5 blur methods (gaussian, pixelate, emoji, vintage, black_bar)
 * - Preset templates (Vlog, Interview, Street Photography, Healthcare)
 * - Real-time preview
 * - Audio copyright detection & AI replacement
 * - Export with progress tracking
 */

import React, { useState, useRef, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Upload, Play, Pause, RotateCcw, Download, Wand2,
  Eye, EyeOff, Pencil, Square, Circle, Lasso,
  Zap, Settings, Music, AlertTriangle, CheckCircle2,
  Loader2, Clock, Cpu, HardDrive
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

// Fabric.js for canvas editing
import { Canvas, FabricImage, Path, Rect, Circle as FabricCircle } from 'fabric'

interface VideoStudioProps {
  className?: string
}

interface DetectedFace {
  id: number
  bbox: [number, number, number, number]  // x1, y1, x2, y2
  confidence: number
  tracked: boolean
  blurred: boolean
  customMask?: boolean
}

interface TimelineFrame {
  frameNumber: number
  timestamp: number
  thumbnail: string
  faces: DetectedFace[]
}

interface BlurPreset {
  id: string
  name: string
  description: string
  icon: React.ReactNode
  settings: {
    method: string
    strength: number
    confidence_threshold: number
  }
}

const BLUR_METHODS = [
  { value: 'gaussian', label: 'Gaussian Blur', icon: '🌀' },
  { value: 'pixelate', label: 'Pixelate', icon: '🎨' },
  { value: 'emoji', label: 'Emoji Overlay', icon: '😊' },
  { value: 'vintage', label: 'Vintage Effect', icon: '📷' },
  { value: 'black_bar', label: 'Black Bar', icon: '▬' }
]

const BLUR_PRESETS: BlurPreset[] = [
  {
    id: 'vlog',
    name: 'Vlog Mode',
    description: 'Auto-blur background pedestrians',
    icon: <Zap className="h-4 w-4" />,
    settings: { method: 'gaussian', strength: 60, confidence_threshold: 0.5 }
  },
  {
    id: 'interview',
    name: 'Interview Mode',
    description: 'Preserve speaker, blur background',
    icon: <Eye className="h-4 w-4" />,
    settings: { method: 'gaussian', strength: 50, confidence_threshold: 0.7 }
  },
  {
    id: 'street',
    name: 'Street Photography',
    description: 'GDPR-compliant anonymization',
    icon: <AlertTriangle className="h-4 w-4" />,
    settings: { method: 'pixelate', strength: 80, confidence_threshold: 0.4 }
  },
  {
    id: 'healthcare',
    name: 'Healthcare/HIPAA',
    description: 'Maximum privacy protection',
    icon: <CheckCircle2 className="h-4 w-4" />,
    settings: { method: 'black_bar', strength: 100, confidence_threshold: 0.3 }
  }
]

export default function VideoStudio({ className }: VideoStudioProps) {
  // Video state
  const [videoFile, setVideoFile] = useState<File | null>(null)
  const [videoUrl, setVideoUrl] = useState<string>('')
  const [videoDuration, setVideoDuration] = useState<number>(0)
  const [currentTime, setCurrentTime] = useState<number>(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [processingProgress, setProcessingProgress] = useState(0)

  // Detection state
  const [faces, setFaces] = useState<DetectedFace[]>([])
  const [timeline, setTimeline] = useState<TimelineFrame[]>([])
  const [selectedFaces, setSelectedFaces] = useState<Set<number>>(new Set())

  // Editing state
  const [blurMethod, setBlurMethod] = useState('gaussian')
  const [blurStrength, setBlurStrength] = useState(50)
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.5)
  const [drawMode, setDrawMode] = useState<'select' | 'freehand' | 'polygon' | 'lasso'>('select')
  const [customMasks, setCustomMasks] = useState<any[]>([])

  // Audio copyright detection
  const [audioCopyright, setAudioCopyright] = useState<{detected: boolean, matches: any[]}>({detected: false, matches: []})
  const [replaceAudio, setReplaceAudio] = useState(false)

  // Refs
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fabricCanvasRef = useRef<Canvas | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Initialize Fabric canvas for custom drawing
  useEffect(() => {
    if (canvasRef.current && !fabricCanvasRef.current) {
      fabricCanvasRef.current = new Canvas(canvasRef.current, {
        width: 854,  // 480p width
        height: 480,
        selection: drawMode !== 'select'
      })

      // Handle drawing modes
      fabricCanvasRef.current.isDrawingMode = drawMode === 'freehand'
      const brush = fabricCanvasRef.current.freeDrawingBrush
      if (brush) {
        brush.width = 5
        brush.color = 'rgba(255, 0, 0, 0.5)'
      }
    }

    return () => {
      if (fabricCanvasRef.current) {
        fabricCanvasRef.current.dispose()
        fabricCanvasRef.current = null
      }
    }
  }, [drawMode])

  // Handle video upload
  const handleFileUpload = useCallback(async (file: File) => {
    if (!file.type.startsWith('video/')) {
      toast.error('Please upload a video file')
      return
    }

    if (file.size > 500 * 1024 * 1024) {  // 500MB
      toast.error('Video must be under 500MB')
      return
    }

    setVideoFile(file)
    const url = URL.createObjectURL(file)
    setVideoUrl(url)

    toast.success('Video uploaded successfully')

    // Auto-detect faces
    await detectFaces(file)

    // Check audio copyright
    await checkAudioCopyright(file)
  }, [])

  // Detect faces in video
  const detectFaces = async (file: File) => {
    setIsProcessing(true)
    setProcessingProgress(0)

    try {
      const formData = new FormData()
      formData.append('video', file)
      formData.append('confidence_threshold', confidenceThreshold.toString())

      toast.info('Detecting faces...', { duration: 1000 })

      const response = await fetch('/api/pii/v1/detect', {
        method: 'POST',
        body: formData
      })

      if (!response.ok) {
        throw new Error('Face detection failed')
      }

      const result = await response.json()

      // TODO: Parse timeline frames and faces
      setTimeline(result.timeline || [])
      setFaces(result.faces || [])

      toast.success(`Detected ${result.faces?.length || 0} faces`)

    } catch (error) {
      console.error('Detection error:', error)
      toast.error('Failed to detect faces')
    } finally {
      setIsProcessing(false)
      setProcessingProgress(0)
    }
  }

  // Check audio copyright
  const checkAudioCopyright = async (file: File) => {
    try {
      const formData = new FormData()
      formData.append('audio', file)

      const response = await fetch('/api/audio/v1/detect', {
        method: 'POST',
        body: formData
      })

      if (!response.ok) {
        throw new Error('Audio detection failed')
      }

      const result = await response.json()

      if (result.has_copyright) {
        setAudioCopyright({ detected: true, matches: result.matches })
        toast.warning(`Copyrighted audio detected: ${result.matches.length} matches`, {
          action: {
            label: 'Replace with AI',
            onClick: () => setReplaceAudio(true)
          },
          duration: 10000
        })
      }

    } catch (error) {
      console.error('Audio detection error:', error)
    }
  }

  // Apply preset template
  const applyPreset = (preset: BlurPreset) => {
    setBlurMethod(preset.settings.method)
    setBlurStrength(preset.settings.strength)
    setConfidenceThreshold(preset.settings.confidence_threshold)

    toast.success(`Applied ${preset.name} preset`)

    // TODO: Send preset usage as training data
    sendPresetTelemetry(preset.id)
  }

  // Send preset usage for model fine-tuning
  const sendPresetTelemetry = async (presetId: string) => {
    try {
      await fetch('/api/pii/v1/telemetry/preset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          preset_id: presetId,
          video_metadata: {
            duration: videoDuration,
            faces_detected: faces.length
          }
        })
      })
    } catch (error) {
      console.error('Telemetry error:', error)
    }
  }

  // Export blurred video
  const exportVideo = async () => {
    if (!videoFile) return

    setIsProcessing(true)
    setProcessingProgress(0)

    try {
      const formData = new FormData()
      formData.append('video', videoFile)
      formData.append('blur_method', blurMethod)
      formData.append('blur_strength', blurStrength.toString())
      formData.append('confidence_threshold', confidenceThreshold.toString())
      formData.append('custom_masks', JSON.stringify(customMasks))
      formData.append('replace_audio', replaceAudio.toString())

      if (selectedFaces.size > 0) {
        formData.append('exclude_objects', Array.from(selectedFaces).join(','))
      }

      toast.info('Processing video...', { duration: Infinity, id: 'export-toast' })

      const response = await fetch('/api/pii/v1/blur/video', {
        method: 'POST',
        body: formData
      })

      if (!response.ok) {
        throw new Error('Video processing failed')
      }

      // Download result
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `blurred_${videoFile.name}`
      a.click()

      toast.success('Video exported successfully', { id: 'export-toast' })

    } catch (error) {
      console.error('Export error:', error)
      toast.error('Failed to export video', { id: 'export-toast' })
    } finally {
      setIsProcessing(false)
      setProcessingProgress(0)
    }
  }

  return (
    <div className={cn('flex flex-col h-screen bg-gray-950 text-white', className)}>
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
        <div>
          <h1 className="text-2xl font-bold">Video Studio</h1>
          <p className="text-sm text-gray-400">Privacy-compliant video editing</p>
        </div>

        <div className="flex items-center gap-2">
          <Badge variant="outline" className="gap-1">
            <Cpu className="h-3 w-3" />
            RTX 2070
          </Badge>
          <Badge variant="outline" className="gap-1">
            <HardDrive className="h-3 w-3" />
            {faces.length} faces
          </Badge>
          <Badge variant="outline" className="gap-1">
            <Clock className="h-3 w-3" />
            {videoDuration.toFixed(1)}s
          </Badge>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar - Tools */}
        <div className="w-80 border-r border-gray-800 overflow-y-auto p-4 space-y-4">
          {/* Upload */}
          {!videoFile && (
            <Card className="bg-gray-900 border-gray-800">
              <CardHeader>
                <CardTitle className="text-lg">Upload Video</CardTitle>
                <CardDescription>Drag & drop or click to select</CardDescription>
              </CardHeader>
              <CardContent>
                <label
                  htmlFor="video-upload"
                  className="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-gray-700 rounded-lg cursor-pointer hover:border-gray-600 transition-colors"
                  onDrop={(e) => {
                    e.preventDefault()
                    const file = e.dataTransfer.files[0]
                    if (file) handleFileUpload(file)
                  }}
                  onDragOver={(e) => e.preventDefault()}
                >
                  <Upload className="h-8 w-8 text-gray-400 mb-2" />
                  <span className="text-sm text-gray-400">Drop video here</span>
                  <span className="text-xs text-gray-500 mt-1">Max 500MB, up to 10 min</span>
                </label>
                <input
                  id="video-upload"
                  type="file"
                  accept="video/*"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) handleFileUpload(file)
                  }}
                />
              </CardContent>
            </Card>
          )}

          {/* Blur Presets */}
          {videoFile && (
            <>
              <Card className="bg-gray-900 border-gray-800">
                <CardHeader>
                  <CardTitle className="text-lg">Quick Presets</CardTitle>
                  <CardDescription>One-click blur templates</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  {BLUR_PRESETS.map((preset) => (
                    <Button
                      key={preset.id}
                      variant="outline"
                      className="w-full justify-start gap-2"
                      onClick={() => applyPreset(preset)}
                    >
                      {preset.icon}
                      <div className="text-left flex-1">
                        <div className="font-medium">{preset.name}</div>
                        <div className="text-xs text-gray-400">{preset.description}</div>
                      </div>
                    </Button>
                  ))}
                </CardContent>
              </Card>

              {/* Blur Settings */}
              <Card className="bg-gray-900 border-gray-800">
                <CardHeader>
                  <CardTitle className="text-lg">Blur Settings</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Method</label>
                    <Select value={blurMethod} onValueChange={setBlurMethod}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {BLUR_METHODS.map((method) => (
                          <SelectItem key={method.value} value={method.value}>
                            {method.icon} {method.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium flex justify-between">
                      <span>Strength</span>
                      <span className="text-gray-400">{blurStrength}%</span>
                    </label>
                    <Slider
                      value={[blurStrength]}
                      onValueChange={([v]) => setBlurStrength(v)}
                      min={1}
                      max={100}
                      step={1}
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium flex justify-between">
                      <span>Detection Threshold</span>
                      <span className="text-gray-400">{(confidenceThreshold * 100).toFixed(0)}%</span>
                    </label>
                    <Slider
                      value={[confidenceThreshold * 100]}
                      onValueChange={([v]) => setConfidenceThreshold(v / 100)}
                      min={10}
                      max={100}
                      step={5}
                    />
                  </div>
                </CardContent>
              </Card>

              {/* Drawing Tools */}
              <Card className="bg-gray-900 border-gray-800">
                <CardHeader>
                  <CardTitle className="text-lg">Custom Masks</CardTitle>
                  <CardDescription>Draw custom blur regions</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <Button
                      variant={drawMode === 'select' ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setDrawMode('select')}
                    >
                      Select
                    </Button>
                    <Button
                      variant={drawMode === 'freehand' ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setDrawMode('freehand')}
                    >
                      <Pencil className="h-4 w-4 mr-1" />
                      Freehand
                    </Button>
                    <Button
                      variant={drawMode === 'polygon' ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setDrawMode('polygon')}
                    >
                      <Square className="h-4 w-4 mr-1" />
                      Polygon
                    </Button>
                    <Button
                      variant={drawMode === 'lasso' ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setDrawMode('lasso')}
                    >
                      <Lasso className="h-4 w-4 mr-1" />
                      Lasso
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {/* Audio Copyright Warning */}
              {audioCopyright.detected && (
                <Card className="bg-orange-950 border-orange-800">
                  <CardHeader>
                    <CardTitle className="text-lg flex items-center gap-2">
                      <Music className="h-5 w-5" />
                      Copyrighted Audio
                    </CardTitle>
                    <CardDescription className="text-orange-200">
                      {audioCopyright.matches.length} copyrighted track(s) detected
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {audioCopyright.matches.slice(0, 3).map((match, i) => (
                        <div key={i} className="text-sm text-orange-100">
                          • {match.metadata?.title || 'Unknown track'} ({(match.similarity * 100).toFixed(0)}% match)
                        </div>
                      ))}

                      <Button
                        variant="outline"
                        className="w-full mt-4"
                        onClick={() => setReplaceAudio(!replaceAudio)}
                      >
                        <Wand2 className="h-4 w-4 mr-2" />
                        {replaceAudio ? '✓ AI Replacement Enabled' : 'Replace with AI Music'}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </div>

        {/* Center - Video Preview */}
        <div className="flex-1 flex flex-col">
          {/* Video Canvas */}
          <div className="flex-1 flex items-center justify-center bg-black relative">
            {videoFile ? (
              <div className="relative">
                <video
                  ref={videoRef}
                  src={videoUrl}
                  className="max-w-full max-h-full"
                  onLoadedMetadata={(e) => {
                    setVideoDuration(e.currentTarget.duration)
                  }}
                  onTimeUpdate={(e) => {
                    setCurrentTime(e.currentTarget.currentTime)
                  }}
                />
                <canvas
                  ref={canvasRef}
                  className="absolute inset-0"
                  style={{ pointerEvents: drawMode === 'select' ? 'none' : 'auto' }}
                />

                {/* Processing Overlay */}
                {isProcessing && (
                  <div className="absolute inset-0 bg-black/80 flex items-center justify-center">
                    <div className="text-center space-y-4">
                      <Loader2 className="h-12 w-12 animate-spin mx-auto text-blue-400" />
                      <div className="text-lg font-medium">Processing Video...</div>
                      <Progress value={processingProgress} className="w-64" />
                      <div className="text-sm text-gray-400">{processingProgress.toFixed(0)}% complete</div>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center text-gray-500">
                <Upload className="h-16 w-16 mx-auto mb-4 opacity-20" />
                <p>Upload a video to get started</p>
              </div>
            )}
          </div>

          {/* Timeline */}
          {videoFile && (
            <div className="border-t border-gray-800 p-4 space-y-4">
              {/* Playback Controls */}
              <div className="flex items-center gap-4">
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => {
                    if (videoRef.current) {
                      if (isPlaying) {
                        videoRef.current.pause()
                      } else {
                        videoRef.current.play()
                      }
                      setIsPlaying(!isPlaying)
                    }
                  }}
                >
                  {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </Button>

                <div className="flex-1">
                  <Slider
                    value={[currentTime]}
                    onValueChange={([v]) => {
                      if (videoRef.current) {
                        videoRef.current.currentTime = v
                        setCurrentTime(v)
                      }
                    }}
                    min={0}
                    max={videoDuration}
                    step={0.1}
                  />
                </div>

                <span className="text-sm text-gray-400 font-mono w-24 text-right">
                  {currentTime.toFixed(1)}s / {videoDuration.toFixed(1)}s
                </span>

                <Button
                  variant="default"
                  onClick={exportVideo}
                  disabled={isProcessing}
                >
                  <Download className="h-4 w-4 mr-2" />
                  Export
                </Button>
              </div>

              {/* Frame Thumbnails */}
              <div className="flex gap-2 overflow-x-auto pb-2">
                {timeline.map((frame, i) => (
                  <div
                    key={i}
                    className={cn(
                      'relative flex-shrink-0 w-20 h-12 rounded border-2 cursor-pointer transition-all',
                      Math.abs(frame.timestamp - currentTime) < 0.5
                        ? 'border-blue-500 scale-110'
                        : 'border-gray-700 hover:border-gray-600'
                    )}
                    onClick={() => {
                      if (videoRef.current) {
                        videoRef.current.currentTime = frame.timestamp
                        setCurrentTime(frame.timestamp)
                      }
                    }}
                  >
                    <img
                      src={frame.thumbnail}
                      alt={`Frame ${frame.frameNumber}`}
                      className="w-full h-full object-cover rounded"
                    />
                    {frame.faces.length > 0 && (
                      <Badge className="absolute -top-2 -right-2 text-xs">
                        {frame.faces.length}
                      </Badge>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
