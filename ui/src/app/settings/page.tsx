"use client";

import { Cpu, Settings as SettingsIcon } from "lucide-react";

import { AppHeader } from "@/components/app-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export default function SettingsPage() {
  // Mock LLM configs
  const configs = [
    {
      name: "gpt-4o-main",
      provider: "openai",
      model: "gpt-4o",
      temperature: 0.0,
      is_current: true,
    },
    {
      name: "claude-3.5-backup",
      provider: "anthropic",
      model: "claude-3.5-sonnet",
      temperature: 0.1,
      is_current: false,
    },
  ];

  return (
    <>
      <AppHeader
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Settings" },
        ]}
      />

      <div className="flex flex-1 flex-col gap-6 p-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
          <p className="text-muted-foreground">
            Coordinator and LLM configuration.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-5 w-5" />
              LLM Configurations
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Provider</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Temperature</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {configs.map((c) => (
                  <TableRow key={c.name}>
                    <TableCell className="font-mono font-medium">
                      {c.name}
                    </TableCell>
                    <TableCell className="capitalize">{c.provider}</TableCell>
                    <TableCell>{c.model}</TableCell>
                    <TableCell>{c.temperature}</TableCell>
                    <TableCell>
                      {c.is_current ? (
                        <Badge variant="default">Active</Badge>
                      ) : (
                        <Badge variant="secondary">Inactive</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SettingsIcon className="h-5 w-5" />
              Coordinator
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-muted-foreground">Host</p>
                <p className="font-mono">0.0.0.0:8765</p>
              </div>
              <div>
                <p className="text-muted-foreground">Protocol</p>
                <p className="font-mono">WebSocket (Agentic Bus Envelope)</p>
              </div>
              <div>
                <p className="text-muted-foreground">Auto-approve</p>
                <p>Disabled</p>
              </div>
              <div>
                <p className="text-muted-foreground">Telemetry</p>
                <p>OpenTelemetry (Console exporter)</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
