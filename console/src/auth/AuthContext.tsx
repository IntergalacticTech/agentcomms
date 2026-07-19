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

const EMPTY_AUTH: AuthState = {
  idToken: null,
  refreshToken: null,
  email: null,
};

// SECURITY: auth tokens are intentionally held in memory only. Persisting the
// id/refresh token in localStorage (or sessionStorage) makes them readable by
// any script, so a single XSS becomes a full account takeover. The tradeoff is
// that a full page reload requires re-authentication. A durable session should
// be restored via an httpOnly, Secure, SameSite refresh cookie set by the
// backend — see the deferred note in the console security workstream.
//
// One-time migration: clear any tokens left in localStorage by older builds.
function purgeLegacyPersistedAuth() {
  try {
    localStorage.removeItem("fm_id_token");
    localStorage.removeItem("fm_refresh_token");
    localStorage.removeItem("fm_email");
  } catch {
    // Ignore storage access errors (e.g. privacy mode).
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(() => {
    purgeLegacyPersistedAuth();
    return EMPTY_AUTH;
  });
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
          `${import.meta.env.VITE_API_URL || "https://api.victorymail.dev/v1"}/console/refresh`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: auth.refreshToken }),
          }
        ).then((r) => r.json());
        if (data.id_token) {
          setAuth((prev) => ({ ...prev, idToken: data.id_token }));
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
      const loginResp = await fetch(
        `${import.meta.env.VITE_API_URL || "https://api.victorymail.dev/v1"}/console/login`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        }
      );
      const data = await loginResp.json();
      if (!loginResp.ok) {
        const msg = data?.error?.message || `Login failed (${loginResp.status})`;
        throw new Error(msg);
      }
      setAuth({
        idToken: data.id_token,
        refreshToken: data.refresh_token,
        email,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  const signup = useCallback(
    async (email: string, password: string, orgName: string) => {
      setLoading(true);
      try {
        const resp = await fetch(
          `${import.meta.env.VITE_API_URL || "https://api.victorymail.dev/v1"}/console/signup`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password, name: orgName }),
          }
        );
        const data = await resp.json();
        if (!resp.ok) {
          const msg = data?.error?.message || `Signup failed (${resp.status})`;
          throw new Error(msg);
        }
        return { apiKey: data.api_key };
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const logout = useCallback(() => {
    purgeLegacyPersistedAuth();
    setAuth(EMPTY_AUTH);
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
