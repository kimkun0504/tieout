import { useEffect, useState } from "react";
import { JobView } from "./components/JobView";
import { JobsPage } from "./components/JobsPage";
import { reviewerName, setReviewerName } from "./lib/api";
import { go, useRoute } from "./lib/route";

export default function App() {
  const route = useRoute();
  return (
    <div className="min-h-screen">
      <TopBar />
      {route.page === "job" ? <JobView key={route.id} id={route.id} /> : <JobsPage />}
    </div>
  );
}

function TopBar() {
  const [name, setName] = useState(reviewerName);
  useEffect(() => setReviewerName(name.trim()), [name]);
  return (
    <header className="flex items-center gap-4 border-b border-rule bg-ink px-5 py-2.5 text-white">
      <a
        href="#/"
        onClick={(e) => {
          e.preventDefault();
          go({ page: "jobs" });
        }}
        className="flex items-center gap-2 font-semibold tracking-tight"
      >
        <Logo />
        tieout
      </a>
      <span className="hidden text-sm text-white/60 sm:inline">Rent roll review</span>
      <label className="ml-auto flex items-center gap-2 text-sm text-white/70">
        Reviewer
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Your name"
          maxLength={60}
          className="w-36 rounded border border-white/20 bg-white/10 px-2 py-1 text-white placeholder:text-white/40"
        />
      </label>
    </header>
  );
}

function Logo() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
      <rect width="16" height="16" rx="3" fill="#2a3a4c" />
      <path d="M4 8.5l2.5 2.5L12 5.5" stroke="#34C3A0" strokeWidth="2" fill="none" />
    </svg>
  );
}
