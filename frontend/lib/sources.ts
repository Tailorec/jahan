/* The persona sources, as every page names and colours them. */

export const SOURCE_NAMES: Record<string, string> = {
  stackoverflow: "Stack Overflow survey", gss: "General Social Survey (US)", prism: "PRISM survey",
  real_human_survey: "Real human survey", amazon: "Amazon reviewers", wiki: "Wikipedia figures", synthetic: "synthetic",
};
export const SOURCE_COLORS: Record<string, string> = {
  stackoverflow: "var(--seg1)", gss: "var(--seg2)", amazon: "var(--seg3)", prism: "var(--seg4)",
  real_human_survey: "var(--seg5)", wiki: "oklch(0.7 0.02 75)",
};
export const SURVEYS = ["stackoverflow", "gss", "prism", "real_human_survey"];
// Every field of these was read from text by a model: never surveyed.
export const TEXT_SOURCES = ["amazon", "wiki"];
