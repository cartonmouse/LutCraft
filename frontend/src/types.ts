export type Recipe = {
  schema_version: number;
  preset_id: string;
  exposure_ev: number;
  warmth: number;
  contrast: number;
  saturation: number;
  lut: LutReference | null;
};
export type LutReference = {
  id: string; name: string; sha256: string; strength: number;
  input_space: "srgb"; output_space: "srgb"; interpolation: "tetrahedral";
};
export type Lut = { id: string; name: string; grid_size: number; sha256: string; byte_size: number; profile?: LutProfile };
export type LutMetadata = {
  description: string; category: string; tags: string[]; aliases: string[]; use_cases: string[];
  cautions: string; publisher: string; source_page: string; license_note: string;
  input_space: "srgb" | "unknown" | "other"; output_space: "srgb" | "unknown" | "other";
  compatibility_basis: string; recommended_strength: number | null; strength_basis: string;
};
export type LutProfile = {
  lut_id: string; name: string; revision: number; enabled: boolean | number;
  compatibility: "unknown" | "confirmed" | "incompatible"; metadata: LutMetadata;
  evidence: Record<string, { source?: string; review?: string; reference?: string }>;
  suggestions: { description?: string; tags?: string[] };
  analysis: { description?: string; sample_count?: number; out_of_range_fraction?: number };
  index_status: string; job: { id: string; status: string; stage: string; error: string | null } | null;
};
export type LutCandidate = {
  id: string; name: string; revision: number; description: string; tags: string[];
  reasons: string[]; conflicts: string[]; recommended_strength: number | null;
  strength_basis: string; trial_strength: number; requires_review: boolean;
};
export type LutSearchResult = {
  search_id: string; status: string; mode: string; query: string; message: string | null;
  candidates: LutCandidate[];
};
export type LutAction = { op: "select"; id: string; strength: number } | { op: "clear" } | { op: "strength"; strength: number };
export type PersonalPreset = { id: string; name: string; recipe: Recipe; revision: number };
export type Asset = {
  id: string;
  ordinal: number;
  name: string;
  width: number;
  height: number;
  format: string;
  recipe: Recipe;
  revision: number;
  thumbnail_url: string;
  original_url: string;
  result_url: string | null;
  download_url: string | null;
};
export type Item = {
  asset_id: string;
  ordinal: number;
  name: string;
  recipe: Recipe;
  status: string;
  error: string | null;
  result_url: string | null;
};
export type Operation = {
  id: string;
  status: string;
  summary: string;
  targets: string[];
  preview_asset_id: string;
  preview_url: string | null;
  error: string | null;
  items: Item[];
  download_url: string | null;
  created_at: string;
};
export type AgentTurn = {
  id: string; project_id: string; status: string; message: string; code: string | null;
  operation_id: string | null; tool_count: number; created_at: string; finished_at: string | null;
};
export type AgentHealth = {
  runtime: "manual" | "direct" | "openclaw"; send_enabled: boolean; configured: boolean;
  compatibility_verified: boolean; plugin: string; gateway: string; last_call: string; message: string;
};
export type Project = {
  lut_search?: LutSearchResult | null;
  id: string;
  name: string;
  revision: number;
  selected: string[];
  viewed: string | null;
  preferences: Record<string, string>;
  assets: Asset[];
  messages: { id: string; role: string; content: string; operation_id?: string | null;
    operation?: { id: string; status: string; summary: string } }[];
  operations: Operation[];
  agent_turns: AgentTurn[];
};
export type Health = {
  embedding?: { configured: boolean; model: string | null; calibrated: boolean };
  agent: AgentHealth;
  status: string;
  image_engine: string;
  model_configured: boolean;
  model_name: string | null;
  lut_engine: { available: boolean; version: string | null };
};
