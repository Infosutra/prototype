import React, { createContext, useContext, useState } from "react";
import { Sidebar, SidebarNav } from "./Sidebar";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

interface LayoutProps {
  children: React.ReactNode;
}

type MobileNavContextValue = {
  open: boolean;
  setOpen: (open: boolean) => void;
};

const MobileNavContext = createContext<MobileNavContextValue | null>(null);

export function useMobileNav() {
  const ctx = useContext(MobileNavContext);
  if (!ctx) {
    return { open: false, setOpen: (_: boolean) => undefined };
  }
  return ctx;
}

export function Layout({ children }: LayoutProps) {
  const [open, setOpen] = useState(false);

  return (
    <MobileNavContext.Provider value={{ open, setOpen }}>
      <div className="flex h-[100dvh] w-full bg-background overflow-hidden">
        {/* Desktop sidebar */}
        <div className="hidden md:flex h-full shrink-0">
          <Sidebar />
        </div>

        {/* Mobile drawer */}
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetContent
            side="left"
            className="w-[min(100%,18rem)] p-0 bg-sidebar text-sidebar-foreground border-sidebar-border [&>button]:text-sidebar-foreground"
          >
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <SidebarNav onNavigate={() => setOpen(false)} />
          </SheetContent>
        </Sheet>

        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">{children}</main>
      </div>
    </MobileNavContext.Provider>
  );
}
