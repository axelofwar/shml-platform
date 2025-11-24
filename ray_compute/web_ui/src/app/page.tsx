"use client";

import { useRouter } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { 
  Activity, 
  CreditCard, 
  DollarSign, 
  Users,
  ArrowUpRight,
  Clock,
  Zap,
  Cpu,
  LogOut,
  AlertCircle
} from "lucide-react";
import { jobsApi, userApi, setAccessToken } from "@/lib/api";

interface DashboardData {
  user: any;
  quota: any;
  jobs: any[];
  stats: {
    totalJobs: number;
    runningJobs: number;
    queuedJobs: number;
    completedJobs: number;
    failedJobs: number;
  };
}

export default function DashboardPage() {
  const router = useRouter();
  const { data: session, status } = useSession({
    required: true,
    onUnauthenticated() {
      router.push('/login');
    },
  });
  const [mounted, setMounted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Set access token when session is available
  useEffect(() => {
    console.log('Session data:', session);
    console.log('Access token:', session?.accessToken);
    if (session?.accessToken) {
      setAccessToken(session.accessToken as string);
      console.log('Access token set successfully');
    } else {
      console.warn('No access token found in session - user needs to re-login');
      // Show error prompting user to log out and back in
      setError('Session is missing authentication token. Please log out and log back in.');
    }
  }, [session]);

  useEffect(() => {
    if (session && mounted) {
      fetchDashboardData();
    }
  }, [session, mounted]);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch user, quota, and jobs in parallel
      const [userResponse, quotaResponse, jobsResponse] = await Promise.all([
        userApi.getMe(),
        userApi.getQuota(),
        jobsApi.listJobs(1, 10) // Get first 10 jobs
      ]);

      // Calculate stats from jobs
      const jobs = jobsResponse.jobs || [];
      const stats = {
        totalJobs: jobsResponse.total || 0,
        runningJobs: jobs.filter((j: any) => j.status === 'RUNNING').length,
        queuedJobs: jobs.filter((j: any) => j.status === 'PENDING' || j.status === 'QUEUED').length,
        completedJobs: jobs.filter((j: any) => j.status === 'SUCCEEDED' || j.status === 'COMPLETED').length,
        failedJobs: jobs.filter((j: any) => j.status === 'FAILED').length,
      };

      setDashboardData({
        user: userResponse,
        quota: quotaResponse,
        jobs: jobs,
        stats
      });
    } catch (err: any) {
      console.error('Failed to fetch dashboard data:', err);
      setError(err.response?.data?.detail || err.message || 'Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  };

  if (!mounted || status === "loading") {
    return null;
  }
  
  if (!session) {
    return null;
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto"></div>
          <p className="mt-4 text-muted-foreground">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  if (error) {
    const isAuthError = error.includes('authentication token') || error.includes('401');
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-destructive">
              <AlertCircle className="h-5 w-5" />
              Error Loading Dashboard
            </CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {isAuthError ? (
              <Button onClick={() => signOut({ callbackUrl: '/login' })} className="w-full" variant="default">
                Log Out and Sign In Again
              </Button>
            ) : (
              <Button onClick={fetchDashboardData} className="w-full">
                Retry
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!dashboardData) {
    return null;
  }

  const { user, quota, jobs, stats } = dashboardData;

  return (
    <div className="flex min-h-screen w-full flex-col">
      <header className="sticky top-0 flex h-16 items-center gap-4 border-b bg-background px-4 md:px-6">
        <nav className="flex-1 flex items-center gap-6 text-lg font-medium md:text-sm">
          <span className="text-xl font-bold">Ray Compute</span>
          <a href="#" className="text-muted-foreground transition-colors hover:text-foreground">
            Dashboard
          </a>
          <a href="#" className="text-muted-foreground transition-colors hover:text-foreground">
            Jobs
          </a>
          <a href="#" className="text-muted-foreground transition-colors hover:text-foreground">
            Cluster
          </a>
        </nav>
        <Button variant="outline" size="sm" onClick={() => signOut()}>
          <LogOut className="mr-2 h-4 w-4" />
          Sign Out
        </Button>
      </header>
      <main className="flex flex-1 flex-col gap-4 p-4 md:gap-8 md:p-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
            <p className="text-muted-foreground">
              Welcome back, {session.user?.name || session.user?.email}
            </p>
          </div>
        </div>
        
        <div className="grid gap-4 md:grid-cols-2 md:gap-8 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                Total Jobs
              </CardTitle>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.totalJobs}</div>
              <p className="text-xs text-muted-foreground">
                {stats.completedJobs} completed, {stats.failedJobs} failed
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                Running Jobs
              </CardTitle>
              <Cpu className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.runningJobs}</div>
              <p className="text-xs text-muted-foreground">
                {stats.queuedJobs} queued
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Concurrent Limit</CardTitle>
              <Zap className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{quota.max_concurrent_jobs}</div>
              <p className="text-xs text-muted-foreground">
                {stats.runningJobs} / {quota.max_concurrent_jobs} used
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                Daily GPU Quota
              </CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{quota.max_gpu_hours_per_day}h</div>
              <p className="text-xs text-muted-foreground">
                Per day limit
              </p>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 md:gap-8 lg:grid-cols-2 xl:grid-cols-3">
          <Card className="xl:col-span-2">
            <CardHeader className="flex flex-row items-center">
              <div className="grid gap-2">
                <CardTitle>Recent Jobs</CardTitle>
                <CardDescription>
                  Your latest job submissions
                </CardDescription>
              </div>
              <Button asChild size="sm" className="ml-auto gap-1">
                <a href="#">
                  View All
                  <ArrowUpRight className="h-4 w-4" />
                </a>
              </Button>
            </CardHeader>
            <CardContent>
              {jobs.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <p>No jobs yet. Submit your first job to get started!</p>
                </div>
              ) : (
                <div className="space-y-8">
                  {jobs.slice(0, 5).map((job: any) => {
                    const getStatusBadge = (status: string) => {
                      const statusMap: Record<string, { variant: any; label: string }> = {
                        'RUNNING': { variant: 'default', label: 'Running' },
                        'PENDING': { variant: 'outline', label: 'Pending' },
                        'QUEUED': { variant: 'outline', label: 'Queued' },
                        'SUCCEEDED': { variant: 'secondary', label: 'Completed' },
                        'COMPLETED': { variant: 'secondary', label: 'Completed' },
                        'FAILED': { variant: 'destructive', label: 'Failed' },
                        'CANCELLED': { variant: 'secondary', label: 'Cancelled' },
                      };
                      return statusMap[status] || { variant: 'outline', label: status };
                    };

                    const getTimeInfo = (job: any) => {
                      if (job.status === 'RUNNING' && job.started_at) {
                        const elapsed = Math.floor((Date.now() - new Date(job.started_at).getTime()) / 1000 / 60);
                        return `${elapsed}m elapsed`;
                      } else if (job.ended_at && job.started_at) {
                        const duration = Math.floor((new Date(job.ended_at).getTime() - new Date(job.started_at).getTime()) / 1000 / 60);
                        return `Completed in ${duration}m`;
                      } else if (job.status === 'PENDING' || job.status === 'QUEUED') {
                        return 'Waiting for resources';
                      }
                      return new Date(job.created_at).toLocaleString();
                    };

                    const badge = getStatusBadge(job.status);
                    
                    return (
                      <div key={job.job_id} className="flex items-center">
                        <div className="ml-4 space-y-1 flex-1">
                          <p className="text-sm font-medium leading-none">
                            {job.name}
                          </p>
                          <p className="text-sm text-muted-foreground">
                            {getTimeInfo(job)}
                          </p>
                        </div>
                        <Badge variant={badge.variant}>{badge.label}</Badge>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Resource Usage</CardTitle>
              <CardDescription>
                Your current quota consumption
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-8">
              <div className="space-y-2">
                <div className="flex items-center">
                  <div className="ml-4 space-y-1 flex-1">
                    <p className="text-sm font-medium leading-none">
                      Daily GPU Quota
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {quota.max_gpu_hours_per_day} hours per day
                    </p>
                  </div>
                  <div className="text-sm font-medium">
                    {quota.can_use_custom_docker ? 'Custom Docker ✓' : 'Standard'}
                  </div>
                </div>
              </div>
              <div className="space-y-2">
                <div className="flex items-center">
                  <div className="ml-4 space-y-1 flex-1">
                    <p className="text-sm font-medium leading-none">
                      Storage Limit
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {quota.max_storage_gb} GB available
                    </p>
                  </div>
                  <div className="text-sm font-medium">
                    {user.role === 'admin' ? 'Unlimited' : `${quota.max_storage_gb} GB`}
                  </div>
                </div>
              </div>
              <div className="space-y-2">
                <div className="flex items-center">
                  <div className="ml-4 space-y-1 flex-1">
                    <p className="text-sm font-medium leading-none">
                      Active Jobs
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {stats.runningJobs} / {quota.max_concurrent_jobs} concurrent
                    </p>
                  </div>
                  <div className="text-sm font-medium">
                    {Math.round((stats.runningJobs / quota.max_concurrent_jobs) * 100)}%
                  </div>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-primary" 
                    style={{ width: `${Math.min((stats.runningJobs / quota.max_concurrent_jobs) * 100, 100)}%` }} 
                  />
                </div>
              </div>
              <div className="space-y-2">
                <div className="flex items-center">
                  <div className="ml-4 space-y-1 flex-1">
                    <p className="text-sm font-medium leading-none">
                      Account Type
                    </p>
                    <p className="text-sm text-muted-foreground capitalize">
                      {user.role} • Priority: {quota.priority_weight}
                    </p>
                  </div>
                  <Badge variant={user.is_active ? 'default' : 'secondary'}>
                    {user.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}
