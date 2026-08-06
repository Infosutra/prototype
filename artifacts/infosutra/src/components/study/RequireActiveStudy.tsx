import { Link } from "wouter";
import { Library } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useStudy } from "@/components/study/StudyProvider";

/** Gate study-scoped pages (DQA, Reports, etc.) until a workspace study is selected. */
export function RequireActiveStudy({
  children,
  title = "Select a study",
  description = "DQA, analytics, and reports run inside a study workspace. Create or select a study first.",
}: {
  children: ReactNode;
  title?: string;
  description?: string;
}) {
  const { activeStudy, studies, isLoading } = useStudy();

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-sm text-muted-foreground">
        Loading studies…
      </div>
    );
  }

  if (activeStudy) return <>{children}</>;

  return (
    <div className="flex-1 flex items-center justify-center p-6 bg-muted/30">
      <Card className="max-w-md w-full">
        <CardContent className="pt-8 pb-6 px-6 text-center space-y-4">
          <div className="mx-auto w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
            <Library className="w-5 h-5 text-primary" />
          </div>
          <div className="space-y-2">
            <h2 className="font-semibold text-lg">{title}</h2>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 justify-center">
            <Button asChild>
              <Link href="/studies">
                {studies.length === 0 ? "Create a study" : "Open Studies"}
              </Link>
            </Button>
            <Button variant="outline" asChild>
              <Link href="/forms">Sync forms</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
