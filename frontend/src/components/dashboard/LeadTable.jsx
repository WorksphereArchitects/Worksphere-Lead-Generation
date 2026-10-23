import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";

import LeadTabs from "./LeadTabs";
import LeadRow from "./LeadRow";
import MobileLeadCard from "./MobileLeadCard";

export default function LeadTable({
  leads,
  search,
  onSearchChange,
  activeTab,
  onTabChange,
  suspectCount,
  prospectCount,
  onSelect,
  onQualify,
  onRemove
}) {
  return (
    <div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
      {/* Header */}
      <div className="flex flex-col gap-4 border-b px-4 py-5 sm:flex-row sm:items-start sm:justify-between sm:px-6 sm:py-6">
        <div className="min-w-0">
          <h2 className="text-xl font-medium text-foreground">
            Company Intelligence
          </h2>

          <p className="mt-1 text-base text-muted-foreground">
            Companies and their current sales stages.
          </p>
        </div>

        <LeadTabs
          activeTab={activeTab}
          onTabChange={onTabChange}
          suspectCount={suspectCount}
          prospectCount={prospectCount}
        />
      </div>

      {/* Search */}
      <div className="px-4 py-4 sm:px-6">
        <div className="relative max-w-sm">
          <Search className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />

          <Input
            value={search}
            onChange={(event) =>
              onSearchChange(event.target.value)
            }
            placeholder="Search companies..."
            className="pl-8"
          />
        </div>
      </div>

      {/* Desktop */}
      <div className="hidden md:block">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-y bg-white">
              <tr>
                <th className="px-7 py-4 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Company
                </th>

                <th className="px-5 py-4 text-right text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Action
                </th>
              </tr>
            </thead>

            <tbody>
              {leads.map((lead) => (
                <LeadRow
                  key={lead.id}
                  lead={lead}
                  onSelect={onSelect}
                  onQualify={onQualify}
                  onRemove={onRemove}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mobile */}
      <div className="space-y-3 px-4 py-4 md:hidden">
        {leads.map((lead) => (
          <MobileLeadCard
            key={lead.id}
            lead={lead}
            onSelect={onSelect}
            onQualify={onQualify}
            onRemove={onRemove}
          />
        ))}
      </div>


      {/* Empty State */}
      {leads.length === 0 && (
        <div className="border-t p-12 text-center">
          <p className="font-medium">
            {search.trim()
              ? "No companies match your search"
              : activeTab === "prospects"
                ? "No prospects yet"
                : "No suspects available"}
          </p>

          <p className="mt-1 text-sm text-muted-foreground">
            {search.trim()
              ? "Try a different company name, symbol, or search term."
              : activeTab === "prospects"
                ? "Move a company from Suspects to Prospects to see it here."
                : "There are currently no companies in this sales stage."}
          </p>
        </div>
      )}

    </div>
  );
}
