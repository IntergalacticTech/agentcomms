import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { api } from "../api/client";

interface AuthState {
  idToken: string | null;
  refreshToken: string | null;
  email: string | null;
}

interface AuthContextValue {
  isAuthenticated: boolean;
  email: string | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (
    email: string,
    password: string,
    orgName: string
  ) => Promise<{ apiKey?: string }>;
  logout: () => void;
  loading: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

function loadAuth(): AuthState {
  try {
    const idToken = localStorage.getItem("fm_id_token");
    const refreshToken = localStorage.getItem("fm_refresh_token");
    const email = localStorage.getItem("fm_email");
    return { idToken, refreshToken, email };
  } catch {
    return { idToken: null, refreshToken: null, email: null };
  }
}

function saveAuth(state: AuthState) {
  if (state.idToken) {
    localStorage.setItem("fm_id_token", state.idToken);
  } else {
    localStorage.removeItem("fm_id_token");
  }
  if (state.refreshToken) {
    localStorage.setItem("fm_refresh_token", state.refreshToken);
  } else {
    localStorage.removeItem("fm_refresh_token");
  }
  if (state.email) {
    localStorage.setItem("fm_email", state.email);
  } else {
    localStorage.removeItem("fm_email");
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(loadAuth);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (auth.idToken) {
      api.setToken(auth.idToken);
    } else {
      api.clearToken();
    }
  }, [auth.idToken]);

  // Auto-refresh token every 45 minutes
  useEffect(() => {
    if (!auth.refreshToken) return;
    const interval = setInterval(async () => {
      try {
        const data = await fetch(
          `${import.meta.env.VITE_API_URL || "https://1h2sal7gf4.execute-api.us-east-1.amazonaws.com/v1"}/console/refresh`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: auth.refreshToken }),
          }
        ).then((r) => r.json());
        if (data.id_token) {
          const next = { ...auth, idToken: data.id_token };
          setAuth(next);
          saveAuth(next);
        }
      } catch {
        // Refresh failed, user will need to re-login
      }
    }, 45 * 60 * 1000);
    return () => clearInterval(interval);
  }, [auth]);

  const login = useCallback(async (email: string, password: string) => {
    setLoading(true);
    try {
      const data = await fetch(
        `${import.meta.env.VITE_API_URL || "https://1h2sal7gf4.execute-api.us-east-1.amazonaws.com/v1"}/console/login`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        }
      ).then((r) => {
        if (!r.ok) throw new Error(`Login failed: ${r.status}`);
        return r.json();
      });
      const state: AuthState = {
        idToken: data.id_token,
        refreshToken: data.refresh_token,
        email,
      };
      setAuth(state);
      saveAuth(state);
    } finally {
      setLoading(false);
    }
  }, []);

  const signup = useCallback(
    async (email: string, password: string, orgName: string) => {
      setLoading(true);
      try {
        const data = await fetch(
          `${import.meta.env.VITE_API_URL || "https://1h2sal7gf4.execute-api.us-east-1.amazonaws.com/v1"}/console/signup`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password, org_name: orgName }),
          }
        ).then((r) => {
          if (!r.ok) throw new Error(`Signup failed: ${r.status}`);
          return r.json();
        });
        return { apiKey: data.api_key };
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const logout = useCallback(() => {
    const empty: AuthState = {
      idToken: null,
      refreshToken: null,
      email: null,
    };
    setAuth(empty);
    saveAuth(empty);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated: !!auth.idToken,
        email: auth.email,
        login,
        signup,
        logout,
        loading,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
