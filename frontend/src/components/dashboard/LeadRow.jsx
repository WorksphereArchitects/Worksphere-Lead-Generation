import { ArrowRight, Building2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export default function LeadRow({
  lead,
  onSelect,
  onQualify,
  onRemove
}) {
  const isProspect = lead.sales_stage === "prospect";
  return (
    <tr
      className="cursor-pointer border-b last:border-b-0 hover:bg-muted/20"
      onClick={() => onSelect(lead)}
    >
      {/* Company */}
      <td className="px-7 py-5">
        <div className="flex items-center gap-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border">
            <Building2 className="h-5 w-5 text-muted-foreground" />
          </div>

          <div className="min-w-0">
            <p className="font-semibold">
              {lead.company}
              <Badge variant="secondary" className="ml-2 align-middle text-[10px]">
                {isProspect ? "Prospect" : "Suspect"}
              </Badge>
            </p>

            <p className="mt-0.5 text-sm text-muted-foreground">
              {lead.industry || "Industry unavailable"}
            </p>
          </div>
        </div>
      </td>

      {/* Action */}
      <td
        className="px-5 py-5 text-right"
        onClick={(event) => event.stopPropagation()}
      >
        {!isProspect ? (
          <Button
            className="bg-black text-white hover:bg-black/90"
            onClick={() => onQualify(lead)}
          >
            Qualify as Prospect
          </Button>
        ) : (
          <Button
            variant="outline"
            onClick={() => onRemove(lead)}
          >
            Remove from Prospects
          </Button>
        )}

        <Button
          variant="ghost"
          size="icon"
          className="ml-2"
          onClick={() => onSelect(lead)}
        >
          <ArrowRight className="h-4 w-4 text-muted-foreground" />
        </Button>
      </td>
    </tr>
  );
}
