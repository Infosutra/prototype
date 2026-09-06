import React from "react";
import { Link } from "wouter";
import { useGetProject } from "@workspace/api-client-react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { SubmissionsGrid } from "./SubmissionsGrid";
import { useFormRouteId } from "@/lib/use-form-route-id";

export default function ProjectSubmissions() {
  const projectId = useFormRouteId("submissions");
  const projectQuery = useGetProject(projectId);

  return (
    <Layout>
      <Header
        title={projectQuery.data ? `${projectQuery.data.name} data` : "Submissions"}
        description="All forms in one table — coloured cells carry DQA flags"
        action={
          <Link href={`/forms/${projectId}`}>
            <Button variant="outline" size="sm">
              <ArrowLeft className="mr-2 h-4 w-4" />
              <span className="hidden sm:inline">Project details</span>
              <span className="sm:hidden">Project</span>
            </Button>
          </Link>
        }
      />
      <div className="flex-1 overflow-auto bg-muted/30 p-4 md:p-6">
        <SubmissionsGrid projectId={projectId} />
      </div>
    </Layout>
  );
}
