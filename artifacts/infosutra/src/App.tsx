import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
import { Route, Switch, Router as WouterRouter } from 'wouter';
import { StudyProvider } from '@/components/study/StudyProvider';

import Dashboard from './pages/dashboard/Dashboard';
import FormsPage from './pages/projects/Projects';
import ProjectDetail from './pages/projects/ProjectDetail';
import ProjectSubmissions from './pages/projects/ProjectSubmissions';
import SubmissionDetail from './pages/projects/SubmissionDetail';
import DataExplorer from './pages/data/DataExplorer';
import Analytics from './pages/analytics/Analytics';
import AiInsights from './pages/ai/AiInsights';
import PromptTemplates from './pages/prompts/PromptTemplates';
import Reports from './pages/reports/Reports';
import Settings from './pages/settings/Settings';
import DqaDashboard from './pages/dqa/DqaDashboard';
import RulePackEditor from './pages/dqa/RulePackEditor';
import TriangulationViewEditor from './pages/dqa/TriangulationViewEditor';
import Studies from './pages/studies/Studies';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 5 * 60 * 1000,
    },
  },
});

function Router() {
  return (
    <Switch>
      <Route path="/" component={Dashboard} />
      <Route path="/studies" component={Studies} />
      <Route path="/forms" component={FormsPage} />
      <Route path="/forms/:id/submissions" component={ProjectSubmissions} />
      <Route path="/forms/:id/rules" component={RulePackEditor} />
      <Route path="/forms/:id" component={ProjectDetail} />
      {/* Legacy /projects URLs redirect via same components */}
      <Route path="/projects" component={FormsPage} />
      <Route path="/projects/:id/submissions" component={ProjectSubmissions} />
      <Route path="/projects/:id/rules" component={RulePackEditor} />
      <Route path="/projects/:id" component={ProjectDetail} />
      <Route path="/submissions/:id" component={SubmissionDetail} />
      <Route path="/dqa" component={DqaDashboard} />
      <Route path="/studies/:studyId/triangulation" component={TriangulationViewEditor} />
      <Route path="/data" component={DataExplorer} />
      <Route path="/analytics" component={Analytics} />
      <Route path="/ai" component={AiInsights} />
      <Route path="/prompts" component={PromptTemplates} />
      <Route path="/reports" component={Reports} />
      <Route path="/settings" component={Settings} />
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <StudyProvider>
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
            <Router />
          </WouterRouter>
          <Toaster />
        </StudyProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
