import {
  Building2,
  CircleHelp,
  LayoutDashboard,
  Settings,
  Users,
  XCircle,
} from "lucide-react";

import { NavLink } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

export default function Sidebar() {
  return (
    <aside className="hidden h-screen w-64 shrink-0 flex-col border-r bg-white lg:flex">
      {/* Logo */}
      <div className="flex h-16 shrink-0 items-center gap-3 px-6">
        <div>
          <h1 className="text-sm font-semibold text-foreground">
            Lead Discovery
          </h1>

          <p className="text-xs text-muted-foreground">
            Market Intelligence
          </p>
        </div>
      </div>

      <Separator />

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto p-4">
        <div className="space-y-1">
          {/* Dashboard */}
          <NavLink
            to="/dashboard"
            className="block text-foreground no-underline"
          >
            {({ isActive }) => (
              <Button
                variant={isActive ? "secondary" : "ghost"}
                className="w-full justify-start gap-3 text-foreground"
              >
                <LayoutDashboard className="h-4 w-4" />
                Dashboard
              </Button>
            )}
          </NavLink>

          {/* Qualified Companies */}
          <NavLink
            to="/qualified"
            className="block text-foreground no-underline"
          >
            {({ isActive }) => (
              <Button
                variant={isActive ? "secondary" : "ghost"}
                className="w-full justify-start gap-3 text-foreground"
              >
                <Users className="h-4 w-4" />
                Qualified Companies
              </Button>
            )}
          </NavLink>

          {/* Not Qualified Companies */}
          <NavLink
            to="/not-qualified"
            className="block text-foreground no-underline"
          >
            {({ isActive }) => (
              <Button
                variant={isActive ? "secondary" : "ghost"}
                className="w-full justify-start gap-3 text-foreground"
              >
                <XCircle className="h-4 w-4" />
                Not Qualified Companies
              </Button>
            )}
          </NavLink>

          {/* Settings */}
          <NavLink
            to="/settings"
            className="block text-foreground no-underline"
          >
            {({ isActive }) => (
              <Button
                variant={isActive ? "secondary" : "ghost"}
                className="w-full justify-start gap-3 text-foreground"
              >
                <Settings className="h-4 w-4" />
                Settings
              </Button>
            )}
          </NavLink>
        </div>
      </nav>

      {/* Bottom Section */}
      <div className="shrink-0 p-4">

        <div className="flex items-center gap-3 px-2">

          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-foreground">
              Sales Team
            </p>

            <p className="truncate text-xs text-muted-foreground">
              Lead Manager
            </p>
          </div>
        </div>
      </div>
    </aside>
  );
}