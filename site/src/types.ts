// Mirrors the export contract in KESSLER_PLAN.md §8.4 (written by `kessler export`).

export interface SourceInfo {
  id: string;
  label: string;
  url: string;
  license: string;
  last_success: string | null;
}

export interface IngestRun {
  run_id: string;
  started_at: string;
  status: "ok" | "partial" | string;
  network_calls: number;
  rows_new: Record<string, number>;
}

export interface Manifest {
  generated_at: string;
  schema_version: number;
  gcat_release: string | null;
  publish_raw_omm: boolean;
  sources: SourceInfo[];
  files: Record<string, string>;
  ingest_status: {
    last_run: IngestRun | null;
    runs: IngestRun[];
    tasks: { task: string; status: string; error?: string }[];
    http: { url: string; host: string; status: number | null; from_cache: boolean; started_at: string; bytes: number; duration_ms: number; error: string | null }[];
    table_rows: Record<string, number>;
    backfill_remaining: number | null;
  };
}

export type Flag =
  | "LOW_CONFIDENCE"
  | "FEW_FRAGMENTS"
  | "NO_PUBLIC_FRAGMENTS"
  | "PARENT_ONLY"
  | "STALE_PARENT"
  | "LONG_BACKPROP"
  | "INSUFFICIENT_HISTORY"
  | "STRETCH"
  | string;

export interface Validation {
  ref_time: string;
  ref_label: string;
  delta_min: number | null;
  within_precision: boolean | null;
  precision_hours: number;
}

export interface EventIndexEntry {
  id: string;
  title: string;
  regime: string;
  mode: "fragments" | "parent_only" | "insufficient";
  parent_norad: number;
  parent_name: string;
  t_p50: string | null;
  t_p05: string | null;
  t_p95: string | null;
  n_fragments: number;
  n_decayed: number;
  alt_km: number | null;
  flags: Flag[];
  validation: Validation | null;
  stretch: boolean;
  sparkline: { period: number; apo: number; peri: number; parent: boolean }[];
}

export interface Reference {
  label: string;
  time: string;
  kind: "registry" | "alt" | "gcat" | "ours" | "ours-alt";
  dv_ms?: number | null;
  delta_min?: number | null;
}

export interface Solution {
  method: string;
  t_p05: string | null;
  t_p50: string | null;
  t_p95: string | null;
  spread_km: number | null;
  n_used: number;
  lat: number | null;
  lon: number | null;
  alt_km: number | null;
  arg_lat_deg: number | null;
  flags: Flag[];
  curve?: { t: string; spread_km: number }[];
  sensitivity?: { label: string; t: string | null; spread_km: number | null }[];
}

export interface EventSummary {
  id: string;
  title: string;
  blurb: string;
  regime: string;
  mode: EventIndexEntry["mode"];
  parent: { norad: number; name: string; intdes: string };
  reference_time: string;
  reference_precision_hours: number;
  reference_note: string | null;
  references: Reference[];
  solution: Solution | null;
  alt_solutions: Solution[];
  parent_only: {
    n_elsets: number;
    window_start: string | null;
    window_end: string | null;
    dv_t_ms: number | null;
    series: { epoch: string; mean_motion: number; eccentricity: number; bstar: number; a_km: number }[];
    changepoints: { field: string; epoch: string }[];
    note: string;
  } | null;
  membership: {
    counts: Record<string, number>;
    candidates: number;
    clusters: { norad: number; name: string; label: number; assignment: string; first_epoch: string; x: number; y: number; inc: number; raan: number; in_event: boolean }[];
    explain: string;
  };
  dv_stats: { n: number; median_ms: number; p90_ms: number; max_ms: number; lognorm_mu: number; lognorm_sigma: number } | null;
  fragments: { norad: number; name: string; first_epoch: string; decay_date: string | null; assignment: string; dv_ms: number | null; apogee_km: number | null; perigee_km: number | null; forecast_p50: string | null }[];
  decay_curve: { date: string; remaining: number; p10?: number; p50?: number; p90?: number; forecast?: boolean }[];
  ephem: { available: boolean; reason?: string };
  computed_at: string;
}

export interface GabbardRow { norad: number; epoch: string; period: number; apo: number; peri: number; parent: boolean; snapshot: string }
export interface DvRow { norad: number; r: number; t: number; n: number; mag: number; residual_km: number }

export interface EphemMeta {
  t0: string;
  step_s: number[]; // per-sample step (non-uniform: dense then daily)
  times: number[]; // seconds since t0 for each sample
  T: number;
  N: number;
  norads: number[];
  names: string[];
  parent_index: number;
  decay_s: (number | null)[]; // seconds since t0 when each object decayed, if known
  breakup: { lat: number; lon: number; alt_km: number } | null;
}

export interface ForecastRow {
  norad: number;
  name: string;
  object_type: string;
  event_id: string | null;
  perigee_km: number;
  apogee_km: number;
  epoch: string;
  issued_at: string;
  p10: string;
  p50: string;
  p90: string;
  baseline: string | null;
}

export interface Backtest {
  generated_at: string;
  n_train: number;
  n_holdout: number;
  holdout_start: string;
  metrics: { model: string; mae_days: number; mae_pct: number; coverage80: number; median_lead_days: number | null; skill_vs_baseline: number | null }[];
  calibration: { nominal: number; empirical: number; model: string }[];
  lead_time: { days_before: number; coverage: number; model: string }[];
  scored_live: { norad: number; issued_at: string; p50: string; actual: string; abs_err_days: number; inside80: boolean }[];
  feature_importance?: { feature: string; importance: number }[];
  notes: string[];
}

export interface SpaceWeather {
  daily: { date: string; f107: number | null; f107_81: number | null; ap: number | null; kp_max: number | null; type: string | null }[];
  kp_live: { t: string; kp: number }[];
}

export interface ScorecardRow {
  family: string;
  launches: number;
  rb_in_orbit: number;
  rb_total: number;
  stage_debris: number;
  stage_debris_in_orbit: number;
  frag_events: number;
  debris_per_launch: number;
  median_days_to_first_debris: number | null;
  highlight: boolean;
}
export interface Scorecard { gcat_release: string; citation: string; since_year: number; rows: ScorecardRow[]; events: { parent: string; name: string; family: string; date: string; pieces: number }[] }
