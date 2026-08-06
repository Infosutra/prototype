import React from "react";
import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useMobileNav } from "./Layout";

interface HeaderProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function Header({ title, description, action }: HeaderProps) {
  const { setOpen } = useMobileNav();

  return (
    <header className="min-h-14 md:h-16 flex items-center justify-between gap-3 px-4 md:px-6 py-2 md:py-0 bg-card border-b border-border z-10 sticky top-0">
      <div className="flex items-start gap-2 min-w-0 flex-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="md:hidden shrink-0 -ml-1 mt-0.5"
          onClick={() => setOpen(true)}
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </Button>
        <div className="flex flex-col min-w-0">
          <h1 className="text-base md:text-lg font-bold tracking-tight text-foreground truncate">
            {title}
          </h1>
          {description && (
            <p className="text-xs text-muted-foreground line-clamp-2 md:line-clamp-1">
              {description}
            </p>
          )}
        </div>
      </div>
      {action && (
        <div className="flex items-center gap-1.5 sm:gap-2 shrink-0 flex-wrap justify-end max-w-[50%] sm:max-w-none">
          {action}
        </div>
      )}
    </header>
  );
}
