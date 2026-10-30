import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router-dom";
import "./index.css";
import Overview from "./pages/Overview";
import Agreements from "./pages/Agreements";
import NewAgreement from "./pages/NewAgreement";
import AgreementDetail from "./pages/AgreementDetail";
import { Sponsor, Worker } from "./pages/Dashboards";
import Settings from "./pages/Settings";

// Hash routing: the app is a static bundle that works from any host or folder, no server rewrites needed.
const router = createHashRouter([
  { path: "/", element: <Overview /> },
  { path: "/agreements", element: <Agreements /> },
  { path: "/agreements/new", element: <NewAgreement /> },
  { path: "/agreements/:id", element: <AgreementDetail /> },
  { path: "/sponsor", element: <Sponsor /> },
  { path: "/worker", element: <Worker /> },
  { path: "/settings", element: <Settings /> },
  { path: "*", element: <Overview /> },
], {
  future: { v7_relativeSplatPath: true, v7_fetcherPersist: true, v7_normalizeFormMethod: true, v7_partialHydration: true, v7_skipActionErrorRevalidation: true },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} future={{ v7_startTransition: true }} />
  </StrictMode>,
);
