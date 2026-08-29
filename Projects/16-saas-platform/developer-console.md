# Developer Console Frontend Architecture

The Developer Console is the web dashboard for AgentMail -- the interface where developers sign up, create inboxes, configure custom domains, view messages, manage API keys, set up webhooks, monitor usage, and handle billing. It is a React single-page application that communicates exclusively with the same REST API (`https://api.agentmail.aws/v1/`) that customers use programmatically. There is no separate "admin API" -- the console is a first-class API client that authenticates via Cognito JWTs instead of API keys.

The console is hosted as a static SPA on CloudFront + S3 at `console.agentmail.dev`. It is entirely client-side rendered -- no server-side rendering, no Node.js backend, no BFF layer. This simplifies deployment, reduces operational surface area, and ensures the console scales effortlessly behind CloudFront's edge network.

---

## Table of Contents

- [1. Technology Stack](#1-technology-stack)
- [2. Authentication Flow](#2-authentication-flow)
- [3. Page Architecture](#3-page-architecture)
- [4. Key UI Components](#4-key-ui-components)
- [5. CloudFront + S3 Deployment](#5-cloudfront--s3-deployment)
- [6. API Integration Layer](#6-api-integration-layer)
- [7. Responsive Design](#7-responsive-design)
- [8. Security](#8-security)

---

## 1. Technology Stack

### Core Framework

| Technology | Version | Purpose |
|------------|---------|---------|
| **React** | 18.3+ | UI framework. Concurrent features enabled (Suspense, useTransition for route navigation). |
| **TypeScript** | 5.4+ | Strict mode, no `any` allowed in CI. All API responses typed with generated types from OpenAPI spec. |
| **Vite** | 5.x | Build tooling. Dev server with HMR, production builds with Rollup under the hood. |

### Routing

| Technology | Version | Purpose |
|------------|---------|---------|
| **TanStack Router** | 1.x | Type-safe, file-based routing. Route params, search params, and loader data are fully typed. |

TanStack Router is chosen over React Router for three reasons:

1. **Type-safe route params.** When navigating to `/dashboard/inboxes/:id`, the `id` param is typed as `string` in the route definition and enforced at the call site. This eliminates an entire class of runtime bugs where params are misspelled or missing.
2. **Built-in search param serialization.** URL search params (filters, pagination cursors) are declared in the route definition with Zod schemas and automatically serialized/deserialized. The URL is always the source of truth for list page state.
3. **File-based route generation.** Routes are defined by file system convention in `src/routes/`, and TanStack Router's CLI generates the route tree at build time. Adding a new page means creating a file -- no manual route registration.

### File-Based Route Structure

```
src/routes/
├── __root.tsx                          # Root layout (providers, error boundary)
├── _auth.tsx                           # Auth layout (sidebar, header -- wraps all /dashboard)
├── _auth/
│   ├── dashboard/
│   │   ├── index.tsx                   # /dashboard (home)
│   │   ├── inboxes/
│   │   │   ├── index.tsx               # /dashboard/inboxes (list)
│   │   │   ├── $inboxId.tsx            # /dashboard/inboxes/:inboxId (detail)
│   │   │   └── $inboxId/
│   │   │       └── messages/
│   │   │           └── $messageId.tsx  # /dashboard/inboxes/:inboxId/messages/:messageId
│   │   ├── domains/
│   │   │   ├── index.tsx               # /dashboard/domains (list)
│   │   │   └── $domainId.tsx           # /dashboard/domains/:domainId (detail)
│   │   ├── webhooks/
│   │   │   ├── index.tsx               # /dashboard/webhooks (list)
│   │   │   └── $webhookId.tsx          # /dashboard/webhooks/:webhookId (detail)
│   │   ├── api-keys/
│   │   │   └── index.tsx               # /dashboard/api-keys
│   │   ├── pods/
│   │   │   ├── index.tsx               # /dashboard/pods (list)
│   │   │   └── $podId.tsx              # /dashboard/pods/:podId (detail)
│   │   ├── usage/
│   │   │   └── index.tsx               # /dashboard/usage
│   │   ├── settings/
│   │   │   ├── index.tsx               # /dashboard/settings (profile)
│   │   │   └── billing.tsx             # /dashboard/settings/billing
│   │   └── docs/
│   │       └── index.tsx               # /dashboard/docs (embedded API reference)
├── login.tsx                           # /login (Cognito redirect)
├── signup.tsx                          # /signup (Cognito redirect)
└── index.tsx                           # / (redirect to /dashboard or /login)
```

### State Management

| Technology | Version | Purpose |
|------------|---------|---------|
| **TanStack Query** | 5.x | Server state management. All API data flows through Query -- caching, background refetching, optimistic updates, pagination. |
| **Zustand** | 4.x | Client-only state. Auth tokens, user preferences (dark mode, sidebar collapsed), transient UI state. |

**Why TanStack Query instead of Redux / SWR / custom hooks:**

- **Automatic cache invalidation.** When a user creates an inbox, the mutation's `onSuccess` invalidates the inbox list query, and the list automatically refetches. No manual cache management.
- **Optimistic updates.** Deleting an inbox removes it from the list immediately while the DELETE request is in flight. If the request fails, the cache rolls back.
- **Background refetching.** Stale data is shown immediately while fresh data loads in the background. The user never sees a loading spinner when navigating back to a previously visited page.
- **Request deduplication.** If two components both call `useInboxes()`, only one HTTP request fires.
- **Pagination support.** `useInfiniteQuery` handles cursor-based pagination with automatic page merging.

**Why Zustand instead of Context / Redux / Jotai:**

- **Minimal boilerplate.** A store is a single function call. No providers, no reducers, no action creators.
- **Works outside React.** The API client (a plain class) can read auth tokens from the Zustand store without being inside a React component tree. This is critical for interceptors that refresh tokens.
- **Selective subscriptions.** Components subscribe to specific store slices. Changing `sidebarCollapsed` does not re-render components that only read `accessToken`.

### UI Layer

| Technology | Version | Purpose |
|------------|---------|---------|
| **Tailwind CSS** | 3.4+ | Utility-first CSS. All styling is done via Tailwind classes -- no CSS modules, no styled-components, no CSS-in-JS. |
| **shadcn/ui** | Latest | Component library. Not an npm package -- components are copied into `src/components/ui/` and owned by the project. Based on Radix UI primitives. |
| **Radix UI** | 1.x | Accessible, unstyled primitives used by shadcn/ui. Dialog, Dropdown, Tooltip, Popover, Select, etc. |
| **TipTap** | 2.x | Rich text editor for email composition. Headless editor with custom Tailwind-styled UI. |
| **Recharts** | 2.x | Usage analytics charts. Line charts for email volume over time, bar charts for feature usage, area charts for storage consumption. |
| **Lucide React** | Latest | Icon library. Consistent with shadcn/ui's default icon set. |

### Build and Deployment

| Technology | Purpose |
|------------|---------|
| **Vite** | Dev server (port 5173), production build, environment variable injection (`import.meta.env`). |
| **pnpm** | Package manager. Strict dependency resolution, workspace support for potential monorepo. |
| **ESLint** | Linting. `@typescript-eslint/strict`, `eslint-plugin-react-hooks`, `eslint-plugin-tailwindcss`. |
| **Prettier** | Formatting. Tailwind class sorting via `prettier-plugin-tailwindcss`. |
| **Vitest** | Unit testing. Same config as Vite, runs in jsdom environment. |
| **Playwright** | E2E testing. Login flows, inbox creation, domain verification, billing upgrade. |
| **GitHub Actions** | CI/CD. Lint, type-check, test, build, deploy to S3, invalidate CloudFront. |

### Dependency Summary

```json
{
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "@tanstack/react-router": "^1.45.0",
    "@tanstack/react-query": "^5.50.0",
    "zustand": "^4.5.0",
    "recharts": "^2.12.0",
    "@tiptap/react": "^2.4.0",
    "@tiptap/starter-kit": "^2.4.0",
    "@tiptap/extension-link": "^2.4.0",
    "@tiptap/extension-image": "^2.4.0",
    "@tiptap/extension-placeholder": "^2.4.0",
    "@radix-ui/react-dialog": "^1.1.0",
    "@radix-ui/react-dropdown-menu": "^2.1.0",
    "@radix-ui/react-tooltip": "^1.1.0",
    "@radix-ui/react-select": "^2.1.0",
    "@radix-ui/react-tabs": "^1.1.0",
    "@radix-ui/react-toast": "^1.2.0",
    "lucide-react": "^0.400.0",
    "tailwind-merge": "^2.3.0",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.0",
    "zod": "^3.23.0",
    "dompurify": "^3.1.0",
    "date-fns": "^3.6.0"
  },
  "devDependencies": {
    "typescript": "^5.4.0",
    "vite": "^5.3.0",
    "@tanstack/router-vite-plugin": "^1.45.0",
    "@tanstack/router-devtools": "^1.45.0",
    "@tanstack/react-query-devtools": "^5.50.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "prettier-plugin-tailwindcss": "^0.6.0",
    "eslint": "^9.0.0",
    "@typescript-eslint/eslint-plugin": "^7.0.0",
    "vitest": "^1.6.0",
    "@testing-library/react": "^15.0.0",
    "jsdom": "^24.0.0",
    "playwright": "^1.44.0",
    "msw": "^2.3.0"
  }
}
```

### Vite Configuration

```typescript
// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { TanStackRouterVite } from '@tanstack/router-vite-plugin'
import path from 'path'

export default defineConfig({
  plugins: [
    react(),
    TanStackRouterVite(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    target: 'es2022',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom'],
          'vendor-router': ['@tanstack/react-router'],
          'vendor-query': ['@tanstack/react-query'],
          'vendor-editor': ['@tiptap/react', '@tiptap/starter-kit'],
          'vendor-charts': ['recharts'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'https://api.agentmail.aws',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '/v1'),
      },
    },
  },
})
```

### Environment Variables

```bash
# .env.development
VITE_API_BASE_URL=http://localhost:5173/api          # Proxied to API Gateway
VITE_COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
VITE_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
VITE_COGNITO_DOMAIN=auth.agentmail.dev
VITE_COGNITO_REDIRECT_URI=http://localhost:5173/auth/callback
VITE_STRIPE_PUBLISHABLE_KEY=pk_test_...
VITE_WEBSOCKET_URL=wss://ws.agentmail.aws/v1
VITE_DOCS_URL=https://docs.agentmail.dev

# .env.production
VITE_API_BASE_URL=https://api.agentmail.aws/v1
VITE_COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
VITE_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
VITE_COGNITO_DOMAIN=auth.agentmail.dev
VITE_COGNITO_REDIRECT_URI=https://console.agentmail.dev/auth/callback
VITE_STRIPE_PUBLISHABLE_KEY=pk_live_...
VITE_WEBSOCKET_URL=wss://ws.agentmail.aws/v1
VITE_DOCS_URL=https://docs.agentmail.dev
```

---

## 2. Authentication Flow

### Overview

The console authenticates users through AWS Cognito's Hosted UI. Cognito handles the entire identity management surface -- registration, login, password reset, MFA enrollment, and social provider federation (Google, GitHub). The console never touches raw passwords. It receives JWTs from Cognito and uses them to authenticate API requests.

### Auth Architecture

```
                 Console (React SPA)
                        │
          ┌─────────────┼──────────────┐
          │             │              │
     ┌────▼────┐  ┌─────▼─────┐  ┌────▼─────┐
     │ Cognito │  │  Zustand   │  │  API      │
     │ Hosted  │  │  Auth      │  │  Client   │
     │ UI      │  │  Store     │  │  (fetch)  │
     └────┬────┘  └─────┬─────┘  └────┬─────┘
          │             │              │
          │  tokens     │  Bearer JWT  │
          └─────────────┘──────────────┘
                        │
               API Gateway + Lambda Authorizer
```

### Cognito Hosted UI Configuration

The Cognito Hosted UI is accessed at `https://auth.agentmail.dev` (custom domain on the Cognito User Pool). The SPA never renders its own login form -- it redirects to the Hosted UI, which handles all identity provider flows and returns tokens via the authorization code grant (PKCE).

```
App Client Configuration:
  Client ID: xxxxxxxxxxxxxxxxxxxxxxxxxx
  Client Secret: None (public client -- SPA cannot keep secrets)
  Auth Flow: Authorization Code Grant with PKCE
  Allowed OAuth Flows: code
  Allowed OAuth Scopes: openid, email, profile
  Callback URLs:
    - https://console.agentmail.dev/auth/callback (production)
    - http://localhost:5173/auth/callback (development)
  Logout URLs:
    - https://console.agentmail.dev/login (production)
    - http://localhost:5173/login (development)
  Token Validity:
    - Access Token: 1 hour
    - ID Token: 1 hour
    - Refresh Token: 30 days
  Prevent User Existence Errors: Enabled
  Enable Token Revocation: Enabled
```

### Sign-Up Flow

```
1. User clicks "Sign Up" in console
   │
2. Console redirects to Cognito Hosted UI:
   GET https://auth.agentmail.dev/signup
     ?response_type=code
     &client_id={COGNITO_CLIENT_ID}
     &redirect_uri={CALLBACK_URL}
     &scope=openid+email+profile
     &code_challenge={PKCE_CHALLENGE}
     &code_challenge_method=S256
     &state={CSRF_STATE}
   │
3. User chooses sign-up method:
   ├── Email + Password: enter email, choose password (min 12 chars, upper+lower+number)
   │   │
   │   └── Cognito sends verification email
   │       │
   │       └── User clicks verification link → account confirmed
   │
   ├── Google: redirect to Google OAuth consent screen
   │   │
   │   └── Google returns to Cognito → account auto-confirmed
   │
   └── GitHub: redirect to GitHub OAuth authorization
       │
       └── GitHub returns to Cognito (via OIDC adapter Lambda) → account auto-confirmed
   │
4. Cognito redirects back to console callback URL:
   GET https://console.agentmail.dev/auth/callback
     ?code={AUTHORIZATION_CODE}
     &state={CSRF_STATE}
   │
5. Console exchanges authorization code for tokens:
   POST https://auth.agentmail.dev/oauth2/token
   Content-Type: application/x-www-form-urlencoded

   grant_type=authorization_code
   &code={AUTHORIZATION_CODE}
   &redirect_uri={CALLBACK_URL}
   &client_id={COGNITO_CLIENT_ID}
   &code_verifier={PKCE_VERIFIER}
   │
6. Cognito returns tokens:
   {
     "id_token": "eyJhbGci...",
     "access_token": "eyJhbGci...",
     "refresh_token": "eyJhbGci...",
     "expires_in": 3600,
     "token_type": "Bearer"
   }
   │
7. Console triggers Post-Authentication Lambda:
   (Cognito invokes this automatically on first login)
   │
   └── Lambda creates Organization record in DynamoDB:
       - org_id: new ULID
       - email: user's email
       - tier: "free"
       - billing_channel: "none"
       - Sets custom:org_id attribute on Cognito user
   │
8. Console stores tokens in Zustand auth store
   │
9. Console redirects to /dashboard
```

### Sign-In Flow

```
1. User clicks "Sign In" or visits protected route while unauthenticated
   │
2. Console redirects to Cognito Hosted UI:
   GET https://auth.agentmail.dev/login
     ?response_type=code
     &client_id={COGNITO_CLIENT_ID}
     &redirect_uri={CALLBACK_URL}
     &scope=openid+email+profile
     &code_challenge={PKCE_CHALLENGE}
     &code_challenge_method=S256
     &state={CSRF_STATE}
   │
3. User authenticates (email+password, Google, or GitHub)
   │
4. Cognito redirects back with authorization code
   │
5. Console exchanges code for tokens (same as sign-up step 5-6)
   │
6. Console stores tokens in Zustand auth store
   │
7. Console redirects to originally requested route (or /dashboard)
```

### Token Storage Strategy

Tokens are stored in the Zustand auth store, which lives in JavaScript memory. This means tokens are lost on page refresh. To handle this:

1. **On page load:** The console checks for a refresh token in an `httpOnly` cookie (`agentmail_refresh`). If present, it silently exchanges it for new access/ID tokens before rendering any protected route.
2. **After auth callback:** The access and ID tokens are stored in the Zustand store (memory). The refresh token is set as an `httpOnly`, `Secure`, `SameSite=Strict` cookie via a lightweight `/auth/set-cookie` CloudFront Function.
3. **On each API request:** The access token is read from the Zustand store and included as `Authorization: Bearer {access_token}`.

**Why not localStorage:**
- localStorage is accessible to any JavaScript running on the page, including injected scripts from browser extensions or XSS vulnerabilities.
- Access tokens in memory + refresh tokens in httpOnly cookies is the OWASP-recommended pattern for SPAs.

### Zustand Auth Store

```typescript
// src/stores/auth.ts
import { create } from 'zustand'
import { jwtDecode } from 'jwt-decode'

interface CognitoIdTokenClaims {
  sub: string
  email: string
  email_verified: boolean
  name?: string
  picture?: string
  'custom:org_id': string
  'custom:tier': string
  iss: string
  aud: string
  exp: number
  iat: number
  auth_time: number
}

interface AuthState {
  // Tokens
  accessToken: string | null
  idToken: string | null
  tokenExpiresAt: number | null

  // Derived user info (from ID token claims)
  user: {
    sub: string
    email: string
    name?: string
    picture?: string
    orgId: string
    tier: string
  } | null

  // State
  isAuthenticated: boolean
  isLoading: boolean
  refreshInProgress: boolean

  // Actions
  setTokens: (tokens: {
    accessToken: string
    idToken: string
    expiresIn: number
  }) => void
  clearAuth: () => void
  setLoading: (loading: boolean) => void
  setRefreshInProgress: (inProgress: boolean) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  idToken: null,
  tokenExpiresAt: null,
  user: null,
  isAuthenticated: false,
  isLoading: true, // true on initial load until refresh attempt completes
  refreshInProgress: false,

  setTokens: ({ accessToken, idToken, expiresIn }) => {
    const claims = jwtDecode<CognitoIdTokenClaims>(idToken)
    set({
      accessToken,
      idToken,
      tokenExpiresAt: Date.now() + expiresIn * 1000,
      user: {
        sub: claims.sub,
        email: claims.email,
        name: claims.name,
        picture: claims.picture,
        orgId: claims['custom:org_id'],
        tier: claims['custom:tier'],
      },
      isAuthenticated: true,
      isLoading: false,
    })
  },

  clearAuth: () => {
    set({
      accessToken: null,
      idToken: null,
      tokenExpiresAt: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
    })
  },

  setLoading: (loading) => set({ isLoading: loading }),
  setRefreshInProgress: (inProgress) =>
    set({ refreshInProgress: inProgress }),
}))
```

### Token Refresh

Silent token refresh happens proactively -- not reactively. A timer fires 5 minutes before the access token expires and exchanges the refresh token for new tokens. If the refresh fails (refresh token expired, user revoked), the user is redirected to login.

```typescript
// src/lib/auth/token-refresh.ts

const REFRESH_BUFFER_MS = 5 * 60 * 1000 // Refresh 5 minutes before expiry

let refreshTimer: ReturnType<typeof setTimeout> | null = null

export function scheduleTokenRefresh() {
  const { tokenExpiresAt } = useAuthStore.getState()
  if (!tokenExpiresAt) return

  if (refreshTimer) clearTimeout(refreshTimer)

  const refreshAt = tokenExpiresAt - REFRESH_BUFFER_MS
  const delay = Math.max(refreshAt - Date.now(), 0)

  refreshTimer = setTimeout(async () => {
    const store = useAuthStore.getState()
    if (store.refreshInProgress) return

    store.setRefreshInProgress(true)
    try {
      const response = await fetch(
        `https://${import.meta.env.VITE_COGNITO_DOMAIN}/oauth2/token`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({
            grant_type: 'refresh_token',
            client_id: import.meta.env.VITE_COGNITO_CLIENT_ID,
            refresh_token: getRefreshTokenFromCookie(),
          }),
          credentials: 'include',
        }
      )

      if (!response.ok) throw new Error('Token refresh failed')

      const data = await response.json()
      store.setTokens({
        accessToken: data.access_token,
        idToken: data.id_token,
        expiresIn: data.expires_in,
      })

      // Schedule next refresh
      scheduleTokenRefresh()
    } catch (error) {
      store.clearAuth()
      window.location.href = '/login'
    } finally {
      store.setRefreshInProgress(false)
    }
  }, delay)
}

