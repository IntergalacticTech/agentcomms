import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

export default function SignupPage() {
  const { signup, loading } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [error, setError] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [copied, setCopied] = useState(false);

  const passwordErrors = (() => {
    const errs: string[] = [];
    if (password.length > 0) {
      if (password.length < 8) errs.push("at least 8 characters");
      if (!/[a-z]/.test(password)) errs.push("a lowercase letter");
      if (!/[A-Z]/.test(password)) errs.push("an uppercase letter");
      if (!/[0-9]/.test(password)) errs.push("a number");
    }
    return errs;
  })();

  const passwordValid = password.length >= 8 && /[a-z]/.test(password) && /[A-Z]/.test(password) && /[0-9]/.test(password);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!passwordValid) {
      setError("Password must include an uppercase letter, a lowercase letter, and a number.");
      return;
    }
    try {
      const result = await signup(email, password, orgName);
      if (result.apiKey) {
        setApiKey(result.apiKey);
      } else {
        navigate("/login");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
    }
  }

  function copyKey() {
    navigator.clipboard.writeText(apiKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (apiKey) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="w-full max-w-md">
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-8">
            <h2 className="text-xl font-semibold text-gray-900 mb-2">
              Account created
            </h2>
            <p className="text-sm text-gray-600 mb-4">
              Save your API key now. You will not be able to see it again.
            </p>
            <div className="bg-gray-900 rounded-md p-4 mb-4">
              <code className="text-green-400 text-sm break-all">{apiKey}</code>
            </div>
            <button
              onClick={copyKey}
              className="w-full py-2 px-4 bg-indigo-600 text-white font-medium rounded-md hover:bg-indigo-700 mb-3"
            >
              {copied ? "Copied!" : "Copy API Key"}
            </button>
            <Link
              to={`/verify?email=${encodeURIComponent(email)}`}
              className="block text-center text-sm text-indigo-600 hover:text-indigo-700 font-medium"
            >
              Verify your email
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900">AgentComms</h1>
          <p className="text-gray-500 mt-1">Create your account</p>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-6">Sign up</h2>
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md text-sm">
              {error}
            </div>
          )}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="orgName"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Organization name
              </label>
              <input
                id="orgName"
                type="text"
                required
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                placeholder="Acme Inc."
              />
            </div>
            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                placeholder="you@example.com"
              />
            </div>
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 ${password.length > 0 && !passwordValid ? "border-red-300" : "border-gray-300"}`}
                placeholder="Min. 8 characters"
              />
              {password.length > 0 && passwordErrors.length > 0 && (
                <p className="mt-1 text-xs text-red-600">
                  Needs {passwordErrors.join(", ")}
                </p>
              )}
              {password.length > 0 && passwordValid && (
                <p className="mt-1 text-xs text-green-600">
                  Password meets requirements
                </p>
              )}
            </div>
            <button
              type="submit"
              disabled={loading || !passwordValid}
              className="w-full py-2 px-4 bg-indigo-600 text-white font-medium rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "Creating account..." : "Create account"}
            </button>
          </form>
          <p className="mt-4 text-center text-sm text-gray-500">
            Already have an account?{" "}
            <Link
              to="/login"
              className="text-indigo-600 hover:text-indigo-700 font-medium"
            >
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
