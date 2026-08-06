import { useRoute } from "wouter";

/** Resolve form id from `/forms/:id…` or legacy `/projects/:id…` routes. */
export function useFormRouteId(suffix?: string): string {
  const formsPath = suffix ? `/forms/:id/${suffix}` : "/forms/:id";
  const projectsPath = suffix ? `/projects/:id/${suffix}` : "/projects/:id";
  const [, forms] = useRoute<{ id: string }>(formsPath);
  const [, projects] = useRoute<{ id: string }>(projectsPath);
  return forms?.id ?? projects?.id ?? "";
}
