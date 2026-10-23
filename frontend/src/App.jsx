import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
} from "react-router-dom";

import Sidebar from "./components/layout/Sidebar";

import Dashboard from "./pages/Dashboard";
import QualifiedCompanies from "./pages/QualifiedCompanies";
import NotQualifiedCompanies from "./pages/NotQualifiedCompanies";


function Settings() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold">
        Settings
      </h1>
    </div>
  );
}


export default function App() {
  return (
    <BrowserRouter>

      <div className="flex min-h-screen flex-col bg-muted/30 lg:flex-row">

        <Sidebar />

        <main className="min-w-0 flex-1">

          <Routes>

            <Route
              path="/"
              element={
                <Navigate
                  to="/dashboard"
                  replace
                />
              }
            />

            <Route
              path="/dashboard"
              element={<Dashboard />}
            />

            <Route
              path="/qualified"
              element={
                <QualifiedCompanies />
              }
            />

            <Route
              path="/not-qualified"
              element={
                <NotQualifiedCompanies />
              }
            />

            <Route
              path="/settings"
              element={<Settings />}
            />

          </Routes>

        </main>

      </div>

    </BrowserRouter>
  );
}