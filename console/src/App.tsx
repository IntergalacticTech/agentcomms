import { BrowserRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import LoginPage from "./auth/LoginPage";
import SignupPage from "./auth/SignupPage";
import VerifyPage from "./auth/VerifyPage";
import Layout from "./components/Layout";
import DashboardPage from "./pages/DashboardPage";
import InboxesPage from "./pages/InboxesPage";
import InboxDetailPage from "./pages/InboxDetailPage";
import MessagePage from "./pages/MessagePage";
import ApiKeysPage from "./pages/ApiKeysPage";
import DomainsPage from "./pages/DomainsPage";
import SettingsPage from "./pages/SettingsPage";

function PublicRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  if (isAuthenticated) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function LegacyInboxRedirect({ message }: { message?: boolean }) {
  const { id, mid } = useParams<{ id: string; mid: string }>();
  if (message && id && mid) return <Navigate to={`/agents/${id}/messages/${mid}`} replace />;
  if (id) return <Navigate to={`/agents/${id}`} replace />;
  return <Navigate to="/agents" replace />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicRoute>
            <LoginPage />
          </PublicRoute>
        }
      />
      <Route
        path="/signup"
        element={
          <PublicRoute>
            <SignupPage />
          </PublicRoute>
        }
      />
      <Route
        path="/verify"
        element={
          <PublicRoute>
            <VerifyPage />
          </PublicRoute>
        }
      />
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="agents" element={<InboxesPage />} />
        <Route path="agents/:id" element={<InboxDetailPage />} />
        <Route path="agents/:id/messages/:mid" element={<MessagePage />} />
        <Route path="inboxes" element={<LegacyInboxRedirect />} />
        <Route path="inboxes/:id" element={<LegacyInboxRedirect />} />
        <Route path="inboxes/:id/messages/:mid" element={<LegacyInboxRedirect message />} />
        <Route path="api-keys" element={<ApiKeysPage />} />
        <Route path="domains" element={<DomainsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
