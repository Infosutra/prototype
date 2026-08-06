import React from "react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Edit2, Trash2, Plus, MessageSquare } from "lucide-react";

const PROMPTS = [
  {
    id: "prm-1",
    name: "Executive Monthly Summary",
    category: "executive",
    description: "High-level summary of submissions, key findings, and bottlenecks for management.",
    content: "Act as a senior data analyst for an NGO. Summarize the dataset focusing on total submissions, completion rates, and any critical anomalies. Use a professional, executive tone. Keep it under 500 words.",
    updatedAt: "2024-05-10"
  },
  {
    id: "prm-2",
    name: "Donor Compliance Report",
    category: "donor",
    description: "Extracts indicators required for USAID/BHA compliance reporting.",
    content: "Review the provided data and extract the following indicators: 1) Total beneficiaries reached, 2) Disaggregation by gender and age, 3) Instances of service denial. Format as a strict data table followed by a brief narrative.",
    updatedAt: "2024-05-12"
  },
  {
    id: "prm-3",
    name: "Field Team Data Quality Feedback",
    category: "field",
    description: "Constructive feedback for enumerators based on form errors.",
    content: "Identify common data entry errors in the provided submissions (e.g., empty optional fields, GPS outliers, contradictory answers). Draft a supportive, clear email to the field enumerators outlining these issues and how to avoid them tomorrow.",
    updatedAt: "2024-05-14"
  }
];

export default function PromptTemplates() {
  return (
    <Layout>
      <Header 
        title="Prompt Templates" 
        description="Manage instructions used by AI to generate reports and insights"
        action={
          <Button size="sm" className="bg-primary text-primary-foreground">
            <Plus className="w-4 h-4 mr-2" />
            New Prompt
          </Button>
        }
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
          {PROMPTS.map(prompt => (
            <Card key={prompt.id} className="flex flex-col">
              <CardHeader className="pb-3 border-b">
                <div className="flex justify-between items-start mb-2">
                  <Badge variant="outline" className="uppercase text-[10px] tracking-wider bg-card text-muted-foreground">
                    {prompt.category}
                  </Badge>
                  <span className="text-xs font-mono text-muted-foreground">Updated: {prompt.updatedAt}</span>
                </div>
                <CardTitle className="text-lg flex items-center">
                  <MessageSquare className="w-4 h-4 mr-2 text-primary" />
                  {prompt.name}
                </CardTitle>
                <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{prompt.description}</p>
              </CardHeader>
              <CardContent className="p-4 flex-1 bg-muted/10">
                <div className="relative">
                  <div className="text-xs font-mono text-foreground/80 whitespace-pre-wrap bg-card border rounded p-3 h-32 overflow-y-auto">
                    {prompt.content}
                  </div>
                </div>
              </CardContent>
              <CardFooter className="p-3 border-t bg-card flex justify-end gap-2">
                <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-foreground">
                  <Edit2 className="w-4 h-4 mr-2" />
                  Edit
                </Button>
                <Button variant="ghost" size="sm" className="text-destructive hover:bg-destructive/10 hover:text-destructive">
                  <Trash2 className="w-4 h-4" />
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </div>
    </Layout>
  );
}