function getRefreshTokenFromCookie(): string {
  // The refresh token is stored in an httpOnly cookie.
  // This function is called server-side by a CloudFront Function
  // that proxies the token exchange. The SPA itself never reads
  // the cookie directly -- it sends a request to /auth/refresh
  // which is a CloudFront Function that reads the cookie and
  // forwards it to Cognito's token endpoint.
  //
  // For the actual implementation, see the CloudFront Function
  // in the deployment section.
  throw new Error('Not called directly -- see /auth/refresh endpoint')
}
```

### Auth Refresh Endpoint (CloudFront Function)

Because the refresh token is stored in an `httpOnly` cookie that JavaScript cannot read, the SPA calls a CloudFront Function at `/auth/refresh` that reads the cookie and proxies the request to Cognito.

```javascript
// cloudfront-functions/auth-refresh.js
// CloudFront Function (ECMAScript 5.1, max 10KB)

function handler(event) {
  var request = event.request
  var cookies = request.cookies || {}
  var refreshToken = cookies['agentmail_refresh']
    ? cookies['agentmail_refresh'].value
    : null

  if (!refreshToken) {
    return {
      statusCode: 401,
      statusDescription: 'Unauthorized',
      body: { encoding: 'text', data: '{"error":"No refresh token"}' },
    }
  }

  // Forward to Cognito token endpoint
  // (This is handled by a CloudFront origin request policy
  // that routes /auth/refresh to the Cognito domain)
  request.headers['content-type'] = {
    value: 'application/x-www-form-urlencoded',
  }
  request.uri = '/oauth2/token'
  request.method = 'POST'
  request.body = {
    encoding: 'text',
    data:
      'grant_type=refresh_token' +
      '&client_id=' + COGNITO_CLIENT_ID +
      '&refresh_token=' + refreshToken,
  }

  return request
}
```

### Logout Flow

```
1. User clicks "Sign Out" in the console
   │
2. Console calls Cognito's revoke endpoint:
   POST https://auth.agentmail.dev/oauth2/revoke
   Content-Type: application/x-www-form-urlencoded

   token={REFRESH_TOKEN}
   &client_id={COGNITO_CLIENT_ID}
   │
3. Console clears the Zustand auth store:
   useAuthStore.getState().clearAuth()
   │
4. Console clears the refresh token cookie:
   document.cookie = 'agentmail_refresh=; Max-Age=0; Path=/; Secure; SameSite=Strict'
   │
5. Console redirects to Cognito's logout endpoint:
   GET https://auth.agentmail.dev/logout
     ?client_id={COGNITO_CLIENT_ID}
     &logout_uri=https://console.agentmail.dev/login
   │
6. Cognito clears its session cookies and redirects to /login
```

### Protected Route Guard

All `/dashboard` routes are wrapped in an auth layout component (`_auth.tsx`) that checks authentication state before rendering children.

```typescript
// src/routes/_auth.tsx
import { createFileRoute, Outlet, redirect } from '@tanstack/react-router'
import { useAuthStore } from '@/stores/auth'
import { AppShell } from '@/components/layout/AppShell'
import { FullPageSpinner } from '@/components/ui/spinner'

export const Route = createFileRoute('/_auth')({
  beforeLoad: async () => {
    const { isAuthenticated, isLoading } = useAuthStore.getState()

    // If still checking auth state (initial page load), wait
    if (isLoading) {
      await waitForAuthCheck()
    }

    if (!useAuthStore.getState().isAuthenticated) {
      throw redirect({
        to: '/login',
        search: {
          redirect: window.location.pathname,
        },
      })
    }
  },
  component: AuthLayout,
})

function AuthLayout() {
  const { isLoading } = useAuthStore()

  if (isLoading) {
    return <FullPageSpinner />
  }

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  )
}

async function waitForAuthCheck(): Promise<void> {
  return new Promise((resolve) => {
    const unsubscribe = useAuthStore.subscribe((state) => {
      if (!state.isLoading) {
        unsubscribe()
        resolve()
      }
    })
  })
}
```

### Auth Callback Handler

```typescript
// src/routes/auth/callback.tsx
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { useAuthStore } from '@/stores/auth'
import { exchangeCodeForTokens } from '@/lib/auth/cognito'
import { scheduleTokenRefresh } from '@/lib/auth/token-refresh'

export const Route = createFileRoute('/auth/callback')({
  validateSearch: (search: Record<string, unknown>) => ({
    code: search.code as string,
    state: search.state as string,
  }),
  component: AuthCallback,
})

