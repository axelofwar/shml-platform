"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { jobsApi } from "@/lib/api";

interface JobDownloadModalProps {
  jobId: string;
  jobName: string;
}

export function JobDownloadModal({ jobId, jobName }: JobDownloadModalProps) {
  const [open, setOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [options, setOptions] = useState({
    workspace: true,
    logs: true,
    checkpoints: true,
    mlflow: false,
  });

  const handleDownload = async () => {
    if (!Object.values(options).some((v) => v)) {
      alert("Please select at least one component to download");
      return;
    }

    try {
      setDownloading(true);

      const blob = await jobsApi.downloadJob(jobId, options);

      // Create download link
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.style.display = "none";
      a.href = url;
      a.download = `${jobName}_${jobId}_${Date.now()}.tar.gz`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      setOpen(false);
    } catch (error: any) {
      console.error("Download failed:", error);
      alert(`Download failed: ${error.response?.data?.detail || error.message}`);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Download className="h-4 w-4 mr-1" />
          Download
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Download Job Artifacts</DialogTitle>
          <DialogDescription>
            Select which components to include in the download for <strong>{jobName}</strong>
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="flex items-center space-x-2">
            <Checkbox
              id="workspace"
              checked={options.workspace}
              onCheckedChange={(checked) =>
                setOptions({ ...options, workspace: checked as boolean })
              }
            />
            <label
              htmlFor="workspace"
              className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer flex-1"
            >
              <div className="font-semibold">Workspace Files</div>
              <div className="text-xs text-muted-foreground">
                Job working directory, scripts, and outputs
              </div>
            </label>
          </div>
          <div className="flex items-center space-x-2">
            <Checkbox
              id="logs"
              checked={options.logs}
              onCheckedChange={(checked) =>
                setOptions({ ...options, logs: checked as boolean })
              }
            />
            <label
              htmlFor="logs"
              className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer flex-1"
            >
              <div className="font-semibold">Ray Logs</div>
              <div className="text-xs text-muted-foreground">
                Job driver and worker logs from Ray
              </div>
            </label>
          </div>
          <div className="flex items-center space-x-2">
            <Checkbox
              id="checkpoints"
              checked={options.checkpoints}
              onCheckedChange={(checked) =>
                setOptions({ ...options, checkpoints: checked as boolean })
              }
            />
            <label
              htmlFor="checkpoints"
              className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer flex-1"
            >
              <div className="font-semibold">Checkpoints</div>
              <div className="text-xs text-muted-foreground">
                Model checkpoints and training snapshots
              </div>
            </label>
          </div>
          <div className="flex items-center space-x-2">
            <Checkbox
              id="mlflow"
              checked={options.mlflow}
              onCheckedChange={(checked) =>
                setOptions({ ...options, mlflow: checked as boolean })
              }
            />
            <label
              htmlFor="mlflow"
              className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer flex-1"
            >
              <div className="font-semibold">MLflow Artifacts</div>
              <div className="text-xs text-muted-foreground">
                Experiment metrics, models, and logged artifacts
              </div>
            </label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={downloading}>
            Cancel
          </Button>
          <Button onClick={handleDownload} disabled={downloading}>
            {downloading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {downloading ? "Downloading..." : "Download"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
