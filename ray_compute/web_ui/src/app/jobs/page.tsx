"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useRef, useCallback } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Play,
  Pause,
  Square,
  Trash2,
  Download,
  RefreshCw,
  Plus,
  FileText,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  Terminal,
  FolderOpen,
  ExternalLink,
  LogOut,
} from "lucide-react";
import { jobsApi, logsApi, userApi, waitForAuth, Job, JobDownloadOptions, JobSubmitRequest, jobSubmissionApi } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { Toaster } from "@/components/ui/toaster";
import { formatDistanceToNow, format } from "date-fns";

// Status badge colors
const statusColors: Record<string, string> = {
  PENDING: "bg-yellow-100 text-yellow-800",
  QUEUED: "bg-blue-100 text-blue-800",
  RUNNING: "bg-green-100 text-green-800",
  SUCCEEDED: "bg-emerald-100 text-emerald-800",
  COMPLETED: "bg-emerald-100 text-emerald-800",
  FAILED: "bg-red-100 text-red-800",
  STOPPED: "bg-gray-100 text-gray-800",
  CANCELLED: "bg-gray-100 text-gray-800",
};

const statusIcons: Record<string, React.ReactNode> = {
  PENDING: <Clock className="h-4 w-4" />,
  QUEUED: <Clock className="h-4 w-4" />,
  RUNNING: <Loader2 className="h-4 w-4 animate-spin" />,
  SUCCEEDED: <CheckCircle className="h-4 w-4" />,
  COMPLETED: <CheckCircle className="h-4 w-4" />,
  FAILED: <XCircle className="h-4 w-4" />,
  STOPPED: <Square className="h-4 w-4" />,
  CANCELLED: <Square className="h-4 w-4" />,
};

interface JobWithLogs extends Job {
  logs?: string[];
  logsLoading?: boolean;
  expanded?: boolean;
}

