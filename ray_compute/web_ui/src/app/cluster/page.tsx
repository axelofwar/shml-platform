"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Cpu,
  HardDrive,
  Server,
  Activity,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  Monitor,
  ExternalLink,
  LogOut,
  Layers,
  Zap,
} from "lucide-react";
import { clusterApi, ClusterStatus, NodeInfo, GPUInfo, ResourceUsage, waitForAuth } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { Toaster } from "@/components/ui/toaster";

// GPU name to icon mapping for known GPUs
const GPU_COLORS: Record<string, string> = {
  "NVIDIA GeForce RTX 3090": "text-green-500",
  "NVIDIA GeForce RTX 2070": "text-blue-500",
};

export default function ClusterPage() {
  const { toast } = useToast();

  const [mounted, setMounted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [clusterStatus, setClusterStatus] = useState<ClusterStatus | null>(null);
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [gpus, setGPUs] = useState<GPUInfo[]>([]);
  const [resourceUsage, setResourceUsage] = useState<ResourceUsage | null>(null);
  const [actors, setActors] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (mounted) {
      fetchClusterData();

      // Auto-refresh every 10 seconds
      const interval = setInterval(() => {
        fetchClusterData(true);
      }, 10000);

      return () => clearInterval(interval);
    }
  }, [mounted]);

  const fetchClusterData = async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      else setRefreshing(true);
      setError(null);

      await waitForAuth();

      // Fetch all cluster data in parallel
      const [statusRes, nodesRes, gpusRes, resourceRes, actorsRes] = await Promise.allSettled([
        clusterApi.getStatus(),
        clusterApi.getNodes(),
        clusterApi.getGPUs(),
        clusterApi.getResourceUsage(),
        clusterApi.getActors(),
      ]);

      if (statusRes.status === 'fulfilled') {
        setClusterStatus(statusRes.value);
      }
      if (nodesRes.status === 'fulfilled') {
        setNodes(nodesRes.value.nodes);
      }
      if (gpusRes.status === 'fulfilled') {
        setGPUs(gpusRes.value.gpus);
      }
      if (resourceRes.status === 'fulfilled') {
        setResourceUsage(resourceRes.value);
      }
      if (actorsRes.status === 'fulfilled') {
        setActors(actorsRes.value.actors);
      }

      // Check if all failed
      const allFailed = [statusRes, nodesRes, gpusRes, resourceRes, actorsRes]
        .every(r => r.status === 'rejected');

      if (allFailed) {
        setError('Unable to connect to Ray cluster. Please check that the Ray head node is running.');
      }

    } catch (err: any) {
      console.error('Error fetching cluster data:', err);
      setError(err.message || 'Failed to fetch cluster data');
      if (!silent) {
        toast({
          variant: "destructive",
          title: "Error loading cluster data",
          description: err.message,
        });
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatGB = (gb: number) => {
    if (gb < 1) return `${(gb * 1024).toFixed(0)} MB`;
    return `${gb.toFixed(1)} GB`;
  };

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
          <a href="/ray/ui/jobs" className="text-muted-foreground transition-colors hover:text-foreground">
            Jobs
          </a>
          <a href="/ray/ui/cluster" className="text-foreground font-semibold">
            Cluster
          </a>
        </nav>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => window.open('/ray', '_blank')}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Ray Dashboard
          </Button>
          <Button variant="outline" size="sm" onClick={() => window.location.href = '/oauth2-proxy/sign_out?rd=/ray/ui'}>
            <LogOut className="mr-2 h-4 w-4" />
            Sign Out
          </Button>
        </div>
      </header>

      <main className="flex flex-1 flex-col gap-4 p-4 md:gap-8 md:p-8">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Cluster</h1>
            <p className="text-muted-foreground">
              Monitor Ray cluster resources and GPU utilization
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => fetchClusterData()}
              disabled={refreshing}
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Connection Error</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {loading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {[1, 2, 3, 4].map(i => (
              <Card key={i}>
                <CardHeader>
                  <Skeleton className="h-4 w-24" />
                </CardHeader>
                <CardContent>
                  <Skeleton className="h-8 w-16" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : clusterStatus ? (
          <>
            {/* Summary Cards */}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              {/* Cluster Status */}
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Cluster Status</CardTitle>
                  <Server className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                  <div className="flex items-center gap-2">
                    {clusterStatus.status === 'healthy' ? (
                      <CheckCircle className="h-5 w-5 text-green-500" />
                    ) : (
                      <AlertCircle className="h-5 w-5 text-yellow-500" />
                    )}
                    <span className="text-2xl font-bold capitalize">{clusterStatus.status}</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Ray {clusterStatus.ray_version} • {clusterStatus.active_nodes} node(s)
                  </p>
                </CardContent>
              </Card>

              {/* CPU Usage */}
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">CPU Usage</CardTitle>
                  <Cpu className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {clusterStatus.used_cpus.toFixed(1)} / {clusterStatus.total_cpus}
                  </div>
                  <Progress
                    value={(clusterStatus.used_cpus / clusterStatus.total_cpus) * 100}
                    className="mt-2"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    {((clusterStatus.used_cpus / clusterStatus.total_cpus) * 100).toFixed(0)}% utilized
                  </p>
                </CardContent>
              </Card>

              {/* GPU Usage */}
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">GPU Usage</CardTitle>
                  <Monitor className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {clusterStatus.used_gpus.toFixed(1)} / {clusterStatus.total_gpus}
                  </div>
                  <Progress
                    value={(clusterStatus.used_gpus / clusterStatus.total_gpus) * 100}
                    className="mt-2"
                    indicatorClassName="bg-green-500"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    {((clusterStatus.used_gpus / clusterStatus.total_gpus) * 100).toFixed(0)}% allocated
                  </p>
                </CardContent>
              </Card>

              {/* Memory Usage */}
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Memory</CardTitle>
                  <HardDrive className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {formatGB(clusterStatus.used_memory_gb)} / {formatGB(clusterStatus.total_memory_gb)}
                  </div>
                  <Progress
                    value={(clusterStatus.used_memory_gb / clusterStatus.total_memory_gb) * 100}
                    className="mt-2"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Object store: {formatGB(clusterStatus.object_store_used_gb)} / {formatGB(clusterStatus.object_store_memory_gb)}
                  </p>
                </CardContent>
              </Card>
            </div>

            {/* Detailed Views */}
            <Tabs defaultValue="gpus" className="space-y-4">
              <TabsList>
                <TabsTrigger value="gpus">
                  <Zap className="mr-2 h-4 w-4" />
                  GPUs
                </TabsTrigger>
                <TabsTrigger value="nodes">
                  <Server className="mr-2 h-4 w-4" />
                  Nodes
                </TabsTrigger>
                <TabsTrigger value="actors">
                  <Layers className="mr-2 h-4 w-4" />
                  Actors
                </TabsTrigger>
                <TabsTrigger value="resources">
                  <Activity className="mr-2 h-4 w-4" />
                  Resources
                </TabsTrigger>
              </TabsList>

              {/* GPUs Tab */}
              <TabsContent value="gpus">
                <div className="grid gap-4 md:grid-cols-2">
                  {gpus.length === 0 ? (
                    <Card className="col-span-2">
                      <CardContent className="flex flex-col items-center justify-center py-12">
                        <Monitor className="h-12 w-12 text-muted-foreground mb-4" />
                        <p className="text-muted-foreground">No GPU information available</p>
                      </CardContent>
                    </Card>
                  ) : (
                    gpus.map((gpu, index) => (
                      <Card key={`${gpu.node_id}-${gpu.index}`}>
                        <CardHeader>
                          <div className="flex items-center justify-between">
                            <div>
                              <CardTitle className={`text-lg ${GPU_COLORS[gpu.name] || ''}`}>
                                {gpu.name}
                              </CardTitle>
                              <CardDescription>
                                GPU {gpu.index} • {gpu.node_ip}
                              </CardDescription>
                            </div>
                            <Badge variant={gpu.utilization_percent > 80 ? "destructive" : "secondary"}>
                              {gpu.utilization_percent.toFixed(0)}% Util
                            </Badge>
                          </div>
                        </CardHeader>
                        <CardContent className="space-y-4">
                          {/* Memory */}
                          <div>
                            <div className="flex justify-between text-sm mb-1">
                              <span>Memory</span>
                              <span>
                                {(gpu.memory_used_mb / 1024).toFixed(1)} / {(gpu.memory_total_mb / 1024).toFixed(1)} GB
                              </span>
                            </div>
                            <Progress
                              value={(gpu.memory_used_mb / gpu.memory_total_mb) * 100}
                              indicatorClassName={
                                (gpu.memory_used_mb / gpu.memory_total_mb) > 0.9
                                  ? "bg-red-500"
                                  : "bg-green-500"
                              }
                            />
                          </div>

                          {/* Utilization */}
                          <div>
                            <div className="flex justify-between text-sm mb-1">
                              <span>Utilization</span>
                              <span>{gpu.utilization_percent.toFixed(0)}%</span>
                            </div>
                            <Progress
                              value={gpu.utilization_percent}
                              indicatorClassName={
                                gpu.utilization_percent > 80
                                  ? "bg-yellow-500"
                                  : "bg-blue-500"
                              }
                            />
                          </div>

                          {/* Temperature */}
                          {gpu.temperature_c !== undefined && gpu.temperature_c !== null && (
                            <div className="flex justify-between text-sm">
                              <span>Temperature</span>
                              <span className={
                                gpu.temperature_c > 80
                                  ? "text-red-500 font-semibold"
                                  : gpu.temperature_c > 70
                                    ? "text-yellow-500"
                                    : "text-green-500"
                              }>
                                {gpu.temperature_c}°C
                              </span>
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    ))
                  )}
                </div>

                {/* GPU Allocation Hint */}
                <Alert className="mt-4">
                  <Monitor className="h-4 w-4" />
                  <AlertTitle>GPU Allocation</AlertTitle>
                  <AlertDescription>
                    <ul className="list-disc list-inside mt-2 space-y-1 text-sm">
                      <li><strong>RTX 3090 (GPU 0)</strong>: Primary training GPU (24GB VRAM)</li>
                      <li><strong>RTX 2070 (GPU 1)</strong>: Inference / fallback (8GB VRAM)</li>
                    </ul>
                    <p className="mt-2 text-xs">
                      For detailed GPU metrics, see{" "}
                      <a href="/grafana" target="_blank" className="text-blue-500 hover:underline">
                        Grafana Dashboard
                      </a>
                    </p>
                  </AlertDescription>
                </Alert>
              </TabsContent>

              {/* Nodes Tab */}
              <TabsContent value="nodes">
                <div className="space-y-4">
                  {nodes.length === 0 ? (
                    <Card>
                      <CardContent className="flex flex-col items-center justify-center py-12">
                        <Server className="h-12 w-12 text-muted-foreground mb-4" />
                        <p className="text-muted-foreground">No node information available</p>
                      </CardContent>
                    </Card>
                  ) : (
                    nodes.map((node, index) => (
                      <Card key={node.node_id || index}>
                        <CardHeader>
                          <div className="flex items-center justify-between">
                            <div>
                              <CardTitle className="flex items-center gap-2">
                                {node.is_head && (
                                  <Badge variant="default">Head</Badge>
                                )}
                                {node.hostname || node.ip}
                              </CardTitle>
                              <CardDescription className="font-mono text-xs">
                                {node.node_id?.slice(0, 16)}... • {node.ip}
                              </CardDescription>
                            </div>
                            <Badge variant={node.state === 'ALIVE' ? "success" : "secondary"}>
                              {node.state}
                            </Badge>
                          </div>
                        </CardHeader>
                        <CardContent>
                          <div className="grid grid-cols-3 gap-4">
                            {/* CPU */}
                            <div>
                              <p className="text-sm font-medium">CPU</p>
                              <p className="text-2xl font-bold">{node.cpu?.toFixed(0) || 0}%</p>
                            </div>

                            {/* Memory */}
                            <div>
                              <p className="text-sm font-medium">Memory</p>
                              <p className="text-2xl font-bold">
                                {node.mem ? `${node.mem[2]?.toFixed(0) || 0}%` : 'N/A'}
                              </p>
                            </div>

                            {/* GPUs */}
                            <div>
                              <p className="text-sm font-medium">GPUs</p>
                              <p className="text-2xl font-bold">{node.gpus?.length || 0}</p>
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    ))
                  )}
                </div>
              </TabsContent>

              {/* Actors Tab */}
              <TabsContent value="actors">
                <Card>
                  <CardHeader>
                    <CardTitle>Ray Actors</CardTitle>
                    <CardDescription>
                      Active actors in the cluster
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {actors.length === 0 ? (
                      <div className="flex flex-col items-center justify-center py-12">
                        <Layers className="h-12 w-12 text-muted-foreground mb-4" />
                        <p className="text-muted-foreground">No active actors</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          Actors are created when jobs use Ray's actor API
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {actors.map((actor, index) => (
                          <div
                            key={actor.actor_id || index}
                            className="flex items-center justify-between p-3 bg-muted rounded-lg"
                          >
                            <div>
                              <p className="font-medium">{actor.class_name}</p>
                              <p className="text-xs text-muted-foreground font-mono">
                                {actor.actor_id?.slice(0, 16)}...
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <Badge variant={actor.state === 'ALIVE' ? "success" : "secondary"}>
                                {actor.state}
                              </Badge>
                              {actor.num_restarts > 0 && (
                                <Badge variant="outline">
                                  {actor.num_restarts} restarts
                                </Badge>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>

              {/* Resources Tab */}
              <TabsContent value="resources">
                <Card>
                  <CardHeader>
                    <CardTitle>Resource Allocation</CardTitle>
                    <CardDescription>
                      Detailed resource usage from Ray cluster
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {resourceUsage && resourceUsage.resources ? (
                      <div className="space-y-4">
                        {Object.entries(resourceUsage.resources).map(([key, value]) => (
                          <div key={key}>
                            <div className="flex justify-between text-sm mb-1">
                              <span className="font-medium">{key}</span>
                              <span>
                                {typeof value.used === 'number'
                                  ? value.used.toFixed(2)
                                  : value.used} / {typeof value.total === 'number'
                                    ? value.total.toFixed(2)
                                    : value.total}
                              </span>
                            </div>
                            <Progress value={value.percent} />
                            <p className="text-xs text-muted-foreground mt-1">
                              {value.percent.toFixed(1)}% used
                            </p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="flex flex-col items-center justify-center py-12">
                        <Activity className="h-12 w-12 text-muted-foreground mb-4" />
                        <p className="text-muted-foreground">No resource data available</p>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* External Links */}
                <div className="grid gap-4 md:grid-cols-2 mt-4">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">Ray Native Dashboard</CardTitle>
                      <CardDescription>
                        Full Ray dashboard with jobs, actors, and detailed metrics
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <Button
                        variant="outline"
                        className="w-full"
                        onClick={() => window.open('/ray', '_blank')}
                      >
                        <ExternalLink className="mr-2 h-4 w-4" />
                        Open Ray Dashboard
                      </Button>
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">Grafana Monitoring</CardTitle>
                      <CardDescription>
                        GPU metrics, system stats, and historical data
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <Button
                        variant="outline"
                        className="w-full"
                        onClick={() => window.open('/grafana', '_blank')}
                      >
                        <ExternalLink className="mr-2 h-4 w-4" />
                        Open Grafana
                      </Button>
                    </CardContent>
                  </Card>
                </div>
              </TabsContent>
            </Tabs>
          </>
        ) : (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Unable to load cluster data</AlertTitle>
            <AlertDescription>
              Please check that the Ray cluster is running and accessible.
            </AlertDescription>
          </Alert>
        )}
      </main>
    </div>
  );
}