function AuthCallback() {
  const { code, state } = Route.useSearch()
  const navigate = useNavigate()

  useEffect(() => {
    async function handleCallback() {
      // Verify CSRF state matches what we stored before redirect
      const savedState = sessionStorage.getItem('auth_csrf_state')
      if (state !== savedState) {
        console.error('CSRF state mismatch')
        navigate({ to: '/login' })
        return
      }
      sessionStorage.removeItem('auth_csrf_state')

      // Exchange authorization code for tokens
      const codeVerifier = sessionStorage.getItem('auth_pkce_verifier')
      if (!codeVerifier) {
        console.error('Missing PKCE verifier')
        navigate({ to: '/login' })
        return
      }
      sessionStorage.removeItem('auth_pkce_verifier')

      try {
        const tokens = await exchangeCodeForTokens(code, codeVerifier)
        useAuthStore.getState().setTokens(tokens)
        scheduleTokenRefresh()

        // Redirect to the page the user originally requested
        const redirectTo = sessionStorage.getItem('auth_redirect') || '/dashboard'
        sessionStorage.removeItem('auth_redirect')
        navigate({ to: redirectTo })
      } catch (error) {
        console.error('Token exchange failed:', error)
        navigate({ to: '/login' })
      }
    }

    handleCallback()
  }, [code, state, navigate])

  return <FullPageSpinner />
}
```

---

## 3. Page Architecture

### Route Map

| Route | Page | Description | Data Dependencies |
|-------|------|-------------|-------------------|
| `/` | Root | Redirects to `/dashboard` if authenticated, `/login` if not. | Auth state |
| `/login` | Login | Initiates Cognito Hosted UI redirect for sign-in. Shows "Sign In" button with Google/GitHub options as badges. | None |
| `/signup` | Sign Up | Initiates Cognito Hosted UI redirect for sign-up. Shows pricing tiers below the sign-up CTA. | None |
| `/auth/callback` | Auth Callback | Handles the Cognito redirect. Exchanges authorization code for tokens. Not user-visible. | URL search params (code, state) |
| `/dashboard` | Dashboard Home | Usage overview cards, quick actions (create inbox, add domain), onboarding checklist for new users, upgrade prompt for free tier. | `GET /organizations/me`, `POST /metrics/query` |
| `/dashboard/inboxes` | Inbox List | Paginated table of all inboxes across all pods. Search by address, filter by pod. Bulk actions (delete). "Create Inbox" button. | `GET /inboxes?limit=25` |
| `/dashboard/inboxes/:inboxId` | Inbox Detail | Message list for a single inbox. Thread view toggle. Compose button. Inbox settings (display name, auto-reply). | `GET /inboxes/:id`, `GET /inboxes/:id/messages` |
| `/dashboard/inboxes/:inboxId/messages/:messageId` | Message View | Full email display -- headers, HTML body (sandboxed), plain text fallback, attachment list with download links. Reply/forward actions. | `GET /inboxes/:id/messages/:mid` |
| `/dashboard/domains` | Domain List | All custom domains with verification status badges (pending, verified, failed). "Add Domain" button triggers the DomainOnboardingWizard. | `GET /domains` |
| `/dashboard/domains/:domainId` | Domain Detail | DNS records table with copy buttons. Verification progress indicator. "Re-verify" button. Domain settings (catch-all, default inbox). | `GET /domains/:id` |
| `/dashboard/webhooks` | Webhook List | All webhook endpoints with URL, event subscriptions, status (active, paused, failing). "Create Webhook" button. | `GET /webhooks` |
| `/dashboard/webhooks/:webhookId` | Webhook Detail | Webhook configuration form (URL, events, secret). Delivery log table. "Test Webhook" button sends a test event. | `GET /webhooks/:id`, delivery logs |
| `/dashboard/api-keys` | API Keys | List of all API keys with prefix, scope, created date, last used. "Generate Key" button. "Revoke" button per key. | `GET /api-keys` |
| `/dashboard/pods` | Pod List | List of pods with inbox count, message count, created date. Hidden on free tier (only one default pod). "Create Pod" button. | `GET /pods` |
| `/dashboard/pods/:podId` | Pod Detail | Pod settings, inbox list filtered to this pod, usage stats for this pod. | `GET /pods/:id`, `GET /inboxes?pod_id=:id` |
| `/dashboard/usage` | Usage & Analytics | Real-time usage meters (emails, inboxes, storage, AI features). Historical charts (30/60/90 day). Tier comparison with upgrade CTAs. | `GET /organizations/me`, `POST /metrics/query` |
| `/dashboard/settings` | Account Settings | Profile form (name, email -- read-only if social login). Password change (for email+password users). Organization name. | `GET /organizations/me` |
| `/dashboard/settings/billing` | Billing | Stripe Customer Portal embed via redirect. Current plan, next invoice date, payment method. Invoice history. | `GET /organizations/me`, Stripe Customer Portal URL |
| `/dashboard/docs` | API Documentation | Embedded Scalar/Redoc API reference generated from the OpenAPI spec. Searchable. Shows the user's actual API key prefix in examples (personalized). | OpenAPI spec (static asset) |

### Dashboard Home Page Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  Header: AgentMail logo │ Search (Cmd+K) │ Theme toggle │ Avatar │
├────────────┬─────────────────────────────────────────────────────┤
│            │                                                     │
│  Sidebar   │  Welcome back, {name}                               │
│            │                                                     │
│  Dashboard │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐  │
│  Inboxes   │  │  Emails     │ │  Inboxes    │ │  Storage    │  │
│  Domains   │  │  847/1,000  │ │  3/5        │ │  12MB/100MB │  │
│  Webhooks  │  │  ████████░░ │ │  ██████░░░░ │ │  █░░░░░░░░░ │  │
│  API Keys  │  │  84.7%      │ │  60%        │ │  12%        │  │
│  Pods      │  └─────────────┘ └─────────────┘ └─────────────┘  │
│  Usage     │                                                     │
│  Settings  │  ┌─────────────────────────────┐ ┌─────────────┐  │
│            │  │  Quick Actions              │ │  Activity   │  │
│  ───────── │  │  + Create Inbox             │ │  Feed       │  │
│  Docs      │  │  + Add Domain               │ │  (recent    │  │
│            │  │  + Generate API Key          │ │   events)   │  │
│            │  │  + Set Up Webhook            │ │             │  │
│            │  └─────────────────────────────┘ └─────────────┘  │
│            │                                                     │
│            │  ┌─────────────────────────────────────────────┐   │
│            │  │  Email Volume (Last 30 Days)                │   │
│            │  │  [LINE CHART: daily sent + received]        │   │
│            │  └─────────────────────────────────────────────┘   │
│            │                                                     │
│  ───────── │  ┌─────────────────────────────────────────────┐   │
│  Free Tier │  │  Onboarding Checklist (new users only)      │   │
│  Upgrade → │  │  ✓ Create account                           │   │
│            │  │  ✓ Get API key                               │   │
│            │  │  ○ Create first inbox                        │   │
│            │  │  ○ Send a test email                         │   │
│            │  │  ○ Set up a custom domain                    │   │
│            │  │  ○ Configure a webhook                       │   │
│            │  └─────────────────────────────────────────────┘   │
│            │                                                     │
└────────────┴─────────────────────────────────────────────────────┘
```

### Inbox Detail Page Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  Header                                                          │
├────────────┬─────────────────────────────────────────────────────┤
│            │                                                     │
│  Sidebar   │  ← Back to Inboxes                                 │
│            │                                                     │
│            │  agent-inbox-7kx3@mail.agentmail.dev                │
│            │  Pod: default │ Created: Apr 1, 2026                │
│            │                                                     │
│            │  [Compose] [Settings] [Delete]                      │
│            │                                                     │
│            │  ┌─────────────────────────────────────────────┐   │
│            │  │  Messages                          Search ▼ │   │
│            │  ├─────────────────────────────────────────────┤   │
│            │  │  ★ RE: Invoice #4521                        │   │
│            │  │    billing@acme.com → agent-inbox-7kx3      │   │
│            │  │    Apr 10, 2026 2:31 PM │ Thread (3)        │   │
│            │  ├─────────────────────────────────────────────┤   │
│            │  │  Welcome to AgentMail                        │   │
│            │  │    noreply@agentmail.dev → agent-inbox-7kx3 │   │
│            │  │    Apr 1, 2026 9:00 AM │ Single             │   │
│            │  ├─────────────────────────────────────────────┤   │
│            │  │  [Load more messages...]                     │   │
│            │  └─────────────────────────────────────────────┘   │
│            │                                                     │
└────────────┴─────────────────────────────────────────────────────┘
```

### Message View Page Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  Header                                                          │
├────────────┬─────────────────────────────────────────────────────┤
│            │                                                     │
│  Sidebar   │  ← Back to Inbox                                   │
│            │                                                     │
│            │  RE: Invoice #4521                                   │
│            │                                                     │
│            │  From: billing@acme.com                             │
│            │  To: agent-inbox-7kx3@mail.agentmail.dev            │
│            │  CC: finance@acme.com                               │
│            │  Date: April 10, 2026 2:31 PM UTC                   │
│            │  Message-ID: <abc123@acme.com>                      │
│            │                                                     │
│            │  [Reply] [Forward] [View Headers] [View Source]     │
│            │                                                     │
│            │  ┌─────────────────────────────────────────────┐   │
│            │  │                                             │   │
│            │  │  (Sandboxed iframe with email HTML body)    │   │
│            │  │                                             │   │
│            │  │  Hi,                                        │   │
│            │  │                                             │   │
│            │  │  Please find attached invoice #4521 for     │   │
│            │  │  the month of March 2026.                   │   │
│            │  │                                             │   │
│            │  └─────────────────────────────────────────────┘   │
│            │                                                     │
│            │  Attachments (1)                                    │
│            │  ┌────────────────────────────┐                    │
│            │  │ 📎 invoice-4521.pdf (142KB) │ [Download]        │
│            │  └────────────────────────────┘                    │
│            │                                                     │
│            │  ─── Thread (2 earlier messages) ──────────────    │
│            │  ▶ Original: Invoice #4521 (Apr 8, 2:00 PM)       │
│            │  ▶ RE: Invoice #4521 (Apr 9, 10:15 AM)            │
│            │                                                     │
└────────────┴─────────────────────────────────────────────────────┘
```

---

## 4. Key UI Components

### UsageMeter

A horizontal progress bar showing current consumption against the tier limit for a specific resource.

```typescript
// src/components/dashboard/UsageMeter.tsx

interface UsageMeterProps {
  /** Resource label displayed above the bar (e.g., "Emails this month") */
  label: string
  /** Current consumption count */
  current: number
  /** Maximum allowed by the current tier. -1 means unlimited. */
  limit: number
  /** Optional unit label (e.g., "emails", "MB", "inboxes") */
  unit?: string
  /** Whether to show the upgrade button when at >80% */
  showUpgrade?: boolean
  /** Callback when the "Upgrade" button is clicked */
  onUpgrade?: () => void
}

/**
 * Color logic:
 *   - Green (#22c55e):  usage < 60% of limit
 *   - Yellow (#eab308): usage >= 60% and < 80%
 *   - Red (#ef4444):    usage >= 80%
 *
 * When usage >= 100%, the bar is fully red and a pulsing "Limit Reached"
 * badge appears alongside the "Upgrade" button.
 *
 * When limit is -1 (unlimited), the bar shows a flat green fill at ~20%
 * with the text "Unlimited" instead of a count.
 *
 * The bar uses a CSS transition (300ms ease-out) for smooth animation
 * when the value updates.
 */
```

**Visual States:**

| Condition | Bar Color | Badge | Upgrade Button |
|-----------|-----------|-------|----------------|
| `current / limit < 0.6` | Green `bg-green-500` | None | Hidden |
| `current / limit >= 0.6 && < 0.8` | Yellow `bg-yellow-500` | "Approaching limit" (yellow) | Visible |
| `current / limit >= 0.8 && < 1.0` | Red `bg-red-500` | "Near limit" (red) | Visible, emphasized |
| `current / limit >= 1.0` | Red `bg-red-500` (full width, pulsing) | "Limit reached" (red, pulsing) | Visible, primary CTA |
| `limit === -1` | Green `bg-green-500` (20% width) | "Unlimited" (green) | Hidden |

### DnsRecordTable

Displays the DNS records a customer must create to verify their domain. Each record has a copy-to-clipboard button for the value, and a status indicator showing whether the record has been verified.

```typescript
// src/components/domains/DnsRecordTable.tsx

interface DnsRecord {
  /** Record type: TXT, MX, CNAME */
  type: 'TXT' | 'MX' | 'CNAME'
  /** DNS record name (e.g., "_dmarc.example.com") */
  name: string
  /** DNS record value (e.g., "v=DMARC1; p=none; ...") */
  value: string
  /** Priority (for MX records only) */
  priority?: number
  /** Verification status */
  status: 'pending' | 'verified' | 'failed'
  /** When the record was last checked */
  lastCheckedAt?: string
}

interface DnsRecordTableProps {
  /** List of DNS records to display */
  records: DnsRecord[]
  /** Domain name (shown in the header) */
  domain: string
  /** Whether a DNS check is currently in progress */
  isChecking: boolean
  /** Callback when "Check DNS" is clicked */
  onCheckDns: () => void
}

/**
 * Table columns:
 *   Type | Name | Value | Priority | Status
 *
 * The Name and Value columns use monospace font (font-mono) for readability.
 * Long values (DKIM keys) are truncated with an ellipsis and expand on click.
 *
 * Copy button behavior:
 *   - Clipboard icon button next to each Name and Value cell
 *   - On click: copies full value to clipboard, shows "Copied!" toast (2s)
 *   - Uses navigator.clipboard.writeText with a fallback for older browsers
 *
 * Status badges:
 *   - Pending: gray badge with clock icon
 *   - Verified: green badge with checkmark icon
 *   - Failed: red badge with X icon, tooltip shows "Record not found or incorrect"
 *
 * "Check DNS" button:
 *   - Calls POST /v1/domains/:id/verify
 *   - Shows spinner while checking
 *   - Disabled for 30 seconds after last check (rate limited)
 *   - After check completes, the status badges update automatically via cache invalidation
 *
 * DNS provider hint:
 *   Below the table, a collapsible section shows provider-specific instructions
 *   based on the domain registrar detected from WHOIS (if available) or a
 *   dropdown selector: Cloudflare, GoDaddy, Namecheap, Route 53, Google Domains, Other
 */
```

### InboxComposer

A full email composition form with rich text editing, recipient management, and attachment uploads.