export default function JobsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();

  const [mounted, setMounted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [jobs, setJobs] = useState<JobWithLogs[]>([]);
  const [totalJobs, setTotalJobs] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selectedJob, setSelectedJob] = useState<string | null>(null);
  const [showSubmitDialog, setShowSubmitDialog] = useState(false);
  const [showDownloadDialog, setShowDownloadDialog] = useState(false);
  const [downloadJobId, setDownloadJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showAllJobs, setShowAllJobs] = useState(false);
  const [currentUser, setCurrentUser] = useState<{ role: string } | null>(null);

  // Auto-refresh for running jobs
  const refreshIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Log streaming refs
  const logSocketRef = useRef<WebSocket | null>(null);
  const logContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (mounted) {
      fetchJobs();

      // Auto-refresh every 5 seconds if there are running jobs
      refreshIntervalRef.current = setInterval(() => {
        const hasRunningJobs = jobs.some(j => j.status === 'RUNNING' || j.status === 'PENDING');
        if (hasRunningJobs) {
          fetchJobs(true);
        }
      }, 5000);

      return () => {
        if (refreshIntervalRef.current) {
          clearInterval(refreshIntervalRef.current);
        }
        if (logSocketRef.current) {
          logSocketRef.current.close();
        }
      };
    }
  }, [mounted]);

  // Refetch when showAllJobs toggle changes
  useEffect(() => {
    if (mounted) {
      fetchJobs();
    }
  }, [showAllJobs]);

  const fetchJobs = async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      else setRefreshing(true);

      await waitForAuth();

      // Fetch current user if not already loaded
      if (!currentUser) {
        try {
          const user = await userApi.getMe();
          setCurrentUser({ role: user.role });
        } catch (e) {
          console.error('Error fetching user:', e);
        }
      }

      const response = await jobsApi.listJobs(page, 20, showAllJobs);
      setJobs(response.jobs.map(j => ({ ...j, expanded: false })));
      setTotalJobs(response.total);
    } catch (error: any) {
      console.error('Error fetching jobs:', error);
      if (!silent) {
        toast({
          variant: "destructive",
          title: "Error loading jobs",
          description: error.message || "Failed to fetch jobs",
        });
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleJobAction = async (action: string, jobId: string) => {
    try {
      let result;
      switch (action) {
        case 'cancel':
          result = await jobsApi.cancelJob(jobId);
          toast({
            title: "Job cancelled",
            description: `Job ${jobId} has been cancelled`,
          });
          break;
        case 'restart':
          result = await jobsApi.restartJob(jobId);
          toast({
            title: "Job restarted",
            description: `New job created: ${result.new_job_id}`,
          });
          break;
        case 'start':
          result = await jobsApi.startJob(jobId);
          toast({
            title: "Job started",
            description: `Job ${jobId} is starting`,
          });
          break;
        case 'delete':
          result = await jobsApi.deleteJob(jobId);
          toast({
            title: "Job deleted",
            description: `Job ${jobId} and its resources have been cleaned up`,
          });
          break;
      }
      fetchJobs();
    } catch (error: any) {
      toast({
        variant: "destructive",
        title: `Failed to ${action} job`,
        description: error.response?.data?.detail || error.message,
      });
    }
  };

  const handleDownload = async (options: JobDownloadOptions) => {
    if (!downloadJobId) return;

    try {
      toast({
        title: "Preparing download...",
        description: "Creating archive of selected files",
      });

      const blob = await jobsApi.downloadJob(downloadJobId, options);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `job_${downloadJobId}_artifacts.tar.gz`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      toast({
        variant: "success",
        title: "Download started",
        description: "Your job artifacts are being downloaded",
      });
      setShowDownloadDialog(false);
    } catch (error: any) {
      toast({
        variant: "destructive",
        title: "Download failed",
        description: error.response?.data?.detail || error.message,
      });
    }
  };

  const toggleJobExpansion = async (jobId: string) => {
    setJobs(prev => prev.map(job => {
      if (job.job_id === jobId) {
        const newExpanded = !job.expanded;
        if (newExpanded && !job.logs) {
          // Fetch logs when expanding
          loadJobLogs(jobId);
        }
        return { ...job, expanded: newExpanded };
      }
      return job;
    }));
  };

  const loadJobLogs = async (jobId: string) => {
    setJobs(prev => prev.map(j =>
      j.job_id === jobId ? { ...j, logsLoading: true } : j
    ));

    try {
      const logsResponse = await logsApi.getJobLogs(jobId, 200);
      setJobs(prev => prev.map(j =>
        j.job_id === jobId ? { ...j, logs: logsResponse.lines, logsLoading: false } : j
      ));
    } catch (error) {
      console.error('Error loading logs:', error);
      setJobs(prev => prev.map(j =>
        j.job_id === jobId ? { ...j, logs: ['Error loading logs'], logsLoading: false } : j
      ));
    }
  };

  const startLogStream = (jobId: string) => {
    if (logSocketRef.current) {
      logSocketRef.current.close();
    }

    const socket = logsApi.createLogSocket(jobId);
    logSocketRef.current = socket;

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'log') {
        setJobs(prev => prev.map(j => {
          if (j.job_id === jobId) {
            const newLogs = [...(j.logs || []), data.line];
            // Keep only last 500 lines
            if (newLogs.length > 500) {
              newLogs.splice(0, newLogs.length - 500);
            }
            return { ...j, logs: newLogs };
          }
          return j;
        }));

        // Auto-scroll to bottom
        if (logContainerRef.current) {
          logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
        }
      }
    };

    socket.onerror = (error) => {
      console.error('WebSocket error:', error);
      toast({
        variant: "destructive",
        title: "Log stream error",
        description: "Failed to connect to log stream",
      });
    };
  };

  const filteredJobs = statusFilter === 'all'
    ? jobs
    : jobs.filter(j => j.status === statusFilter);

  if (!mounted) return null;

  return (
    <div className="flex min-h-screen w-full flex-col">
      <Toaster />

      {/* Header */}
      <header className="sticky top-0 z-10 flex h-16 items-center gap-4 border-b bg-background px-4 md:px-6">
        <nav className="flex-1 flex items-center gap-6 text-lg font-medium md:text-sm">
          <span className="text-xl font-bold">Ray Compute</span>
          <a href="/ray/ui" className="text-muted-foreground transition-colors hover:text-foreground">
            Dashboard
          </a>
          <a href="/ray/ui/jobs" className="text-foreground font-semibold">
            Jobs
          </a>
          <a href="/ray/ui/cluster" className="text-muted-foreground transition-colors hover:text-foreground">
            Cluster
          </a>
        </nav>
        <Button variant="outline" size="sm" onClick={() => window.location.href = '/oauth2-proxy/sign_out?rd=/ray/ui'}>
          <LogOut className="mr-2 h-4 w-4" />
          Sign Out
        </Button>
      </header>

      <main className="flex flex-1 flex-col gap-4 p-4 md:gap-8 md:p-8">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Jobs</h1>
            <p className="text-muted-foreground">
              Manage and monitor your Ray compute jobs
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => fetchJobs()}
              disabled={refreshing}
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
            <Button onClick={() => setShowSubmitDialog(true)}>
              <Plus className="mr-2 h-4 w-4" />
              New Job
            </Button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-4 items-center">
          <Label htmlFor="status-filter">Filter by status:</Label>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="PENDING">Pending</SelectItem>
              <SelectItem value="RUNNING">Running</SelectItem>
              <SelectItem value="SUCCEEDED">Succeeded</SelectItem>
              <SelectItem value="FAILED">Failed</SelectItem>
              <SelectItem value="STOPPED">Stopped</SelectItem>
              <SelectItem value="CANCELLED">Cancelled</SelectItem>
            </SelectContent>
          </Select>

          {/* Admin toggle to show all users' jobs */}
          {currentUser?.role === 'admin' && (
            <div className="flex items-center space-x-2 ml-4 pl-4 border-l">
              <Checkbox
                id="show-all-jobs"
                checked={showAllJobs}
                onCheckedChange={(checked) => {
                  setShowAllJobs(checked === true);
                  // Refetch will happen via useEffect
                }}
              />
              <Label htmlFor="show-all-jobs" className="text-sm font-normal cursor-pointer">
                Show all users&apos; jobs
              </Label>
            </div>
          )}

          <span className="text-sm text-muted-foreground">
            {filteredJobs.length} of {totalJobs} jobs
            {showAllJobs && ' (all users)'}
          </span>
        </div>

        {/* Jobs List */}
        {loading ? (
          <div className="space-y-4">
            {[1, 2, 3].map(i => (
              <Card key={i}>
                <CardHeader>
                  <Skeleton className="h-6 w-48" />
                  <Skeleton className="h-4 w-32" />
                </CardHeader>
              </Card>
            ))}
          </div>
        ) : filteredJobs.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <FileText className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="text-lg font-semibold">No jobs found</h3>
              <p className="text-muted-foreground mb-4">
                {statusFilter !== 'all'
                  ? `No jobs with status "${statusFilter}"`
                  : "Submit your first job to get started!"}
              </p>
              <Button onClick={() => setShowSubmitDialog(true)}>
                <Plus className="mr-2 h-4 w-4" />
                Submit New Job
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4">
            {filteredJobs.map(job => (
              <Card key={job.job_id} className="overflow-hidden">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="p-0 h-6 w-6"
                        onClick={() => toggleJobExpansion(job.job_id)}
                      >
                        {job.expanded ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </Button>
                      <div>
                        <CardTitle className="text-lg">{job.name}</CardTitle>
                        <CardDescription className="font-mono text-xs">
                          {job.job_id}
                        </CardDescription>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge className={statusColors[job.status] || "bg-gray-100"}>
                        {statusIcons[job.status]}
                        <span className="ml-1">{job.status}</span>
                      </Badge>
                    </div>
                  </div>
                </CardHeader>

                <CardContent>
                  {/* Job Summary */}
                  <div className="flex flex-wrap gap-4 text-sm text-muted-foreground mb-4">
                    <span>
                      Created: {format(new Date(job.created_at), 'MMM d, yyyy HH:mm')}
                    </span>
                    {job.started_at && (
                      <span>
                        Started: {formatDistanceToNow(new Date(job.started_at))} ago
                      </span>
                    )}
                    {job.ended_at && (
                      <span>
                        Duration: {formatDistanceToNow(new Date(job.started_at || job.created_at), {
                          includeSeconds: true
                        })}
                      </span>
                    )}
                  </div>

                  {/* Job Actions */}
                  <div className="flex flex-wrap gap-2 mb-4">
                    {(job.status === 'RUNNING' || job.status === 'PENDING') && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleJobAction('cancel', job.job_id)}
                      >
                        <Square className="mr-2 h-4 w-4" />
                        Stop
                      </Button>
                    )}
                    {(job.status === 'STOPPED' || job.status === 'FAILED') && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleJobAction('restart', job.job_id)}
                      >
                        <RefreshCw className="mr-2 h-4 w-4" />
                        Restart
                      </Button>
                    )}
                    {['SUCCEEDED', 'FAILED', 'STOPPED', 'CANCELLED'].includes(job.status) && (
                      <>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            setDownloadJobId(job.job_id);
                            setShowDownloadDialog(true);
                          }}
                        >
                          <Download className="mr-2 h-4 w-4" />
                          Download
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-red-600 hover:text-red-700"
                          onClick={() => handleJobAction('delete', job.job_id)}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          Delete
                        </Button>
                      </>
                    )}
                    {job.status === 'RUNNING' && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => startLogStream(job.job_id)}
                      >
                        <Terminal className="mr-2 h-4 w-4" />
                        Live Logs
                      </Button>
                    )}
                  </div>

                  {/* Expanded Content */}
                  {job.expanded && (
                    <div className="border-t pt-4">
                      <Tabs defaultValue="logs">
                        <TabsList>
                          <TabsTrigger value="logs">
                            <Terminal className="mr-2 h-4 w-4" />
                            Logs
                          </TabsTrigger>
                          <TabsTrigger value="details">
                            <FileText className="mr-2 h-4 w-4" />
                            Details
                          </TabsTrigger>
                          <TabsTrigger value="outputs">
                            <FolderOpen className="mr-2 h-4 w-4" />
                            Outputs
                          </TabsTrigger>
                        </TabsList>

                        <TabsContent value="logs" className="mt-4">
                          {job.logsLoading ? (
                            <div className="flex items-center justify-center py-8">
                              <Loader2 className="h-6 w-6 animate-spin mr-2" />
                              Loading logs...
                            </div>
                          ) : (
                            <div
                              ref={logContainerRef}
                              className="bg-black text-green-400 font-mono text-xs p-4 rounded-lg max-h-96 overflow-auto"
                            >
                              {job.logs && job.logs.length > 0 ? (
                                job.logs.map((line, i) => (
                                  <div key={i} className="whitespace-pre-wrap">
                                    {line}
                                  </div>
                                ))
                              ) : (
                                <div className="text-gray-500">
                                  No logs available yet
                                </div>
                              )}
                            </div>
                          )}
                          <div className="flex justify-end mt-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => loadJobLogs(job.job_id)}
                            >
                              <RefreshCw className="mr-2 h-4 w-4" />
                              Refresh Logs
                            </Button>
                          </div>
                        </TabsContent>

                        <TabsContent value="details" className="mt-4">
                          <div className="grid grid-cols-2 gap-4 text-sm">
                            <div>
                              <Label className="text-muted-foreground">Job ID</Label>
                              <p className="font-mono">{job.job_id}</p>
                            </div>
                            <div>
                              <Label className="text-muted-foreground">Status</Label>
                              <p>{job.status}</p>
                            </div>
                            <div>
                              <Label className="text-muted-foreground">Created</Label>
                              <p>{format(new Date(job.created_at), 'PPpp')}</p>
                            </div>
                            {job.started_at && (
                              <div>
                                <Label className="text-muted-foreground">Started</Label>
                                <p>{format(new Date(job.started_at), 'PPpp')}</p>
                              </div>
                            )}
                            {job.ended_at && (
                              <div>
                                <Label className="text-muted-foreground">Ended</Label>
                                <p>{format(new Date(job.ended_at), 'PPpp')}</p>
                              </div>
                            )}
                            {job.metadata && (
                              <div className="col-span-2">
                                <Label className="text-muted-foreground">Metadata</Label>
                                <pre className="bg-muted p-2 rounded text-xs overflow-auto">
                                  {JSON.stringify(job.metadata, null, 2)}
                                </pre>
                              </div>
                            )}
                          </div>
                        </TabsContent>

                        <TabsContent value="outputs" className="mt-4">
                          <div className="space-y-4">
                            <Alert>
                              <FolderOpen className="h-4 w-4" />
                              <AlertTitle>Output Locations</AlertTitle>
                              <AlertDescription>
                                <div className="mt-2 space-y-2 text-sm">
                                  <p>
                                    <strong>Workspace:</strong>{" "}
                                    <code className="bg-muted px-1 rounded">
                                      /data/job_workspaces/{job.job_id}/
                                    </code>
                                  </p>
                                  <p>
                                    <strong>Logs:</strong>{" "}
                                    <code className="bg-muted px-1 rounded">
                                      /tmp/ray/session_latest/logs/job-driver-{job.job_id}.log
                                    </code>
                                  </p>
                                  {job.metadata?.checkpoint_dir && (
                                    <p>
                                      <strong>Checkpoints:</strong>{" "}
                                      <code className="bg-muted px-1 rounded">
                                        {job.metadata.checkpoint_dir}
                                      </code>
                                    </p>
                                  )}
                                </div>
                              </AlertDescription>
                            </Alert>

                            <div className="flex gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => {
                                  setDownloadJobId(job.job_id);
                                  setShowDownloadDialog(true);
                                }}
                              >
                                <Download className="mr-2 h-4 w-4" />
                                Download Artifacts
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => window.open('/mlflow', '_blank')}
                              >
                                <ExternalLink className="mr-2 h-4 w-4" />
                                View in MLflow
                              </Button>
                            </div>
                          </div>
                        </TabsContent>
                      </Tabs>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalJobs > 20 && (
          <div className="flex justify-center gap-2 mt-4">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
            >
              Previous
            </Button>
            <span className="flex items-center px-4 text-sm">
              Page {page} of {Math.ceil(totalJobs / 20)}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= Math.ceil(totalJobs / 20)}
              onClick={() => setPage(p => p + 1)}
            >
              Next
            </Button>
          </div>
        )}
      </main>

      {/* Job Submit Dialog */}
      <JobSubmitDialog
        open={showSubmitDialog}
        onOpenChange={setShowSubmitDialog}
        onSubmit={async (request) => {
          setSubmitting(true);
          try {
            const job = await jobSubmissionApi.submitJob(request);
            toast({
              variant: "success",
              title: "Job submitted",
              description: `Job ${job.job_id} has been submitted`,
            });
            setShowSubmitDialog(false);
            fetchJobs();
          } catch (error: any) {
            toast({
              variant: "destructive",
              title: "Job submission failed",
              description: error.response?.data?.detail || error.message,
            });
          } finally {
            setSubmitting(false);
          }
        }}
        submitting={submitting}
      />

      {/* Download Dialog */}
      <DownloadDialog
        open={showDownloadDialog}
        onOpenChange={setShowDownloadDialog}
        onDownload={handleDownload}
      />
    </div>
  );
}

