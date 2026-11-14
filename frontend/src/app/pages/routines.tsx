import { RoutinesPage } from "../../PersonalPages";
import { useWorkspace } from "../workspace";

/** /routines, ?tab=confirm|tasks|runs (the address keeps the tab; P7.2 starts reading it). */
export function RoutinesRoute() {
  const ws = useWorkspace();
  return <RoutinesPage bots={ws.bots.bots} onNavigate={ws.go} onChanged={() => void ws.bots.reload()} />;
}
