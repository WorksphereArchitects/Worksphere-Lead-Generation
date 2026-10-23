import { Target, Users } from "lucide-react";

import {
  Card,
  CardContent
} from "@/components/ui/card";

export default function StatCards({
  suspectCount,
  prospectCount,
}) {

const stats = [
  {
    title: "Suspects",
    value: suspectCount,
    icon: Users,
    description: "Companies under initial review",
  },
  {
    title: "Prospects",
    value: prospectCount,
    icon: Target,
    description: "Companies advanced by the sales team",
  },
];


  return (
    <div className="grid gap-4 p-4 sm:grid-cols-2 sm:p-6">
      {stats.map((stat) => {
        const Icon = stat.icon;

        return (
          <Card key={stat.title}>
            <CardContent className="flex items-center justify-between p-5">
              <div>
                <p className="text-sm text-muted-foreground">
                  {stat.title}
                </p>

                <p className="mt-2 text-2xl font-semibold">
                  {stat.value}
                </p>

                <p className="mt-1 text-xs text-muted-foreground">
                  {stat.description}
                </p>
              </div>

              <div className="rounded-lg bg-muted p-3">
                <Icon className="h-5 w-5" />
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
