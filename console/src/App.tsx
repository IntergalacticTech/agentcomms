import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import LoginPage from "./auth/LoginPage";
import SignupPage from "./auth/SignupPage";
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
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="inboxes" element={<InboxesPage />} />
        <Route path="inboxes/:id" element={<InboxDetailPage />} />
        <Route path="inboxes/:id/messages/:mid" element={<MessagePage />} />
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
