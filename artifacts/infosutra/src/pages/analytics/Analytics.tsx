import React from "react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BarChart3, Download } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, AreaChart, Area, Cell } from "recharts";

const BY_PROJECT_DATA = [
  { name: "WASH 24", count: 4250 },
  { name: "Edu Base", count: 3100 },
  { name: "Health Map", count: 2840 },
  { name: "Nut Q1", count: 1560 },
  { name: "Cash PD", count: 840 },
];

const OVER_TIME_DATA = [
  { month: "Jan", count: 400 },
  { month: "Feb", count: 600 },
  { month: "Mar", count: 1200 },
  { month: "Apr", count: 1800 },
  { month: "May", count: 2400 },
  { month: "Jun", count: 2200 },
  { month: "Jul", count: 3100 },
];

const ENUMERATOR_STATS = [
  { name: "john.doe", submissions: 450, validated: 442, errorRate: "1.8%" },
  { name: "jane.smith", submissions: 410, validated: 390, errorRate: "4.8%" },
  { name: "ali.hassan", submissions: 385, validated: 380, errorRate: "1.3%" },
  { name: "sarah.m", submissions: 320, validated: 300, errorRate: "6.2%" },
];

export default function Analytics() {
  return (
    <Layout>
      <Header 
        title="Analytics" 
        description="Cross-project statistical overview"
        action={
          <Button variant="outline" size="sm">
            <Download className="w-4 h-4 mr-2" />
            Export Report
          </Button>
        }
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <Card>
            <CardHeader className="py-4 border-b">
              <CardTitle className="text-sm font-semibold flex items-center">
                <BarChart3 className="w-4 h-4 mr-2 text-primary" />
                Submissions by Project
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={BY_PROJECT_DATA} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="hsl(var(--border))" />
                  <XAxis type="number" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))", fontFamily: "var(--app-font-mono)" }} />
                  <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "hsl(var(--foreground))" }} />
                  <Tooltip cursor={{ fill: "hsl(var(--muted))" }} contentStyle={{ backgroundColor: "hsl(var(--card))", borderRadius: "4px", fontSize: "12px", fontFamily: "var(--app-font-mono)" }} />
                  <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                    {BY_PROJECT_DATA.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={`hsl(var(--chart-${(index % 5) + 1}))`} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="py-4 border-b">
              <CardTitle className="text-sm font-semibold flex items-center">
                <BarChart3 className="w-4 h-4 mr-2 text-secondary" />
                Global Submission Velocity
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 h-72">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={OVER_TIME_DATA} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(var(--secondary))" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="hsl(var(--secondary))" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                  <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))", fontFamily: "var(--app-font-mono)" }} />
                  <Tooltip contentStyle={{ backgroundColor: "hsl(var(--card))", borderColor: "hsl(var(--border))", borderRadius: "4px", fontSize: "12px", fontFamily: "var(--app-font-mono)" }} />
                  <Area type="monotone" dataKey="count" stroke="hsl(var(--secondary))" strokeWidth={2} fillOpacity={1} fill="url(#colorCount)" />
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="py-4 border-b">
            <CardTitle className="text-sm font-semibold">Top Performing Enumerators</CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-muted text-muted-foreground text-xs uppercase">
                <tr>
                  <th className="px-6 py-3 font-medium">Enumerator ID</th>
                  <th className="px-6 py-3 font-medium text-right">Total Submissions</th>
                  <th className="px-6 py-3 font-medium text-right">Validated</th>
                  <th className="px-6 py-3 font-medium text-right">Error Rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border bg-card">
                {ENUMERATOR_STATS.map((stat, i) => (
                  <tr key={i} className="hover:bg-muted/50 transition-colors">
                    <td className="px-6 py-4 font-medium">{stat.name}</td>
                    <td className="px-6 py-4 text-right font-mono">{stat.submissions}</td>
                    <td className="px-6 py-4 text-right font-mono text-green-600 dark:text-green-400">{stat.validated}</td>
                    <td className="px-6 py-4 text-right">
                      <span className={`px-2 py-1 rounded text-xs font-mono font-medium ${
                        parseFloat(stat.errorRate) > 5 ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400' : 'text-muted-foreground'
                      }`}>
                        {stat.errorRate}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

      </div>
    </Layout>
  );
}
