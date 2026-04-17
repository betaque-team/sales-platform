import { Routes, Route } from "react-router-dom";
import { ProtectedRoute } from "./lib/auth";
import { Layout } from "./components/Layout";
import { DashboardPage } from "./pages/DashboardPage";
import { JobsPage } from "./pages/JobsPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { ReviewQueuePage } from "./pages/ReviewQueuePage";
import { CompaniesPage } from "./pages/CompaniesPage";
import { PipelinePage } from "./pages/PipelinePage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { LoginPage } from "./pages/LoginPage";
import { SettingsPage } from "./pages/SettingsPage";
import { PlatformsPage } from "./pages/PlatformsPage";
import { MonitoringPage } from "./pages/MonitoringPage";
import { ResumeScorePage } from "./pages/ResumeScorePage";
import { ApplicationsPage } from "./pages/ApplicationsPage";
import { AnswerBookPage } from "./pages/AnswerBookPage";
import { UserManagementPage } from "./pages/UserManagementPage";
import { RoleClustersPage } from "./pages/RoleClustersPage";
import { CredentialsPage } from "./pages/CredentialsPage";
import { CompanyDetailPage } from "./pages/CompanyDetailPage";
import { FeedbackPage } from "./pages/FeedbackPage";
import { DocsPage } from "./pages/DocsPage";
import { IntelligencePage } from "./pages/IntelligencePage";
import { InsightsPage } from "./pages/InsightsPage";

function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <Layout>{children}</Layout>
    </ProtectedRoute>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedLayout>
            <DashboardPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/jobs"
        element={
          <ProtectedLayout>
            <JobsPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/jobs/:id"
        element={
          <ProtectedLayout>
            <JobDetailPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/review"
        element={
          <ProtectedLayout>
            <ReviewQueuePage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/companies"
        element={
          <ProtectedLayout>
            <CompaniesPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/companies/:id"
        element={
          <ProtectedLayout>
            <CompanyDetailPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/pipeline"
        element={
          <ProtectedLayout>
            <PipelinePage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/platforms"
        element={
          <ProtectedLayout>
            <PlatformsPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/analytics"
        element={
          <ProtectedLayout>
            <AnalyticsPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/resume-score"
        element={
          <ProtectedLayout>
            <ResumeScorePage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/applications"
        element={
          <ProtectedLayout>
            <ApplicationsPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/answer-book"
        element={
          <ProtectedLayout>
            <AnswerBookPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/credentials"
        element={
          <ProtectedLayout>
            <CredentialsPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/monitoring"
        element={
          <ProtectedLayout>
            <MonitoringPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/settings"
        element={
          <ProtectedLayout>
            <SettingsPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/users"
        element={
          <ProtectedLayout>
            <UserManagementPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/role-clusters"
        element={
          <ProtectedLayout>
            <RoleClustersPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/feedback"
        element={
          <ProtectedLayout>
            <FeedbackPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/intelligence"
        element={
          <ProtectedLayout>
            <IntelligencePage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/insights"
        element={
          <ProtectedLayout>
            <InsightsPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/docs"
        element={
          <ProtectedLayout>
            <DocsPage />
          </ProtectedLayout>
        }
      />
    </Routes>
  );
}
