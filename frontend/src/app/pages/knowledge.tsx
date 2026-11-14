import { KnowledgeAdminPage } from "../../KnowledgeAdminPage";
import { useWorkspace } from "../workspace";

/** /assistant/knowledge */
export function KnowledgeRoute() {
  const ws = useWorkspace();
  return <KnowledgeAdminPage onBack={() => ws.go("admin")} />;
}
