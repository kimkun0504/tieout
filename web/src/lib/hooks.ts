import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { JobResponse } from "./types";

export const jobKey = (id: string) => ["job", id] as const;

export function useJob(id: string) {
  return useQuery({ queryKey: jobKey(id), queryFn: () => api.job(id) });
}

export function useFields() {
  return useQuery({ queryKey: ["fields"], queryFn: api.fields, staleTime: Infinity });
}

export function useSource(id: string, enabled: boolean) {
  return useQuery({ queryKey: ["source", id], queryFn: () => api.source(id), enabled, staleTime: Infinity });
}

/** Every review action returns the re-run result; put it straight into the cache. */
export function useJobAction<A>(id: string, fn: (args: A) => Promise<JobResponse>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => {
      qc.setQueryData(jobKey(id), data);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}