```typescript
// src/components/inboxes/InboxComposer.tsx

interface InboxComposerProps {
  /** The inbox to send from */
  inboxId: string
  /** The inbox email address (shown in the "From" field, read-only) */
  fromAddress: string
  /** Pre-filled recipient (for replies) */
  defaultTo?: string
  /** Pre-filled subject (for replies) */
  defaultSubject?: string
  /** Pre-filled body (for replies -- quoted text) */
  defaultBody?: string
  /** Whether this is a reply (determines "Send" vs "Reply" button label) */
  isReply?: boolean
  /** Thread ID to attach this message to (for replies) */
  threadId?: string
  /** In-Reply-To header value (for replies) */
  inReplyTo?: string
  /** Callback when the email is sent successfully */
  onSent?: (messageId: string) => void
  /** Callback when the composer is dismissed */
  onCancel?: () => void
}

/**
 * Layout:
 *   ┌──────────────────────────────────────────────────────┐
 *   │ From: agent-inbox-7kx3@mail.agentmail.dev (read-only)│
 *   ├──────────────────────────────────────────────────────┤
 *   │ To:   [tag input with email validation]              │
 *   │ CC:   [tag input] (collapsed by default, toggle)     │
 *   │ BCC:  [tag input] (collapsed by default, toggle)     │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Subject: [text input]                                │
 *   ├──────────────────────────────────────────────────────┤
 *   │                                                      │
 *   │ [TipTap rich text editor]                            │
 *   │ Toolbar: Bold | Italic | Link | Bullet List |       │
 *   │          Numbered List | Code | Quote                │
 *   │                                                      │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Attachments: [drag-drop zone or file picker]         │
 *   │   📎 report.pdf (2.1 MB) [x]                        │
 *   ├──────────────────────────────────────────────────────┤
 *   │                          [Cancel]  [Send / Reply]    │
 *   └──────────────────────────────────────────────────────┘
 *
 * Rich text editor:
 *   - TipTap with StarterKit (bold, italic, lists, code, blockquote)
 *   - Link extension with URL validation
 *   - Placeholder extension ("Write your message...")
 *   - On submit: HTML body from editor.getHTML(), plain text from editor.getText()
 *   - Keyboard shortcut: Cmd+Enter (Mac) / Ctrl+Enter (Windows) to send
 *
 * Recipient input:
 *   - Tag-style input: type email address, press Enter/Tab/comma to add
 *   - Validates email format on add (Zod z.string().email())
 *   - Backspace removes last tag
 *   - Paste a comma-separated list of emails to add multiple at once
 *
 * Attachment upload:
 *   - Drag-and-drop zone (visible when dragging over composer)
 *   - File picker button (fallback)
 *   - Upload flow:
 *     1. POST /v1/inboxes/:id/attachments/presign → returns S3 presigned PUT URL
 *     2. PUT to presigned URL with file content
 *     3. Attachment metadata (key, filename, size, content_type) stored in form state
 *     4. On send, attachment references included in the POST /v1/inboxes/:id/messages body
 *   - Max file size: 25 MB (validated client-side)
 *   - Max total attachments: 10 files
 *   - Progress bar per file during upload
 *
 * Send action:
 *   POST /v1/inboxes/:inboxId/messages
 *   {
 *     "to": [{ "email": "...", "name": "..." }],
 *     "cc": [...],
 *     "bcc": [...],
 *     "subject": "...",
 *     "body_html": "<p>...</p>",
 *     "body_text": "...",
 *     "attachments": [{ "key": "...", "filename": "...", "size": 123, "content_type": "..." }],
 *     "thread_id": "..." (if reply),
 *     "in_reply_to": "..." (if reply)
 *   }
 *
 * Validation (Zod):
 *   - At least one recipient in "to"
 *   - Subject required (non-empty string)
 *   - Body required (non-empty HTML or plain text)
 *   - All email addresses pass z.string().email()
 */
```

### MessageViewer

Renders an email message safely, including HTML bodies, headers, and attachment links.

```typescript
// src/components/messages/MessageViewer.tsx

interface MessageViewerProps {
  /** Full message object from the API */
  message: {
    id: string
    from: { email: string; name?: string }
    to: Array<{ email: string; name?: string }>
    cc?: Array<{ email: string; name?: string }>
    subject: string
    body_html?: string
    body_text?: string
    attachments: Array<{
      id: string
      filename: string
      size: number
      content_type: string
      download_url: string
    }>
    headers: Record<string, string>
    created_at: string
    thread_id?: string
  }
  /** Whether to show the full header block or compact headers */
  showFullHeaders?: boolean
  /** Callback when "Reply" is clicked */
  onReply?: () => void
  /** Callback when "Forward" is clicked */
  onForward?: () => void
}

/**
 * HTML body rendering:
 *   The email HTML body is rendered in a sandboxed iframe to prevent XSS
 *   and style leakage. The approach:
 *
 *   1. Create an iframe with sandbox="allow-same-origin" (no scripts, no forms,
 *      no popups, no top-level navigation).
 *   2. Use DOMPurify to sanitize the HTML before injecting it:
 *      - ALLOWED_TAGS: standard HTML elements (p, div, span, a, img, table, tr, td, etc.)
 *      - FORBID_TAGS: script, style, form, iframe, object, embed
 *      - ALLOWED_ATTR: href, src, alt, class, style (inline styles allowed for email formatting)
 *      - ADD_ATTR: target="_blank" on all <a> tags (opens in new tab)
 *      - FORBID_ATTR: on* event handlers
 *   3. Inject a base <style> block that:
 *      - Sets max-width: 100% on images to prevent horizontal overflow
 *      - Sets default font to system-ui for consistency
 *      - Applies dark mode styles if the user has dark mode enabled
 *   4. The iframe auto-resizes to fit its content height (via postMessage
 *      from an injected resize observer script -- the only script allowed).
 *
 *   Fallback: if body_html is not available, render body_text in a <pre>
 *   block with white-space: pre-wrap.
 *
 * Full headers toggle:
 *   - Compact view (default): From, To, CC, Subject, Date
 *   - Full view: all raw headers in a scrollable monospace block
 *   - "View Source" button: opens the raw MIME source in a new tab
 *     (fetches from GET /v1/inboxes/:id/messages/:mid/source)
 *
 * Attachment list:
 *   - Each attachment shows filename, human-readable size, and content type icon
 *   - Click triggers download via the presigned download_url
 *   - Image attachments (.png, .jpg, .gif) show inline previews (thumbnail)
 *   - PDF attachments show a preview icon
 */
```

### ThreadView

Displays a chain of messages in a thread with collapsible quoted content.

```typescript
// src/components/messages/ThreadView.tsx

interface ThreadViewProps {
  /** Thread ID */
  threadId: string
  /** Inbox ID (for fetching thread messages) */
  inboxId: string
}

/**
 * Fetches all messages in the thread:
 *   GET /v1/inboxes/:inboxId/threads/:threadId/messages?ascending=true
 *
 * Layout:
 *   Messages are displayed in chronological order (oldest first).
 *   The most recent message is fully expanded. Earlier messages are
 *   collapsed by default, showing only:
 *     - From address
 *     - Date
 *     - First line of plain text (truncated to 120 chars)
 *   Click to expand any collapsed message.
 *
 * Quoted reply detection:
 *   When a message body contains quoted text (lines starting with ">",
 *   or content after "On {date}, {name} wrote:"), the quoted portion
 *   is collapsed behind a "Show quoted text" toggle (three dots icon).
 *   This prevents the thread view from being dominated by repeated
 *   quoted content.
 *
 * Thread header:
 *   Shows the thread subject (from the first message), total message
 *   count, and participants list (unique from/to addresses).
 *
 * Auto-scroll:
 *   On initial load, the view scrolls to the most recent (last) message.
 */
```

### WebhookDeliveryLog

Displays the history of webhook delivery attempts with status, timing, and expandable request/response bodies.

```typescript
// src/components/webhooks/WebhookDeliveryLog.tsx

interface WebhookDelivery {
  id: string
  timestamp: string
  event_type: string
  status_code: number | null  // null if connection failed
  response_time_ms: number | null
  retry_count: number
  success: boolean
  request_body: string   // JSON string of the event payload
  response_body: string  // First 10KB of the response
  error_message?: string // Network error message if connection failed
}

interface WebhookDeliveryLogProps {
  /** Webhook endpoint ID */
  webhookId: string
  /** Number of deliveries to show per page */
  pageSize?: number  // default: 20
}

/**
 * Table columns:
 *   Timestamp | Event Type | Status | Response Time | Retries | Actions
 *
 * Status column:
 *   - 2xx: green badge "200 OK"
 *   - 3xx: yellow badge "301 Redirect"
 *   - 4xx: orange badge "400 Bad Request"
 *   - 5xx: red badge "500 Error"
 *   - null (connection failed): red badge "Failed" with tooltip showing error_message
 *
 * Response time column:
 *   - <200ms: green text
 *   - 200-1000ms: yellow text
 *   - >1000ms: red text
 *
 * Retry count:
 *   - 0: hidden
 *   - 1-3: shown as "Retry 1/3", "Retry 2/3", "Retry 3/3"
 *   - Background color intensifies with retry count
 *
 * Expandable row:
 *   Click a row to expand it, showing:
 *   - Request body (JSON, syntax highlighted with Shiki or a lightweight highlighter)
 *   - Response body (truncated to 10KB, with "Full response truncated" note if larger)
 *   - Request headers (content-type, x-agentmail-signature, x-agentmail-delivery-id)
 *   - Response headers
 *
 * "Test Webhook" button (in the parent WebhookDetail page, not in this component):
 *   Sends POST /v1/webhooks/:id/test, which delivers a test event to the endpoint.
 *   The delivery appears in this log immediately (via query invalidation after mutation).
 *
 * Pagination:
 *   Cursor-based, using TanStack Query's useInfiniteQuery.
 *   "Load more" button at the bottom.
 */
```

### ApiKeyCard

Displays a single API key with its metadata and action buttons.

```typescript
// src/components/api-keys/ApiKeyCard.tsx

interface ApiKeyCardProps {
  apiKey: {
    id: string
    name: string
    prefix: string      // e.g., "ak_live_7kB3"
    scope: 'org' | 'pod' | 'inbox'
    scope_resource_id?: string
    environment: 'live' | 'test'
    status: 'active' | 'revoked'
    last_used_at: string | null
    created_at: string
    expires_at: string | null
  }
  /** If this key was just created, the full plaintext key is passed here
   *  for one-time display. It is stored in sessionStorage temporarily
   *  and cleared on page navigation. */
  plaintextKey?: string
  /** Callback when the "Revoke" button is confirmed */
  onRevoke: (keyId: string) => void
}

/**
 * Card layout:
 *   ┌────────────────────────────────────────────────────┐
 *   │  🔑 Production Key                     [Revoke]   │
 *   │                                                    │
 *   │  Key:     ak_live_7kB3••••••••••••••    [Reveal]  │
 *   │  Scope:   Organization                             │
 *   │  Created: April 1, 2026                            │
 *   │  Last used: 2 hours ago                            │
 *   │  Expires: Never                                    │
 *   │                                                    │
 *   │  [live] badge (green) or [test] badge (yellow)     │
 *   └────────────────────────────────────────────────────┘
 *
 * Key display:
 *   - By default, shows prefix + dots: "ak_live_7kB3••••••••••••••"
 *   - "Reveal" button: only available if plaintextKey is provided
 *     (i.e., the key was just created in this session).
 *     On click, shows the full key and changes button to "Copy".
 *     The key is stored in sessionStorage under `apikey:{id}`.
 *   - After navigating away and coming back, "Reveal" is disabled
 *     with tooltip: "Full key was only shown at creation time"
 *   - "Copy" button: copies the full key to clipboard, shows checkmark
 *     for 2 seconds
 *
 * Revoke confirmation:
 *   - "Revoke" button opens a Dialog (Radix UI Dialog)
 *   - Dialog shows: "Are you sure you want to revoke {name}?"
 *   - Warning text: "This action cannot be undone. Any applications using
 *     this key will immediately lose access."
 *   - Requires typing the key prefix ("ak_live_7kB3") to confirm
 *   - "Revoke Key" button (destructive variant, red)
 *   - Calls DELETE /v1/api-keys/:id
 *   - On success: invalidates api-keys query, shows success toast
 *
 * Status:
 *   - Active keys show a green dot indicator
 *   - Revoked keys show a red dot indicator and are grayed out
 *   - Expired keys show an orange dot indicator with "Expired" text
 */
```

### TierComparisonTable

Side-by-side comparison of all available tiers with feature checkmarks and upgrade CTAs.

