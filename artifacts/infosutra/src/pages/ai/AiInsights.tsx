import React, { useState } from "react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BrainCircuit, TrendingUp, AlertTriangle, Lightbulb, Sparkles, X } from "lucide-react";

const INSIGHTS = [
  {
    id: "ins-1",
    type: "anomaly",
    severity: "critical",
    title: "Suspicious coordinate clustering detected",
    projectName: "WASH Assessment 2024",
    summary: "42 submissions in the last 24 hours share identical GPS coordinates despite reporting different villages.",
    content: "Our AI analysis of spatial data indicates a high probability of enumerator stationary surveying (filling forms from a single location). The coordinates point to a location in central Garissa. Recommend immediate validation of submissions from enumerator IDs: field.agent2, field.agent4.",
    createdAt: "2 hours ago",
    tags: ["data-quality", "gps", "fraud-risk"]
  },
  {
    id: "ins-2",
    type: "trend",
    severity: "info",
    title: "Increasing wait times at water points",
    projectName: "WASH Assessment 2024",
    summary: "Average reported wait time has increased by 45% over the past 3 weeks.",
    content: "Longitudinal analysis of the 'wait_time_mins' field shows a steady upward trend. Week 1 avg: 15m. Week 3 avg: 22m. This correlates with the onset of the dry season. The trend is most pronounced in Turkana North.",
    createdAt: "1 day ago",
    tags: ["trend", "wash", "seasonality"]
  },
  {
    id: "ins-3",
    type: "recommendation",
    severity: "warning",
    title: "Form abandonment high on Section C",
    projectName: "Health Facility Mapping",
    summary: "Incomplete submissions frequently terminate at the 'Drug Inventory' section.",
    content: "We noticed a pattern where partial saves or abandoned forms stop at Section C. The matrix question format used for drug inventory might be too complex for mobile devices. Recommendation: Break the matrix into sequential single-select questions or provide additional enumerator training.",
    createdAt: "2 days ago",
    tags: ["form-design", "ux", "training"]
  }
];

export default function AiInsights() {
  const [isGenerating, setIsGenerating] = useState(false);

  const getIconForType = (type: string) => {
    switch (type) {
      case 'anomaly': return <AlertTriangle className="w-5 h-5 text-destructive" />;
      case 'trend': return <TrendingUp className="w-5 h-5 text-primary" />;
      case 'recommendation': return <Lightbulb className="w-5 h-5 text-accent" />;
      default: return <BrainCircuit className="w-5 h-5 text-muted-foreground" />;
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical': return "bg-red-100 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-400";
      case 'warning': return "bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400";
      case 'info': return "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400";
      default: return "bg-gray-100 text-gray-800 border-gray-200";
    }
  };

  return (
    <Layout>
      <Header 
        title="AI Insights" 
        description="Automated anomaly detection and data trends" 
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        
        {/* Generate Box */}
        <Card className="mb-8 border-primary/20 bg-primary/5 dark:bg-primary/10 shadow-sm">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary shrink-0 mt-1">
                <Sparkles className="w-5 h-5" />
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-semibold mb-2">Generate Custom Insight</h3>
                <p className="text-sm text-muted-foreground mb-4">Ask a question about your data to generate a specific AI analysis report.</p>
                <div className="flex gap-3">
                  <Select defaultValue="all">
                    <SelectTrigger className="w-[200px] bg-background">
                      <SelectValue placeholder="Target Project" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Projects</SelectItem>
                      <SelectItem value="p1">WASH Assessment 2024</SelectItem>
                      <SelectItem value="p2">Health Facility Mapping</SelectItem>
                    </SelectContent>
                  </Select>
                  <Input placeholder="e.g. Are there any discrepancies in the nutrition data reported in Garissa?" className="flex-1 bg-background" />
                  <Button 
                    onClick={() => { setIsGenerating(true); setTimeout(() => setIsGenerating(false), 2000); }} 
                    disabled={isGenerating}
                  >
                    {isGenerating ? <span className="animate-pulse">Analyzing...</span> : "Analyze Data"}
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Insights List */}
        <div className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-4">Recent Automated Findings</h2>
          {INSIGHTS.map(insight => (
            <Card key={insight.id} className="overflow-hidden hover:shadow-md transition-shadow">
              <div className="flex flex-col md:flex-row">
                <div className="p-4 md:w-64 border-b md:border-b-0 md:border-r bg-muted/20 flex flex-col gap-3">
                  <div className="flex items-center gap-2">
                    {getIconForType(insight.type)}
                    <span className="font-semibold capitalize text-sm">{insight.type}</span>
                  </div>
                  <Badge variant="outline" className={`w-fit uppercase text-[10px] tracking-wider ${getSeverityColor(insight.severity)}`}>
                    {insight.severity}
                  </Badge>
                  <div className="text-xs text-muted-foreground mt-auto pt-4">
                    <div className="font-medium text-foreground truncate" title={insight.projectName}>{insight.projectName}</div>
                    <div>{insight.createdAt}</div>
                  </div>
                </div>
                
                <div className="p-5 flex-1 flex flex-col">
                  <div className="flex justify-between items-start mb-2">
                    <h3 className="text-lg font-bold">{insight.title}</h3>
                    <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground -mt-1 -mr-1">
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                  <p className="text-sm font-medium text-foreground mb-3">{insight.summary}</p>
                  <p className="text-sm text-muted-foreground leading-relaxed mb-4">{insight.content}</p>
                  <div className="flex gap-2 mt-auto">
                    {insight.tags.map(tag => (
                      <Badge key={tag} variant="secondary" className="text-xs bg-secondary/10 text-secondary-foreground font-mono">
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
    </Layout>
  );
}
