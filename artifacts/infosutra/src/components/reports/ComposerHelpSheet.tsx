import type { SpecCatalogOut } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  ComponentUsagePreview,
  componentBlurb,
  componentTitle,
  examplePromptFor,
  sortComponentTypes,
} from "@/components/reports/ComponentUsagePreview";

export function ComposerHelpSheet({
  open,
  onOpenChange,
  catalog,
  loading,
  error,
  onTryPrompt,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  catalog: SpecCatalogOut | undefined;
  loading?: boolean;
  error?: string | null;
  onTryPrompt: (prompt: string) => void;
}) {
  const componentTypes = sortComponentTypes(
    catalog?.componentTypes?.length
      ? catalog.componentTypes
      : (catalog?.components ?? []).map((row) => row.type),
  );
  const dataSources = catalog?.dataSources ?? [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 overflow-hidden sm:max-w-lg">
        <SheetHeader className="shrink-0 border-b pb-4 text-left">
          <SheetTitle>Compose help</SheetTitle>
          <SheetDescription>
            Components and data sources from the live report catalog. Previews use sample data —
            not your study.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-8 overflow-y-auto py-4 pr-1">
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading catalog…</p>
          ) : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}

          <section className="space-y-4">
            <div>
              <h3 className="text-sm font-semibold">Components</h3>
              <p className="text-xs text-muted-foreground">
                What you can ask for. Click Try this to put an example in the draft.
              </p>
            </div>
            {componentTypes.map((type) => (
              <article key={type} className="space-y-2 border-b border-border/60 pb-4 last:border-0">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <code className="rounded bg-muted px-1.5 py-0.5 text-[11px]">{type}</code>
                  <span className="text-sm font-medium">{componentTitle(type)}</span>
                </div>
                <p className="text-xs text-muted-foreground">{componentBlurb(type)}</p>
                <ComponentUsagePreview type={type} />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 text-xs"
                  onClick={() => {
                    onTryPrompt(examplePromptFor(type));
                    onOpenChange(false);
                  }}
                >
                  Try this
                </Button>
                <p className="text-[11px] text-muted-foreground">{examplePromptFor(type)}</p>
              </article>
            ))}
            {!loading && !error && componentTypes.length === 0 ? (
              <p className="text-sm text-muted-foreground">No components in the catalog.</p>
            ) : null}
          </section>

          <section className="space-y-3">
            <div>
              <h3 className="text-sm font-semibold">Data sources</h3>
              <p className="text-xs text-muted-foreground">
                Bind figures to these ids when you describe the report.
              </p>
            </div>
            <ul className="space-y-3">
              {dataSources.map((source) => (
                <li key={source.id} className="text-sm">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <code className="rounded bg-muted px-1.5 py-0.5 text-[11px]">{source.id}</code>
                    <span className="font-medium">{source.title}</span>
                    <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
                      {source.kind}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{source.description}</p>
                </li>
              ))}
            </ul>
            {!loading && !error && dataSources.length === 0 ? (
              <p className="text-sm text-muted-foreground">No data sources in the catalog.</p>
            ) : null}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}