```typescript
// src/components/billing/TierComparisonTable.tsx

interface TierComparisonTableProps {
  /** The user's current tier (highlighted column) */
  currentTier: 'free' | 'pro' | 'business' | 'scale' | 'enterprise'
  /** Callback when an "Upgrade" button is clicked */
  onUpgrade: (targetTier: string) => void
  /** Whether to show annual pricing toggle */
  showAnnualToggle?: boolean  // default: true
}

/**
 * Table layout:
 *   ┌──────────────────┬─────────┬────────┬──────────┬─────────┬────────────┐
 *   │                  │  Free   │  Pro   │ Business │  Scale  │ Enterprise │
 *   │                  │  $0/mo  │ $29/mo │  $99/mo  │ $299/mo │  Custom    │
 *   ├──────────────────┼─────────┼────────┼──────────┼─────────┼────────────┤
 *   │ Inboxes          │    5    │   25   │   100    │   500   │  Custom    │
 *   │ Emails/month     │  1,000  │ 10,000 │  50,000  │ 200,000 │  Custom    │
 *   │ Custom domains   │    1    │    3   │    10    │ Unlim.  │  Unlim.    │
 *   │ API rate limit   │  5/sec  │ 50/sec │  200/sec │ 500/sec │  Custom    │
 *   │ Webhooks         │    3    │   10   │    25    │   100   │  Unlim.    │
 *   │ WebSocket conns  │    1    │    5   │    25    │   100   │  Custom    │
 *   │ Storage          │ 100 MB  │  1 GB  │  10 GB   │ 100 GB  │  Custom    │
 *   │ Pods             │    1    │    3   │    10    │ Unlim.  │  Unlim.    │
 *   │ API keys         │    1    │    5   │    25    │ Unlim.  │  Unlim.    │
 *   ├──────────────────┼─────────┼────────┼──────────┼─────────┼────────────┤
 *   │ REST API         │    ✓    │   ✓    │    ✓     │    ✓    │     ✓      │
 *   │ MCP Server       │    ✓    │   ✓    │    ✓     │    ✓    │     ✓      │
 *   │ Webhooks         │    ✓    │   ✓    │    ✓     │    ✓    │     ✓      │
 *   │ OTP Extraction   │    ✓    │   ✓    │    ✓     │    ✓    │     ✓      │
 *   │ Semantic Search  │    ✗    │   ✓    │    ✓     │    ✓    │     ✓      │
 *   │ AI Categorize    │    ✗    │   ✓    │    ✓     │    ✓    │     ✓      │
 *   │ AI Extract       │    ✗    │   ✓    │    ✓     │    ✓    │     ✓      │
 *   │ IMAP/SMTP        │    ✗    │   ✗    │    ✓     │    ✓    │     ✓      │
 *   │ Audit Logs       │    ✗    │   ✗    │    ✗     │  Basic  │    Full    │
 *   │ SSO/SAML         │    ✗    │   ✗    │    ✗     │    ✗    │     ✓      │
 *   │ Dedicated IPs    │    ✗    │   ✗    │    ✗     │ Add-on  │  Included  │
 *   ├──────────────────┼─────────┼────────┼──────────┼─────────┼────────────┤
 *   │ SLA              │  None   │ 99.5%  │  99.9%   │ 99.95%  │ Custom     │
 *   │ Support          │ 48h     │ 24h    │  4h      │  1h     │ Dedicated  │
 *   │ Retention        │ 30 days │ 90 days│ 365 days │ Config  │ Config     │
 *   ├──────────────────┼─────────┼────────┼──────────┼─────────┼────────────┤
 *   │                  │ Current │Upgrade │ Upgrade  │ Upgrade │Contact Us  │
 *   └──────────────────┴─────────┴────────┴──────────┴─────────┴────────────┘
 *
 * Pricing toggle:
 *   When showAnnualToggle is true, a "Monthly / Annual (save 20%)" toggle
 *   appears above the table. Annual prices: Pro $23.20/mo, Business $79.20/mo,
 *   Scale $239.20/mo (billed annually).
 *
 * Current tier highlighting:
 *   The column for the user's current tier has a highlighted header with
 *   "Current Plan" badge and a subtle blue border. The upgrade button
 *   in that column is replaced with "Current Plan" text.
 *
 * Upgrade buttons:
 *   - Tiers above current: "Upgrade" button (primary variant)
 *   - Tiers below current: "Downgrade" text (muted, links to billing settings)
 *   - Enterprise column: "Contact Sales" button (opens mailto or HubSpot form)
 *
 * Upgrade flow:
 *   1. User clicks "Upgrade" on a tier
 *   2. If upgrading from Free → Paid: redirect to Stripe Checkout via
 *      POST /v1/billing/checkout-session (returns Stripe checkout URL)
 *   3. If upgrading between paid tiers: redirect to Stripe Customer Portal
 *      via POST /v1/billing/portal-session (Stripe handles proration)
 */
```

### DomainOnboardingWizard

A multi-step wizard that guides users through adding and verifying a custom domain.

```typescript
// src/components/domains/DomainOnboardingWizard.tsx

interface DomainOnboardingWizardProps {
  /** Callback when the wizard completes (domain verified, first inbox created) */
  onComplete: (domainId: string) => void
  /** Callback when the wizard is dismissed */
  onCancel: () => void
}

/**
 * Step 1: Choose Domain
 *   ┌───────────────────────────────────────────────────┐
 *   │  Add Custom Domain                        Step 1/5│
 *   │                                                   │
 *   │  Domain name:                                     │
 *   │  [________________________________]               │
 *   │                                                   │
 *   │  Do you already receive email on this domain?     │
 *   │  ( ) No -- this is a new domain or not used for   │
 *   │      email yet                                    │
 *   │  ( ) Yes -- I use Google Workspace                │
 *   │  ( ) Yes -- I use Microsoft 365                   │
 *   │  ( ) Yes -- I use another email provider          │
 *   │                                                   │
 *   │                          [Cancel]  [Next →]       │
 *   └───────────────────────────────────────────────────┘
 *
 * Step 2: Choose Approach (shown only if existing provider selected)
 *   ┌───────────────────────────────────────────────────┐
 *   │  Email Routing Strategy                   Step 2/5│
 *   │                                                   │
 *   │  How should AgentMail coexist with {provider}?    │
 *   │                                                   │
 *   │  ┌─────────────────────────────────────────────┐  │
 *   │  │ 🔀 Subdomain Routing (Recommended)          │  │
 *   │  │ Use a subdomain like mail.example.com for   │  │
 *   │  │ AgentMail inboxes. Your existing email on   │  │
 *   │  │ example.com continues working unchanged.    │  │
 *   │  │ Best for: Most users. Zero risk to existing │  │
 *   │  │ email.                                      │  │
 *   │  └─────────────────────────────────────────────┘  │
 *   │                                                   │
 *   │  ┌─────────────────────────────────────────────┐  │
 *   │  │ 📨 Transport Rule Routing (Advanced)        │  │
 *   │  │ Route specific addresses from {provider} to │  │
 *   │  │ AgentMail via transport rules. Both systems  │  │
 *   │  │ share the same domain.                       │  │
 *   │  │ Best for: Users who need agent@example.com   │  │
 *   │  │ addresses (no subdomain).                    │  │
 *   │  └─────────────────────────────────────────────┘  │
 *   │                                                   │
 *   │  ┌─────────────────────────────────────────────┐  │
 *   │  │ 📤 Outbound Only                            │  │
 *   │  │ Send emails from example.com via AgentMail  │  │
 *   │  │ but do not receive inbound email through    │  │
 *   │  │ AgentMail. No MX record changes needed.     │  │
 *   │  │ Best for: Notification senders, no-reply.   │  │
 *   │  └─────────────────────────────────────────────┘  │
 *   │                                                   │
 *   │                       [← Back]  [Next →]          │
 *   └───────────────────────────────────────────────────┘
 *
 * Step 3: DNS Records
 *   Shows the DnsRecordTable component with all required records.
 *   The records differ based on the approach chosen in step 2:
 *
 *   Standalone (no provider):
 *     - MX record: 10 inbound-smtp.us-east-1.amazonaws.com
 *     - TXT record: domain verification token
 *     - TXT record: SPF (v=spf1 include:amazonses.com ~all)
 *     - CNAME records: DKIM (3 records)
 *     - TXT record: DMARC (v=DMARC1; p=none; ...)
 *
 *   Subdomain (e.g., mail.example.com):
 *     - MX record on subdomain: 10 inbound-smtp.us-east-1.amazonaws.com
 *     - TXT record on subdomain: verification token
 *     - TXT record on subdomain: SPF
 *     - CNAME records on subdomain: DKIM (3 records)
 *     - TXT record on subdomain: DMARC
 *
 *   Transport rule:
 *     - TXT record: domain verification token
 *     - TXT record: SPF (add include:amazonses.com to existing SPF)
 *     - CNAME records: DKIM (3 records)
 *     - Provider-specific transport rule instructions
 *
 *   Outbound only:
 *     - TXT record: domain verification token
 *     - TXT record: SPF (add include:amazonses.com to existing SPF)
 *     - CNAME records: DKIM (3 records)
 *     - No MX record change
 *
 *   "I've added the DNS records" button to proceed.
 *
 * Step 4: Verify Domain
 *   Shows a loading state while calling POST /v1/domains/:id/verify.
 *   If verification succeeds: green checkmark, proceed to step 5.
 *   If verification fails: shows which records are missing/incorrect
 *   with specific guidance ("TXT record not found on _agentmail.example.com").
 *   "Check Again" button with 30-second cooldown.
 *   "I'll verify later" link to skip (domain stays in pending state).
 *
 *   Note: DNS propagation can take up to 48 hours. The console shows
 *   estimated propagation time based on the detected registrar.
 *   A background job checks verification every 15 minutes for pending
 *   domains and sends an email notification when verified.
 *
 * Step 5: Create First Inbox
 *   ┌───────────────────────────────────────────────────┐
 *   │  Create Your First Inbox              Step 5/5    │
 *   │                                                   │
 *   │  ✅ Domain verified: mail.example.com              │
 *   │                                                   │
 *   │  Inbox address:                                   │
 *   │  [agent-1_______]@mail.example.com                │
 *   │                                                   │
 *   │  Display name (optional):                         │
 *   │  [________________________________]               │
 *   │                                                   │
 *   │                       [Skip]  [Create Inbox]      │
 *   └───────────────────────────────────────────────────┘
 *
 *   Calls POST /v1/inboxes with the chosen address and domain.
 *   On success: closes wizard, navigates to the new inbox page.
 */
```

### MarketplaceMigrationBanner

A promotional banner shown to Scale tier users encouraging them to migrate to AWS Marketplace for enterprise features and pricing.

```typescript
// src/components/billing/MarketplaceMigrationBanner.tsx

interface MarketplaceMigrationBannerProps {
  /** Current monthly spend (for showing potential savings) */
  currentMonthlySpend: number
  /** Whether the banner has been dismissed (stored in localStorage) */
  dismissed?: boolean
  /** Callback when "Contact Sales" is clicked */
  onContactSales: () => void
  /** Callback when "Learn More" is clicked */
  onLearnMore: () => void
  /** Callback when the dismiss button is clicked */
  onDismiss: () => void
}

/**
 * Banner layout:
 *   ┌────────────────────────────────────────────────────────────────┐
 *   │  🏢 Ready to scale further?                             [×]  │
 *   │                                                               │
 *   │  Upgrade to Enterprise via AWS Marketplace for:               │
 *   │  • Consolidated billing with existing AWS spend               │
 *   │  • Apply AWS EDP credits to AgentMail                         │
 *   │  • Custom contracts and volume discounts                      │
 *   │  • SSO/SAML, full audit logs, dedicated infrastructure        │
 *   │  • 99.99% SLA with dedicated support engineer                 │
 *   │  • Zero-downtime migration -- all data stays intact           │
 *   │                                                               │
 *   │  [Contact Sales]  [Learn More]                                │
 *   └────────────────────────────────────────────────────────────────┘
 *
 * Visibility logic:
 *   - Only shown when user.tier === 'scale'
 *   - Hidden if dismissed (persisted in localStorage key 'marketplace_banner_dismissed')
 *   - Re-shown after 30 days if dismissed
 *   - Also shown on the /dashboard/usage page as a subtle inline card
 *
 * "Contact Sales" action:
 *   Opens a mailto link to sales@agentmail.dev with pre-filled subject
 *   "Enterprise Inquiry - {org_name}" or opens an embedded HubSpot form.
 *
 * "Learn More" action:
 *   Opens /docs/enterprise or a dedicated landing page explaining the
 *   Marketplace offering.
 */
```

---

## 5. CloudFront + S3 Deployment

### S3 Bucket Configuration

```json
{
  "BucketName": "agentmail-console-production",
  "BucketPolicy": "Private (no public access)",
  "Versioning": "Enabled",
  "Encryption": "AES-256 (SSE-S3)",
  "LifecycleRules": [
    {
      "Id": "expire-old-versions",
      "Status": "Enabled",
      "NoncurrentVersionExpiration": {
        "NoncurrentDays": 30
      }
    }
  ],
  "Tags": {
    "Project": "agentmail",
    "Component": "console",
    "Environment": "production"
  }
}
```

Bucket naming convention per environment:
- Production: `agentmail-console-production`
- Staging: `agentmail-console-staging`
- Development: `agentmail-console-dev`

No public access is configured on any bucket. All access flows through CloudFront using Origin Access Control (OAC).

### CloudFront Distribution

