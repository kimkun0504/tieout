import { useEffect, useState } from "react";

export type Route = { page: "jobs" } | { page: "job"; id: string };

export function parseHash(hash: string): Route {
  const m = /^#\/jobs\/([0-9a-f]{32})$/.exec(hash);
  return m ? { page: "job", id: m[1]! } : { page: "jobs" };
}

export function go(route: Route): void {
  window.location.hash = route.page === "job" ? `/jobs/${route.id}` : "/";
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
