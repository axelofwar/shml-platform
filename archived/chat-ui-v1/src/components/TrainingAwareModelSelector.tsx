/**
 * Training-Aware Model Selector Component
 *
 * This component implements intelligent model routing:
 * - Primary model is HIDDEN during training (not selectable)
 * - Auto model shows smart routing behavior
 * - Queue status displayed when requests are queued
 * - Admin can force primary with warning/confirmation
 *
 * Architecture: Dedicated GPU allocation
 * - GPU 0 (3090 Ti): Training OR Primary model (mutually exclusive)
 * - GPU 1 (2070): Fallback model (always available)
 *
 * AG-UI Protocol Events:
 * - STATE_DELTA: Training state updates
 * - TEXT_MESSAGE_*: Queue status messages
 * - RUN_STARTED/FINISHED: Training job lifecycle
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Sparkles,
  Zap,
  AlertTriangle,
  Clock,
  Loader2,
  ChevronDown,
  Activity,
  ShieldAlert,
} from 'lucide-react';

// Types for model availability and routing
export interface ModelAvailability {
  primary: {
    available: boolean;
    selectable: boolean;
    reason: string | null;
    display_name: string | null;
  };
  auto: {
    available: boolean;
    selectable: boolean;
    behavior: 'fallback_preferred' | 'smart_routing';
    display_name: string;
  };
  fallback: {
    available: boolean;
    selectable: boolean;
    reason: string | null;
    display_name: string;
  };
  training_active: boolean;
  queue_length: number;
  recommended: string;
}

export interface QueueStatus {
  queue_enabled: boolean;
  queue_length: number;
  oldest_request_age_seconds: number | null;
  estimated_wait_time_seconds: number | null;
  will_trigger_checkpoint: boolean;
  checkpoint_trigger_threshold: number;
  training_active: boolean;
}

export interface RoutingResult {
  decision: 'primary' | 'fallback' | 'queued_for_primary' | 'rejected';
  reason: string;
  target_model: string | null;
  queue_position: number | null;
  estimated_wait_seconds: number | null;
  complexity_score: number;
  skills_detected: string[];
  requires_confirmation: boolean;
}

interface TrainingAwareModelSelectorProps {
  selectedModel: string;
  onModelSelect: (model: string) => void;
  userRole: 'admin' | 'developer' | 'viewer';
  apiBaseUrl?: string;
}

export function TrainingAwareModelSelector({
  selectedModel,
  onModelSelect,
  userRole,
  apiBaseUrl = '/api',
}: TrainingAwareModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const [modelAvailability, setModelAvailability] = useState<ModelAvailability | null>(null);
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [showForceConfirm, setShowForceConfirm] = useState(false);

  // Fetch model availability
  const fetchModelAvailability = useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/routing/models`);
      if (response.ok) {
        const data = await response.json();
        setModelAvailability(data);
      }
    } catch (error) {
      console.error('Failed to fetch model availability:', error);
    }
  }, [apiBaseUrl]);

  // Fetch queue status
  const fetchQueueStatus = useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/queue/status`);
      if (response.ok) {
        const data = await response.json();
        setQueueStatus(data);
      }
    } catch (error) {
      console.error('Failed to fetch queue status:', error);
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  // Initial fetch and polling
  useEffect(() => {
    fetchModelAvailability();
    fetchQueueStatus();

    // Poll every 5 seconds during training
    const interval = setInterval(() => {
      fetchModelAvailability();
      fetchQueueStatus();
    }, 5000);

    return () => clearInterval(interval);
  }, [fetchModelAvailability, fetchQueueStatus]);

  // Handle model selection
  const handleModelSelect = (modelId: string) => {
    // If selecting primary during training as admin, show confirmation
    if (
      modelId === 'primary' &&
      modelAvailability?.training_active &&
      userRole === 'admin'
    ) {
      setShowForceConfirm(true);
      return;
    }

    // Normal selection
    onModelSelect(modelId);
    setOpen(false);
  };

  // Handle admin force confirmation
  const handleForceConfirm = () => {
    onModelSelect('primary');
    setShowForceConfirm(false);
    setOpen(false);
  };

  // Get display info for selected model
  const getSelectedDisplay = () => {
    if (loading || !modelAvailability) {
      return { icon: <Loader2 className="w-4 h-4 animate-spin" />, name: 'Loading...' };
    }

    switch (selectedModel) {
      case 'auto':
        return {
          icon: <Sparkles className="w-4 h-4 text-primary-400" />,
          name: modelAvailability.auto.display_name,
          badge: modelAvailability.training_active ? 'Fallback Mode' : null,
        };
      case 'primary':
        if (modelAvailability.training_active) {
          return {
            icon: <ShieldAlert className="w-4 h-4 text-yellow-400" />,
            name: 'Primary (Queued)',
            badge: `Queue: ${modelAvailability.queue_length}`,
          };
        }
        return {
          icon: <Sparkles className="w-4 h-4 text-purple-400" />,
          name: modelAvailability.primary.display_name || 'Primary (32B)',
        };
      case 'fallback':
        return {
          icon: <Zap className="w-4 h-4 text-yellow-400" />,
          name: modelAvailability.fallback.display_name,
        };
      default:
        return { icon: <Sparkles className="w-4 h-4" />, name: selectedModel };
    }
  };

  const selectedDisplay = getSelectedDisplay();

  return (
    <div className="relative">
      {/* Training indicator */}
      {modelAvailability?.training_active && (
        <div className="absolute -top-6 left-0 flex items-center gap-1 text-xs text-yellow-400">
          <Activity className="w-3 h-3 animate-pulse" />
          <span>Training Active</span>
        </div>
      )}

      {/* Main selector button */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-dark-800 border border-dark-600 hover:border-dark-500 transition-colors"
      >
        {selectedDisplay.icon}
        <span className="text-sm">{selectedDisplay.name}</span>
        {selectedDisplay.badge && (
          <span className="text-xs px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded">
            {selectedDisplay.badge}
          </span>
        )}
        <ChevronDown className="w-4 h-4" />
      </button>

      {/* Dropdown */}
      {open && modelAvailability && (
        <div className="absolute top-full mt-1 left-0 w-80 bg-dark-800 border border-dark-600 rounded-lg shadow-xl z-50">
          {/* Auto option - always available, routes intelligently */}
          <button
            onClick={() => handleModelSelect('auto')}
            className={`w-full px-4 py-3 text-left hover:bg-dark-700 transition-colors rounded-t-lg ${
              selectedModel === 'auto' ? 'bg-dark-700' : ''
            }`}
          >
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-primary-400" />
              <span className="font-medium">{modelAvailability.auto.display_name}</span>
              {modelAvailability.training_active ? (
                <span className="text-xs px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded ml-auto">
                  → Fallback Only
                </span>
              ) : (
                <span className="text-xs px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded ml-auto">
                  Recommended
                </span>
              )}
            </div>
            <p className="text-xs text-dark-400 mt-1">
              {modelAvailability.training_active
                ? 'Routes to Fallback model while Primary is training'
                : 'Automatically selects Primary (32B) or Fallback (3B) based on complexity'}
            </p>
          </button>

          {/* Primary option - show as offline during training, selectable otherwise */}
          <button
            onClick={() => handleModelSelect('primary')}
            disabled={modelAvailability.training_active && userRole !== 'admin'}
            className={`w-full px-4 py-3 text-left transition-colors ${
              selectedModel === 'primary' ? 'bg-dark-700' : 'hover:bg-dark-700'
            } ${modelAvailability.training_active ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            <div className="flex items-center gap-2">
              <Sparkles className={`w-4 h-4 ${modelAvailability.training_active ? 'text-gray-500' : 'text-purple-400'}`} />
              <span className={`font-medium ${modelAvailability.training_active ? 'text-gray-500' : ''}`}>
                {modelAvailability.primary.display_name || 'Primary (32B)'}
              </span>
              {modelAvailability.training_active ? (
                <span className="text-xs px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded ml-auto flex items-center gap-1">
                  <Activity className="w-3 h-3" />
                  Offline - Training
                </span>
              ) : (
                <span className="text-xs text-green-400 ml-auto">Online</span>
              )}
            </div>
            <p className="text-xs text-dark-400 mt-1">
              {modelAvailability.training_active
                ? 'GPU dedicated to training job - use Auto or Fallback'
                : 'Best quality for complex tasks - RTX 3090 Ti'}
            </p>
            {modelAvailability.training_active && userRole === 'admin' && (
              <p className="text-xs text-yellow-400 mt-1 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                Admin: Click to interrupt training (not recommended)
              </p>
            )}
          </button>

          {/* Fallback option - always available */}
          <button
            onClick={() => handleModelSelect('fallback')}
            className={`w-full px-4 py-3 text-left hover:bg-dark-700 transition-colors rounded-b-lg ${
              selectedModel === 'fallback' ? 'bg-dark-700' : ''
            }`}
          >
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-yellow-400" />
              <span className="font-medium">{modelAvailability.fallback.display_name}</span>
              <span className="text-xs text-green-400 ml-auto">Always Available</span>
            </div>
            <p className="text-xs text-dark-400 mt-1">
              Fast responses for simple tasks - RTX 2070
            </p>
          </button>

          {/* Queue status during training */}
          {modelAvailability.training_active && queueStatus && queueStatus.queue_length > 0 && (
            <div className="px-4 py-2 border-t border-dark-600 bg-dark-900/50">
              <div className="flex items-center gap-2 text-xs text-dark-400">
                <Clock className="w-3 h-3" />
                <span>
                  {queueStatus.queue_length} request{queueStatus.queue_length > 1 ? 's' : ''} queued
                  {queueStatus.estimated_wait_time_seconds && (
                    <> • ~{Math.round(queueStatus.estimated_wait_time_seconds)}s wait</>
                  )}
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Force primary confirmation modal */}
      {showForceConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-dark-800 border border-dark-600 rounded-lg p-6 max-w-md mx-4">
            <div className="flex items-center gap-3 mb-4">
              <AlertTriangle className="w-6 h-6 text-yellow-400" />
              <h3 className="font-semibold text-lg">Pause Training?</h3>
            </div>
            <p className="text-dark-300 mb-4">
              Training is currently active. Using the primary model will pause training
              until your request is complete. This may delay the training job.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowForceConfirm(false)}
                className="px-4 py-2 text-sm rounded-lg bg-dark-700 hover:bg-dark-600 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleForceConfirm}
                className="px-4 py-2 text-sm rounded-lg bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30 transition-colors"
              >
                Use Primary Anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Queue Status Display Component
 *
 * Shows when the user's request is queued for the primary model.
 * Displays position and estimated wait time.
 */
export function QueueStatusBanner({ queueInfo }: { queueInfo: RoutingResult }) {
  if (queueInfo.decision !== 'queued_for_primary') {
    return null;
  }

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded-lg text-sm">
      <Clock className="w-4 h-4 text-blue-400" />
      <span>
        Request queued for primary model
        {queueInfo.queue_position && <> • Position #{queueInfo.queue_position}</>}
        {queueInfo.estimated_wait_seconds && (
          <> • ~{Math.round(queueInfo.estimated_wait_seconds)}s wait</>
        )}
      </span>
    </div>
  );
}

export default TrainingAwareModelSelector;