```json
{
  "DistributionConfig": {
    "Comment": "AgentMail Developer Console",
    "Enabled": true,
    "HttpVersion": "http2and3",
    "PriceClass": "PriceClass_100",
    "DefaultRootObject": "index.html",

    "Aliases": ["console.agentmail.dev"],

    "ViewerCertificate": {
      "AcmCertificateArn": "arn:aws:acm:us-east-1:ACCOUNT:certificate/CERT-ID",
      "SslSupportMethod": "sni-only",
      "MinimumProtocolVersion": "TLSv1.2_2021"
    },

    "Origins": [
      {
        "Id": "S3-console",
        "DomainName": "agentmail-console-production.s3.us-east-1.amazonaws.com",
        "S3OriginConfig": {},
        "OriginAccessControlId": "OAC-ID"
      }
    ],

    "DefaultCacheBehavior": {
      "TargetOriginId": "S3-console",
      "ViewerProtocolPolicy": "redirect-to-https",
      "AllowedMethods": ["GET", "HEAD", "OPTIONS"],
      "CachedMethods": ["GET", "HEAD"],
      "Compress": true,
      "CachePolicyId": "CUSTOM-SPA-CACHE-POLICY",
      "ResponseHeadersPolicyId": "CUSTOM-SECURITY-HEADERS",
      "FunctionAssociations": [
        {
          "EventType": "viewer-request",
          "FunctionARN": "arn:aws:cloudfront::ACCOUNT:function/spa-rewrite"
        }
      ]
    },

    "CacheBehaviors": [
      {
        "PathPattern": "/assets/*",
        "TargetOriginId": "S3-console",
        "ViewerProtocolPolicy": "redirect-to-https",
        "CachePolicyId": "IMMUTABLE-ASSETS-CACHE-POLICY",
        "Compress": true
      }
    ],

    "CustomErrorResponses": [
      {
        "ErrorCode": 403,
        "ResponseCode": 200,
        "ResponsePagePath": "/index.html",
        "ErrorCachingMinTTL": 0
      },
      {
        "ErrorCode": 404,
        "ResponseCode": 200,
        "ResponsePagePath": "/index.html",
        "ErrorCachingMinTTL": 0
      }
    ]
  }
}
```

### Origin Access Control (OAC)

CloudFront uses OAC (not the legacy OAI) to authenticate requests to S3. The S3 bucket policy grants access only to the CloudFront distribution's service principal.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowCloudFrontOAC",
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudfront.amazonaws.com"
      },
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::agentmail-console-production/*",
      "Condition": {
        "StringEquals": {
          "AWS:SourceArn": "arn:aws:cloudfront::ACCOUNT:distribution/DIST-ID"
        }
      }
    }
  ]
}
```

### CloudFront Function: SPA Routing

All requests that are not for static assets (JS, CSS, images, fonts) are rewritten to `/index.html` so the SPA router handles them.

```javascript
// cloudfront-functions/spa-rewrite.js

function handler(event) {
  var request = event.request
  var uri = request.uri

  // If the URI has a file extension, serve the file directly
  if (uri.match(/\.\w{2,4}$/)) {
    return request
  }

  // Otherwise, rewrite to index.html for SPA routing
  request.uri = '/index.html'
  return request
}
```

### Cache Policies

**Default cache policy (index.html and HTML routes):**

```json
{
  "Name": "agentmail-console-spa",
  "DefaultTTL": 300,
  "MaxTTL": 300,
  "MinTTL": 0,
  "ParametersInCacheKeyAndForwardedToOrigin": {
    "HeadersConfig": { "HeaderBehavior": "none" },
    "CookiesConfig": { "CookieBehavior": "none" },
    "QueryStringsConfig": { "QueryStringBehavior": "none" },
    "EnableAcceptEncodingGzip": true,
    "EnableAcceptEncodingBrotli": true
  }
}
```

**Why 5-minute cache for index.html:** The index.html file contains `<script>` tags pointing to hashed JS bundles. When deploying, new bundles get new hashes. Users will pick up the new index.html (and thus the new bundles) within 5 minutes of deployment. The CloudFront invalidation in CI/CD clears this cache immediately, but the 5-minute TTL provides a safety net if invalidation fails.

**Immutable assets cache policy (JS, CSS, images, fonts under `/assets/`):**

```json
{
  "Name": "agentmail-console-immutable",
  "DefaultTTL": 31536000,
  "MaxTTL": 31536000,
  "MinTTL": 31536000,
  "ParametersInCacheKeyAndForwardedToOrigin": {
    "HeadersConfig": { "HeaderBehavior": "none" },
    "CookiesConfig": { "CookieBehavior": "none" },
    "QueryStringsConfig": { "QueryStringBehavior": "none" },
    "EnableAcceptEncodingGzip": true,
    "EnableAcceptEncodingBrotli": true
  }
}
```

All JS/CSS files produced by Vite include a content hash in the filename (e.g., `index-a1b2c3d4.js`). These files are immutable -- the content at a given URL never changes. They can be cached forever (1 year TTL).

### Security Response Headers Policy

```json
{
  "Name": "agentmail-console-security-headers",
  "SecurityHeadersConfig": {
    "ContentSecurityPolicy": {
      "Override": true,
      "ContentSecurityPolicy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self' https://api.agentmail.aws https://auth.agentmail.dev wss://ws.agentmail.aws https://js.stripe.com; frame-src https://js.stripe.com https://hooks.stripe.com; object-src 'none'; base-uri 'self'; form-action 'self' https://auth.agentmail.dev; frame-ancestors 'none';"
    },
    "ContentTypeOptions": {
      "Override": true
    },
    "FrameOptions": {
      "Override": true,
      "FrameOption": "DENY"
    },
    "ReferrerPolicy": {
      "Override": true,
      "ReferrerPolicy": "strict-origin-when-cross-origin"
    },
    "StrictTransportSecurity": {
      "Override": true,
      "AccessControlMaxAgeSec": 31536000,
      "IncludeSubdomains": true,
      "Preload": true
    },
    "XSSProtection": {
      "Override": true,
      "Protection": true,
      "ModeBlock": true
    }
  },
  "CustomHeadersConfig": {
    "Items": [
      {
        "Header": "Permissions-Policy",
        "Value": "camera=(), microphone=(), geolocation=(), payment=(self)",
        "Override": true
      }
    ]
  }
}
```

### ACM Certificate

The SSL certificate for `console.agentmail.dev` is provisioned in ACM in `us-east-1` (required for CloudFront). DNS validation via a CNAME record on the `agentmail.dev` domain.

```
Certificate:
  Domain: console.agentmail.dev
  Subject Alternative Names: console.agentmail.dev
  Validation: DNS (CNAME record)
  Region: us-east-1
  Auto-renewal: Enabled (ACM handles this automatically)
```

### DNS (Route 53)

```
console.agentmail.dev  →  ALIAS  →  d1234abcdef8.cloudfront.net
```

This is an A-record alias in Route 53 pointing to the CloudFront distribution.

### CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy-console.yml
name: Deploy Console

on:
  push:
    branches: [main]
    paths: ['console/**']

env:
  AWS_REGION: us-east-1
  S3_BUCKET: agentmail-console-production
  CLOUDFRONT_DISTRIBUTION_ID: E1234ABCDEF

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read

    steps:
      - uses: actions/checkout@v4

      - uses: pnpm/action-setup@v3
        with:
          version: 9

      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: pnpm
          cache-dependency-path: console/pnpm-lock.yaml

      - name: Install dependencies
        working-directory: console
        run: pnpm install --frozen-lockfile

      - name: Type check
        working-directory: console
        run: pnpm tsc --noEmit

      - name: Lint
        working-directory: console
        run: pnpm eslint .

      - name: Test
        working-directory: console
        run: pnpm vitest run

      - name: Build
        working-directory: console
        run: pnpm build
        env:
          VITE_API_BASE_URL: https://api.agentmail.aws/v1
          VITE_COGNITO_USER_POOL_ID: ${{ secrets.COGNITO_USER_POOL_ID }}
          VITE_COGNITO_CLIENT_ID: ${{ secrets.COGNITO_CLIENT_ID }}
          VITE_COGNITO_DOMAIN: auth.agentmail.dev
          VITE_COGNITO_REDIRECT_URI: https://console.agentmail.dev/auth/callback
          VITE_STRIPE_PUBLISHABLE_KEY: ${{ secrets.STRIPE_PUBLISHABLE_KEY }}
          VITE_WEBSOCKET_URL: wss://ws.agentmail.aws/v1

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::ACCOUNT:role/github-actions-console-deploy
          aws-region: ${{ env.AWS_REGION }}

      - name: Sync to S3
        working-directory: console
        run: |
          # Sync hashed assets with long cache
          aws s3 sync dist/assets/ s3://$S3_BUCKET/assets/ \
            --cache-control "public, max-age=31536000, immutable" \
            --delete

          # Sync index.html and other root files with short cache
          aws s3 sync dist/ s3://$S3_BUCKET/ \
            --cache-control "public, max-age=300" \
            --exclude "assets/*" \
            --delete

      - name: Invalidate CloudFront
        run: |
          aws cloudfront create-invalidation \
            --distribution-id $CLOUDFRONT_DISTRIBUTION_ID \
            --paths "/index.html" "/"
```

**Deployment notes:**
- Only `/index.html` and `/` are invalidated (not `/*`). Hashed assets do not need invalidation because new filenames are generated on every build.
- The `--delete` flag on `aws s3 sync` removes old assets from S3. This is safe because index.html is deployed last and always references current hashes.
- The GitHub Actions role uses OIDC federation (no long-lived access keys).

### Environment Promotion

```
Feature Branch → PR Preview (optional, via Vercel/Netlify preview)
                              ↓ merge to main
                   Staging (agentmail-console-staging)
                              ↓ manual promotion (tag release)
                   Production (agentmail-console-production)
```

Staging and production use separate CloudFront distributions, S3 buckets, and Cognito User Pools. Environment variables in the build step control which backends the console talks to.

---

## 6. API Integration Layer

### API Client

A centralized `ApiClient` class wraps the native `fetch` API with authentication, error handling, and retry logic. This client is used by all TanStack Query hooks.

```typescript
// src/lib/api/client.ts

import { useAuthStore } from '@/stores/auth'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

interface ApiError {
  code: string
  message: string
}

interface ApiErrorResponse {
  error: ApiError
}

export class ApiClientError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
    this.name = 'ApiClientError'
  }
}

class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  private getAuthHeader(): Record<string, string> {
    const { accessToken } = useAuthStore.getState()
    if (!accessToken) return {}
    return { Authorization: `Bearer ${accessToken}` }
  }

  private async request<T>(
    method: HttpMethod,
    path: string,
    body?: unknown,
    options?: {
      params?: Record<string, string | number | boolean | undefined>
      signal?: AbortSignal
    },
  ): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`)

    // Append query parameters
    if (options?.params) {
      Object.entries(options.params).forEach(([key, value]) => {
        if (value !== undefined) {
          url.searchParams.set(key, String(value))
        }
      })
    }

    const headers: Record<string, string> = {
      ...this.getAuthHeader(),
      'Content-Type': 'application/json',
    }

    const response = await fetch(url.toString(), {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: options?.signal,
    })

    // Handle 401: attempt token refresh and retry once
    if (response.status === 401) {
      const refreshed = await this.attemptTokenRefresh()
      if (refreshed) {
        // Retry the original request with new token
        const retryHeaders = {
          ...this.getAuthHeader(),
          'Content-Type': 'application/json',
        }
        const retryResponse = await fetch(url.toString(), {
          method,
          headers: retryHeaders,
          body: body ? JSON.stringify(body) : undefined,
          signal: options?.signal,
        })
        return this.handleResponse<T>(retryResponse)
      }
      // Refresh failed -- redirect to login
      useAuthStore.getState().clearAuth()
      window.location.href = '/login'
      throw new ApiClientError(401, 'UNAUTHORIZED', 'Session expired')
    }

    // Handle 429: show rate limit toast
    if (response.status === 429) {
      const retryAfter = response.headers.get('Retry-After')
      const message = retryAfter
        ? `Rate limited. Retry after ${retryAfter} seconds.`
        : 'Rate limited. Please slow down.'
      // Toast is triggered by the calling component or a global error handler
      throw new ApiClientError(429, 'RATE_LIMITED', message)
    }

    return this.handleResponse<T>(response)
  }

  private async handleResponse<T>(response: Response): Promise<T> {
    if (response.status === 204) {
      return undefined as T
    }

    const data = await response.json()

    if (!response.ok) {
      const errorData = data as ApiErrorResponse
      throw new ApiClientError(
        response.status,
        errorData.error?.code || 'UNKNOWN_ERROR',
        errorData.error?.message || 'An unexpected error occurred',
      )
    }

    return data as T
  }

  private async attemptTokenRefresh(): Promise<boolean> {
    try {
      const response = await fetch('/auth/refresh', {
        method: 'POST',
        credentials: 'include',
      })
      if (!response.ok) return false
      const tokens = await response.json()
      useAuthStore.getState().setTokens(tokens)
      return true
    } catch {
      return false
    }
  }

  // Public methods
  get<T>(path: string, params?: Record<string, string | number | boolean | undefined>, signal?: AbortSignal) {
    return this.request<T>('GET', path, undefined, { params, signal })
  }

  post<T>(path: string, body?: unknown) {
    return this.request<T>('POST', path, body)
  }

  put<T>(path: string, body?: unknown) {
    return this.request<T>('PUT', path, body)
  }

  patch<T>(path: string, body?: unknown) {
    return this.request<T>('PATCH', path, body)
  }

  delete<T>(path: string) {
    return this.request<T>('DELETE', path)
  }
}

export const apiClient = new ApiClient(API_BASE_URL)
```

### TanStack Query Configuration

```typescript
// src/lib/api/query-client.ts

import { QueryClient } from '@tanstack/react-query'
import { ApiClientError } from './client'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,          // 30 seconds before data is considered stale
      gcTime: 5 * 60 * 1000,         // 5 minutes before inactive data is garbage collected
      retry: (failureCount, error) => {
        // Do not retry on 4xx errors (except 429)
        if (error instanceof ApiClientError) {
          if (error.status >= 400 && error.status < 500 && error.status !== 429) {
            return false
          }
        }
        return failureCount < 3
      },
      retryDelay: (attemptIndex) =>
        Math.min(1000 * 2 ** attemptIndex, 30000),
      refetchOnWindowFocus: true,     // Refetch when user returns to tab
      refetchOnReconnect: true,       // Refetch when network reconnects
    },
    mutations: {
      retry: false, // Mutations are not retried automatically
    },
  },
})
```

### Query Key Factory

A centralized key factory ensures consistent cache key naming and enables targeted invalidation.

```typescript
// src/lib/api/query-keys.ts

export const queryKeys = {
  // Organization
  organization: {
    all: ['organization'] as const,
    me: () => [...queryKeys.organization.all, 'me'] as const,
  },

  // Inboxes
  inboxes: {
    all: ['inboxes'] as const,
    list: (params?: { podId?: string; limit?: number; pageToken?: string }) =>
      [...queryKeys.inboxes.all, 'list', params] as const,
    detail: (inboxId: string) =>
      [...queryKeys.inboxes.all, 'detail', inboxId] as const,
  },

  // Messages
  messages: {
    all: (inboxId: string) => ['messages', inboxId] as const,
    list: (inboxId: string, params?: { limit?: number; pageToken?: string }) =>
      [...queryKeys.messages.all(inboxId), 'list', params] as const,
    detail: (inboxId: string, messageId: string) =>
      [...queryKeys.messages.all(inboxId), 'detail', messageId] as const,
  },

  // Threads
  threads: {
    all: (inboxId: string) => ['threads', inboxId] as const,
    detail: (inboxId: string, threadId: string) =>
      [...queryKeys.threads.all(inboxId), 'detail', threadId] as const,
    messages: (inboxId: string, threadId: string) =>
      [...queryKeys.threads.detail(inboxId, threadId), 'messages'] as const,
  },

  // Domains
  domains: {
    all: ['domains'] as const,
    list: () => [...queryKeys.domains.all, 'list'] as const,
    detail: (domainId: string) =>
      [...queryKeys.domains.all, 'detail', domainId] as const,
  },

  // Webhooks
  webhooks: {
    all: ['webhooks'] as const,
    list: () => [...queryKeys.webhooks.all, 'list'] as const,
    detail: (webhookId: string) =>
      [...queryKeys.webhooks.all, 'detail', webhookId] as const,
    deliveries: (webhookId: string) =>
      [...queryKeys.webhooks.detail(webhookId), 'deliveries'] as const,
  },

  // API Keys
  apiKeys: {
    all: ['apiKeys'] as const,
    list: () => [...queryKeys.apiKeys.all, 'list'] as const,
  },

  // Pods
  pods: {
    all: ['pods'] as const,
    list: () => [...queryKeys.pods.all, 'list'] as const,
    detail: (podId: string) =>
      [...queryKeys.pods.all, 'detail', podId] as const,
  },

  // Usage / Metrics
  usage: {
    all: ['usage'] as const,
    current: () => [...queryKeys.usage.all, 'current'] as const,
    history: (params: { period: string; metric: string }) =>
      [...queryKeys.usage.all, 'history', params] as const,
  },
} as const
```

### Resource Hooks

Each API resource has a dedicated set of hooks. Below are the key hooks with their full implementation.

```typescript
// src/hooks/api/use-inboxes.ts

import {
  useQuery,
  useMutation,
  useInfiniteQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { queryKeys } from '@/lib/api/query-keys'
import type { Inbox, InboxCreateRequest, PaginatedResponse } from '@/types/api'

/** Fetch a paginated list of inboxes */
export function useInboxes(params?: { podId?: string; limit?: number }) {
  return useInfiniteQuery({
    queryKey: queryKeys.inboxes.list(params),
    queryFn: async ({ pageParam }) => {
      return apiClient.get<PaginatedResponse<Inbox>>('/inboxes', {
        pod_id: params?.podId,
        limit: params?.limit ?? 25,
        page_token: pageParam,
      })
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_page_token : undefined,
  })
}

/** Fetch a single inbox by ID */
export function useInbox(inboxId: string) {
  return useQuery({
    queryKey: queryKeys.inboxes.detail(inboxId),
    queryFn: () => apiClient.get<Inbox>(`/inboxes/${inboxId}`),
    enabled: !!inboxId,
  })
}

/** Create a new inbox (with optimistic update) */
export function useCreateInbox() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: InboxCreateRequest) =>
      apiClient.post<Inbox>('/inboxes', data),

    onMutate: async (newInbox) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: queryKeys.inboxes.all })

      // Snapshot the previous value
      const previousInboxes = queryClient.getQueryData(
        queryKeys.inboxes.list(),
      )

      // Optimistically add the new inbox to the list with a temp ID
      queryClient.setQueryData(
        queryKeys.inboxes.list(),
        (old: any) => {
          if (!old) return old
          const tempInbox: Inbox = {
            id: `temp-${Date.now()}`,
            email: `${newInbox.username}@${newInbox.domain || 'mail.agentmail.dev'}`,
            display_name: newInbox.display_name || '',
            pod_id: newInbox.pod_id || 'default',
            status: 'active',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }
          return {
            ...old,
            pages: old.pages.map((page: any, index: number) =>
              index === 0
                ? { ...page, data: [tempInbox, ...page.data] }
                : page,
            ),
          }
        },
      )

      return { previousInboxes }
    },

    onError: (_err, _newInbox, context) => {
      // Roll back on error
      if (context?.previousInboxes) {
        queryClient.setQueryData(
          queryKeys.inboxes.list(),
          context.previousInboxes,
        )
      }
    },

    onSettled: () => {
      // Refetch to get the real data
      queryClient.invalidateQueries({ queryKey: queryKeys.inboxes.all })
      // Also update the org usage counts
      queryClient.invalidateQueries({ queryKey: queryKeys.organization.me() })
    },
  })
}

