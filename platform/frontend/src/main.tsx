import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./lib/auth";
import { initStaleBundleCheck } from "./lib/staleBundle";
import App from "./App";
import "./index.css";

// Regression finding 207.c: auto-reload tabs whose bundle predates the
// latest deploy. Prevents "new deploy shipped a fix, but users who had
// the app open before the deploy are still running the buggy bundle"
// — most acutely felt with the F207 JobDetailPage fix: users stuck on
// pre-F207 JS kept seeing "Job not found" on every session-expired
// click. See `src/lib/staleBundle.ts` for the full rationale.
initStaleBundleCheck();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 2,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
