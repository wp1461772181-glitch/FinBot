import { useParams } from "react-router";
import { SkillsPage } from "../../SkillsPage";

/** /assistant/skills and /assistant/skills/:skillId (a draft's link opens that skill's editor). */
export function SkillsRoute() { return <SkillsPage skillId={useParams().skillId ?? null} />; }
