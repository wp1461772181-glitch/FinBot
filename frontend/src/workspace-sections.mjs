// The old section names (what an address maps to through routes.mjs `sectionOfPath`) and the groups the chrome folds
// them into.  Moved out of the old Shell.tsx unchanged: the pages still speak these names (`go("forecast")`) and the
// new sidebar reads them to know where it is.
//
// 公司 holds 总览; 预测 holds the forecast home, one forecast's page, 模型成绩 (#evaluation) and 历史回放, and #revisions
// opens the versions of a forecast; 资料库 holds 材料库 and 证据.  These names are section names, not addresses.
const FORECAST_TABS = ["forecast", "revisions", "evaluation", "replay"];
const LIBRARY_TABS = ["materials", "evidence"];

/** The group a section belongs to. */
export function navGroup(section) {
  if (section === "agent" || section === "bot") return "chat";
  if (section === "admin" || section === "knowledge") return "settings";
  if (section === "routines" || section === "portfolio" || section === "news" || section === "skills" || section === "memory") return section;
  if (section === "me") return "memory";
  if (LIBRARY_TABS.includes(section)) return "library";
  if (FORECAST_TABS.includes(section)) return "forecast";
  return "company";
}

/** The research area is the company, forecast and library groups. */
export function isResearchSection(section) {
  const group = navGroup(section);
  return group === "company" || group === "forecast" || group === "library";
}

/** The page titles of the old research header. */
export const WORKSPACE_SECTION_TITLE = {
  overview: "研究总览", forecast: "预测", evidence: "证据中心", materials: "材料库", revisions: "预测修订", evaluation: "模型成绩", replay: "历史回放",
};
