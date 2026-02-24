"use client";

import * as React from "react";
import { useState, useEffect, useMemo } from "react";
import { Check, ChevronsUpDown, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  fetchPersistentAgents,
  fetchManagedAgents,
  fetchEphemeralAgents,
} from "@/lib/api";
import type {
  PersistentAgent,
  ManagedAgent,
  EphemeralAgent,
} from "@/lib/types";

interface AgentOption {
  agent_id: string;
  label: string;
  group: "persistent" | "managed" | "ephemeral";
}

interface AgentMultiSelectProps {
  /** Currently selected agent IDs */
  selected: string[];
  /** Callback when selection changes */
  onChange: (agentIds: string[]) => void;
  /** Placeholder text when nothing is selected */
  placeholder?: string;
}

export function AgentMultiSelect({
  selected,
  onChange,
  placeholder = "Select agents…",
}: AgentMultiSelectProps) {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const [persistent, managed, ephemeral] = await Promise.allSettled([
          fetchPersistentAgents(),
          fetchManagedAgents(),
          fetchEphemeralAgents(),
        ]);

        if (cancelled) return;

        const options: AgentOption[] = [];

        if (persistent.status === "fulfilled") {
          persistent.value.forEach((a: PersistentAgent) =>
            options.push({
              agent_id: a.agent_id,
              label: `${a.agent_id} (${a.status})`,
              group: "persistent",
            }),
          );
        }

        if (managed.status === "fulfilled") {
          managed.value.forEach((a: ManagedAgent) =>
            options.push({
              agent_id: a.agent_id,
              label: `${a.agent_id} — ${a.name}`,
              group: "managed",
            }),
          );
        }

        if (ephemeral.status === "fulfilled") {
          ephemeral.value.forEach((a: EphemeralAgent) =>
            options.push({
              agent_id: a.agent_id,
              label: `${a.agent_id} (ephemeral)`,
              group: "ephemeral",
            }),
          );
        }

        // Deduplicate by agent_id (an agent may appear in multiple lists)
        const seen = new Set<string>();
        const deduped = options.filter((o) => {
          if (seen.has(o.agent_id)) return false;
          seen.add(o.agent_id);
          return true;
        });

        setAgents(deduped);
      } catch {
        // Silently fail – we'll show empty list
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const grouped = useMemo(() => {
    const groups: Record<string, AgentOption[]> = {};
    for (const a of agents) {
      (groups[a.group] ??= []).push(a);
    }
    return groups;
  }, [agents]);

  const groupLabels: Record<string, string> = {
    persistent: "Persistent Agents",
    managed: "Managed Agents",
    ephemeral: "Ephemeral Agents",
  };

  function toggle(agentId: string) {
    if (selected.includes(agentId)) {
      onChange(selected.filter((id) => id !== agentId));
    } else {
      onChange([...selected, agentId]);
    }
  }

  function remove(agentId: string) {
    onChange(selected.filter((id) => id !== agentId));
  }

  return (
    <div className="grid gap-1.5">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="h-auto min-h-9 w-full justify-between font-normal"
          >
            {selected.length === 0 ? (
              <span className="text-muted-foreground">{placeholder}</span>
            ) : (
              <span className="text-sm">
                {selected.length} agent{selected.length !== 1 ? "s" : ""}{" "}
                selected
              </span>
            )}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[--radix-popover-trigger-width] p-0">
          <Command>
            <CommandInput placeholder="Search agents…" />
            <CommandList>
              {loading ? (
                <div className="py-6 text-center text-sm text-muted-foreground">
                  Loading agents…
                </div>
              ) : agents.length === 0 ? (
                <CommandEmpty>No agents found.</CommandEmpty>
              ) : (
                Object.entries(grouped).map(([group, items]) => (
                  <CommandGroup key={group} heading={groupLabels[group] ?? group}>
                    {items.map((agent) => {
                      const isSelected = selected.includes(agent.agent_id);
                      return (
                        <CommandItem
                          key={agent.agent_id}
                          value={agent.agent_id}
                          onSelect={() => toggle(agent.agent_id)}
                        >
                          <Check
                            className={cn(
                              "mr-2 h-4 w-4",
                              isSelected ? "opacity-100" : "opacity-0",
                            )}
                          />
                          <span className="truncate">{agent.label}</span>
                        </CommandItem>
                      );
                    })}
                  </CommandGroup>
                ))
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {/* Selected agent badges */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {selected.map((id) => (
            <Badge key={id} variant="secondary" className="gap-1 pr-1">
              <span className="max-w-[150px] truncate text-xs">{id}</span>
              <button
                type="button"
                className="ml-0.5 rounded-full outline-none hover:bg-muted-foreground/20"
                onClick={() => remove(id)}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
