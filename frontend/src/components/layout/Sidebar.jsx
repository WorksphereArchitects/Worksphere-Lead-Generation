import {
  LayoutDashboard,
  Menu,
  Settings,
  Users,
  XCircle,
} from "lucide-react";

import { NavLink } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

export default function Sidebar() {
  return (
    <>
      <Sheet>
        <div className="flex h-14 items-center justify-between border-b bg-white px-4 lg:hidden">
          <div>
            <p className="text-sm font-semibold text-foreground">Lead Discovery</p>
            <p className="text-xs text-muted-foreground">Market Intelligence</p>
          </div>

          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Open navigation menu">
              <Menu className="h-5 w-5" />
            </Button>
          </SheetTrigger>
        </div>

        <SheetContent
          side="left"
          className="w-72 border-r p-0 lg:hidden"
        >
          <SheetHeader className="border-b px-6 py-5 pr-14 text-left">
            <SheetTitle>Lead Discovery</SheetTitle>
            <SheetDescription>Market Intelligence</SheetDescription>
          </SheetHeader>

          <nav aria-label="Main navigation" className="flex-1 overflow-y-auto p-4">
            <div className="space-y-1">
              <MobileNavLink to="/dashboard" icon={LayoutDashboard}>Dashboard</MobileNavLink>
              <MobileNavLink to="/qualified" icon={Users}>Qualified Companies</MobileNavLink>
              <MobileNavLink to="/not-qualified" icon={XCircle}>Not Qualified Companies</MobileNavLink>
              <MobileNavLink to="/settings" icon={Settings}>Settings</MobileNavLink>
            </div>
          </nav>

          <div className="shrink-0 border-t p-4">
            <p className="text-sm font-medium text-foreground">Sales Team</p>
            <p className="text-xs text-muted-foreground">Lead Manager</p>
          </div>
        </SheetContent>
      </Sheet>

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
        <nav aria-label="Main navigation" className="flex-1 overflow-y-auto p-4">
          <div className="space-y-1">
            <DesktopNavLink to="/dashboard" icon={LayoutDashboard}>Dashboard</DesktopNavLink>
            <DesktopNavLink to="/qualified" icon={Users}>Qualified Companies</DesktopNavLink>
            <DesktopNavLink to="/not-qualified" icon={XCircle}>Not Qualified Companies</DesktopNavLink>
            <DesktopNavLink to="/settings" icon={Settings}>Settings</DesktopNavLink>
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
    </>
  );
}

function DesktopNavLink({ to, icon: Icon, children }) {
  return (
    <NavLink to={to} className="block text-foreground no-underline">
      {({ isActive }) => (
        <Button
          variant={isActive ? "secondary" : "ghost"}
          className="w-full justify-start gap-3 text-foreground"
        >
          <Icon className="h-4 w-4" />
          {children}
        </Button>
      )}
    </NavLink>
  );
}

function MobileNavLink({ to, icon: Icon, children }) {
  return (
    <SheetClose asChild>
      <NavLink
        to={to}
        className="flex h-9 w-full items-center gap-3 rounded-md px-3 text-sm font-medium text-foreground no-underline hover:bg-muted aria-[current=page]:bg-secondary aria-[current=page]:text-secondary-foreground"
      >
        <Icon className="h-4 w-4" />
        {children}
      </NavLink>
    </SheetClose>
  );
}