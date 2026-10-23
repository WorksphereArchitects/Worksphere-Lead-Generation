import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function LeadTabs({
  activeTab,
  onTabChange,
  suspectCount,
  prospectCount
}) {
  return (
    <Tabs value={activeTab} onValueChange={onTabChange}>
      <TabsList>
        <TabsTrigger value="suspects">
          Suspects
          <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs">
            {suspectCount}
          </span>
        </TabsTrigger>

        <TabsTrigger value="prospects">
          Prospects
          <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs">
            {prospectCount}
          </span>
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );
}