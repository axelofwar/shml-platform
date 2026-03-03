"use client";

import { useState } from "react";
import { Play, Square, RefreshCw, Trash2, Loader2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { jobsApi, Job } from "@/lib/api";

interface JobActionsProps {
  job: Job;
  onJobUpdated: () => void;
  userRole: string;
}

export function JobActions({ job, onJobUpdated, userRole }: JobActionsProps) {
  const [loading, setLoading] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isAdmin = userRole === "admin";
  const isRunning = job.status === "RUNNING";
  const isStopped = job.status === "STOPPED" || job.status === "CANCELLED";
  const isCompleted = job.status === "SUCCEEDED" || job.status === "FAILED";

  const handleAction = async (
    action: "stop" | "restart" | "start",
    apiCall: () => Promise<any>
  ) => {
    try {
      setLoading(action);
      setError(null);
      await apiCall();
      onJobUpdated();
    } catch (err: any) {
      console.error(`Failed to ${action} job:`, err);
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(null);
    }
  };

  const handleStop = () => handleAction("stop", () => jobsApi.stopJob(job.job_id));

  const handleRestart = () => handleAction("restart", () => jobsApi.restartJob(job.job_id));

  const handleStart = () => handleAction("start", () => jobsApi.startJob(job.job_id));

  const handleDelete = async () => {
    try {
      setLoading("delete");
      setError(null);
      await jobsApi.deleteJob(job.job_id, true);
      setDeleteDialogOpen(false);
      onJobUpdated();
    } catch (err: any) {
      console.error("Failed to delete job:", err);
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(null);
    }
  };

  return (
    <>
      <div className="flex gap-2">
        {/* Stop Button - Only for running jobs */}
        {isRunning && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleStop}
            disabled={loading !== null}
          >
            {loading === "stop" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Square className="h-4 w-4" />
            )}
          </Button>
        )}

        {/* Start Button - Only for stopped jobs */}
        {isStopped && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleStart}
            disabled={loading !== null}
          >
            {loading === "start" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
          </Button>
        )}

        {/* Restart Button - For any non-running job */}
        {!isRunning && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleRestart}
            disabled={loading !== null}
          >
            {loading === "restart" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </Button>
        )}

        {/* Delete Button - For completed or stopped jobs */}
        {(isCompleted || isStopped) && (
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setDeleteDialogOpen(true)}
            disabled={loading !== null}
          >
            {loading === "delete" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
          </Button>
        )}
      </div>

      {/* Error Display */}
      {error && (
        <div className="flex items-center gap-2 text-sm text-destructive mt-2">
          <AlertCircle className="h-4 w-4" />
          <span>{error}</span>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Job</DialogTitle>
            <DialogDescription>
              This will permanently delete job <strong>{job.name}</strong> and clean up:
              <ul className="list-disc list-inside mt-2 space-y-1">
                <li>Workspace files</li>
                <li>Ray logs</li>
                <li>Checkpoints</li>
                <li>Job metadata</li>
              </ul>
              <p className="mt-2 text-sm">
                <strong>Note:</strong> MLflow experiment data will be preserved for audit purposes.
              </p>
              <p className="mt-2 font-semibold">This action cannot be undone.</p>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              disabled={loading === "delete"}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={loading === "delete"}
            >
              {loading === "delete" && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Delete Permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
