import { useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
import { Route, Switch, Router as WouterRouter } from 'wouter';
import { StudyProvider } from '@/components/study/StudyProvider';

import Dashboard from './pages/dashboard/Dashboard';
import ProjectDetail from './pages/projects/ProjectDetail';
import ProjectSubmissions from './pages/projects/ProjectSubmissions';
import SubmissionDetail from './pages/projects/SubmissionDetail';
import DataExplorer from './pages/data/DataExplorer';
import Analytics from './pages/analytics/Analytics';
import AiInsights from './pages/ai/AiInsights';
import PromptTemplates from './pages/prompts/PromptTemplates';
import Reports from './pages/reports/Reports';
import ReportTemplates from './pages/reports/ReportTemplates';
import ReportExecutePreview from './pages/reports/ReportExecutePreview';
import ReportPreview from './pages/reports/ReportPreview';
import Settings from './pages/settings/Settings';
import DqaDashboard from './pages/dqa/DqaDashboard';
import RulePackEditor from './pages/dqa/RulePackEditor';
import TriangulationViewEditor from './pages/dqa/TriangulationViewEditor';
import Studies from './pages/studies/Studies';
import Portfolio from './pages/portfolio/Portfolio';
import Recordings from './pages/recordings/Recordings';
import RecordingDetail from './pages/recordings/RecordingDetail';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 5 * 60 * 1000,
    },
  },
});

/** Former Forms/Projects index → Dashboard; preserve ?study= and other params. */
function FormsIndexRedirect() {
  useEffect(() => {
    const search = window.location.search;
    const base = String(import.meta.env.BASE_URL || "/").replace(/\/$/, "");
    window.location.replace(`${base}/${search}`);
  }, []);
  return (
    <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
      Redirecting…
    </div>
  );
}

function Router() {
  return (
    <Switch>
      <Route path="/" component={Dashboard} />
      <Route path="/portfolio" component={Portfolio} />
      <Route path="/studies" component={Studies} />
      <Route path="/forms" component={FormsIndexRedirect} />
      <Route path="/forms/:id/submissions" component={ProjectSubmissions} />
      <Route path="/forms/:id/rules" component={RulePackEditor} />
      <Route path="/forms/:id" component={ProjectDetail} />
      {/* Legacy /projects URLs */}
      <Route path="/projects" component={FormsIndexRedirect} />
      <Route path="/projects/:id/submissions" component={ProjectSubmissions} />
      <Route path="/projects/:id/rules" component={RulePackEditor} />
      <Route path="/projects/:id" component={ProjectDetail} />
      <Route path="/submissions/:id" component={SubmissionDetail} />
      <Route path="/dqa" component={DqaDashboard} />
      <Route path="/studies/:studyId/triangulation" component={TriangulationViewEditor} />
      <Route path="/data" component={DataExplorer} />
      <Route path="/analytics" component={Analytics} />
      <Route path="/ai" component={AiInsights} />
      <Route path="/recordings/:id" component={RecordingDetail} />
      <Route path="/recordings" component={Recordings} />
      <Route path="/prompts" component={PromptTemplates} />
      <Route path="/reports/execute-preview" component={ReportExecutePreview} />
      <Route path="/reports/:reportId/preview" component={ReportPreview} />
      <Route path="/reports" component={Reports} />
      <Route path="/report-templates" component={ReportTemplates} />
      <Route path="/settings" component={Settings} />
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
          <StudyProvider>
            <Router />
            <Toaster />
          </StudyProvider>
        </WouterRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
