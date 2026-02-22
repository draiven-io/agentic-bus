"use client";

import { Cpu, Settings as SettingsIcon, Loader2 } from "lucide-react";

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

import { useAsync } from "@/hooks/use-async";
import { fetchLLMConfigs, fetchSettings } from "@/lib/api";

export default function SettingsPage() {
  const { data: configs, loading: configsLoading } = useAsync(() =>
    fetchLLMConfigs(),
  );
  const { data: settings, loading: settingsLoading } = useAsync(() =>
    fetchSettings(),
  );

  const isLoading = configsLoading || settingsLoading;

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

        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading settings…
          </div>
        )}

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
                {(configs ?? []).length === 0 && !configsLoading ? (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="py-8 text-center text-muted-foreground"
                    >
                      No LLM configurations. Use the CLI to add one:
                      <code className="ml-2 rounded bg-muted px-2 py-0.5 text-xs">
                        agbus llm add
                      </code>
                    </TableCell>
                  </TableRow>
                ) : (
                  (configs ?? []).map((c) => (
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
                  ))
                )}
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
                <p className="font-mono">
                  {settings
                    ? `${settings.host}:${settings.port}`
                    : "—"}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Protocol</p>
                <p className="font-mono">WebSocket (Agentic Bus Envelope)</p>
              </div>
              <div>
                <p className="text-muted-foreground">Auto-approve</p>
                <p>{settings?.auto_approve ? "Enabled" : "Disabled"}</p>
              </div>
              <div>
                <p className="text-muted-foreground">OIDC</p>
                <p>
                  {settings?.oidc_enabled
                    ? settings.oidc_issuer
                    : "Disabled (dev mode)"}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Database</p>
                <p className="font-mono truncate max-w-[300px]" title={settings?.database_url}>
                  {settings?.database_url ?? "—"}
                </p>
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
