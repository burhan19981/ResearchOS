import { QueryClientProvider } from "@tanstack/react-query";
import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { ProjectProvider } from "@/lib/ProjectContext";
import { queryClient } from "@/lib/queryClient";
import { AnalysisPage } from "@/features/analysis/AnalysisPage";
import { ApprovalsPage } from "@/features/approvals/ApprovalsPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { EvidencePage } from "@/features/literature/EvidencePage";
import { GapsPage } from "@/features/gaps/GapsPage";
import { NoveltyPage } from "@/features/novelty/NoveltyPage";
import { ExperimentDetailPage } from "@/features/experiments/ExperimentDetailPage";
import { ExperimentsPage } from "@/features/experiments/ExperimentsPage";
import { RunDetailPage } from "@/features/experiments/RunDetailPage";
import { NotFoundPage } from "@/features/misc/NotFoundPage";
import { OverviewPage } from "@/features/overview/OverviewPage";
import { PipelinePage } from "@/features/pipeline/PipelinePage";
import { PlanningPage } from "@/features/planning/PlanningPage";
import { ReviewsPage } from "@/features/reviews/ReviewsPage";

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ProjectProvider>
        <Router>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<AppShell />}>
              <Route index element={<OverviewPage />} />
              <Route path="projects/:projectId" element={<OverviewPage />} />
              <Route path="pipeline" element={<PipelinePage />} />
              <Route path="evidence" element={<EvidencePage />} />
              <Route path="evidence/gaps" element={<GapsPage />} />
              <Route path="evidence/novelty" element={<NoveltyPage />} />
              <Route path="planning" element={<PlanningPage />} />
              <Route path="experiments" element={<ExperimentsPage />} />
              <Route path="experiments/:experimentId" element={<ExperimentDetailPage />} />
              <Route path="experiments/runs/:runId" element={<RunDetailPage />} />
              <Route path="analysis" element={<AnalysisPage />} />
              <Route path="analysis/reviews" element={<ReviewsPage />} />
              <Route path="approvals" element={<ApprovalsPage />} />
              <Route path="audit" element={<AuditPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Router>
      </ProjectProvider>
    </QueryClientProvider>
  );
}

export default App;
