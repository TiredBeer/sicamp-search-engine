export interface Tag {
  id: number;
  name: string;
  synonyms: string[];
}
export interface Solution {
  id?: number;
  source: "code" | "llm";
  trusted: boolean;
  key_idea: string;
  sketch: string;
  facts: { name: string | null; statement: string }[];
  reduction: string[];
  tags: string[];
  free_tags: string[];
  difficulty: number | null;
  difficulty_reason: string;
  complexity: { time: string; memory: string };
  prerequisite: string[];
  code: string | null;
  origin: string;
}
export interface Problem {
  id: number;
  title: string;
  origin: string;
  abstract: string;
  difficulty: number | null;
  tags: string[];
  solution_count: number;
  llm_solution_count: number;
  created_at: string;
  updated_at: string;
  score?: number | null;
}
export interface ProblemDetail extends Problem {
  statement: string;
  solutions: Solution[];
  analysis: Record<string, unknown>;
}
export interface Job {
  id: string;
  kind: string;
  status: string;
  completed: number;
  total: number;
  error: string | null;
  result: { solutions_added?: number; promoted_tags?: string[] };
  created_at: string;
}
export interface Stats {
  problems: number;
  solutions: number;
  tags: number;
  pending_tags: number;
}
export interface Health {
  llm_provider: string;
  embedding_provider: string;
  llm_configured: boolean;
}
export interface SearchResults {
  items: Problem[];
  total: number;
  query: string;
}
