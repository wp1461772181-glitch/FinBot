import { Suspense, lazy } from "react";
import { useRunningTasks } from "./tasks";

const TaskBar = lazy(() => import("./TaskBar").then((m) => ({ default: m.TaskBar })));

/** The strip along the bottom of the main column where running tasks show; nothing is loaded or drawn until one runs. */
export function TaskDock({ bottom }: { bottom: string }) {
  const running = useRunningTasks();
  if (!running.length) return null;
  return <div data-slot="task-dock" className="pointer-events-none sticky z-sticky mt-auto px-4 pb-3 lg:px-6" style={{ bottom }}>
    <Suspense fallback={null}><TaskBar className="pointer-events-auto mx-auto w-full max-w-xl" /></Suspense>
  </div>;
}
