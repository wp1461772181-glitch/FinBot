import { RouterProvider } from "react-router";
import { router } from "./app/router";

/** The app is its router: addresses and pages live in app/router.tsx, the old shell and chat session in app/session.tsx. */
export function App() {
  return <RouterProvider router={router} />;
}
