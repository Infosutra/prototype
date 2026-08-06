import React, { useState } from "react";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search, Filter, Download, ChevronDown, ChevronRight, FileJson } from "lucide-react";

const MOCK_DATA = Array.from({ length: 25 }, (_, i) => ({
  id: `sub-${2000 + i}`,
  projectId: "proj-1",
  projectName: "WASH Assessment 2024",
  enumerator: `field.agent${(i % 5) + 1}`,
  status: i % 7 === 0 ? "flagged" : i % 3 === 0 ? "pending" : "validated",
  submittedAt: new Date(Date.now() - i * 3600000).toISOString(),
  location: i % 2 === 0 ? "Nairobi" : "Turkana",
  data: {
    water_source: "borehole",
    wait_time_mins: 15 + (i * 2),
    quality_rating: "acceptable"
  }
}));

export default function DataExplorer() {
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const toggleRow = (id: string) => {
    setExpandedRow(expandedRow === id ? null : id);
  };

  return (
    <Layout>
      <Header 
        title="Data Explorer" 
        description="Inspect, filter, and export raw submission data"
        action={
          <Button variant="outline" size="sm">
            <Download className="w-4 h-4 mr-2" />
            Export CSV
          </Button>
        }
      />
      <div className="flex flex-col flex-1 overflow-hidden bg-muted/20">
        
        {/* Filters Toolbar */}
        <div className="p-4 bg-card border-b flex flex-wrap gap-3 items-center z-0">
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input placeholder="Search submissions by ID, enumerator..." className="pl-9 h-9" />
          </div>
          
          <Select defaultValue="all">
            <SelectTrigger className="w-[180px] h-9">
              <SelectValue placeholder="All Projects" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Projects</SelectItem>
              <SelectItem value="proj-1">WASH Assessment 2024</SelectItem>
              <SelectItem value="proj-2">Education Baseline</SelectItem>
            </SelectContent>
          </Select>

          <Select defaultValue="all">
            <SelectTrigger className="w-[150px] h-9">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Statuses</SelectItem>
              <SelectItem value="validated">Validated</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="flagged">Flagged</SelectItem>
            </SelectContent>
          </Select>

          <Button variant="ghost" size="sm" className="h-9">
            <Filter className="w-4 h-4 mr-2" />
            More Filters
          </Button>
        </div>

        {/* Data Table */}
        <div className="flex-1 overflow-auto">
          <table className="w-full min-w-[640px] text-sm text-left border-collapse">
            <thead className="bg-muted/50 text-muted-foreground text-xs uppercase sticky top-0 backdrop-blur-sm z-10 shadow-sm">
              <tr>
                <th className="px-4 py-3 font-medium w-10"></th>
                <th className="px-4 py-3 font-medium">ID</th>
                <th className="px-4 py-3 font-medium">Project</th>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Enumerator</th>
                <th className="px-4 py-3 font-medium">Location</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-card">
              {MOCK_DATA.map((row) => (
                <React.Fragment key={row.id}>
                  <tr 
                    className="hover:bg-muted/30 transition-colors cursor-pointer group"
                    onClick={() => toggleRow(row.id)}
                  >
                    <td className="px-4 py-3 text-muted-foreground">
                      {expandedRow === row.id ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-primary">{row.id}</td>
                    <td className="px-4 py-3 truncate max-w-[200px]" title={row.projectName}>{row.projectName}</td>
                    <td className="px-4 py-3 text-muted-foreground text-xs">{new Date(row.submittedAt).toLocaleString()}</td>
                    <td className="px-4 py-3">{row.enumerator}</td>
                    <td className="px-4 py-3">{row.location}</td>
                    <td className="px-4 py-3">
                      <Badge variant="outline" className={
                        row.status === 'validated' ? 'bg-green-100 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800' : 
                        row.status === 'pending' ? 'bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800' : 
                        'bg-red-100 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800'
                      }>
                        {row.status}
                      </Badge>
                    </td>
                  </tr>
                  {expandedRow === row.id && (
                    <tr className="bg-muted/20 border-b">
                      <td colSpan={7} className="p-0">
                        <div className="p-4 m-4 border rounded-md bg-card shadow-inner flex flex-col">
                          <div className="flex items-center text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">
                            <FileJson className="w-4 h-4 mr-2" />
                            Raw Submission Payload
                          </div>
                          <pre className="font-mono text-xs overflow-x-auto p-4 bg-muted/50 rounded text-foreground">
                            {JSON.stringify(row.data, null, 2)}
                          </pre>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
        
        {/* Pagination Footer */}
        <div className="p-3 border-t bg-card flex items-center justify-between text-xs text-muted-foreground z-0">
          <span>Showing 1-25 of 12,458 submissions</span>
          <div className="flex gap-1">
            <Button variant="outline" size="sm" disabled>Previous</Button>
            <Button variant="outline" size="sm" className="bg-muted">1</Button>
            <Button variant="outline" size="sm">2</Button>
            <Button variant="outline" size="sm">3</Button>
            <span className="px-2 self-center">...</span>
            <Button variant="outline" size="sm">Next</Button>
          </div>
        </div>
      </div>
    </Layout>
  );
}