/** Delete an inbox */
export function useDeleteInbox() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (inboxId: string) =>
      apiClient.delete(`/inboxes/${inboxId}`),

    onMutate: async (inboxId) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.inboxes.all })

      const previousInboxes = queryClient.getQueryData(
        queryKeys.inboxes.list(),
      )

      // Optimistically remove the inbox from the list
      queryClient.setQueryData(
        queryKeys.inboxes.list(),
        (old: any) => {
          if (!old) return old
          return {
            ...old,
            pages: old.pages.map((page: any) => ({
              ...page,
              data: page.data.filter((inbox: Inbox) => inbox.id !== inboxId),
            })),
          }
        },
      )

      return { previousInboxes }
    },

    onError: (_err, _inboxId, context) => {
      if (context?.previousInboxes) {
        queryClient.setQueryData(
          queryKeys.inboxes.list(),
          context.previousInboxes,
        )
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.inboxes.all })
      queryClient.invalidateQueries({ queryKey: queryKeys.organization.me() })
    },
  })
}
```

```typescript
// src/hooks/api/use-messages.ts

import { useQuery, useInfiniteQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { queryKeys } from '@/lib/api/query-keys'
import type { Message, PaginatedResponse } from '@/types/api'

/** Fetch paginated messages for an inbox */
export function useMessages(inboxId: string, params?: { limit?: number }) {
  return useInfiniteQuery({
    queryKey: queryKeys.messages.list(inboxId, params),
    queryFn: async ({ pageParam }) => {
      return apiClient.get<PaginatedResponse<Message>>(
        `/inboxes/${inboxId}/messages`,
        {
          limit: params?.limit ?? 25,
          page_token: pageParam,
        },
      )
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_page_token : undefined,
    enabled: !!inboxId,
  })
}

/** Fetch a single message */
export function useMessage(inboxId: string, messageId: string) {
  return useQuery({
    queryKey: queryKeys.messages.detail(inboxId, messageId),
    queryFn: () =>
      apiClient.get<Message>(`/inboxes/${inboxId}/messages/${messageId}`),
    enabled: !!inboxId && !!messageId,
  })
}
```

```typescript
// src/hooks/api/use-domains.ts

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { queryKeys } from '@/lib/api/query-keys'
import type { Domain, DomainCreateRequest } from '@/types/api'

export function useDomains() {
  return useQuery({
    queryKey: queryKeys.domains.list(),
    queryFn: () => apiClient.get<{ data: Domain[] }>('/domains'),
  })
}

export function useDomain(domainId: string) {
  return useQuery({
    queryKey: queryKeys.domains.detail(domainId),
    queryFn: () => apiClient.get<Domain>(`/domains/${domainId}`),
    enabled: !!domainId,
    // Poll every 30 seconds while domain is pending verification
    refetchInterval: (query) => {
      const domain = query.state.data
      return domain?.status === 'pending' ? 30_000 : false
    },
  })
}

export function useCreateDomain() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: DomainCreateRequest) =>
      apiClient.post<Domain>('/domains', data),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.domains.all })
    },
  })
}

export function useVerifyDomain() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (domainId: string) =>
      apiClient.post<Domain>(`/domains/${domainId}/verify`),
    onSettled: (_data, _error, domainId) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.domains.detail(domainId),
      })
    },
  })
}
```

```typescript
// src/hooks/api/use-usage.ts

import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { queryKeys } from '@/lib/api/query-keys'
import type { Organization, MetricsResponse } from '@/types/api'

/** Fetch current organization with usage data */
export function useOrganization() {
  return useQuery({
    queryKey: queryKeys.organization.me(),
    queryFn: () => apiClient.get<Organization>('/organizations/me'),
    staleTime: 60 * 1000, // 1 minute -- usage data does not need instant freshness
  })
}

/** Fetch historical usage metrics */
export function useUsageHistory(params: {
  metric: 'emails_sent' | 'emails_received' | 'api_calls' | 'storage_bytes' | 'ai_invocations'
  period: '7d' | '30d' | '60d' | '90d'
  granularity: 'hour' | 'day'
}) {
  return useQuery({
    queryKey: queryKeys.usage.history(params),
    queryFn: () =>
      apiClient.post<MetricsResponse>('/metrics/query', {
        metric: params.metric,
        period: params.period,
        granularity: params.granularity,
      }),
    staleTime: 5 * 60 * 1000, // 5 minutes -- historical data changes slowly
  })
}
```

### WebSocket Integration

The console maintains a WebSocket connection for real-time updates. This is used sparingly -- only for live event counters and webhook delivery notifications -- not as a replacement for TanStack Query's polling.

```typescript
// src/lib/api/websocket.ts

import { useAuthStore } from '@/stores/auth'
import { queryClient } from '@/lib/api/query-client'
import { queryKeys } from '@/lib/api/query-keys'

const WS_URL = import.meta.env.VITE_WEBSOCKET_URL

class WebSocketManager {
  private ws: WebSocket | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 10
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private subscriptions: Set<string> = new Set()

  connect() {
    const { accessToken } = useAuthStore.getState()
    if (!accessToken || this.ws?.readyState === WebSocket.OPEN) return

    this.ws = new WebSocket(`${WS_URL}?token=${accessToken}`)

    this.ws.onopen = () => {
      this.reconnectAttempts = 0
      // Re-subscribe to any channels
      this.subscriptions.forEach((channel) => {
        this.ws?.send(JSON.stringify({ action: 'subscribe', channel }))
      })
    }

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      this.handleEvent(data)
    }

    this.ws.onclose = () => {
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  private handleEvent(event: {
    type: string
    channel: string
    data: unknown
  }) {
    switch (event.type) {
      case 'message.received':
        // Invalidate message list for the relevant inbox
        const inboxId = (event.data as any).inbox_id
        queryClient.invalidateQueries({
          queryKey: queryKeys.messages.all(inboxId),
        })
        // Update organization usage counters
        queryClient.invalidateQueries({
          queryKey: queryKeys.organization.me(),
        })
        break

      case 'webhook.delivered':
        const webhookId = (event.data as any).webhook_id
        queryClient.invalidateQueries({
          queryKey: queryKeys.webhooks.deliveries(webhookId),
        })
        break

      case 'domain.verified':
        const domainId = (event.data as any).domain_id
        queryClient.invalidateQueries({
          queryKey: queryKeys.domains.detail(domainId),
        })
        break

      case 'heartbeat':
        // Server heartbeat -- no action needed
        break
    }
  }

  subscribe(channel: string) {
    this.subscriptions.add(channel)
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'subscribe', channel }))
    }
  }

  unsubscribe(channel: string) {
    this.subscriptions.delete(channel)
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'unsubscribe', channel }))
    }
  }

  private scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 30000)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++
      this.connect()
    }, delay)
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
    this.subscriptions.clear()
  }
}

export const wsManager = new WebSocketManager()
```

### Error Handling

Errors flow from the API client through TanStack Query to the UI via a combination of per-component error states and a global error toast system.

```typescript
// src/components/providers/QueryProvider.tsx

import { QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { queryClient } from '@/lib/api/query-client'
import { Toaster } from '@/components/ui/toaster'
import { useToast } from '@/hooks/use-toast'
import { ApiClientError } from '@/lib/api/client'

export function QueryProvider({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <GlobalErrorHandler />
      {children}
      <Toaster />
      {import.meta.env.DEV && <ReactQueryDevtools />}
    </QueryClientProvider>
  )
}

function GlobalErrorHandler() {
  const { toast } = useToast()

  // Global mutation error handler
  queryClient.setMutationDefaults(['*'], {
    onError: (error) => {
      if (error instanceof ApiClientError) {
        toast({
          variant: 'destructive',
          title: 'Error',
          description: error.message,
        })
      }
    },
  })

  return null
}
```

### Form Validation with Zod

All form inputs are validated with Zod schemas before submission. The schemas are shared between client-side validation and the TanStack Query mutation functions.

```typescript
// src/lib/schemas/inbox.ts

import { z } from 'zod'

export const createInboxSchema = z.object({
  username: z
    .string()
    .min(1, 'Username is required')
    .max(64, 'Username must be 64 characters or fewer')
    .regex(
      /^[a-z0-9][a-z0-9._-]*[a-z0-9]$/,
      'Username must start and end with a letter or number, and can contain dots, hyphens, and underscores',
    ),
  domain: z.string().optional(),
  pod_id: z.string().optional(),
  display_name: z.string().max(256).optional(),
})

export type CreateInboxInput = z.infer<typeof createInboxSchema>

// src/lib/schemas/webhook.ts

export const createWebhookSchema = z.object({
  url: z
    .string()
    .url('Must be a valid URL')
    .startsWith('https://', 'URL must use HTTPS'),
  events: z
    .array(z.enum([
      'message.received',
      'message.sent',
      'message.bounced',
      'inbox.created',
      'inbox.deleted',
      'domain.verified',
      'domain.failed',
    ]))
    .min(1, 'Select at least one event'),
  secret: z.string().optional(),
})

export type CreateWebhookInput = z.infer<typeof createWebhookSchema>
```

---

## 7. Responsive Design

### Layout Strategy

The console uses a desktop-first layout targeting developers on laptops and monitors. Mobile support is provided for quick checks and monitoring but is not the primary interaction surface.

### Breakpoints

```css
/* Tailwind default breakpoints, used consistently */
sm: 640px    /* Small phones (rarely targeted) */
md: 768px    /* Tablets and large phones */
lg: 1024px   /* Small laptops */
xl: 1280px   /* Standard laptops and desktops */
2xl: 1536px  /* Large monitors */
```

### Desktop Layout (>= 1024px)

```
┌──────────────────────────────────────────────────────────────┐
│  Header (64px): Logo │ Global Search (Cmd+K) │ Theme │ User │
├──────────┬───────────────────────────────────────────────────┤
│          │                                                   │
│ Sidebar  │  Main Content Area                                │
│ (256px)  │  (flex-1, max-width: 1280px, centered)           │
│          │                                                   │
│ Collaps- │  Page header + breadcrumbs                        │
│ ible to  │  ─────────────────────                            │
│ (64px)   │  Page content                                     │
│          │                                                   │
│ Items:   │                                                   │
│ Dashboard│                                                   │
│ Inboxes  │                                                   │
│ Domains  │                                                   │
│ Webhooks │                                                   │
│ API Keys │                                                   │
│ Pods     │                                                   │
│ Usage    │                                                   │
│ Settings │                                                   │
│ ──────── │                                                   │
│ Docs     │                                                   │
│ ──────── │                                                   │
│ Tier     │                                                   │
│ badge    │                                                   │
│          │                                                   │
└──────────┴───────────────────────────────────────────────────┘
```

The sidebar is collapsible. When collapsed, it shows only icons (64px wide). The collapsed state is persisted in localStorage via the Zustand preferences store.

### Tablet Layout (768px - 1023px)

- Sidebar is hidden by default (overlay mode). Hamburger menu in the header to open.
- When open, sidebar overlays the content with a semi-transparent backdrop.
- Main content takes full width.
- Tables switch to a more compact layout with horizontal scroll where needed.

### Mobile Layout (< 768px)

```
┌───────────────────────────────────────┐
│  Header: ☰ │ Logo │ Theme │ Avatar   │
├───────────────────────────────────────┤
│                                       │
│  Main Content Area (full width)       │
│  Padding: 16px                        │
│                                       │
│  Cards stack vertically               │
│  Tables become card lists             │
│  Forms are full-width                 │
│                                       │
├───────────────────────────────────────┤
│  Bottom Nav: Dashboard │ Inboxes │    │
│              Domains │ Settings │ More│
└───────────────────────────────────────┘
```

- Bottom navigation bar replaces the sidebar.
- Five primary items shown; "More" opens a sheet with remaining items.
- Tables are replaced with card-style lists (each row becomes a card).
- The email composer becomes a full-screen modal.
- The message viewer is full-screen with a back button.

### Dark Mode

Dark mode is supported via Tailwind's `dark:` variant, driven by a combination of system preference and manual toggle.

```typescript
// src/stores/preferences.ts

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Theme = 'light' | 'dark' | 'system'

interface PreferencesState {
  theme: Theme
  sidebarCollapsed: boolean
  setTheme: (theme: Theme) => void
  setSidebarCollapsed: (collapsed: boolean) => void
}

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      theme: 'system',
      sidebarCollapsed: false,
      setTheme: (theme) => set({ theme }),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
    }),
    {
      name: 'agentmail-preferences',
    },
  ),
)
```

```typescript
// src/hooks/use-theme.ts

import { useEffect } from 'react'
import { usePreferencesStore } from '@/stores/preferences'

export function useTheme() {
  const { theme, setTheme } = usePreferencesStore()

  useEffect(() => {
    const root = document.documentElement

    function applyTheme(resolvedTheme: 'light' | 'dark') {
      root.classList.toggle('dark', resolvedTheme === 'dark')
    }

    if (theme === 'system') {
      const media = window.matchMedia('(prefers-color-scheme: dark)')
      applyTheme(media.matches ? 'dark' : 'light')

      const listener = (e: MediaQueryListEvent) => {
        applyTheme(e.matches ? 'dark' : 'light')
      }
      media.addEventListener('change', listener)
      return () => media.removeEventListener('change', listener)
    } else {
      applyTheme(theme)
    }
  }, [theme])

  return { theme, setTheme }
}
```

### Tailwind Configuration

```typescript
// tailwind.config.ts

import type { Config } from 'tailwindcss'

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#2563eb',  // AgentMail brand blue
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'monospace'],
      },
      maxWidth: {
        'content': '1280px',
      },
    },
  },
  plugins: [
    require('tailwindcss-animate'), // For shadcn/ui animations
  ],
} satisfies Config
```

---

## 8. Security

### Content Security Policy (CSP)

The CSP header (defined in the CloudFront response headers policy above) enforces the following:

| Directive | Value | Rationale |
|-----------|-------|-----------|
| `default-src` | `'self'` | Only load resources from the console's own origin by default. |
| `script-src` | `'self'` | No inline scripts, no eval, no external script sources. All JS is bundled by Vite and served from the same origin. |
| `style-src` | `'self' 'unsafe-inline'` | `unsafe-inline` is required for Tailwind's runtime style injection and TipTap editor styles. A future improvement is to use nonces. |
| `img-src` | `'self' data: https:` | Allow images from any HTTPS source (email avatars, user-uploaded images) and data URIs (inline images in emails). |
| `font-src` | `'self'` | Fonts are bundled and served from the same origin. No external font CDNs. |
| `connect-src` | `'self' https://api.agentmail.aws https://auth.agentmail.dev wss://ws.agentmail.aws https://js.stripe.com` | API calls, Cognito auth, WebSocket, and Stripe.js. |
| `frame-src` | `https://js.stripe.com https://hooks.stripe.com` | Stripe embeds for payment forms and Customer Portal. |
| `object-src` | `'none'` | No Flash, no Java applets, no ActiveX. |
| `base-uri` | `'self'` | Prevent `<base>` tag injection that could redirect relative URLs. |
| `form-action` | `'self' https://auth.agentmail.dev` | Forms can only submit to the console itself or Cognito. |
| `frame-ancestors` | `'none'` | Prevent the console from being embedded in iframes (clickjacking protection). |

### XSS Prevention

1. **React's built-in escaping.** React escapes all string values rendered in JSX by default. The only way to inject raw HTML is via `dangerouslySetInnerHTML`, which is never used in the codebase (enforced by ESLint rule `react/no-danger`).

2. **DOMPurify for email HTML.** Email bodies are the only user-generated HTML rendered in the console. They are sanitized by DOMPurify before injection into the sandboxed iframe:

```typescript
import DOMPurify from 'dompurify'

const PURIFY_CONFIG: DOMPurify.Config = {
  ALLOWED_TAGS: [
    'p', 'div', 'span', 'br', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'a', 'img',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
    'ul', 'ol', 'li',
    'b', 'strong', 'i', 'em', 'u', 'strike', 's',
    'blockquote', 'pre', 'code',
    'center', 'font', 'sup', 'sub',
  ],
  ALLOWED_ATTR: [
    'href', 'src', 'alt', 'title', 'width', 'height',
    'style', 'class', 'align', 'valign', 'bgcolor', 'color',
    'border', 'cellpadding', 'cellspacing', 'colspan', 'rowspan',
    'face', 'size',
  ],
  FORBID_TAGS: ['script', 'style', 'form', 'iframe', 'object', 'embed', 'svg', 'math'],
  FORBID_ATTR: [
    'onerror', 'onclick', 'onload', 'onmouseover', 'onfocus', 'onblur',
    'onsubmit', 'onreset', 'onabort', 'onchange', 'oninput',
  ],
  ADD_ATTR: ['target'],
  WHOLE_DOCUMENT: false,
  RETURN_DOM: false,
  RETURN_DOM_FRAGMENT: false,
}

export function sanitizeEmailHtml(html: string): string {
  const clean = DOMPurify.sanitize(html, PURIFY_CONFIG)

  // Force all links to open in new tab
  return clean.replace(/<a /g, '<a target="_blank" rel="noopener noreferrer" ')
}
```

3. **Iframe sandboxing for email bodies.** The sanitized HTML is rendered in an iframe with restrictive sandbox attributes:

```html
<iframe
  sandbox="allow-same-origin"
  srcdoc={sanitizedHtml}
  style="width: 100%; border: none;"
  title="Email content"
/>
```

The `sandbox` attribute with only `allow-same-origin` means:
- No JavaScript execution (`allow-scripts` is absent)
- No form submission (`allow-forms` is absent)
- No top-level navigation (`allow-top-navigation` is absent)
- No popups (`allow-popups` is absent)
- The iframe content can be styled via same-origin CSS but cannot execute any code

### CSRF Protection

CSRF is not a concern for the console because:
- API calls use `Authorization: Bearer {token}` headers, not cookies.
- Browsers do not automatically attach custom headers to cross-origin requests.
- The `SameSite=Strict` attribute on the refresh token cookie prevents it from being sent in cross-origin requests.

The only form submission that crosses origins is the Cognito OAuth flow, which is protected by PKCE (the `code_verifier` is stored in `sessionStorage` and cannot be accessed cross-origin) and a CSRF `state` parameter.

### Secret Management

- **No secrets in the client bundle.** The Vite build embeds only public-safe values: Cognito client ID (public by design), Stripe publishable key (public by design), API base URL (public by design).
- **API keys are generated server-side** via `POST /v1/api-keys`. The console displays them once and stores them in `sessionStorage` (cleared on tab close), never in `localStorage`.
- **Stripe secret key is never in the client.** All Stripe operations that require the secret key (creating checkout sessions, creating portal sessions, reporting usage) happen in Lambda functions. The console calls the AgentMail API, which calls Stripe server-side.

### Subresource Integrity (SRI)

For any third-party scripts loaded from CDNs (currently only Stripe.js), SRI hashes are included:

```html
<script
  src="https://js.stripe.com/v3/"
  integrity="sha384-{hash}"
  crossorigin="anonymous"
></script>
```

This ensures that if the CDN is compromised, the browser rejects the modified script. The SRI hash is updated as part of the dependency update process.

### Additional Security Headers

| Header | Value | Purpose |
|--------|-------|---------|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` | Force HTTPS for 1 year, including subdomains. Eligible for HSTS preload list. |
| `X-Content-Type-Options` | `nosniff` | Prevent MIME type sniffing. |
| `X-Frame-Options` | `DENY` | Prevent clickjacking (backup for CSP `frame-ancestors`). |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Send origin only for cross-origin requests. Never send path/query. |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(self)` | Disable camera, microphone, and geolocation. Payment API allowed for Stripe. |

### Dependency Security

- `pnpm audit` runs in CI on every pull request. Any `high` or `critical` vulnerability blocks merge.
- Dependabot is enabled for automated dependency update PRs.
- The `pnpm-lock.yaml` lockfile is committed and `--frozen-lockfile` is used in CI to prevent supply-chain attacks from dependency confusion.
- No `postinstall` scripts are allowed from third-party packages (enforced by `.npmrc` configuration).
