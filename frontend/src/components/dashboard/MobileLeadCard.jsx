import { ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export default function MobileLeadCard({
  lead,
  onSelect,
  onQualify,
  onRemove
}) {
  const isProspect = lead.sales_stage === "prospect";
  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <button
            onClick={() => onSelect(lead)}
            className="text-left"
          >
            <h3 className="font-medium">
              {lead.company}
            </h3>
          </button>

          <p className="mt-1 text-xs text-muted-foreground">
            {lead.industry || "Industry unavailable"}
          </p>
        </div>

        <Badge variant="secondary">
          {lead.sales_stage === "prospect" ? "Prospect" : "Suspect"}
        </Badge>
      </div>

      <div className="mt-4 flex gap-2">
        {isProspect ? (
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={() => onRemove(lead)}
          >
            Remove Prospect
          </Button>
        ) : (
          <Button
            size="sm"
            className="flex-1"
            onClick={() => onQualify(lead)}
          >
            Qualify as Prospect
          </Button>
        )}

        <Button
          variant="outline"
          size="icon"
          onClick={() => onSelect(lead)}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