// Job Submit Dialog Component
function JobSubmitDialog({
  open,
  onOpenChange,
  onSubmit,
  submitting,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (request: JobSubmitRequest) => void;
  submitting: boolean;
}) {
  const [formData, setFormData] = useState<JobSubmitRequest>({
    name: '',
    job_type: 'training',
    code: '',
    cpu: 2,
    memory_gb: 8,
    gpu: 0,
    timeout_hours: 2,
    no_timeout: false,
    priority: 'normal',
  });

  const [quota, setQuota] = useState<import('@/lib/api').UserQuota | null>(null);
  const [gpuInfo, setGpuInfo] = useState<import('@/lib/api').ClusterGPUResponse | null>(null);
  const [loadingQuota, setLoadingQuota] = useState(true);
  const [showGpuHelp, setShowGpuHelp] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load user quota and GPU info when dialog opens
  useEffect(() => {
    if (open) {
      loadQuotaAndGpuInfo();
    }
  }, [open]);

  const loadQuotaAndGpuInfo = async () => {
    setLoadingQuota(true);
    try {
      const [quotaData, gpuData] = await Promise.all([
        userApi.getQuota(),
        userApi.getClusterGPUs(),
      ]);
      setQuota(quotaData);
      setGpuInfo(gpuData);

      // Set defaults based on quota (use reasonable defaults within limits)
      setFormData(prev => ({
        ...prev,
        cpu: Math.min(2, 96),
        memory_gb: Math.min(8, 512),
        gpu: Math.min(0.25, quotaData.max_gpu_fraction),
        timeout_hours: quotaData.max_job_timeout_hours ? Math.min(2, quotaData.max_job_timeout_hours) : 2,
      }));
    } catch (error) {
      console.error('Error loading quota/GPU info:', error);
    } finally {
      setLoadingQuota(false);
    }
  };

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file && file.name.endsWith('.txt')) {
      const reader = new FileReader();
      reader.onload = (e) => {
        const content = e.target?.result as string;
        const packages = content.split('\n').map(line => line.trim()).filter(Boolean);
        setFormData(prev => ({
          ...prev,
          requirements: packages,
        }));
      };
      reader.readAsText(file);
    }
  };

  const isAdmin = quota?.allow_no_timeout || false;
  const maxGpuFraction = quota?.max_gpu_fraction || 0.25;
  const maxTimeout = quota?.max_job_timeout_hours;
  const allowExclusiveGpu = quota?.allow_exclusive_gpu || false;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Submit New Job</DialogTitle>
          <DialogDescription>
            Configure and submit a new Ray compute job
            {quota && (
              <span className="block mt-1 text-xs">
                Your limits: {maxTimeout ? `${maxTimeout}h timeout` : 'Unlimited timeout'} •
                Up to {maxGpuFraction * 100}% GPU •
                {quota.max_concurrent_jobs} concurrent jobs
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {loadingQuota ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-4 py-4">
            {/* Basic Info */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">Job Name *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="my-training-job"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="job_type">Job Type</Label>
                <Select
                  value={formData.job_type}
                  onValueChange={(v) => setFormData({ ...formData, job_type: v as any })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="training">Training</SelectItem>
                    <SelectItem value="inference">Inference</SelectItem>
                    <SelectItem value="pipeline">Pipeline</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Input
                id="description"
                value={formData.description || ''}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                placeholder="Optional description"
              />
            </div>

            {/* Code */}
            <div className="space-y-2">
              <Label htmlFor="code">Python Code *</Label>
              <Textarea
                id="code"
                value={formData.code || ''}
                onChange={(e) => setFormData({ ...formData, code: e.target.value })}
                placeholder={`# Your Python code here
import ray
print("Hello from Ray!")
`}
                className="font-mono text-sm min-h-[200px]"
              />
            </div>

            {/* Requirements - Enhanced with file upload */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="requirements">Python Packages (one per line)</Label>
                <div className="flex gap-2">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".txt"
                    onChange={handleFileUpload}
                    className="hidden"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    Upload requirements.txt
                  </Button>
                </div>
              </div>
              <Textarea
                id="requirements"
                value={(formData.requirements || []).join('\n')}
                onChange={(e) => setFormData({
                  ...formData,
                  requirements: e.target.value.split('\n').filter(Boolean)
                })}
                placeholder={`numpy
pandas>=2.0
torch==2.1.0
scikit-learn`}
                className="font-mono text-sm min-h-[100px] resize-y"
                rows={4}
              />
              <p className="text-xs text-muted-foreground">
                Supports pip format: package, package==version, package&gt;=version
              </p>
            </div>

            {/* Resources */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="cpu">CPUs (1-96)</Label>
                <Input
                  id="cpu"
                  type="number"
                  min={1}
                  max={96}
                  value={formData.cpu}
                  onChange={(e) => setFormData({ ...formData, cpu: parseInt(e.target.value) || 1 })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="memory">Memory GB (1-512)</Label>
                <Input
                  id="memory"
                  type="number"
                  min={1}
                  max={512}
                  value={formData.memory_gb}
                  onChange={(e) => setFormData({ ...formData, memory_gb: parseInt(e.target.value) || 1 })}
                />
              </div>
            </div>

            {/* GPU Section - Enhanced */}
            <div className="space-y-3 p-3 border rounded-lg bg-muted/30">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">GPU Resources</Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowGpuHelp(!showGpuHelp)}
                >
                  {showGpuHelp ? 'Hide help' : 'What is GPU fraction?'}
                </Button>
              </div>

              {showGpuHelp && gpuInfo && (
                <Alert className="bg-blue-50 border-blue-200">
                  <AlertCircle className="h-4 w-4 text-blue-600" />
                  <AlertDescription className="text-sm text-blue-800 whitespace-pre-line">
                    {gpuInfo.explanation}
                  </AlertDescription>
                </Alert>
              )}

              {/* Available GPUs Display */}
              {gpuInfo && gpuInfo.gpus.length > 0 && (
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">Available GPUs:</Label>
                  <div className="grid grid-cols-2 gap-2">
                    {gpuInfo.gpus.map((gpu, idx) => (
                      <div
                        key={idx}
                        className={`p-2 rounded border text-xs ${
                          gpu.available ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200'
                        }`}
                      >
                        <div className="font-medium">{gpu.name}</div>
                        <div className="text-muted-foreground">
                          {gpu.memory_total_gb}GB • {gpu.utilization_percent.toFixed(0)}% used
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="gpu">GPU Fraction (0 - {maxGpuFraction})</Label>
                  {!allowExclusiveGpu && maxGpuFraction < 1 && (
                    <span className="text-xs text-muted-foreground">
                      Exclusive access (1.0) requires admin role
                    </span>
                  )}
                </div>
                <div className="flex gap-2 items-center">
                  <Input
                    id="gpu"
                    type="number"
                    min={0}
                    max={maxGpuFraction}
                    step={0.05}
                    value={formData.gpu}
                    onChange={(e) => {
                      const val = parseFloat(e.target.value);
                      setFormData({
                        ...formData,
                        gpu: Math.min(val, maxGpuFraction)
                      });
                    }}
                    className="w-24"
                  />
                  <input
                    type="range"
                    min={0}
                    max={maxGpuFraction}
                    step={0.05}
                    value={formData.gpu}
                    onChange={(e) => setFormData({ ...formData, gpu: parseFloat(e.target.value) })}
                    className="flex-1"
                  />
                  <span className="text-sm w-16 text-right">
                    {((formData.gpu || 0) * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            </div>

            {/* Timeout Section */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="timeout">
                    Timeout (hours)
                    {maxTimeout && <span className="text-xs text-muted-foreground ml-1">(max: {maxTimeout})</span>}
                  </Label>
                </div>
                <Input
                  id="timeout"
                  type="number"
                  min={1}
                  max={maxTimeout || 999}
                  value={formData.timeout_hours || ''}
                  onChange={(e) => setFormData({ ...formData, timeout_hours: parseInt(e.target.value) || 1 })}
                  disabled={formData.no_timeout}
                />
              </div>

              {/* No Timeout Checkbox - Admin Only */}
              {isAdmin && (
                <div className="space-y-2">
                  <Label className="text-sm">Admin Options</Label>
                  <div className="flex items-center space-x-2 pt-2">
                    <Checkbox
                      id="no_timeout"
                      checked={formData.no_timeout}
                      onCheckedChange={(checked) => setFormData({
                        ...formData,
                        no_timeout: checked === true
                      })}
                    />
                    <Label htmlFor="no_timeout" className="text-sm font-normal cursor-pointer">
                      No timeout limit (run until completion)
                    </Label>
                  </div>
                </div>
              )}
            </div>

            {/* Priority */}
            <div className="space-y-2">
              <Label htmlFor="priority">Priority</Label>
              <Select
                value={formData.priority}
                onValueChange={(v) => setFormData({ ...formData, priority: v as any })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="normal">Normal</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="critical">Critical</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* MLflow Integration */}
            <div className="space-y-2">
              <Label htmlFor="mlflow_experiment">MLflow Experiment (optional)</Label>
              <Input
                id="mlflow_experiment"
                value={formData.mlflow_experiment || ''}
                onChange={(e) => setFormData({ ...formData, mlflow_experiment: e.target.value })}
                placeholder="experiment-name"
              />
              <p className="text-xs text-muted-foreground">
                If specified, job metrics will be automatically logged to MLflow
              </p>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => onSubmit(formData)}
            disabled={submitting || !formData.name || !formData.code || loadingQuota}
          >
            {submitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Submitting...
              </>
            ) : (
              <>
                <Play className="mr-2 h-4 w-4" />
                Submit Job
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Download Dialog Component
function DownloadDialog({
  open,
  onOpenChange,
  onDownload,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDownload: (options: JobDownloadOptions) => void;
}) {
  const [options, setOptions] = useState<JobDownloadOptions>({
    workspace: true,
    logs: true,
    checkpoints: true,
    mlflow: false,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Download Job Artifacts</DialogTitle>
          <DialogDescription>
            Select which artifacts to include in the download
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="flex items-center space-x-2">
            <Checkbox
              id="workspace"
              checked={options.workspace}
              onCheckedChange={(checked) =>
                setOptions({ ...options, workspace: checked as boolean })
              }
            />
            <Label htmlFor="workspace">Workspace files (code, data)</Label>
          </div>
          <div className="flex items-center space-x-2">
            <Checkbox
              id="logs"
              checked={options.logs}
              onCheckedChange={(checked) =>
                setOptions({ ...options, logs: checked as boolean })
              }
            />
            <Label htmlFor="logs">Ray logs (stdout, stderr)</Label>
          </div>
          <div className="flex items-center space-x-2">
            <Checkbox
              id="checkpoints"
              checked={options.checkpoints}
              onCheckedChange={(checked) =>
                setOptions({ ...options, checkpoints: checked as boolean })
              }
            />
            <Label htmlFor="checkpoints">Checkpoints (model weights)</Label>
          </div>
          <div className="flex items-center space-x-2">
            <Checkbox
              id="mlflow"
              checked={options.mlflow}
              onCheckedChange={(checked) =>
                setOptions({ ...options, mlflow: checked as boolean })
              }
            />
            <Label htmlFor="mlflow">MLflow artifacts</Label>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => onDownload(options)}
            disabled={!options.workspace && !options.logs && !options.checkpoints && !options.mlflow}
          >
            <Download className="mr-2 h-4 w-4" />
            Download
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
