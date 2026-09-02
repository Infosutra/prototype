import React, { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetInsightsQueryKey,
  useDeleteInsight,
  useGenerateInsight,
  useGetInsights,
  useGetProjects,
} from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  BrainCircuit,
  TrendingUp,
  AlertTriangle,
  Lightbulb,
  Sparkles,
  X,
} from "lucide-react";
import { useStudy } from "@/components/study/StudyProvider";
import { RequireActiveStudy } from "@/components/study/RequireActiveStudy";

function formatRelativeTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

export default function AiInsights() {
  const queryClient = useQueryClient();
  const { activeStudyId } = useStudy();
  const [question, setQuestion] = useState("");
  const [projectId, setProjectId] = useState<string>("all");
  const [feedback, setFeedback] = useState<string | null>(null);

  const projectsQuery = useGetProjects(
    activeStudyId ? { studyId: activeStudyId } : undefined,
    { query: { enabled: Boolean(activeStudyId) } as never },
  );
  const insightsQuery = useGetInsights(
    activeStudyId ? { studyId: activeStudyId } : undefined,
    { query: { enabled: Boolean(activeStudyId) } as never },
  );

  const generateInsight = useGenerateInsight({
    mutation: {
      onSuccess: async () => {
        setQuestion("");
        setFeedback(null);
        await queryClient.invalidateQueries({
          queryKey: getGetInsightsQueryKey(
            activeStudyId ? { studyId: activeStudyId } : undefined,
          ),
        });
      },
      onError: (err) => {
        setFeedback(err instanceof Error ? err.message : "Generation failed");
      },
    },
  });

  const deleteInsight = useDeleteInsight({
    mutation: {
      onSuccess: async () => {
        await queryClient.invalidateQueries({
          queryKey: getGetInsightsQueryKey(
            activeStudyId ? { studyId: activeStudyId } : undefined,
          ),
        });
      },
    },
  });

  const insights = insightsQuery.data ?? [];
  const projects = projectsQuery.data ?? [];

  const getIconForType = (type: string) => {
    switch (type) {
      case "anomaly":
        return <AlertTriangle className="w-5 h-5 text-destructive" />;
      case "trend":
        return <TrendingUp className="w-5 h-5 text-primary" />;
      case "recommendation":
        return <Lightbulb className="w-5 h-5 text-accent" />;
      default:
        return <BrainCircuit className="w-5 h-5 text-muted-foreground" />;
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case "critical":
        return "bg-red-100 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-400";
      case "warning":
        return "bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400";
      case "info":
        return "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400";
      default:
        return "bg-gray-100 text-gray-800 border-gray-200";
    }
  };

  const onGenerate = () => {
    if (!activeStudyId || !question.trim()) return;
    setFeedback(null);
    generateInsight.mutate({
      data: {
        question: question.trim(),
        studyId: activeStudyId,
        projectId: projectId === "all" ? null : projectId,
      },
    });
  };

  return (
    <Layout>
      <RequireActiveStudy
        title="Select a study"
        description="AI Insights are generated and stored for the active study."
      >
        <Header title="AI Insights" description="Ask questions about study data and review saved findings" />
        <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
          <Card className="mb-8 border-primary/20 bg-primary/5 dark:bg-primary/10 shadow-sm">
            <CardContent className="p-6">
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary shrink-0 mt-1">
                  <Sparkles className="w-5 h-5" />
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold mb-2">Generate Custom Insight</h3>
                  <p className="text-sm text-muted-foreground mb-4">
                    Ask a question about your data to generate a specific AI analysis. Uses the
                    OpenRouter settings from Settings → General.
                  </p>
                  <div className="flex flex-col sm:flex-row gap-3">
                    <Select value={projectId} onValueChange={setProjectId}>
                      <SelectTrigger className="w-full sm:w-[220px]">
                        <SelectValue placeholder="Target Project" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All forms in study</SelectItem>
                        {projects.map((project) => (
                          <SelectItem key={project.id} value={project.id}>
                            {project.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Input
                      placeholder="e.g. Are there GPS clusters that look suspicious?"
                      className="flex-1"
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") onGenerate();
                      }}
                    />
                    <Button
                      onClick={onGenerate}
                      disabled={generateInsight.isPending || !question.trim()}
                    >
                      {generateInsight.isPending ? (
                        <span className="animate-pulse">Analyzing…</span>
                      ) : (
                        "Analyze Data"
                      )}
                    </Button>
                  </div>
                  {feedback && (
                    <p className="mt-3 text-sm text-destructive">{feedback}</p>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-4">
              Saved findings
            </h2>
            {insightsQuery.isLoading && (
              <p className="text-sm text-muted-foreground">Loading insights…</p>
            )}
            {insightsQuery.error && (
              <p className="text-sm text-destructive">{insightsQuery.error.message}</p>
            )}
            {!insightsQuery.isLoading && insights.length === 0 && (
              <Card>
                <CardContent className="p-8 text-center text-sm text-muted-foreground">
                  No insights yet. Generate one above (AI must be enabled in Settings).
                </CardContent>
              </Card>
            )}
            {insights.map((insight) => (
              <Card key={insight.id} className="overflow-hidden hover:shadow-md transition-shadow">
                <div className="flex flex-col md:flex-row">
                  <div className="p-4 md:w-64 border-b md:border-b-0 md:border-r bg-muted/20 flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                      {getIconForType(insight.type)}
                      <span className="font-semibold capitalize text-sm">{insight.type}</span>
                    </div>
                    <Badge
                      variant="outline"
                      className={`w-fit uppercase text-[10px] tracking-wider ${getSeverityColor(insight.severity)}`}
                    >
                      {insight.severity}
                    </Badge>
                    <div className="text-xs text-muted-foreground mt-auto pt-4">
                      <div
                        className="font-medium text-foreground truncate"
                        title={insight.projectName ?? undefined}
                      >
                        {insight.projectName || "Study-wide"}
                      </div>
                      <div>{formatRelativeTime(insight.createdAt)}</div>
                    </div>
                  </div>

                  <div className="p-5 flex-1 flex flex-col">
                    <div className="flex justify-between items-start mb-2">
                      <h3 className="text-lg font-bold">{insight.title}</h3>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground -mt-1 -mr-1"
                        disabled={deleteInsight.isPending}
                        onClick={() =>
                          deleteInsight.mutate({ insightId: insight.id })
                        }
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    </div>
                    <p className="text-sm font-medium text-foreground mb-3">{insight.summary}</p>
                    <p className="text-sm text-muted-foreground leading-relaxed mb-4 whitespace-pre-wrap">
                      {insight.content}
                    </p>
                    <div className="flex flex-wrap gap-2 mt-auto">
                      {(insight.tags ?? []).map((tag) => (
                        <Badge
                          key={tag}
                          variant="secondary"
                          className="text-xs bg-secondary/10 text-secondary-foreground font-mono"
                        >
                          #{tag}
                        </Badge>
                      ))}
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>
      </RequireActiveStudy>
    </Layout>
  );
}
