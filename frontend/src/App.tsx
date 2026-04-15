import { App as AntdApp, Spin } from "antd";
import { ReactNode, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/Layout/AppLayout";
import AIPage from "./pages/AI";
import MAFBPage from "./pages/MAFB";
import ProfilePage from "./pages/Profile";
import CommunityPage from "./pages/Community";
import DashboardPage from "./pages/Dashboard";
import LoginPage from "./pages/Login";
import NotePage from "./pages/Note";
import TradePage from "./pages/Trade";
import FbtiTestPage from "./pages/FbtiTest";
import FbtiResultPage from "./pages/FbtiResult";
import AiFundPickPage from "./pages/AiFundPick";
import { postWarmFundCatalog } from "./services/agent";
import { fetchMe } from "./services/user";
import { useAppStore } from "./store/appStore";
import { useUserStore } from "./store/userStore";

function ProtectedLayout({ children }: { children: ReactNode }) {
  const token = useUserStore((state) => state.token);
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <AppLayout>{children}</AppLayout>;
}

export default function App() {
  const token = useUserStore((state) => state.token);
  const setAuth = useUserStore((state) => state.setAuth);
  const logout = useUserStore((state) => state.logout);
  const currentUser = useUserStore((state) => state.currentUser);
  const apiLoading = useAppStore((state) => state.loadingCount > 0);
  const [loading, setLoading] = useState(Boolean(token && !currentUser));

  useEffect(() => {
    if (!token || currentUser) return;
    void fetchMe()
      .then((user) => {
        setAuth({ access_token: token, token_type: "bearer", user });
        void postWarmFundCatalog().catch(() => {});
      })
      .catch(() => logout())
      .finally(() => setLoading(false));
  }, [token, currentUser, setAuth, logout]);

  if (loading) {
    return <Spin fullscreen />;
  }

  return (
    <AntdApp>
      <Spin spinning={apiLoading} fullscreen tip="加载中…" />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<ProtectedLayout><DashboardPage /></ProtectedLayout>} />
        <Route path="/trade" element={<ProtectedLayout><TradePage /></ProtectedLayout>} />
        <Route path="/note" element={<ProtectedLayout><NotePage /></ProtectedLayout>} />
        <Route path="/ai" element={<ProtectedLayout><AIPage /></ProtectedLayout>} />
        <Route path="/similar-funds" element={<Navigate to="/mafb" replace />} />
        <Route path="/mafb" element={<ProtectedLayout><MAFBPage /></ProtectedLayout>} />
        <Route path="/fbti" element={<Navigate to="/fbti-result" replace />} />
        <Route path="/fbti-test" element={<ProtectedLayout><FbtiTestPage /></ProtectedLayout>} />
        <Route path="/fbti-result" element={<ProtectedLayout><FbtiResultPage /></ProtectedLayout>} />
        <Route path="/ai-fund-pick" element={<ProtectedLayout><AiFundPickPage /></ProtectedLayout>} />
        <Route path="/profile" element={<ProtectedLayout><ProfilePage /></ProtectedLayout>} />
        <Route path="/community" element={<ProtectedLayout><CommunityPage /></ProtectedLayout>} />
        <Route path="*" element={<Navigate to={token ? "/" : "/login"} replace />} />
      </Routes>
    </AntdApp>
  );
}
